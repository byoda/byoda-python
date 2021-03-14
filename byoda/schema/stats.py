'''
Schema for server to server APIs

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from marshmallow import fields, Schema


_LOGGER = logging.getLogger(__name__)


class Stats:
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


class StatsResponseSchema(Schema):
    accounts = fields.Int()
    services = fields.Int()
    uuid = fields.UUID()
    remote_addr = fields.Str()
    dns_update = fields.Boolean()
