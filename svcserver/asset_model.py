'''
Defines the Redis/FastAPI/Pydantic model for the 'public_assets' data class in the
service schema. This is hardcoded so needs to be kept alligned to the schema. We can
extract the code from:
  byoda-python/podserver/codegen/pydnatic_service_<service_id>_<schema_version>.py
and replace 'BaseModel' with 'JsonModel

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

# flake8: noqa: E501

from uuid import UUID
from typing import Self
from datetime import datetime

import orjson

from aredis_om import JsonModel, HashModel, Field as OMField

from pydantic import BaseModel
from pydantic import Field as PydanticField

# redis-om does not support lists of nested models so we need to serialize
# the lists to strings.
PRIMARY_STRING_SEPARATOR: str = '___byoda___'
SECONDARY_STRING_SEPARATOR: str = '_____byoda_____'

class Video_chapter(BaseModel):
    chapter_id: UUID = PydanticField(description="The UUID of the video chapter")
    start: float = PydanticField(description="The start of the chapter, as an offset in seconds from the start of the video")
    end: float = PydanticField(description="The start of the chapter, as an offset in seconds from the start of the video")
    title: str | None = PydanticField(default=None, description="The title of the chapter")

    def __str__(self) -> str:
        data = self.model_dump()
        return orjson.dumps(data).decode('utf-8')

    @staticmethod
    def from_str(chapter: str) -> Self:
        json_data = orjson.loads(chapter)
        return Video_chapter(**json_data)


class Video_thumbnail(BaseModel):
    thumbnail_id: UUID = PydanticField(description="The UUID of the video thumbnail")
    width: float = PydanticField(description="The width of the thumbnail")
    height: float = PydanticField(description="The height of the thumbnail")
    size: str | None = PydanticField(default=None, description="a textual description of the resolution of the thumbnail, ie. '640x480' or '4k'")
    preference: str | None = PydanticField(default=None, description="The preference of the thumbnail, ie. 'default', 'high', 'medium', 'low'")
    url: str = PydanticField(description="The URL of the thumbnail")

    def __str__(self) -> str:
        data = self.model_dump()
        return orjson.dumps(data).decode('utf-8')

    @staticmethod
    def from_str(thumbnail: str) -> Self:
        json_data = orjson.loads(thumbnail)
        return Video_thumbnail(**json_data)


class Claim(BaseModel):
    claim_id: UUID = PydanticField(description="The UUID of the claim")
    cert_expiration: datetime = PydanticField(description="the timestamp when the cert used to create the signature expires")
    cert_fingerprint: str = PydanticField(description="the SHA2-256 fingerprint of the certificate used to sign the claim")
    issuer_id: UUID = PydanticField(description="The UUID of the claim issuer")
    issuer_type: str = PydanticField(description="what type of entity issued this claim")
    keyfield: str = PydanticField(description="name of the field used to identify the object, ie. 'asset_id'. The field must be of type 'UUID'")
    keyfield_id: UUID = PydanticField(description="The UUID of the keyfield of the claim")
    object_fields: list[str] = PydanticField(description="The fields covered by the signature of the object with ID 'object_id' stored in the array 'object_type'")
    object_type: str = PydanticField(description="The name of the array storing the object of the claim, ie. 'public_assets' and not 'asset'. The array must store objects that have a data property 'asset_id'")
    requester_id: UUID = PydanticField(description="The UUID of the entity that requested the claim to be signed by the issuer")
    requester_type: str = PydanticField(description="what type of entity requested this claim to be signed by the issuer")
    signature: str = PydanticField(description="base64-encoding signature for the values for the 'object_fields' of the object with uuid 'object_id' of type 'object_class'")
    signature_format_version: str = PydanticField(description="The version of the signature format used. Each version defines the hashing algorithm and how to format the data to be signed. The formats are defined in byoda-python/byoda/datamodel/claim.py")
    signature_timestamp: datetime = PydanticField(description="Date &amp; time for when the signature was created")
    signature_url: str = PydanticField(description="URL to visit to get additional info about the signature")
    renewal_url: str = PydanticField(description="URL to request new signature of the asset")
    confirmation_url: str = PydanticField(description="URL of API to call to confirm the signature has not been revoked")
    claims: list[str] | None = PydanticField(default=None, description="The claims that are validated by the issuer")

    def __str__(self) -> str:
        data = self.model_dump()
        return orjson.dumps(data).decode('utf-8')

    @staticmethod
    def from_str(claim_data: str) -> Self:
        data = orjson.loads(claim_data)
        return Claim(**data)

class Test(JsonModel):
    test: str = OMField(description="test")

    class Meta:
        embedded: bool = True

class Asset(JsonModel):
    asset_id: UUID = OMField(primary_key=True, description="The UUID of the asset")
    asset_type: str = OMField(index=True, description="type of asset, ie. a tweet, a message, a video, etc.")
    created_timestamp: datetime = OMField(index=True, description="time the asset was added to the pod")
    annotations: list[str] | None = OMField(default=None, description="annotations for the asset, things like 'genre:action' or 'city:San Francisco'")
    asset_merkle_root_hash: str | None = OMField(default=None, description="the base64-encoded merkle root hash of the asset. The full hash tree can be downloaded by taking the asset_url and replace the filename in that url with 'merkle-tree.db'")
    asset_url: str | None = OMField(default=None, description="type of asset, ie. a tweet, a message, a video, etc.")
    channel_id: UUID | None = OMField(default=None, description="UUID of the channel, if any, that the asset was posted to")
    content_warnings: list[str] | None = OMField(default=None, description="list of terms with potential triggers, such as violence, or cursing")
    contents: str | None = OMField(default=None, full_text_search=True, description="text for the asset")
    copyright_years: list[str] | None = OMField(default=None, description="Years for which copyright is asserted")
    creator: str | None = OMField(default=None, description="creator of the asset")
    encoding_profiles: list[str] | None = OMField(default=None, description="DEPRECATED: encoding profile used for the asset")
    forum: str | None = OMField(default=None, description="forum, if any, that the asset was posted to")
    ingest_status: str | None = OMField(default=None, description="status of the ingest process")
    keywords: list[str] | None = OMField(default=None, description="comma-separated list of keywords")
    locale: str | None = OMField(default=None, description="locale for the metadata, ie. en_US")
    monetizations: list[str] | None = OMField(default=None, description="enabled monetizations for the asset")
    published_timestamp: datetime | None = OMField(default=None, description="date-time of first publication of the content")
    publisher: str | None = OMField(default=None, description="the publisher of the asset")
    publisher_asset_id: str | None = OMField(default=None, description="Identifier of the asset set by the publisher")
    screen_orientation_horizontal: bool | None = OMField(default=None, description="Whether content is optimized for consumption on a screen with horizontal orietation")
    subject: str | None = OMField(default=None, full_text_search=True, description="a brief description of the asset")
    title: str | None = OMField(default=None, full_text_search=True, description="title of the asset")
    _meta_member_id: UUID = OMField(index=True)
    _meta_last_updated: datetime = OMField(index=True)

    claims: list[str] | None = OMField(default=None, description="list of claims for the asset")
    video_chapters: list[str] | None = OMField(default=None, description="list of video chapters for the asset")
    video_thumbnails: list[str] | None = OMField(default=None, description="list of thumbnails for the asset")
    cursor: str = OMField(index=True)
    tests: list[Test] | None = OMField(default=None, description="list of tests for the asset")

    class Meta:
        global_key_prefix: str = 'service:assetdb'