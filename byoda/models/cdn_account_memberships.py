'''
Schema for pod to report its memberships to the CDN

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from uuid import UUID

from pydantic import BaseModel

from byoda.datatypes import StorageType


class BucketMap(BaseModel):
    storage_type: StorageType
    container: str


class CdnAccountOriginsRequestModel(BaseModel):
    service_id: int
    member_id: UUID
    buckets: dict[str, str]
