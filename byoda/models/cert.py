'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from pydantic import BaseModel

_LOGGER = logging.getLogger(__name__)


class CertChainRequestModel(BaseModel):
    certchain: str

    def __repr__(self):
        return ('<CertChain=(certchain: str)>')

    def as_dict(self):
        return {'certchainrequest': self.certchain}


class CertSigningRequestModel(BaseModel):
    csr: str

    def __repr__(self):
        return ('<Csr=(csr: str)>')

    def as_dict(self):
        return {'certsigningrequest': self.csr}


class SignedCertResponseModel(BaseModel):
    signed_cert: str
    cert_chain: str
    network_root_ca_cert: str
    data_cert: str

    def __repr__(self):
        return(
            '<SignedCertResponseModel={certchain: Dict[str:str], '
            'root_ca: str, data_cert: str}>'
        )

    def as_dict(self):
        return {
            'signed_cert': {
                'cert': self.certchain.signed_cert,
                'certchain': self.certchain.cert_chain
            },
            'network_root_ca_cert': str,
            'network_data_cert': str
        }
