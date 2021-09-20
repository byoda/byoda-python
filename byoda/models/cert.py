'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class CertSigningRequestModel(BaseModel):
    csr: str

    def __repr__(self):
        return ('<Cert=(csr: str)>')

    def as_dict(self):
        return {'certsigningrequest': self.csr}


class CertChainModel(BaseModel):
    cert_chain: str
    signed_cert: str

    def __repr__(self):
        return ('<CertChainModel=(certchain: str)>')

    def as_dict(self):
        return {
            'signed_cert': self.signed_cert,
            'cert_chain': self.cert_chain
        }
