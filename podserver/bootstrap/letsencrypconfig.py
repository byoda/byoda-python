'''
Bootstrap a Let's Encrypt TLS cert

TODO: This is dead code as support for Let's Encrypt is pushed out. Considering
to use certbot with byoda-dns extension script or sub-git certbot code
base and hook in to logic there.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import datetime

from byoda.util.secrets import TlsSecret

from byoda.datatypes import CertStatus

from .targetconfig import TargetConfig

_LOGGER = logging.getLogger(__name__)


class LetsEncryptConfig(TargetConfig):
    def __init__(self, tls_secret: TlsSecret):
        '''
        Constructor for LetsEncryptConfig

        :param paths: instance with all file locations
        :param fqdn: FQDN to use for LetsEncrypt SSL cert
        '''

        self.tls_secret = tls_secret

    def exists(self):
        try:
            self.tls_secret.cert_file_exists()
            self.tls_secret.load()

            # We want to renew if cert expiration is within 30 days
            now = datetime.datetime.utcnow()
            expires = self.tls_secret.cert.not_valid_after
            if now + datetime.timedelta(days=30) < expires:
                return CertStatus.OK
            elif now < expires:
                return CertStatus.EXPIRED
        except OSError as exc:
            with open('/var/www/wwwroot/index.html', 'w') as file_desc:
                file_desc.write('<HTML><BODY>SSL cert does not exist')
                file_desc.write(f'{exc}</BODY></HTML>')

        return CertStatus.NOTFOUND

    def create(self):
        csr = self.tls_secret.create_csr()
        self.tls_secret.get_csr_signature(csr)
        self.tls_secret.save()
