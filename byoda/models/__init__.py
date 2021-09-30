'''
Models for input and output of FastAPI APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

# flake8: noqa=F401
from .stats import Stats, StatsResponseModel
from .cert import CertSigningRequestModel
from .cert import SignedCertResponseModel
from .ipaddress import IpAddressResponseModel
from .service import ServiceSummariesResponseModel

# from .letsencrypt import LetsEncryptSecretModel
