'''
API models for service schema aka. data contracts

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from logging import getLogger
from byoda.util.logger import Logger

from pydantic import BaseModel

from byoda.datatypes import ReviewStatusType

_LOGGER: Logger = getLogger(__name__)


class SchemaModel(BaseModel):
    service_id: int
    version: int
    name: str
    description: str
    owner: str
    website: str
    supportemail: str
    cors_origins: list[str]
    signatures: dict
    # Can't use 'schema' as property as it conflicts with a property
    # of the pydantic.BaseModel class
    jsonschema: dict
    listen_relations: list[dict[str, str | list[str]]]
    max_query_depth: int = 1

    def __repr__(self):
        return ('<SchemaModel)={ServiceId: str}>')

    def as_dict(self):
        return {
            'service_id': self.service_id,
            'version': self.version,
            'name': self.name,
            'description': self.description,
            'owner': self.owner,
            'website': self.website,
            'supportemail': self.supportemail,
            'cors_origins': self.cors_origins,
            'signatures': self.signatures,
            'jsonschema': self.jsonschema,
            'listen_relations': self.listen_relations,
            'max_query_depth': self.max_query_depth,
        }


class SchemaResponseModel(BaseModel):
    status: ReviewStatusType
    errors: list[str]
    timestamp: str

    class Config:
        use_enum_values = True

    def __repr__(self):
        return (
            '<SchemaResponseModel={status: str, errors: list[str],'
            ' timestamp: str}>'
        )

    def as_dict(self):
        return {
            'status': self.status,
            'errors': self.errors,
            'timestamp': self.timestamp,
        }
