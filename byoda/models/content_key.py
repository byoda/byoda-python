'''
Schema for server to server APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

from uuid import UUID
from datetime import datetime

from pydantic import BaseModel
from pydantic import Field

from byoda.datatypes import IdType


# Copied from podserver/codegen/pydantic_service_*_?.py
class Claim(BaseModel):
    cert_expiration: datetime = Field(
        description=(
            'the timestamp when the cert used to create the signature expires'
        )
    )
    cert_fingerprint: str = Field(
        description=(
            'the SHA2-256 fingerprint of the certificate used to sign the '
            'claim'
        )
    )
    claim_id: UUID = Field(
        description='The UUID of the claim, unique to the signer of the claim'
    )
    confirmation_url: str = Field(
        description=(
            'URL of API to call to confirm the signature has not been revoked'
        )
    )
    issuer_id: UUID = Field(description='The UUID of the claim issuer')
    issuer_type: IdType = Field(
        description='what type of entity issued this claim'
    )
    keyfield: str = Field(
        description=(
            'name of the field used to identify the object, ie. asset_id. '
            'The field must be of type UUID'
        )
    )
    keyfield_id: UUID = Field(
        description='The UUID of the keyfield of the claim'
    )
    object_fields: list[str] = Field(
        description=(
            'The fields covered by the signature of the object with '
            'ID object_id stored in the array object_type'
        )
    )
    renewal_url: str = Field(
        description='URL to request new signature of the asset'
    )
    requester_id: UUID = Field(
        description=(
            'The UUID of the entity that requested the claim '
            'to be signed by the issuer'
        )
    )
    requester_type: str = Field(
        description=(
            'what type of entity requested this claim to '
            'be signed by the issuer'
        )
    )
    signature: str = Field(
        description=(
            'base64-encoding signature for the values for the object_fields '
            'of the object with uuid object_id of type object_class'
        )
    )
    signature_format_version: int = Field(
        description=(
            'The version of the signature format used. Each version defines '
            'the hashing algorithm and how to format the data to be signed. '
            'The formats are defined in byoda-python/byoda/datamodel/claim.py'
        )
    )
    signature_timestamp: datetime = Field(
        description='Date & time for when the signature was created'
    )
    signature_url: str = Field(
        description='URL to visit to get additional info about the signature'
    )
    claims: list[str] | None = Field(
        default=None, description='The claims that are validated by the issuer'
    )
    object_type: str | None = Field(
        default=None,
        description=(
            'The name of the array storing the object of the claim, ie. '
            'public_assets and not asset. The array must store objects that '
            'have a data property asset_id'
        )
    )


# Must stay in sync with byopay:payserver.models.BurstAttestResponsemodel
class BurstAttestModel(BaseModel):
    created_timestamp: datetime
    attest_id: UUID
    service_id: int
    member_id: UUID
    member_type: IdType
    burst_points_greater_equal: int
    claims: list[Claim] = []


class ContentTokenRequestModel(BaseModel):
    service_id: int
    asset_id: UUID
    member_id: UUID | None = None
    member_id_type: IdType | None = None
    attestation: BurstAttestModel | None = None


class ContentTokenResponseModel(BaseModel):
    key_id: int
    content_token: str

    def __repr__(self) -> str:
        return ('<ContentToken=(key_id: int, content_token: str)>')

    def as_dict(self) -> dict[str, any]:
        return {
            'key_id': self.key_id,
            'content_token': self.content_token
        }


class ContentKeyRequestModel(BaseModel):
    key_id: int = Field(gt=0)
    key: str
    not_before: datetime
    not_after: datetime

    def __repr__(self) -> str:
        return (
            '<ContentKeyRequestModel=(key_id: int, key: str, '
            'not_before: datetime, not_after: datetime)>'
        )

    def as_dict(self) -> dict[str, str | int | datetime]:
        return {
            'key_id': self.key_id,
            'key': self.key,
            'not_before': self.not_before,
            'not_after': self.not_after
        }
