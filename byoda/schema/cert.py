'''
Schema for server to server APIs

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from dataclasses import dataclass

from marshmallow import fields, Schema, post_load


_LOGGER = logging.getLogger(__name__)


class Cert:
    def __init__(self, certificate):
        self.certificate = certificate


class CertResponseSchema(Schema):
    certificate = fields.String()


@dataclass
class CertSigningRequest:
    csr: str


class CertSigningRequestSchema(Schema):
    csr = fields.String()

    @post_load
    def make(self, data, **kwargs):
        return CertSigningRequest(**data)
