'''
TODO: Obsolete, can be removed
Schema for server to server APIs

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging

from marshmallow import fields, Schema


_LOGGER = logging.getLogger(__name__)


class ServerApiRequestSchema(Schema):
    ipv4_address = fields.IPv4()
    name = fields.String()
    public_key = fields.String()


class ServerApiResponseSchema(Schema):
    name = fields.String()
    ipv4_address = fields.Integer()
    roles = fields.List(fields.String())
    cert = fields.String()
    networks = fields.List(fields.Integer())
