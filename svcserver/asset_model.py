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

import os
import yaml

from uuid import UUID
from typing import Self
from datetime import datetime

import orjson

from aredis_om.connections import get_redis_connection

from aredis_om import JsonModel, HashModel, Field as Field

from pydantic import BaseModel

# redis-om does not support lists of nested models so we need to serialize
# the lists to strings.
PRIMARY_STRING_SEPARATOR: str = '___byoda___'
SECONDARY_STRING_SEPARATOR: str = '_____byoda_____'

with open(os.environ.get('CONFIG_FILE', 'config.yml')) as file_desc:
    REDIS_URL: str = yaml.safe_load(file_desc)['svcserver']['cache']

class Video_chapter(JsonModel):
    chapter_id: str = Field(description="The UUID of the video chapter")
    start: str = Field(description="The start of the chapter, as an offset in seconds from the start of the video")
    end: str = Field(description="The start of the chapter, as an offset in seconds from the start of the video")
    title: str | None = Field(default=None, description="The title of the chapter")

    class Meta:
        embedded: bool = True


class Video_thumbnail(JsonModel):
    thumbnail_id: str = Field(description="The UUID of the video thumbnail")
    width: str = Field(description="The width of the thumbnail")
    height: str = Field(description="The height of the thumbnail")
    size: str | None = Field(default=None, description="a textual description of the resolution of the thumbnail, ie. '640x480' or '4k'")
    preference: str | None = Field(default=None, description="The preference of the thumbnail, ie. 'default', 'high', 'medium', 'low'")
    url: str = Field(description="The URL of the thumbnail")

    class Meta:
        embedded: bool = True


class Claim(JsonModel):
    claim_id: str = Field(primary_key=True, description="The UUID of the claim")
    cert_expiration: str = Field(description="the timestamp when the cert used to create the signature expires")
    cert_fingerprint: str = Field(description="the SHA2-256 fingerprint of the certificate used to sign the claim")
    issuer_id: str = Field(description="The UUID of the claim issuer")
    issuer_type: str = Field(description="what type of entity issued this claim")
    keyfield: str = Field(description="name of the field used to identify the object, ie. 'asset_id'. The field must be of type 'UUID'")
    keyfield_id: str = Field(description="The UUID of the keyfield of the claim")
    object_fields: list[str] = Field(description="The fields covered by the signature of the object with ID 'object_id' stored in the array 'object_type'")
    object_type: str = Field(description="The name of the array storing the object of the claim, ie. 'public_assets' and not 'asset'. The array must store objects that have a data property 'asset_id'")
    requester_id: str = Field(description="The UUID of the entity that requested the claim to be signed by the issuer")
    requester_type: str = Field(description="what type of entity requested this claim to be signed by the issuer")
    signature: str = Field(description="base64-encoding signature for the values for the 'object_fields' of the object with uuid 'object_id' of type 'object_class'")
    signature_format_version: str = Field(description="The version of the signature format used. Each version defines the hashing algorithm and how to format the data to be signed. The formats are defined in byoda-python/byoda/datamodel/claim.py")
    signature_timestamp: str = Field(description="Date &amp; time for when the signature was created")
    signature_url: str = Field(description="URL to visit to get additional info about the signature")
    renewal_url: str = Field(description="URL to request new signature of the asset")
    confirmation_url: str = Field(description="URL of API to call to confirm the signature has not been revoked")
    claims: list[str] | None = Field(default=None, description="The claims that are validated by the issuer")

    class Meta:
        embedded: bool = True

class Monetization(JsonModel):
    monetization_id: str = Field(primary_key=True, description="The UUID of the monetization")
    monetization_scheme: str = Field(description="The scheme of the monetization, ie. 'pay-per-view', 'subscription', etc.")

    class Meta:
        embedded: bool = True
class Asset(JsonModel):
    asset_id: UUID = Field(primary_key=True, description="The UUID of the asset")
    asset_type: str = Field(index=True, description="type of asset, ie. a tweet, a message, a video, etc.")
    created_timestamp: datetime = Field(index=True, description="time the asset was added to the pod")
    annotations: list[str] | None = Field(default=None, description="annotations for the asset, things like 'genre:action' or 'city:San Francisco'")
    asset_merkle_root_hash: str | None = Field(default=None, description="the base64-encoded merkle root hash of the asset. The full hash tree can be downloaded by taking the asset_url and replace the filename in that url with 'merkle-tree.db'")
    asset_url: str | None = Field(default=None, description="type of asset, ie. a tweet, a message, a video, etc.")
    channel_id: UUID | None = Field(default=None, description="UUID of the channel, if any, that the asset was posted to")
    content_warnings: list[str] | None = Field(default=None, description="list of terms with potential triggers, such as violence, or cursing")
    contents: str | None = Field(default=None, full_text_search=True, description="text for the asset")
    copyright_years: list[str] | None = Field(default=None, description="Years for which copyright is asserted")
    creator: str | None = Field(default=None, description="creator of the asset")
    ingest_status: str | None = Field(default=None, description="status of the ingest process")
    keywords: list[str] | None = Field(default=None, description="comma-separated list of keywords")
    locale: str | None = Field(default=None, description="locale for the metadata, ie. en_US")
    monetizations: list[str] | None = Field(default=None, description="enabled monetizations for the asset")
    published_timestamp: datetime | None = Field(default=None, description="date-time of first publication of the content")
    publisher: str | None = Field(default=None, description="the publisher of the asset")
    publisher_asset_id: str | None = Field(default=None, description="Identifier of the asset set by the publisher")
    screen_orientation_horizontal: bool | None = Field(default=None, description="Whether content is optimized for consumption on a screen with horizontal orietation")
    subject: str | None = Field(default=None, full_text_search=True, description="a brief description of the asset")
    title: str | None = Field(default=None, full_text_search=True, description="title of the asset")
    _meta_member_id: UUID = Field(index=True)
    _meta_last_updated: datetime = Field(index=True)
    _meta_asset_visibility: str = Field(default='public', description="visibility of the asset, ie. 'public', 'network', 'private', etc.")
    _meta_cursor: str = Field(index=True)

    claims: list[Claim] | None = Field(default=None, description="list of claims for the asset")
    video_chapters: list[Video_chapter] | None = Field(default=None, description="list of video chapters for the asset")
    video_thumbnails: list[Video_thumbnail] | None = Field(default=None, description="list of thumbnails for the asset")
    monetizations: list[Monetization] | None = Field(default=None, description="list of monetizations for the asset")

    class Meta:
        global_key_prefix: str = 'service:assetdb:assets:'
        #database = get_redis_connection(url=REDIS_URL, decode_responses=True)