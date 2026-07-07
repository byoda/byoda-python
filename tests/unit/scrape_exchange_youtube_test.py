#!/usr/bin/env python3
'''
Unit tests for Scrape.Exchange YouTube import helpers.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2026
:license    : GPLv3
'''

import os
import unittest

import orjson

from byoda.datatypes import IngestStatus

from byoda.data_import.scrape_exchange_youtube import CHANNEL_ENTITY
from byoda.data_import.scrape_exchange_youtube import DEFAULT_API_URL
from byoda.data_import.scrape_exchange_youtube import DEFAULT_SCHEMA_OWNER
from byoda.data_import.scrape_exchange_youtube import DEFAULT_SCHEMA_VERSION
from byoda.data_import.scrape_exchange_youtube import ENV_API_URL
from byoda.data_import.scrape_exchange_youtube import ENV_SCHEMA_OWNER
from byoda.data_import.scrape_exchange_youtube import ENV_SCHEMA_VERSION
from byoda.data_import.scrape_exchange_youtube import VIDEO_ENTITY
from byoda.data_import.scrape_exchange_youtube import ScrapeExchangeYouTubeClient
from byoda.data_import.scrape_exchange_youtube import channel_from_payload
from byoda.data_import.scrape_exchange_youtube import normalize_youtube_channel
from byoda.data_import.scrape_exchange_youtube import validate_payload
from byoda.data_import.scrape_exchange_youtube import video_from_payload
from byoda.data_import.youtube_channel import YouTubeChannel


class FakeResponse:
    def __init__(
        self,
        status_code: int = 200,
        body: dict | None = None,
        content: bytes | None = None,
        text: str = '',
    ) -> None:
        self.status_code = status_code
        self._body = body or {}
        self.content = content or orjson.dumps(self._body)
        self.text = text

    def json(self) -> dict:
        return self._body


class FakeHttpClient:
    def __init__(self) -> None:
        self.posts: list[tuple[str, dict]] = []
        self.gets: list[str] = []
        self.post_responses: list[FakeResponse] = []
        self.get_responses: dict[str, FakeResponse] = {}
        self.closed: bool = False

    async def post(self, url: str, json: dict) -> FakeResponse:
        self.posts.append((url, json))
        return self.post_responses.pop(0)

    async def get(self, url: str) -> FakeResponse:
        self.gets.append(url)
        return self.get_responses[url]

    async def aclose(self) -> None:
        self.closed = True


def channel_payload() -> dict[str, object]:
    return {
        'channel_id': 'UC22BdTgxefuvUivrjesETjg',
        'channel_handle': 'testchannel',
        'url': 'https://www.youtube.com/@testchannel',
        'title': 'Test Channel',
        'description': 'About the channel',
        'keywords': ['video'],
        'category': 'Education',
        'is_family_safe': True,
        'country': 'United States',
        'available_country_codes': ['US'],
        'channel_thumbnails': [
            {
                'url': 'https://img.example/channel.jpg',
                'width': 88,
                'height': 88,
            }
        ],
        'banners': [
            {
                'url': 'https://img.example/banner.jpg',
                'width': 1024,
                'height': 256,
            }
        ],
        'external_urls': [
            {
                'name': 'Site',
                'url': 'https://example.com',
                'priority': 10,
            }
        ],
        'joined_date': '2024-01-02T03:04:05Z',
        'rss_url': 'https://www.youtube.com/feeds/videos.xml?channel_id=UC22',
        'verified': True,
        'subscriber_count': 10,
        'video_count': 20,
        'view_count': 30,
        'courses': [{'title': 'Course'}],
        'playlists': [{'title': 'Playlist'}],
        'posts': [{'title': 'Post'}],
        'merch': [{'title': 'Shirt'}],
        'channel_links': [{'title': 'Site'}],
        'video_ids': ['video-1'],
    }


