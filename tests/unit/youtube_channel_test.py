#!/usr/bin/env python3
'''
Unit tests for the YouTubeChannel class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026, 2026
:license    : GPLv3
'''


from re import Match, Pattern
import unittest

from byoda.data_import.youtube_channel import YouTubeChannel
from byoda.data_import.youtube_thumbnail import YouTubeThumbnail


class TestYouTubeChannelInit(unittest.TestCase):
    '''Test suite for YouTubeChannel initialization'''

    def test_init_with_name(self) -> None:
        '''Test initialization with channel name'''
        channel = YouTubeChannel(name='TestChannel')
        self.assertEqual(channel.name, 'TestChannel')
        self.assertIsNone(channel.channel_id)
        self.assertEqual(channel.videos, {})

    def test_init_with_name_strips_at(self) -> None:
        '''Test that @ is stripped from channel name'''
        channel = YouTubeChannel(name='@TestChannel')
        self.assertEqual(channel.name, 'TestChannel')

    def test_init_with_channel_id(self) -> None:
        '''Test initialization with channel ID'''
        channel = YouTubeChannel(
            name='TestChannel',
            channel_id='UC22BdTgxefuvUivrjesETjg'
        )
        self.assertEqual(
            channel.youtube_channel_id, 'UC22BdTgxefuvUivrjesETjg'
        )

    def test_init_with_ingest_flag(self) -> None:
        '''Test initialization with ingest flag'''
        channel = YouTubeChannel(name='TestChannel', ingest=True)
        self.assertTrue(channel.ingest_videos)

    def test_init_default_values(self) -> None:
        '''Test default values after initialization'''
        channel = YouTubeChannel(name='TestChannel')
        self.assertIsNone(channel.description)
        self.assertEqual(channel.keywords, set())
        self.assertFalse(channel.is_family_safe)
        self.assertEqual(channel.available_country_codes, set())
        self.assertEqual(len(channel.channel_thumbnails), 0)
        self.assertIsNone(channel.channel_thumbnail)
        self.assertEqual(channel.banners, set())
        self.assertEqual(channel.external_urls, set())


class TestYouTubeChannelExtractChannelId(unittest.TestCase):
    '''Test suite for extract_channel_id static method'''

    def test_extract_channel_id_success(self) -> None:
        '''Test successful extraction of channel ID'''
        page_data = '''
        <html>
            <script>
                var data = {"externalId":"UC22BdTgxefuvUivrjesETjg"};
            </script>
        </html>
        '''
        channel_id: str = YouTubeChannel.extract_channel_id(page_data)
        self.assertEqual(channel_id, 'UC22BdTgxefuvUivrjesETjg')

    def test_extract_channel_id_not_found(self) -> None:
        '''Test extraction when channel ID is not present'''
        page_data = '<html><body>No channel ID here</body></html>'
        with self.assertRaises(ValueError) as context:
            YouTubeChannel.extract_channel_id(page_data)
        self.assertIn('Channel ID not found', str(context.exception))

    def test_extract_channel_id_empty_string(self) -> None:
        '''Test extraction with empty string'''
        with self.assertRaises(ValueError):
            YouTubeChannel.extract_channel_id('')

    def test_extract_channel_id_multiple_matches(self) -> None:
        '''Test extraction with multiple channel IDs (returns first)'''
        page_data = '''
        {"externalId":"FIRST_ID"}
        {"externalId":"SECOND_ID"}
        '''
        channel_id: str = YouTubeChannel.extract_channel_id(page_data)
        self.assertEqual(channel_id, 'FIRST_ID')


