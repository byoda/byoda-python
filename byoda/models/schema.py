'''
API models for service schema aka. data contracts

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging

from pydantic import BaseModel
from typing import Dict, List

from byoda.datatypes import ReviewStatusType

_LOGGER = logging.getLogger(__name__)


class SchemaModel(BaseModel):
    service_id: int
    version: int
    name: str
    description: str
    owner: str
    website: str
    supportemail: str
    signatures: Dict
    # Can't use 'schema' as property as it conflicts with a property
    # of the pydantic.BaseModel class
    jsonschema: Dict

    def __repr__(self):
        return('<SchemaModel)={ServiceId: str}>')

    def as_dict(self):
        return {
            'service_id': self.service_id,
            'version': self.version,
            'name': self.name,
            'description': self.description,
            'owner': self.owner,
            'website': self.website,
            'supportemail': self.supportemail,
            'signatures': self.signatures,
            'jsonschema': self.jsonschema,
        }


class SchemaResponseModel(BaseModel):
    status: ReviewStatusType
    errors: List[str]
    timestamp: str

    class Config:
        use_enum_values = True

    def __repr__(self):
        return(
            '<SchemaResponseModel={status: str, errors: List[str],'
            ' timestamp: str}>'
        )

    def as_dict(self):
        return {
            'status': self.status,
            'errors': self.errors,
            'timestamp': self.timestamp,
        }