def video_payload() -> dict[str, object]:
    return {
        'video_id': 'dQw4w9WgXcQ',
        'url': 'https://www.youtube.com/watch?v=dQw4w9WgXcQ',
        'available_country_codes': ['US', 'NL'],
        'embed_url': 'https://www.youtube.com/embed/dQw4w9WgXcQ',
        'title': 'Video title',
        'long_title': 'Video title - long',
        'description': 'Video description',
        'channel_id': 'UC22BdTgxefuvUivrjesETjg',
        'channel_handle': 'testchannel',
        'channel_url': 'https://www.youtube.com/@testchannel',
        'channel_country': 'US',
        'channel_is_verified': True,
        'channel_follower_count': 10,
        'created_timestamp': '2024-01-02T03:04:05Z',
        'uploaded_timestamp': '2024-01-03T03:04:05Z',
        'published_timestamp': '2024-01-04T03:04:05Z',
        'availability': 'public',
        'view_count': 100,
        'like_count': 10,
        'comment_count': 5,
        'thumbnails': {
            'high': {
                'url': 'https://img.example/video.jpg',
                'width': 480,
                'height': 360,
            }
        },
        'is_live': False,
        'was_live': False,
        'media_type': 'video',
        'is_tv_film_video': False,
        'embedable': True,
        'age_limit': 0,
        'age_restricted': False,
        'is_family_safe': True,
        'aspect_ratio': 1.777,
        'duration': 213,
        'heatmaps': [{'start_time': 0, 'end_time': 10, 'value': 0.5}],
        'chapters': [
            {'start_time': 0, 'end_time': 10, 'title': 'Intro'}
        ],
        'license': 'youtube',
        'locale': 'en-US',
        'default_audio_language': 'en',
        'tags': ['tag'],
        'category': 'Music',
        'annotations': ['source:scrape.exchange'],
        'keywords': ['keyword'],
        'privacy_status': 'public',
        'subtitles': {
            'en': [
                {
                    'url': 'https://caption.example/en.vtt',
                    'extension': 'vtt',
                    'protocol': 'https',
                }
            ]
        },
        'automatic_captions': {},
        'formats': {'251': {'format_id': '251'}},
    }