class TestYouTubeChannelFindNestedDicts(unittest.TestCase):
    '''Test suite for find_nested_dicts static method'''

    def test_find_in_simple_dict(self) -> None:
        '''Test finding a key in a simple dictionary'''
        data: dict[str, str] = {'key1': 'value1', 'target': 'found'}
        result: str | None = YouTubeChannel.find_nested_dicts('target', data)
        self.assertEqual(result, 'found')

    def test_find_in_nested_dict(self) -> None:
        '''Test finding a key in nested dictionaries'''
        data: dict[str, dict[str, dict[str, str]]] = {
            'level1': {
                'level2': {
                    'target': 'found_it'
                }
            }
        }
        result: str = YouTubeChannel.find_nested_dicts('target', data)
        self.assertEqual(result, 'found_it')

    def test_find_in_list(self) -> None:
        '''Test finding a key in a list of dictionaries'''
        data: list[dict[str, str]] = [
            {'key1': 'value1'},
            {'target': 'found_in_list'},
            {'key2': 'value2'}
        ]
        result = YouTubeChannel.find_nested_dicts('target', data)
        self.assertEqual(result, 'found_in_list')

    def test_find_in_nested_list_and_dict(self) -> None:
        '''Test finding a key in nested lists and dictionaries'''
        data: dict[str, list[dict[str, dict[str, str]]]] = {
            'level1': [
                {'level2': {'target': 'deep_value'}}
            ]
        }
        result: str = YouTubeChannel.find_nested_dicts('target', data)
        self.assertEqual(result, 'deep_value')

    def test_find_not_found(self) -> None:
        '''Test when target key is not found'''
        data: dict[str, str] = {'key1': 'value1', 'key2': 'value2'}
        result: dict[str, any] | None = YouTubeChannel.find_nested_dicts(
            'target', data
        )
        self.assertIsNone(result)

    def test_find_with_empty_dict(self) -> None:
        '''Test with empty dictionary'''
        result: None = YouTubeChannel.find_nested_dicts('target', {})
        self.assertIsNone(result)

    def test_find_with_empty_list(self) -> None:
        '''Test with empty list'''
        result: None = YouTubeChannel.find_nested_dicts('target', [])
        self.assertIsNone(result)


class TestYouTubeChannelParseNestedDicts(unittest.TestCase):
    '''Test suite for parse_nested_dicts static method'''

    def test_parse_simple_path(self) -> None:
        '''Test parsing a simple path'''
        data: dict[str, str] = {'key1': 'value1'}
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts(['key1'], data, str)
        self.assertEqual(result, 'value1')

    def test_parse_nested_path(self) -> None:
        '''Test parsing a nested path'''
        data: dict[str, dict[str, dict[str, str]]] = {
            'level1': {
                'level2': {
                    'level3': 'deep_value'
                }
            }
        }
        keys: list[str] = ['level1', 'level2', 'level3']
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts(keys, data, str)
        self.assertEqual(result, 'deep_value')

    def test_parse_returns_list(self) -> None:
        '''Test parsing that returns a list'''
        data: dict[str, list[str]] = {'items': ['item1', 'item2', 'item3']}
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts(['items'], data, list)
        self.assertEqual(result, ['item1', 'item2', 'item3'])

    def test_parse_returns_dict(self) -> None:
        '''Test parsing that returns a dict'''
        data: dict[str, dict[str, object]] = {
            'metadata': {'name': 'test', 'value': 123}
        }
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts(['metadata'], data, dict)
        self.assertEqual(result, {'name': 'test', 'value': 123})

    def test_parse_key_not_found(self) -> None:
        '''Test parsing when key is not found'''
        data: dict[str, dict[str, str]] = {'key1': {'key2': 'value'}}
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts(
            ['key1', 'nonexistent'], data, str
        )
        self.assertIsNone(result)

    def test_parse_wrong_type(self) -> None:
        '''Test parsing when final type doesn't match'''
        data: dict[str, str] = {'key1': 'string_value'}
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts(['key1'], data, list)
        self.assertIsNone(result)

    def test_parse_empty_keys(self) -> None:
        '''Test parsing with empty keys list'''
        data: dict[str, str] = {'key1': 'value1'}
        result: object | list[object] | None = \
            YouTubeChannel.parse_nested_dicts([], data, dict)
        self.assertEqual(result, data)

    def test_parse_numeric_value(self) -> None:
        '''Test parsing numeric values'''
        data: dict[str, int] = {'count': 42}
        result = YouTubeChannel.parse_nested_dicts(['count'], data, int)
        self.assertEqual(result, 42)


