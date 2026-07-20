'''
Scrape.Exchange YouTube metadata import helpers.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2026
:license    : GPLv3
'''

import os
import time
import brotli

from collections.abc import AsyncIterator
from datetime import datetime
from datetime import timezone
from logging import Logger
from logging import getLogger
from urllib.parse import urlparse

import orjson

from anyio import sleep
from httpx2 import AsyncClient
from httpx2 import Response

from byoda.datatypes import IngestStatus

from byoda.exceptions import ByodaRuntimeError
from byoda.exceptions import ByodaValueError

from .youtube_external_link import YouTubeExternalLink
from .youtube_thumbnail import YouTubeThumbnail
from .youtube_video import YouTubeCaption
from .youtube_video import YouTubeVideo
from .youtube_video import YouTubeVideoChapter


_LOGGER: Logger = getLogger(__name__)


DEFAULT_API_URL: str = 'https://scrape.exchange'
DEFAULT_SCHEMA_OWNER: str = 'boinko'
DEFAULT_SCHEMA_VERSION: str = '0.0.2'
FILTER_PATH: str = '/api/v1/filter'
YOUTUBE_PLATFORM: str = 'youtube'
CHANNEL_ENTITY: str = 'channel'
VIDEO_ENTITY: str = 'video'
MAX_DATA_URL_FETCHES_PER_SECOND: int = 10

ENV_API_URL: str = 'SCRAPE_EXCHANGE_API_URL'
ENV_SCHEMA_OWNER: str = 'SCRAPE_EXCHANGE_YOUTUBE_SCHEMA_OWNER'
ENV_SCHEMA_VERSION: str = 'SCRAPE_EXCHANGE_YOUTUBE_SCHEMA_VERSION'


class ScrapeExchangeValidationError(ByodaValueError):
    '''
    Raised when a Scrape.Exchange payload does not match the expected shape.
    '''


