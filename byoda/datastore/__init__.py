'''
Datastores provide interfaces for data in persistent storage,
regardless of storage technologies used. Implementations of specific
storage technologies are in the byoda.storage module

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

# flake8: noqa=E221
from .dnsdb import DnsDb
from .certstore import CertStore
from .document_store import DocumentStore
from .document_store import DocumentStoreType
