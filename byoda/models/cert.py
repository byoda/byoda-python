'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
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


class SignedAccountCertResponseModel(BaseModel):
    signed_cert: str
    cert_chain: str
    network_data_cert_chain: str

    def __repr__(self):
        return (
            '<SignedAccountCertResponseModel={certchain: Dict[str:str], '
            'network_data_cert_chain: str}>'
        )

    def as_dict(self):
        return {
            'signed_cert': {
                'cert': self.certchain.signed_cert,
                'certchain': self.certchain.cert_chain
            },
            'network_data_cert_chain': self.network_data_cert_chain
        }


class SignedServiceCertResponseModel(BaseModel):
    signed_cert: str
    cert_chain: str
    network_data_cert_chain: str

    def __repr__(self):
        return (
            '<SignedServiceCertResponseModel={certchain: Dict[str:str], '
            'network_data_cert_chain: str}>'
        )

    def as_dict(self):
        return {
            'signed_cert': {
                'cert': self.certchain.signed_cert,
                'certchain': self.certchain.cert_chain
            },
            'network_data_cert_chain': self.network_data_cert_chain
        }


class SignedMemberCertResponseModel(BaseModel):
    signed_cert: str
    cert_chain: str
    service_data_cert_chain: str

    def __repr__(self):
        return (
            '<SignedNetworkCertResponseModel={certchain: Dict[str:str], '
            'service_data_cert_chain: str}>'
        )

    def as_dict(self):
        return {
            'signed_cert': {
                'cert': self.certchain.signed_cert,
                'certchain': self.certchain.cert_chain
            },
            'service_data_cert_chain': self.service_data_cert_chain
        }