class ScrapeExchangeYouTubeClient:
    '''
    Client for Scrape.Exchange YouTube metadata.
    '''

    def __init__(
        self,
        api_url: str | None = None,
        schema_owner: str | None = None,
        schema_version: str | None = None,
        client: AsyncClient | None = None,
    ) -> None:
        self.api_url: str = (
            api_url or os.environ.get(ENV_API_URL, DEFAULT_API_URL)
        ).rstrip('/')
        self.schema_owner: str = (
            schema_owner
            or os.environ.get(ENV_SCHEMA_OWNER, DEFAULT_SCHEMA_OWNER)
        )
        self.schema_version: str = (
            schema_version
            or os.environ.get(ENV_SCHEMA_VERSION, DEFAULT_SCHEMA_VERSION)
        )
        self.client: AsyncClient = client or AsyncClient(timeout=30)
        self._owns_client: bool = client is None
        self._last_data_url_fetch: float = 0.0

    async def close(self) -> None:
        if self._owns_client:
            await self.client.aclose()

    async def filter(
        self,
        entity: str,
        platform_creator_id: str | None = None,
        platform_content_id: str | None = None,
        after: str | None = None,
    ) -> dict[str, object]:
        '''
        Call the Scrape.Exchange filter API.
        '''

        filters: dict[str, object] = {
            'schema_username': self.schema_owner,
            'platform': YOUTUBE_PLATFORM,
            'entity': entity,
            'version': self.schema_version,
        }
        if platform_creator_id:
            filters['platform_creator_id'] = platform_creator_id
        if platform_content_id:
            filters['platform_content_id'] = platform_content_id
        if after:
            filters['after'] = after

        url: str = f'{self.api_url}{FILTER_PATH}'
        resp: Response = await self.client.post(url, json=filters)
        if resp.status_code == 404:
            return {
                'total_count': 0,
                'edges': [],
                'page_info': {
                    'has_next_page': False,
                    'end_cursor': None,
                },
            }
        if resp.status_code >= 400:
            raise ByodaRuntimeError(
                f'Scrape.Exchange filter request failed: '
                f'{resp.status_code} -> {resp.text}'
            )

        return resp.json()

    async def fetch_payload(self, data_url: str) -> dict[str, object]:
        '''
        Fetch and decode a Scrape.Exchange data payload.
        '''

        await self._rate_limit_data_url_fetch()
        resp: Response = await self.client.get(data_url)
        if resp.status_code >= 400:
            raise ByodaRuntimeError(
                f'Scrape.Exchange payload request failed: '
                f'{resp.status_code} -> {resp.text}'
            )

        content: bytes = resp.content
        if data_url.endswith('.br') and not content.lstrip().startswith(b'{'):
            content = brotli.decompress(content)

        return orjson.loads(content)

    async def iter_payloads(
        self,
        entity: str,
        platform_creator_id: str | None = None,
        platform_content_id: str | None = None,
    ) -> AsyncIterator[tuple[dict[str, object], dict[str, object]]]:
        '''
        Yield `(envelope, payload)` tuples for a filter query.
        '''

        after: str | None = None
        while True:
            page: dict[str, object] = await self.filter(
                entity,
                platform_creator_id=platform_creator_id,
                platform_content_id=platform_content_id,
                after=after,
            )
            edges: list[dict[str, object]] = page.get('edges') or []
            for edge in edges:
                envelope: dict[str, object] = edge.get('node') or {}
                data_url: str | None = envelope.get('data_url')
                if not data_url:
                    _LOGGER.debug(
                        'Skipping Scrape.Exchange envelope without data_url',
                        extra={'entity': entity, 'envelope': envelope},
                    )
                    continue
                payload: dict[str, object] = await self.fetch_payload(data_url)
                yield envelope, payload

            page_info: dict[str, object] = page.get('page_info') or {}
            if not page_info.get('has_next_page'):
                break
            after = page_info.get('end_cursor')
            if not after:
                break

    async def get_channel_payload(
        self, channel: str,
    ) -> tuple[dict[str, object], dict[str, object]] | None:
        '''
        Fetch a single channel payload by handle or YouTube channel ID.
        '''

        normalized: str = normalize_youtube_channel(channel)
        by_content_id: bool = normalized.startswith('UC')
        kwargs: dict[str, str] = (
            {'platform_content_id': normalized}
            if by_content_id else {'platform_creator_id': normalized}
        )
        async for envelope, payload in self.iter_payloads(
            CHANNEL_ENTITY, **kwargs
        ):
            return envelope, payload

        return None

    async def _rate_limit_data_url_fetch(self) -> None:
        '''
        Keep data_url fetch starts at or below 10/second per process.
        '''

        minimum_interval: float = 1.0 / MAX_DATA_URL_FETCHES_PER_SECOND
        now: float = time.monotonic()
        wait: float = minimum_interval - (now - self._last_data_url_fetch)
        if wait > 0:
            await sleep(wait)
        self._last_data_url_fetch = time.monotonic()


def normalize_youtube_channel(channel: str) -> str:
    '''
    Normalize an operator-provided YouTube channel identifier.
    '''

    normalized: str = (channel or '').strip()
    if normalized.startswith('@'):
        normalized = normalized[1:]
    if not normalized.startswith('UC'):
        normalized = normalized.lower()
    return normalized


def validate_payload(
    payload: dict[str, object], entity: str,
    envelope: dict[str, object] | None = None,
) -> None:
    '''
    Validate the subset of the Boinko schemas the importer depends on.
    '''

    required: tuple[str, ...]
    typed_fields: dict[str, tuple[type, ...]]
    if entity == CHANNEL_ENTITY:
        required = ('channel_id', 'channel_handle', 'url')
        typed_fields = {
            'channel_id': (str, type(None)),
            'channel_handle': (str,),
            'url': (str,),
            'channel_thumbnails': (list,),
            'banners': (list,),
            'external_urls': (list,),
            'video_ids': (list,),
        }
    elif entity == VIDEO_ENTITY:
        required = ('video_id', 'url')
        typed_fields = {
            'video_id': (str, type(None)),
            'url': (str,),
            'thumbnails': (dict,),
            'chapters': (list,),
            'subtitles': (dict,),
            'automatic_captions': (dict,),
            'formats': (dict,),
            'available_country_codes': (list,),
        }
    else:
        raise ScrapeExchangeValidationError(
            f'Unknown Scrape.Exchange YouTube entity: {entity}'
        )

    missing: list[str] = [
        field for field in required if field not in payload
    ]
    if missing:
        _raise_validation('missing required fields', missing, envelope)

    for field, expected_types in typed_fields.items():
        if field not in payload:
            continue
        value: object = payload[field]
        if not isinstance(value, expected_types):
            _raise_validation(
                f'invalid type for {field}',
                {
                    'value_type': type(value).__name__,
                    'expected': [t.__name__ for t in expected_types],
                },
                envelope,
            )

    url: str | None = payload.get('url')
    if url and not urlparse(url).scheme:
        _raise_validation('invalid URL field', {'url': url}, envelope)


