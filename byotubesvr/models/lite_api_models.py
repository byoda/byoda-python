'''
Pydantic model used for BYO.Tube Lite accounts

These are copied from the models generated by the podserver and should be kept
in sync with changes in the BYO.Tube data schema.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024, 2024
:license    : GPLv3
'''

from uuid import UUID
from uuid import uuid4
from datetime import datetime

from pydantic import Field
from pydantic import BaseModel
from pydantic import HttpUrl


class SettingsRequestModel(BaseModel):
    nick: str | None = Field(
        default=None, max_length=24, pattern=r'^[a-zA-Z0-9_\-\.]*$',
        description='The nickname of the BYO.Tube-lite account'
    )
    show_external_assets: bool | None = Field(
        default=None, description='Show videos streaming from other platforms'
    )


class SettingsResponseModel(BaseModel):
    nick: str = Field(
        default=None, max_length=24, pattern=r'^[a-zA-Z0-9_\-\.]*$',
        description='The nickname of the BYO.Tube-lite account'
    )
    show_external_assets: bool | None = Field(
        default=None, description='Show videos streaming from other platforms'
    )


class NetworkLinkRequestModel(BaseModel):
    member_id: UUID = Field(description="The UUID of the other member")
    relation: str = Field(
        description="What relation you have with the other member"
    )
    annotations: set[str] | None = Field(
        default=None,
        description=(
            'annotations for the network link, for example if a ByoTuber '
            'has multiple channels then the specific channel that you want '
            'to follow'
        )
    )

    def __eq__(self, other) -> bool:
        result: bool = (
            self.network_link_id == other.network_link_id
            and self.member_id == other.member_id
            and self.relation == other.relation
            and sorted(self.annotations) == sorted(other.annotations)
        )
        return result


class NetworkLinkResponseModel(BaseModel):
    created_timestamp: datetime = Field(
        default=None, description="time the network link was created"
    )
    network_link_id: UUID = Field(
        default=uuid4(), description="The UUID of the network link"
    )
    member_id: UUID = Field(description="The UUID of the other member")
    relation: str = Field(
        description="What relation you have with the other member"
    )
    annotations: set[str] | None = Field(
        default=None,
        description=(
            'annotations for the network link, for example if a ByoTuber '
            'has multiple channels then the specific channel that you want '
            'to follow'
        )
    )

    def __eq__(self, other) -> bool:
        result: bool = (
            self.network_link_id == other.network_link_id
            and self.member_id == other.member_id
            and self.relation == other.relation
            and sorted(self.annotations) == sorted(other.annotations)
        )
        return result


class AssetReactionRequestModel(BaseModel):
    '''
    Pydantic model used for BYO.Tube Lite accounts, copy from byotube.json
    '''

    member_id: UUID = Field(
        description=(
            'The UUID of the member that owns the asset or the member '
            'that created the reaction'
        )
    )
    asset_id: UUID = Field(
        description='The UUID of the asset that the reaction is for'
    )
    asset_url: HttpUrl = Field(
        description='The playback URL for the asset'
    )
    asset_class: str = Field(
        description='The data class of the asset, ie. public_assets'
    )
    relation: str | None = Field(
        default=None,
        description='The relation of the member to the asset, ie. like'
    )
    bookmark: str | None = Field(
        default=None,
        description='Bookmark where to resume consumption of the asset'
    )
    keywords: list[str] = Field(
        default=[], description=(
            'Keywords for the asset, copied from the metadata of the asset'
        )
    )
    annotations: list[str] = Field(
        default=[], description=(
            'Annotations for the asset, copied from the metadata of the asset'
        )
    )
    categories: list[str] = Field(
        default=[], description=(
            'Categories for the asset, copied from the metadata of the asset'
        )
    )
    list_name: str | None = Field(
        default=None, description='The name of the list to put the asset in'
    )


class AssetReactionResponseModel(AssetReactionRequestModel):
    '''
    Pydantic model used for BYO.Tube Lite accounts, copy from byotube.json
    '''

    created_timestamp: datetime = Field(
        description="time the asset reaction was created"
    )
