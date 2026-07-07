#!/usr/bin/env python3
'''
Unit tests for the YouTubeChannel class.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import unittest

from byoda.data_import.youtube_channel import YouTubeChannel


class TestYouTubeChannelInit(unittest.TestCase):
    '''Test suite for YouTubeChannel initialization.'''

    def test_init_with_name(self) -> None:
        channel = YouTubeChannel(name='TestChannel')

        self.assertEqual(channel.name, 'testchannel')
        self.assertEqual(
            channel.youtube_url, 'https://www.youtube.com/@testchannel'
        )
        self.assertIsNone(channel.channel_id)
        self.assertEqual(channel.videos, {})

    def test_init_with_name_strips_at(self) -> None:
        channel = YouTubeChannel(name='@TestChannel')

        self.assertEqual(channel.name, 'testchannel')

    def test_init_preserves_channel_id_case(self) -> None:
        channel = YouTubeChannel(
            name='UC22BdTgxefuvUivrjesETjg',
            channel_id='UC22BdTgxefuvUivrjesETjg',
        )

        self.assertEqual(channel.name, 'UC22BdTgxefuvUivrjesETjg')
        self.assertEqual(
            channel.youtube_channel_id, 'UC22BdTgxefuvUivrjesETjg'
        )

    def test_init_with_ingest_flag(self) -> None:
        channel = YouTubeChannel(name='TestChannel', ingest=True)

        self.assertTrue(channel.ingest_videos)

    def test_init_default_values(self) -> None:
        channel = YouTubeChannel(name='TestChannel')

        self.assertIsNone(channel.description)
        self.assertEqual(channel.keywords, set())
        self.assertFalse(channel.is_family_safe)
        self.assertEqual(channel.available_country_codes, set())
        self.assertEqual(len(channel.channel_thumbnails), 0)
        self.assertIsNone(channel.channel_thumbnail)
        self.assertEqual(channel.banners, set())
        self.assertEqual(channel.external_urls, set())
        self.assertEqual(channel.courses, [])
        self.assertEqual(channel.playlists, [])
        self.assertEqual(channel.posts, [])
        self.assertEqual(channel.merch, [])
        self.assertEqual(channel.channel_links, [])
        self.assertEqual(channel.video_ids, [])


class TestYouTubeChannelAsDict(unittest.TestCase):
    '''Test suite for as_dict method.'''

    def test_as_dict_basic(self) -> None:
        channel = YouTubeChannel(name='TestChannel')
        channel.channel_id = 'UC123456789'
        channel.description = 'Test description'

        result: dict[str, object] = channel.as_dict()

        self.assertIn('channel_id', result)
        self.assertEqual(result['channel_id'], 'UC123456789')
        self.assertEqual(result['channel'], 'testchannel')
        self.assertEqual(result['description'], 'Test description')
        self.assertIn('created_timestamp', result)

    def test_as_dict_with_platform_counts(self) -> None:
        channel = YouTubeChannel(name='TestChannel')
        channel.channel_id = 'UC123456789'
        channel.subscriber_count = 1000
        channel.video_count = 50
        channel.view_count = 50000

        result: dict[str, object] = channel.as_dict()

        self.assertEqual(result['publisher_platform_followers'], 1000)
        self.assertEqual(result['publisher_platform_videos'], 50)
        self.assertEqual(result['publisher_platform_views'], 50000)

    def test_as_dict_none_counts(self) -> None:
        channel = YouTubeChannel(name='TestChannel')
        channel.channel_id = 'UC123456789'

        result: dict[str, object] = channel.as_dict()

        self.assertEqual(result['publisher_platform_followers'], 0)
        self.assertEqual(result['publisher_platform_videos'], 0)
        self.assertEqual(result['publisher_platform_views'], 0)

    def test_as_dict_includes_boinko_only_fields(self) -> None:
        channel = YouTubeChannel(name='TestChannel')
        channel.courses = [{'title': 'course'}]
        channel.playlists = [{'title': 'playlist'}]
        channel.posts = [{'title': 'post'}]
        channel.merch = [{'title': 'shirt'}]
        channel.channel_links = [{'title': 'site'}]
        channel.video_ids = ['video-1']

        result: dict[str, object] = channel.as_dict()

        self.assertEqual(result['courses'], [{'title': 'course'}])
        self.assertEqual(result['playlists'], [{'title': 'playlist'}])
        self.assertEqual(result['posts'], [{'title': 'post'}])
        self.assertEqual(result['merch'], [{'title': 'shirt'}])
        self.assertEqual(result['channel_links'], [{'title': 'site'}])
        self.assertEqual(result['video_ids'], ['video-1'])


if __name__ == '__main__':
    unittest.main()