def channel_from_payload(payload: dict[str, object], channel) -> object:
    '''
    Populate a `YouTubeChannel` instance from a Boinko channel payload.
    '''

    validate_payload(payload, CHANNEL_ENTITY)
    channel.name = normalize_youtube_channel(
        payload.get('channel_handle') or channel.name
    )
    channel.youtube_channel_id = payload.get('channel_id')
    channel.youtube_url = payload.get('url')
    channel.title = payload.get('title')
    channel.description = payload.get('description')
    channel.keywords = set(payload.get('keywords') or [])
    category: str | None = payload.get('category')
    channel.categories = set(payload.get('categories') or [])
    if category:
        channel.categories.add(category)
    channel.is_family_safe = bool(payload.get('is_family_safe') or False)
    channel.country = payload.get('country')
    channel.available_country_codes = set(
        payload.get('available_country_codes') or []
    )
    channel.channel_thumbnails = _thumbnail_set(
        payload.get('channel_thumbnails') or []
    )
    if channel.channel_thumbnails:
        channel.channel_thumbnail = max(channel.channel_thumbnails)
    channel.banners = _thumbnail_set(payload.get('banners') or [])
    channel.external_urls = {
        YouTubeExternalLink(
            link.get('name'), link.get('url'), link.get('priority', 0)
        )
        for link in payload.get('external_urls') or []
        if link.get('url')
    }
    channel.joined_date = _parse_datetime(payload.get('joined_date'))
    channel.rss_url = payload.get('rss_url')
    channel.verified = bool(payload.get('verified') or False)
    channel.subscriber_count = payload.get('subscriber_count')
    channel.video_count = payload.get('video_count')
    channel.view_count = payload.get('view_count')
    channel.courses = payload.get('courses') or []
    channel.playlists = payload.get('playlists') or []
    channel.posts = payload.get('posts') or []
    channel.merch = payload.get('merch') or []
    channel.channel_links = payload.get('channel_links') or []
    channel.video_ids = payload.get('video_ids') or []
    return channel