class TestScrapeExchangeYouTubeClient(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        for env_var in (ENV_API_URL, ENV_SCHEMA_OWNER, ENV_SCHEMA_VERSION):
            os.environ.pop(env_var, None)

    async def test_filter_uses_default_request_contract(self) -> None:
        http_client = FakeHttpClient()
        http_client.post_responses.append(FakeResponse(body={'edges': []}))
        client = ScrapeExchangeYouTubeClient(client=http_client)

        response = await client.filter(
            CHANNEL_ENTITY, platform_creator_id='testchannel'
        )

        self.assertEqual(response, {'edges': []})
        self.assertEqual(
            http_client.posts,
            [
                (
                    f'{DEFAULT_API_URL}/api/v1/filter',
                    {
                        'schema_username': DEFAULT_SCHEMA_OWNER,
                        'platform': 'youtube',
                        'entity': CHANNEL_ENTITY,
                        'version': DEFAULT_SCHEMA_VERSION,
                        'platform_creator_id': 'testchannel',
                    },
                )
            ],
        )

    async def test_filter_uses_env_overrides(self) -> None:
        os.environ[ENV_API_URL] = 'https://api.example.test'
        os.environ[ENV_SCHEMA_OWNER] = 'owner'
        os.environ[ENV_SCHEMA_VERSION] = '9.9.9'
        http_client = FakeHttpClient()
        http_client.post_responses.append(FakeResponse(body={'edges': []}))
        client = ScrapeExchangeYouTubeClient(client=http_client)

        await client.filter(VIDEO_ENTITY, platform_content_id='video-1')

        self.assertEqual(http_client.posts[0][0], 'https://api.example.test/api/v1/filter')
        self.assertEqual(http_client.posts[0][1]['schema_username'], 'owner')
        self.assertEqual(http_client.posts[0][1]['version'], '9.9.9')

    async def test_iter_payloads_follows_pages_and_fetches_data_urls(self) -> None:
        http_client = FakeHttpClient()
        http_client.post_responses.extend(
            [
                FakeResponse(
                    body={
                        'edges': [
                            {'node': {'data_url': 'https://data.example/1'}}
                        ],
                        'page_info': {
                            'has_next_page': True,
                            'end_cursor': 'cursor-1',
                        },
                    }
                ),
                FakeResponse(
                    body={
                        'edges': [
                            {'node': {'data_url': 'https://data.example/2'}}
                        ],
                        'page_info': {
                            'has_next_page': False,
                            'end_cursor': None,
                        },
                    }
                ),
            ]
        )
        http_client.get_responses = {
            'https://data.example/1': FakeResponse(body={'video_id': 'one'}),
            'https://data.example/2': FakeResponse(body={'video_id': 'two'}),
        }
        client = ScrapeExchangeYouTubeClient(client=http_client)

        payloads = [
            payload async for _, payload in client.iter_payloads(VIDEO_ENTITY)
        ]

        self.assertEqual(payloads, [{'video_id': 'one'}, {'video_id': 'two'}])
        self.assertEqual(http_client.posts[1][1]['after'], 'cursor-1')
        self.assertEqual(
            http_client.gets,
            ['https://data.example/1', 'https://data.example/2'],
        )


class TestScrapeExchangeYouTubeMapping(unittest.TestCase):
    def test_normalize_youtube_channel(self) -> None:
        self.assertEqual(
            normalize_youtube_channel('@TestChannel'), 'testchannel'
        )
        self.assertEqual(
            normalize_youtube_channel('UC22BdTgxefuvUivrjesETjg'),
            'UC22BdTgxefuvUivrjesETjg',
        )

    def test_channel_from_payload_maps_semantic_and_boinko_fields(self) -> None:
        channel = YouTubeChannel(name='placeholder')

        channel_from_payload(channel_payload(), channel)
        data = channel.as_dict()

        self.assertEqual(data['channel'], 'testchannel')
        self.assertEqual(data['publisher_channel_id'], 'UC22BdTgxefuvUivrjesETjg')
        self.assertEqual(data['publisher_platform_followers'], 10)
        self.assertEqual(data['publisher_platform_videos'], 20)
        self.assertEqual(data['publisher_platform_views'], 30)
        self.assertEqual(data['courses'], [{'title': 'Course'}])
        self.assertEqual(data['playlists'], [{'title': 'Playlist'}])
        self.assertEqual(data['posts'], [{'title': 'Post'}])
        self.assertEqual(data['merch'], [{'title': 'Shirt'}])
        self.assertEqual(data['channel_links'], [{'title': 'Site'}])
        self.assertEqual(data['video_ids'], ['video-1'])

    def test_video_from_payload_maps_semantic_and_boinko_fields(self) -> None:
        video = video_from_payload(video_payload(), channel_name='testchannel')

        self.assertEqual(video.video_id, 'dQw4w9WgXcQ')
        self.assertEqual(video.title, 'Video title')
        self.assertEqual(video.long_title, 'Video title - long')
        self.assertEqual(video.channel, 'testchannel')
        self.assertEqual(
            video.channel_url, 'https://www.youtube.com/@testchannel'
        )
        self.assertEqual(video.channel_country, 'US')
        self.assertTrue(video.channel_is_verified)
        self.assertEqual(video.channel_follower_count, 10)
        self.assertEqual(video.availability, 'public')
        self.assertEqual(video.media_type, 'video')
        self.assertTrue(video.embedable)
        self.assertFalse(video.age_restricted)
        self.assertEqual(video.available_country_codes, ['US', 'NL'])
        self.assertEqual(video.aspect_ratio, 1.777)
        self.assertEqual(
            video.heatmaps,
            [{'start_time': 0, 'end_time': 10, 'value': 0.5}],
        )
        self.assertEqual(video.subtitles['en'][0]['extension'], 'vtt')
        self.assertEqual(video.captions[0].extension, 'vtt')
        self.assertEqual(video.formats, {'251': {'format_id': '251'}})
        self.assertEqual(len(video.chapters), 1)
        self.assertEqual(len(video.captions), 1)
        self.assertEqual(video.ingest_status, IngestStatus.QUEUED_START)

    def test_validate_payload_rejects_missing_required_fields(self) -> None:
        with self.assertRaises(Exception):
            validate_payload({'url': 'https://example.com'}, VIDEO_ENTITY)


if __name__ == '__main__':
    unittest.main()
