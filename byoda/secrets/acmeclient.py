'''
ACME client, leeched from
    https://github.com/theandrew168/autocert/blob/main/autocert/acme.py

TODO: This is dead code as support for Let's Encrypt is pushed out. Considering
to use certbot with byoda-dns extension script or sub-git certbot code
base and hook in to logic there.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import base64

import josepy as jose
import pyrfc3339

import requests

from cryptography import x509
# from authlib.jose import JsonWebKey, JsonWebSignature

_LOGGER = logging.getLogger(__name__)

LETS_ENCRYPT_DIRECTORY_URL = 'https://acme-v02.api.letsencrypt.org/directory'
LETS_ENCRYPT_STAGING_DIRECTORY_URL = \
    'https://acme-staging-v02.api.letsencrypt.org/directory'
ACME_ERROR_BAD_NONCE = 'urn:ietf:params:acme:error:badNonce'
ACME_ERROR_MALFORMED = 'urn:ietf:params:acme:error:malformed'
ACME_ERROR_ORDER_NOT_READY = 'urn:ietf:params:acme:error:orderNotReady'

MAX_TRIES = 5

CSR = x509.CertificateSigningRequest


class ACMEServerError(Exception):
    pass


class ACMEOrderNotReady(ACMEServerError):
    pass


class ACMEClient:
    '''
    Request an SSL cert from Let's Encrypt
    '''
    def __init__(self, tls_secret, csr: CSR,
                 accept_tos: bool = True, verify_tls: bool = True,
                 directory_url: str = LETS_ENCRYPT_STAGING_DIRECTORY_URL):

        self.fqdn = tls_secret.common_name
        self.accept_tos = accept_tos
        self.verify_tls = verify_tls
        self.session = requests.Session()
        self.session.headers = {
            'Content-Type': 'application/jose+json',
        }
        self.directory = self._get_directory(directory_url)

        self.contact = f'mailto:postmaster@{self.fqdn}'
        self.nonce = self._get_nonce()
        self.jwk = JsonWebKey.import_key(
            tls_secret.private_key.public_key(), {'kty': 'RSA'}
        ).as_dict()
        self.kid = None
        acct = self._create_or_read_account()
        self.kid = acct.headers['Location']
        _LOGGER.info('Initialized Lets Encrypt account kid: %s', self.kid)

        order = self.create_order(self.fqdn)

    def get_keyauth(self, token):
        thumbprint = self.jwk.thumbprint()
        keyauth = '{}.{}'.format(token, thumbprint)
        keyauth = keyauth.encode()
        return keyauth

    def create_order(self, domain):
        _LOGGER.info('creating LetsEncrypt order for domains: %s', domain)
        url = self.directory['newOrder']
        payload = {
            'identifiers': [
                {'type': 'dns', 'value': [domain]}
            ],
        }
        resp = self._cmd(url, payload)
        resp.raise_for_status()
        data = resp.json()
        return data

    def get_authorization(self, auth_url):
        _LOGGER.info('getting LetsEncrypt authorization: %s', auth_url)
        resp = self._cmd(auth_url, None)
        resp.raise_for_status()
        data = resp.json()
        return data

    def verify_challenge(self, challenge_url):
        _LOGGER.info('verifying LetsEncrypt challenge: %s', challenge_url)
        resp = self._cmd(challenge_url, {})
        resp.raise_for_status()
        data = resp.json()
        return data

    def finalize_order(self, finalize_url, csr):
        payload = {'csr': base64url(csr)}
        resp = self._cmd(finalize_url, payload)
        data = resp.json()
        return data

    def download_certificate(self, cert_url):
        resp = self._cmd(cert_url, None)
        return resp.content

    def _get_directory(self, directory_url):
        resp = self.session.get(directory_url, verify=self.verify_tls)
        resp.raise_for_status()
        directory = resp.json()
        return directory

    def _get_nonce(self):
        resp = self.session.head(
            self.directory['newNonce'], verify=self.verify_tls
        )
        resp.raise_for_status()
        self.nonce = resp.headers['Replay-Nonce']
        return self.nonce

    def _create_or_read_account(self):
        url = self.directory['newAccount']
        payload = {
            'termsOfServiceAgreed': self.accept_tos,
        }

        # apply contact emails if present
        _LOGGER.info(f'attaching contact info to account: {self.contact}')

        # add to payload
        payload['contact'] = [self.contact]

        resp = self._cmd(url, payload)
        resp.raise_for_status()
        return resp

    def _cmd(self, url, payload, tries=0):
        jws = JsonWebSignature()
        protected = {'protected': {'alg': 'HS256'}}
        secret = self.jwk
        data = jws.serialize_json(protected, payload, secret)

        # post message to the ACME server
        resp = self.session.post(
            url, data=data, verify=self.verify_tls
        )
        if resp.status_code not in [200, 201, 204]:
            resp = resp.json()

            # if bad / malformed nonce, get another and retry
            if resp['type'] in [ACME_ERROR_BAD_NONCE, ACME_ERROR_MALFORMED]:
                if tries < MAX_TRIES:
                    self.nonce = self._get_nonce()
                    return self._cmd(url, payload, tries=tries+1)

            if resp['type'] == ACME_ERROR_ORDER_NOT_READY:
                raise ACMEOrderNotReady()

            raise ACMEServerError(resp)

        # update nonce
        self.nonce = resp.headers['Replay-Nonce']

        return resp


# https://tools.ietf.org/html/rfc4648#section-5
def base64url(b):
    return base64.urlsafe_b64encode(b).decode().replace('=', '')


class Fixed(jose.Field):
    """Fixed field."""

    def __init__(self, json_name, value):
        self.value = value
        super().__init__(
            json_name=json_name, default=value, omitempty=False)

    def decode(self, value):
        if value != self.value:
            raise jose.DeserializationError(
                'Expected {0!r}'.format(self.value)
            )
        return self.value

    def encode(self, value):
        if value != self.value:
            _LOGGER.warning(
                'Overriding fixed field (%s) with %r', self.json_name, value
            )
        return value


class RFC3339Field(jose.Field):
    """RFC3339 field encoder/decoder.
    Handles decoding/encoding between RFC3339 strings and aware (not
    naive) `datetime.datetime` objects
    (e.g. ``datetime.datetime.now(pytz.utc)``).
    """

    @classmethod
    def default_encoder(cls, value):
        return pyrfc3339.generate(value)

    @classmethod
    def default_decoder(cls, value):
        try:
            return pyrfc3339.parse(value)
        except ValueError as error:
            raise jose.DeserializationError(error)


class Resource(jose.Field):
    """Resource MITM field."""

    def __init__(self, resource_type, *args, **kwargs):
        self.resource_type = resource_type
        super().__init__(
            'resource', default=resource_type, *args, **kwargs)

    def decode(self, value):
        if value != self.resource_type:
            raise jose.DeserializationError(
                'Wrong resource type: {0} instead of {1}'.format(
                    value, self.resource_type))
        return value