def video_from_payload(
    payload: dict[str, object],
    channel_name: str | None = None,
    channel_thumbnail: YouTubeThumbnail | None = None,
    download_client=None,
    storage_driver=None,
) -> YouTubeVideo:
    '''
    Create a `YouTubeVideo` instance from a Boinko video payload.
    '''

    validate_payload(payload, VIDEO_ENTITY)
    video = YouTubeVideo(
        video_id=payload.get('video_id'),
        download_client=download_client,
        storage_driver=storage_driver,
    )
    video.title = payload.get('title')
    video.long_title = payload.get('long_title')
    video.description = payload.get('description')
    video.channel_id = payload.get('channel_id')
    video.channel = (
        payload.get('channel_name')
        or payload.get('channel_handle')
        or channel_name
    )
    video.channel_url = payload.get('channel_url')
    video.channel_country = payload.get('channel_country')
    video.channel_is_verified = payload.get('channel_is_verified')
    video.channel_follower_count = payload.get('channel_follower_count')
    video.channel_thumbnail_asset = channel_thumbnail
    if payload.get('channel_thumbnail'):
        channel_thumb = _thumbnail_from_any(payload.get('channel_thumbnail'))
        video.channel_thumbnail_asset = channel_thumb
        video.channel_thumbnail_url = channel_thumb.url
        video.channel_thumbnail = channel_thumb.url
    elif channel_thumbnail:
        video.channel_thumbnail_url = channel_thumbnail.url
        video.channel_thumbnail = channel_thumbnail.url
    video.created_timestamp = (
        _parse_datetime(payload.get('created_timestamp'))
        or datetime.now(tz=timezone.utc)
    )
    video.uploaded_timestamp = _parse_datetime(payload.get('uploaded_timestamp'))
    video.published_timestamp = _parse_datetime(
        payload.get('published_timestamp')
    )
    video.availability = payload.get('availability')
    video.view_count = payload.get('view_count')
    video.like_count = payload.get('like_count')
    video.dislike_count = payload.get('dislike_count')
    video.comment_count = payload.get('comment_count')
    video.url = payload.get('url')
    video.embed_url = payload.get('embed_url')
    video.thumbnails = _thumbnail_dict(payload.get('thumbnails') or {})
    video.is_live = bool(payload.get('is_live') or False)
    video.was_live = bool(payload.get('was_live') or False)
    video.media_type = payload.get('media_type')
    video.is_tv_film_video = payload.get('is_tv_film_video')
    video.embedable = payload.get('embedable')
    video.age_limit = payload.get('age_limit') or 0
    video.age_restricted = bool(payload.get('age_restricted') or False)
    video.is_family_safe = payload.get('is_family_safe')
    video.aspect_ratio = payload.get('aspect_ratio')
    video.available_country_codes = payload.get('available_country_codes') or []
    video.duration = payload.get('duration')
    video.heatmaps = payload.get('heatmaps') or []
    video.chapters = [
        YouTubeVideoChapter(chapter)
        for chapter in payload.get('chapters') or []
    ]
    video.license = payload.get('license')
    video.locale = payload.get('locale')
    video.default_audio_language = payload.get('default_audio_language')
    video.tags = set(payload.get('tags') or [])
    category: str | None = payload.get('category')
    video.categories = set(payload.get('categories') or [])
    if category:
        video.categories.add(category)
    video.annotations = set(payload.get('annotations') or [])
    video.keywords = set(payload.get('keywords') or [])
    video.privacy_status = payload.get('privacy_status') or 'public'
    video.subtitles = payload.get('subtitles') or {}
    video.automatic_captions = payload.get('automatic_captions') or {}
    video.formats = payload.get('formats') or {}
    video.captions = _captions(video.subtitles, False)
    video.captions.extend(_captions(video.automatic_captions, True))
    video._transition_state(IngestStatus.QUEUED_START)
    return video


def _raise_validation(
    error: str, details: object, envelope: dict[str, object] | None,
) -> None:
    raise ScrapeExchangeValidationError(
        f'Scrape.Exchange payload validation failed: {error}: {details}',
        extra=envelope or {},
    )


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        parsed: datetime = datetime.fromisoformat(value.replace('Z', '+00:00'))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed
    except ValueError:
        return None


def _thumbnail_from_any(value: object) -> YouTubeThumbnail:
    if isinstance(value, str):
        return YouTubeThumbnail(None, {'url': value})
    return YouTubeThumbnail(value.get('size'), value)


def _thumbnail_set(values: list[dict[str, object]]) -> set[YouTubeThumbnail]:
    thumbnails: set[YouTubeThumbnail] = set()
    for value in values:
        if value.get('url'):
            thumbnails.add(YouTubeThumbnail(value.get('size'), value))
    return thumbnails


def _thumbnail_dict(values: dict[str, object]) -> dict[YouTubeThumbnail]:
    thumbnails: dict[YouTubeThumbnail] = {}
    for label, value in values.items():
        if isinstance(value, list):
            for item in value:
                if item.get('url'):
                    thumbnails[label] = YouTubeThumbnail(label, item)
        elif isinstance(value, dict) and value.get('url'):
            thumbnails[label] = YouTubeThumbnail(label, value)
    return thumbnails


def _captions(
    values: dict[str, list[dict[str, object]]],
    is_auto_generated: bool,
) -> list[YouTubeCaption]:
    captions: list[YouTubeCaption] = []
    for language_code, caption_values in values.items():
        for caption_info in caption_values or []:
            if caption_info.get('url'):
                if (
                    'extension' in caption_info
                    and 'ext' not in caption_info
                ):
                    caption_info = caption_info | {
                        'ext': caption_info.get('extension')
                    }
                captions.append(
                    YouTubeCaption(
                        language_code, is_auto_generated, caption_info
                    )
                )
    return captions
