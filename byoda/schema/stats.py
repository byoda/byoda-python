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
    def __init__(self, accounts, services, uuid, remote_addr):
        self.accounts = accounts
        self.services = services
        self.uuid = uuid
        self.remote_addr = remote_addr

    def __repr__(self):
        return (
            f'<Stats(accounts={self.accounts},services={self.services},'
            f'uuid={self.uuid},remote_addr={self.remote_addr})>'
        )


class StatsResponseSchema(Schema):
    accounts = fields.Int()
    services = fields.Int()
    uuid = fields.UUID()
    remote_addr = fields.Str()