class TestYouTubeChannelParseVideoCount(unittest.TestCase):
    '''Test suite for parse_video_count static method'''

    def test_parse_video_count_success(self) -> None:
        '''Test successful parsing of video count'''
        data: dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, list[dict[str, list[dict[str, dict[str, str]]]]]]]]]]]] = {     # noqa: E501
            'header': {
                'pageHeaderRenderer': {
                    'content': {
                        'pageHeaderViewModel': {
                            'metadata': {
                                'contentMetadataViewModel': {
                                    'metadataRows': [
                                        {
                                            'metadataParts': [
                                                {
                                                    'text': {
                                                        'content':
                                                            '1,234 videos'
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
        result: int | None = YouTubeChannel.parse_video_count(data)
        self.assertEqual(result, 1234)

    def test_parse_video_count_not_found(self) -> None:
        '''Test parsing when video count is not found'''
        data: dict[str, dict] = {'header': {}}
        result: int | None = YouTubeChannel.parse_video_count(data)
        self.assertIsNone(result)

    def test_parse_video_count_malformed_data(self) -> None:
        '''Test parsing with malformed data'''
        data: dict[str, dict[str, str]] = {
            'header': {'pageHeaderRenderer': 'invalid'}
        }
        result: int | None = YouTubeChannel.parse_video_count(data)
        self.assertIsNone(result)


class TestYouTubeChannelParseSubscriberCount(unittest.TestCase):
    '''Test suite for parse_subscriber_count static method'''

    def test_parse_subscriber_count_success(self) -> None:
        '''Test successful parsing of subscriber count'''
        data: dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, list[dict[str, list[dict[str, dict[str, str]]]]]]]]]]]] = {    # noqa: E501
            'header': {
                'pageHeaderRenderer': {
                    'content': {
                        'pageHeaderViewModel': {
                            'metadata': {
                                'contentMetadataViewModel': {
                                    'metadataRows': [
                                        {
                                            'metadataParts': [
                                                {
                                                    'text': {
                                                        'content':
                                                            '5.2M subscribers'
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
        result: int | None = YouTubeChannel.parse_subscriber_count(data)
        self.assertEqual(result, 5200000)

    def test_parse_subscriber_count_thousands(self) -> None:
        '''Test parsing subscriber count with K notation'''
        data: dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, list[dict[str, list[dict[str, dict[str, str]]]]]]]]]]]] = {   # noqa: E501
            'header': {
                'pageHeaderRenderer': {
                    'content': {
                        'pageHeaderViewModel': {
                            'metadata': {
                                'contentMetadataViewModel': {
                                    'metadataRows': [
                                        {
                                            'metadataParts': [
                                                {
                                                    'text': {
                                                        'content':
                                                            '250K subscribers'
                                                    }
                                                }
                                            ]
                                        }
                                    ]
                                }
                            }
                        }
                    }
                }
            }
        }
        result: int | None = YouTubeChannel.parse_subscriber_count(data)
        self.assertEqual(result, 250000)

    def test_parse_subscriber_count_not_found(self) -> None:
        '''Test parsing when subscriber count is not found'''
        data: dict[str, dict] = {'header': {}}
        result: int | None = YouTubeChannel.parse_subscriber_count(data)
        self.assertIsNone(result)


class TestYouTubeChannelParseThumbnails(unittest.TestCase):
    '''Test suite for parse_thumbnails static method'''

    def test_parse_thumbnails_from_page_header(self) -> None:
        '''Test parsing thumbnails from page header'''
        data: dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, dict[str, list[dict[str, list[dict[str, dict[str, str]]]]]]]]]]]]]]]] = {     # noqa: E501
            'header': {
                'pageHeaderRenderer': {
                    'content': {
                        'pageHeaderViewModel': {
                            'image': {
                                'decoratedAvatarViewModel': {
                                    'avatar': {
                                        'avatarViewModel': {
                                            'image': {
                                                'sources': [
                                                    {
                                                        'url':
                                                            'https://example.com/image1.jpg',  # noqa: E501
                                                        'width': 100,
                                                        'height': 100
                                                    },
                                                    {
                                                        'url':
                                                            'https://example.com/image2.jpg',  # noqa: E501
                                                        'width': 200,
                                                        'height': 200
                                                    }
                                                ]
                                            }
                                        }
                                    }
                                }
                            }
                        }
                    }
                }
            }
        }
        result: set[YouTubeThumbnail] = YouTubeChannel.parse_thumbnails(data)
        self.assertEqual(len(result), 2)
        self.assertIsInstance(result, set)

    def test_parse_thumbnails_from_innertube(self) -> None:
        '''Test parsing thumbnails from InnerTube API fallback'''
        data: dict[str, dict[str, list[dict[str, int | str]]]] = {
            'thumbnail': {
                'thumbnails': [
                    {
                        'url': 'https://example.com/thumb1.jpg',
                        'width': 88,
                        'height': 88
                    }
                ]
            }
        }
        result: set[YouTubeThumbnail] = YouTubeChannel.parse_thumbnails(data)
        self.assertEqual(len(result), 1)

    def test_parse_thumbnails_with_protocol_prefix(self) -> None:
        '''Test parsing thumbnails with // protocol prefix'''
        data: dict[str, dict[str, list[dict[str, int | str]]]] = {
            'thumbnail': {
                'thumbnails': [
                    {
                        'url': '//example.com/thumb.jpg',
                        'width': 88,
                        'height': 88
                    }
                ]
            }
        }
        result: set[YouTubeThumbnail] = YouTubeChannel.parse_thumbnails(data)
        self.assertEqual(len(result), 1)
        # Check that https: was prepended
        thumbnail: YouTubeThumbnail = list(result)[0]
        self.assertTrue(thumbnail.url.startswith('https:'))

    def test_parse_thumbnails_empty_data(self) -> None:
        '''Test parsing with no thumbnail data'''
        data: dict[str, dict[str, list[dict[str, int | str]]]] = {}
        result: set[YouTubeThumbnail] = YouTubeChannel.parse_thumbnails(data)
        self.assertEqual(len(result), 0)
        self.assertIsInstance(result, set)


