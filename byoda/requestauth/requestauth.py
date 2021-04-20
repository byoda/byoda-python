'''
Helper functions for API request processing

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license
'''

import logging
from enum import Enum

from fastapi import HTTPException


from ipaddress import ip_address as IpAddress

from byoda.exceptions import NoAuthInfo

_LOGGER = logging.getLogger(__name__)


class TlsStatus(str, Enum):
    '''
    TLS status as reported by nginx variable 'ssl_client_verify':
    http://nginx.org/en/docs/http/ngx_http_ssl_module.html#var_ssl_client_verify
    '''    # noqa

    NONE        = 'NONE'        # noqa: E221
    SUCCESS     = 'SUCCESS'     # noqa: E221


class RequestAuth():
    '''
    Three classes derive from this class:
      - AccountRequestAuth
      - MemberRequestAuth
      - ServiceRequestauth

    With the help of this base class they perform request authentication
    based on the M-TLS client cert passed by a reverse proxy to the
    service as HTTP headers. Each of the derived classes perform
    Request authentication based on the cert chain presented by the client
    calling the API.

    The public properties of the class are:
      - is_authenticated: Was the client successfully authenticated. The value
                          may be False is authentication was not required
      - remote_addr     : the remote_addr as it connected to the reverse proxy
      - id_type         : whether the authentication was for an Account,
                          Member or Service secret
      - client_cn       : the common name of the client cert
      - issuing_ca_cn   : the common name of the CA that signed the cert
      - account_id      : the account_id parsed from the CN of the account cert
      - service_id      : the service_id parsed from the CN of the member or
                          service cert
      - member_id       : the member_id parsed from the CN of the member cert

    Depending on the API, the client can use one of the following for
    authentication with M-TLS:
    - account cert
    - member cert
    - service cert

    The reverse proxy in front of the server must perform TLS handshake to
    verify that the client cert has been signed by a trusted CA and it must
    set HTTP headers for the info learned from the client cert:
        X-Client-SSL-Verify
        X-Client-SSL-Subject
        X-Client-SSL-Issuing-Ca
        X-Forwarded-For

    With nginx this can be achieved by:
        listen 443 ssl;
        ssl_certificate_key /path/to/letsencrypt/private.key;
        ssl_certificate  /path/to/letsencrypt/fullchain.pem;

        ssl_verify_client optional;
        ssl_client_certificate /path/to/network-rootca-cert.pem;

        proxy_set_header X-Client-SSL-Issuing-CA $ssl_client_i_dn;
        proxy_set_header X-Client-SSL-Subject $ssl_client_s_dn;
        proxy_set_header X-Client-SSL-Verify $ssl_client_verify;
        proxy_set_header Host $http_host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;

    The uvicorn server must be run with the '--proxy-headers' setting
    to parse the X-Forwarded-For header set by nginx and present it
    to the web application as client IP
    '''

    def __init__(self, tls_status: TlsStatus,
                 client_dn: str, issuing_ca_dn: str,
                 remote_addr: IpAddress):
        '''
        Get the authentication info for the client that made the API call.
        Information from the M-TLS client cert takes priority over any future
        support for Json Web Token (JWT). The reverse proxy has already
        validated that the client calling the API is the owner of the private
        key for the certificate it presented so we trust the HTTP headers set
        by the reverse proxy

        :param tls_status: instance of TlsStatus enum
        :param client_dn: designated name of the presented client TLS cert
        :param issuing_ca_dn: designated name of the issuing CA for the
        presented TLS client cert
        information in the request for authentication
        :returns: (n/a)
        :raises: ValueError if the no authentication is available and the
        parameter 'required' has a value of True. AuthFailure if authentication
        was provided but is incorrect, regardless of the value of the
        'required' parameter
        '''

        self.is_authenticated = False
        self.remote_addr = remote_addr

        self.client_cn = None
        self.issuing_ca_cn = None
        self.account_id = None
        self.service_id = None
        self.member_id = None

        #
        # Process the headers and if auth is 'required', throw
        # exceptions based on misformed DN/CN in certs
        #
        if (isinstance(tls_status, TlsStatus) and
                tls_status not in (TlsStatus.NONE, TlsStatus.SUCCESS)):
            raise HTTPException(
                status_code=400, detail=f'Client TLS status is {tls_status}'
            )
        elif not tls_status:
            raise NoAuthInfo

        if client_dn:
            self.client_cn = RequestAuth.get_commonname(client_dn)
        else:
            raise NoAuthInfo

        if issuing_ca_dn:
            self.issuing_ca_cn = RequestAuth.get_commonname(issuing_ca_dn)
        else:
            raise NoAuthInfo

        if (self.client_cn and ((self.client_cn == self.issuing_ca_cn)
                                or not self.issuing_ca_cn)):
            # Somehow a self-signed cert made it through the certchain check
            _LOGGER.warning(
                'Misformed cert was proxied by reverse proxy, Client DN: '
                f'{client_dn}: Issuing CA DN: {issuing_ca_dn}'
            )
            raise HTTPException(
                status_code=400,
                detail=(
                    f'Client provided a self-signed or unsigned cert: '
                    f'{client_dn}'
                )
            )

    @staticmethod
    def get_commonname(dname: str) -> str:
        '''
        Extracts the commonname from a distinguished name in a x.509
        certificate

        :param dname: x509 distinguished name
        :returns: commonname
        :raises: ValueError if the commonname could not be extracted
        '''

        bits = dname.split(',')
        for keyvalue in bits:
            if keyvalue.startswith('CN='):
                commonname = keyvalue[(len('CN=')):]
                return commonname

        raise HTTPException(
            status_code=403,
            detail=f'Invalid format for distinguished name: {dname}'
        )