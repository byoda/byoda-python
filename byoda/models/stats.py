'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID
from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

from ipaddress import IPv4Address

_LOGGER: Logger = getLogger(__name__)


class Stats():
    def __init__(self, accounts, services, uuid, remote_addr, dns_update):
        self.accounts = accounts
        self.services = services
        self.uuid = uuid
        self.remote_addr = remote_addr
        self.dns_update = dns_update

    def __repr__(self):
        return (
            f'<Stats(accounts={self.accounts},services={self.services},'
            f'uuid={self.uuid},remote_addr={self.remote_addr},'
            f'dns_update={self.dns_update})>'
        )

    def as_dict(self):
        return {
            'accounts': self.accounts,
            'services': self.services,
            'uuid': self.uuid,
            'remote_addr': self.remote_addr,
            'dns_update': self.dns_update
        }


class StatsResponseModel(BaseModel):
    accounts: int
    services: int
    dns_update: bool
    remote_addr: IPv4Address
    uuid: UUID | None = None
