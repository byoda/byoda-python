'''
Schema for server to server APIs

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
from dataclasses import dataclass

from marshmallow import fields, Schema, post_load, ValidationError


_LOGGER = logging.getLogger(__name__)


class BytesField(fields.Field):
    def _validate(self, value):
        if not isinstance(value, bytes):
            raise ValidationError('Invalid input type.')

        if value is None or value == b'':
            raise ValidationError('Invalid value')


@dataclass
class Cert:
    certificate: str


class CertResponseSchema(Schema):
    certificate = fields.String()

    @post_load
    def make(self, data, **kwargs):
        return Cert(**data)


@dataclass
class CertSigningRequest:
    csr: str


class CertSigningRequestSchema(Schema):
    csr = fields.Str(required=True)

    @post_load
    def make(self, data, **kwargs):
        return CertSigningRequest(**data)
