'''
Imports for the pydantic data models we generate

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

# flake8: noqa: E501

from uuid import UUID
from datetime import datetime

from pydantic import Field

# We define our own BaseModel that inherits from pydantic's BaseModel
# so that we can add our own custom fields and methods to it.
from byoda.models.data_api_models import BaseModel

class annotation(BaseModel):
    annotation_id: UUID = Field(description="The UUID of the annotation")
    asset_id: UUID = Field(description="The ID of the public_asset that this annotation is for")
    key: str | None = Field(default=None, description="The key for the annotation")


class app_url(BaseModel):
    app_id: UUID = Field(description="the UUID for the app")
    name: str = Field(description="the functionality provided by the app at this URL")
    url: str = Field(description="the url for the API")


class asset_link(BaseModel):
    created_timestamp: datetime = Field(description="time the asset link was created")
    member_id: UUID = Field(description="The UUID of the member that published the asset")
    relation: str = Field(description="What relation you have with asset, such as read, liked, etc.")
    asset_id: UUID | None = Field(default=None, description="The UUID of the asset")
    asset_url: str | None = Field(default=None, description="URL to an asset not hosted by a member of the service")
    signature: str | None = Field(default=None, description="the digital signature using our data cert of the concatenation of member_id, asset_id, asset_url, and relation")


class asset_reaction(BaseModel):
    asset_id: UUID = Field(description="The UUID of our asset")
    created_timestamp: datetime = Field(description="time the reaction was created")
    member_id: UUID = Field(description="The UUID of the member that reacted to our asset")
    relation: str = Field(description="What relation the other member has with our asset, for example liked")
    asset_class: UUID | None = Field(default=None, description="The UUID of our asset")


class channel(BaseModel):
    channel_id: UUID | None = Field(default=None, description="The uuid of the channel")
    created_timestamp: datetime | None = Field(default=None, description="time the asset was created")
    description: str | None = Field(default=None, description="description of the channel")
    name: str | None = Field(default=None, description="name of the channel")


class claim(BaseModel):
    cert_expiration: datetime = Field(description="the timestamp when the cert used to create the signature expires")
    cert_fingerprint: str = Field(description="the SHA2-256 fingerprint of the certificate used to sign the claim")
    claim_id: UUID = Field(description="The UUID of the claim, unique to the signer of the claim")
    confirmation_url: str = Field(description="URL of API to call to confirm the signature has not been revoked")
    issuer_id: UUID = Field(description="The UUID of the claim issuer")
    issuer_type: str = Field(description="what type of entity issued this claim")
    keyfield: str = Field(description="name of the field used to identify the object, ie. &#39;asset_id&#39;. The field must be of type &#39;UUID&#39;")
    keyfield_id: UUID = Field(description="The UUID of the keyfield of the claim")
    object_fields: list[str] = Field(description="The fields covered by the signature of the object with ID &#39;object_id&#39; stored in the array &#39;object_type&#39;")
    object_type: str = Field(description="The name of the array storing the object of the claim, ie. &#39;public_assets&#39; and not &#39;asset&#39;. The array must store objects that have a data property &#39;asset_id&#39;")
    renewal_url: str = Field(description="URL to request new signature of the asset")
    requester_id: UUID = Field(description="The UUID of the entity that requested the claim to be signed by the issuer")
    requester_type: str = Field(description="what type of entity requested this claim to be signed by the issuer")
    signature: str = Field(description="base64-encoding signature for the values for the &#39;object_fields&#39; of the object with uuid &#39;object_id&#39; of type &#39;object_class&#39;")
    signature_format_version: float = Field(description="The version of the signature format used. Each version defines the hashing algorithm and how to format the data to be signed. The formats are defined in byoda-python/byoda/datamodel/claim.py")
    signature_timestamp: datetime = Field(description="Date &amp; time for when the signature was created")
    signature_url: str = Field(description="URL to visit to get additional info about the signature")
    claims: list[str] | None = Field(default=None, description="The claims that are validated by the issuer")


class datalog(BaseModel):
    created_timestamp: datetime = Field(description="time the log entry was created")
    object: str = Field(description="name of the object in the Data API query")
    operation: str = Field(description="What operation that was requested by the client")
    remote_addr: str = Field(description="The remote IP address performing the request")
    message: str | None = Field(default=None, description="Additional information about the request")
    origin_member_id: UUID | None = Field(default=None, description="The UUID of the member that originated the recurise query")
    origin_signature: str | None = Field(default=None, description="base64 encoded signature of a recursive query")
    origin_timestamp: datetime | None = Field(default=None, description="The time the query was created by the origin member of the recursive query")
    query_depth: int | None = Field(default=None, description="the depth specified the Data API query")
    query_filters: str | None = Field(default=None, description="the filters specified in the Data API query")
    query_id: UUID | None = Field(default=None, description="Unique identifier for queries so pods can drop duplicate recursive queries")
    query_relations: str | None = Field(default=None, description="the relations specified in the Data API query")
    query_remote_member_id: UUID | None = Field(default=None, description="The member that was specified in the append request to proxy to")
    remote_id: str | None = Field(default=None, description="The ID of the client originating the log entry")
    remote_id_type: str | None = Field(default=None, description="The type of ID used to authenticate, ie. member, service or account")
    signature_format_version: float | None = Field(default=None, description="The version of the signature format used")
    source: str | None = Field(default=None, description="The source of the log entry, ie. the client, a Data API query, etc.")


class monetization(BaseModel):
    monetization_id: UUID | None = Field(default=None, description="the UUID for the monetization method")
    monetization_scheme: str | None = Field(default=None, description="the scheme for monetization, ie. &#39;ad-supported&#39;, &#39;creator-subscription&#39;, &#39;service-subscription&#39;, &#39;pay-per-view, etc. etc.")


class network_invite(BaseModel):
    created_timestamp: datetime = Field(description="time the network invite was created")
    member_id: UUID = Field(description="The UUID of the other member")
    relation: str = Field(description="The relation the other member claims to have with you")
    text: str | None = Field(default=None, description="The text of the invitation provded by the other member")


class network_link(BaseModel):
    created_timestamp: datetime = Field(description="time the network link was created")
    member_id: UUID = Field(description="The UUID of the other member")
    relation: str = Field(description="What relation you have with the other member")


class network_link_inbound(BaseModel):
    created_timestamp: datetime = Field(description="time the network relation was created")
    member_id: UUID = Field(description="The UUID of the other member")
    relation: str = Field(description="The relation the other member has with you")
    signature: str | None = Field(default=None, description="The text of the invitation provded by the other member")
    signature_expiration: datetime | None = Field(default=None, description="The expiration date/time for the certificate used to generate the signature")


class restricted_content_key(BaseModel):
    key: str | None = Field(default=None, description="key used to create content tokens")
    key_id: int | None = Field(default=None, description="identifier for the key")
    not_after: datetime | None = Field(default=None, description="time after which the key is not valid")
    not_before: datetime | None = Field(default=None, description="time before which the key is not valid")


class tweet(BaseModel):
    asset_id: str = Field(description="The Twitter ID of the asset")
    contents: str = Field(description="text for the asset")
    created_timestamp: datetime = Field(description="time the asset was created")
    assets: list[str] | None = Field(default=None, description="list of assets in the tweet")
    conversation_id: str | None = Field(default=None, description="ID of the conversation this asset is part of")
    creator: str | None = Field(default=None, description="creator of the asset")
    geo: str | None = Field(default=None, description="geographic location of the tweet")
    hashtags: list[str] | None = Field(default=None, description="list of hashtags in the tweet")
    lang: str | None = Field(default=None, description="language the contents of the tweet is in")
    like_count: int | None = Field(default=None, description="number of times the tweet has been liked")
    media_ids: list[str] | None = Field(default=None, description="list of media uuids for attachments in the tweet")
    mentions: list[str] | None = Field(default=None, description="list of Twitter IDs of people mentioned in the tweet")
    quote_count: int | None = Field(default=None, description="number of times the tweet has been quoted")
    references: list[str] | None = Field(default=None, description="list of Twitter IDs of people who quoted or replied to the tweet")
    reply_count: int | None = Field(default=None, description="number of times the tweet has been replied to")
    response_to: str | None = Field(default=None, description="Twitter ID of person who created the tweet this is a response to")
    retweet_count: int | None = Field(default=None, description="number of times the tweet has been retweeted")
    urls: list[str] | None = Field(default=None, description="list of URLs in the tweet")


class twitter_account(BaseModel):
    name: str = Field(description="Twitter name of the person")
    twitter_id: str = Field(description="Twitter ID for the person")
    created_timestamp: datetime | None = Field(default=None, description="Date &amp; time when the Twitter account was created")
    display_url: str | None = Field(default=None, description="Text to display for the URL for the person")
    followers_count: int | None = Field(default=None, description="Number of followers")
    following_count: int | None = Field(default=None, description="Number of people the person is following")
    handle: str | None = Field(default=None, description="Twitter handle of the person")
    listed_count: int | None = Field(default=None, description="Number of times the person has been listed")
    pinned_tweet_id: str | None = Field(default=None, description="ID of the pinned tweet")
    profile_image_url: str | None = Field(default=None, description="URL for the profile image")
    tweet_count: int | None = Field(default=None, description="Number of tweets")
    url: str | None = Field(default=None, description="URL for the person")
    verified: bool | None = Field(default=None, description="Whether the person is verified")
    withheld: str | None = Field(default=None, description="Twitter User.withheld field")


class twitter_media(BaseModel):
    media_key: str = Field(description="Twitter media key")
    alt_text: str | None = Field(default=None, description="alernative text for the media if it can&#39;t be displayed")
    created_timestamp: datetime | None = Field(default=None, description="time the asset was added to the pod")
    duration: int | None = Field(default=None, description="duration of the media")
    height: int | None = Field(default=None, description="height of the media")
    media_type: str | None = Field(default=None, description="type of media")
    preview_image_url: str | None = Field(default=None, description="URL of a preview image for the media")
    url: str | None = Field(default=None, description="URL of the media")
    variants: list[str] | None = Field(default=None, description="list of variants for the media")
    view_count: int | None = Field(default=None, description="number of times the media has been viewed")
    width: int | None = Field(default=None, description="width of the media")


class video_chapter(BaseModel):
    chapter_id: UUID = Field(description="The UUID of the video chapter")
    end: float = Field(description="The start of the chapter, as an offset in seconds from the start of the video")
    start: float = Field(description="The start of the chapter, as an offset in seconds from the start of the video")
    title: str | None = Field(default=None, description="The title of the chapter")


class video_thumbnail(BaseModel):
    height: float = Field(description="The height of the thumbnail")
    thumbnail_id: UUID = Field(description="The UUID of the video thumbnail")
    url: str = Field(description="The URL of the thumbnail")
    width: float = Field(description="The width of the thumbnail")
    preference: str | None = Field(default=None, description="The preference of the thumbnail, ie. &#39;default&#39;, &#39;high&#39;, &#39;medium&#39;, &#39;low&#39;")
    size: str | None = Field(default=None, description="a textual description of the resolution of the thumbnail, ie. &#39;640x480&#39; or &#39;4k&#39;")


class app(BaseModel):
    app_id: UUID = Field(description="the UUID for the app")
    app_type: str = Field(description="the type of app, ie. &#39;moderation&#39;, &#39;identity&#39; etc. etc.")
    status: str = Field(description="the status of the app as specified by the member, ie. &#39;active&#39;, &#39;inactive&#39;, &#39;preferred&#39;, etc. etc.")
    app_urls: list[app_url] | None = Field(default=None, description="None")


class asset(BaseModel):
    asset_id: UUID = Field(description="The UUID of the asset")
    asset_type: str = Field(description="type of asset, ie. a tweet, a message, a video, etc.")
    created_timestamp: datetime = Field(description="time the asset was added to the pod")
    annotations: list[str] | None = Field(default=None, description="annotations for the asset, things like &#39;genre:action&#39; or &#39;city:San Francisco&#39;")
    asset_merkle_root_hash: str | None = Field(default=None, description="the base64-encoded merkle root hash of the asset. The full hash tree can be downloaded by taking the asset_url and replace the filename in that url with &#39;merkle-tree.db&#39;")
    asset_url: str | None = Field(default=None, description="Location of the asset")
    categories: list[str] | None = Field(default=None, description="categories for the asset, things like &#39;Education&#39; or &#39;Comedy")
    channel_id: UUID | None = Field(default=None, description="UUID of the channel, if any, that the asset was posted to")
    claims: list[claim] | None = Field(default=None, description="list of claims for the asset")
    content_warnings: list[str] | None = Field(default=None, description="list of terms with potential triggers, such as violence, or cursing")
    contents: str | None = Field(default=None, description="text for the asset")
    copyright_years: list[int] | None = Field(default=None, description="None")
    creator: str | None = Field(default=None, description="creator of the asset")
    creator_thumbnail: str | None = Field(default=None, description="URL for the creator&#39;s thumbnail")
    duration: float | None = Field(default=None, description="the duration of the video")
    encoding_profiles: list[str] | None = Field(default=None, description="DEPRECATED: encoding profile used for the asset")
    forum: str | None = Field(default=None, description="forum, if any, that the asset was posted to")
    ingest_status: str | None = Field(default=None, description="status of the ingest process")
    keywords: list[str] | None = Field(default=None, description="comma-separated list of keywords")
    locale: str | None = Field(default=None, description="locale for the metadata, ie. en_US")
    monetizations: list[monetization] | None = Field(default=None, description="enabled monetizations for the asset")
    published_timestamp: datetime | None = Field(default=None, description="date-time of first publication of the content")
    publisher: str | None = Field(default=None, description="the publisher of the asset")
    publisher_asset_id: str | None = Field(default=None, description="Identifier of the asset set by the publisher")
    response_to_asset_id: UUID | None = Field(default=None, description="ID of asset that this asset is a response to")
    root_asset_class: str | None = Field(default=None, description="top-level class of the root asset in the schema (ie. public_asset)")
    root_asset_id: UUID | None = Field(default=None, description="ID of asset that is the root of the thread")
    screen_orientation_horizontal: bool | None = Field(default=None, description="Whether content is optimized for consumption on a screen with horizontal orietation")
    subject: str | None = Field(default=None, description="a brief description of the asset")
    title: str | None = Field(default=None, description="title of the asset")
    video_chapters: list[video_chapter] | None = Field(default=None, description="list of video chapters for the asset")
    video_thumbnails: list[video_thumbnail] | None = Field(default=None, description="list of thumbnails for the asset")

class apps(BaseModel):
    apps: list[app]

class asset_links(BaseModel):
    asset_links: list[asset_link]

class asset_reactions_received(BaseModel):
    asset_reactions_received: list[asset_reaction]

class channels(BaseModel):
    channels: list[channel]

class datalogs(BaseModel):
    datalogs: list[datalog]

class feed_assets(BaseModel):
    feed_assets: list[asset]

class incoming_assets(BaseModel):
    incoming_assets: list[asset]

class incoming_claims(BaseModel):
    incoming_claims: list[claim]


class member(BaseModel):
    joined: datetime = Field(description="Date &amp; time when the pod became a member of the service")
    member_id: UUID = Field(description="Membership UUID")
    schema_versions: list[str] | None = Field(default=None, description="All the versions of the schema supported by the pod")

class network_assets(BaseModel):
    network_assets: list[asset]

class network_invites(BaseModel):
    network_invites: list[network_invite]

class network_links(BaseModel):
    network_links: list[network_link]

class network_links_inbound(BaseModel):
    network_links_inbound: list[network_link_inbound]


class person(BaseModel):
    email: str = Field(description="None")
    family_name: str = Field(description="Your surname")
    given_name: str = Field(description="Your first given name")
    additional_names: str | None = Field(default=None, description="Any middle names")
    avatar_url: str | None = Field(default=None, description="None")
    homepage_url: str | None = Field(default=None, description="None")

class public_assets(BaseModel):
    public_assets: list[asset]

class restricted_content_keys(BaseModel):
    restricted_content_keys: list[restricted_content_key]

class service_assets(BaseModel):
    service_assets: list[asset]

class tweets(BaseModel):
    tweets: list[tweet]

class twitter_medias(BaseModel):
    twitter_medias: list[twitter_media]

class verified_claims(BaseModel):
    verified_claims: list[claim]