class TestYouTubeChannelAsDict(unittest.TestCase):
    '''Test suite for as_dict method'''

    def test_as_dict_basic(self) -> None:
        '''Test basic as_dict conversion'''
        channel = YouTubeChannel(name='TestChannel')
        channel.channel_id = 'UC123456789'
        channel.description = 'Test description'

        result: dict[str, object] = channel.as_dict()

        self.assertIn('channel_id', result)
        self.assertEqual(result['channel_id'], 'UC123456789')
        self.assertIn('channel', result)
        self.assertEqual(result['channel'], 'TestChannel')
        self.assertIn('description', result)
        self.assertEqual(result['description'], 'Test description')
        self.assertIn('created_timestamp', result)

    def test_as_dict_with_counts(self) -> None:
        '''Test as_dict with subscriber and view counts'''
        channel = YouTubeChannel(name='TestChannel')
        channel.channel_id = 'UC123456789'
        channel.subscriber_count = 1000
        channel.video_count = 50
        channel.view_count = 50000

        result: dict[str, object] = channel.as_dict()

        self.assertEqual(result['publisher_followers'], 1000)
        self.assertEqual(result['publisher_videos'], 50)
        self.assertEqual(result['publisher_views'], 50000)

    def test_as_dict_none_counts(self) -> None:
        '''Test as_dict with None counts (should default to 0)'''
        channel = YouTubeChannel(name='TestChannel')
        channel.channel_id = 'UC123456789'

        result: dict[str, object] = channel.as_dict()

        self.assertEqual(result['publisher_followers'], 0)
        self.assertEqual(result['publisher_videos'], 0)
        self.assertEqual(result['publisher_views'], 0)

    def test_as_dict_strips_at_from_channel(self) -> None:
        '''Test that @ is stripped from channel name in as_dict'''
        channel = YouTubeChannel(name='@TestChannel')
        channel.channel_id = 'UC123456789'

        result: dict[str, object] = channel.as_dict()

        self.assertEqual(result['channel'], 'TestChannel')


class TestYouTubeChannelRegexPatterns(unittest.TestCase):
    '''Test suite for regex patterns in YouTubeChannel'''

    def test_channel_id_regex(self) -> None:
        '''Test CHANNEL_ID_REGEX pattern'''
        pattern: Pattern[str] = YouTubeChannel.CHANNEL_ID_REGEX
        test_string = '"externalId":"UC22BdTgxefuvUivrjesETjg"'
        match: Match[str] | None = pattern.search(test_string)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), 'UC22BdTgxefuvUivrjesETjg')

    def test_channel_scrape_regex_short(self) -> None:
        '''Test CHANNEL_SCRAPE_REGEX_SHORT pattern'''
        pattern: Pattern[str] = YouTubeChannel.CHANNEL_SCRAPE_REGEX_SHORT
        test_string = 'var ytInitialData = {"key": "value"};'
        match: Match[str] | None = pattern.search(test_string)
        self.assertIsNotNone(match)

    def test_channel_scrape_regex(self) -> None:
        '''Test CHANNEL_SCRAPE_REGEX pattern'''
        pattern: Pattern[str] = YouTubeChannel.CHANNEL_SCRAPE_REGEX
        test_string = 'var ytInitialData = {"key": "value"};'
        match: Match[str] | None = pattern.search(test_string)
        self.assertIsNotNone(match)
        self.assertEqual(match.group(1), '{"key": "value"}')


if __name__ == '__main__':
    unittest.main()
