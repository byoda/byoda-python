'''
Cert manipulation for accounts and members

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from byoda.util import Paths

from byoda.datatypes import CsrSource

from . import Secret, CSR

_LOGGER = logging.getLogger(__name__)


class DataSecret(Secret):
    def __init__(self, paths: Paths):
        '''
        Class for the data secret for a pod

        :param paths: instance of Paths class defining the directory structure
        and file names of a BYODA network
        :returns: (none)
        :raises: (none)
        '''

        super().__init__(
            cert_file=paths.get(Paths.DATA_CERT_FILE),
            key_file=paths.get(Paths.DATA_KEY_FILE),
            storage_driver=paths.storage_driver
        )
        self.ca = False

    def create(self, expire: int = 36500):
        '''
        Creates an RSA private key and X.509 cert

        :param int expire: days after which the cert should expire
        :returns: (none)
        :raises: ValueError if the Secret instance already has a private key
                 or cert

        '''

        common_name = f'data-{self.account}'
        super().create(common_name, expire=expire, key_size=4096, ca=self.ca)

    def create_csr(self, expire: int = 3650):
        raise NotImplementedError

    def review_commonname(commonname: str):
        raise NotImplementedError

    def review_csr(self, csr: CSR, source=CsrSource.WEBAPI):
        raise NotImplementedError
