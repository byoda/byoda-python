#!/usr/bin/env python3
'''
Unit tests for the split_quoted_string function

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import unittest

from byoda.util.string_parser import split_quoted_string


class TestSplitQuotedString(unittest.TestCase):
    '''Test suite for the split_quoted_string function'''

    def test_basic_string(self) -> None:
        '''Test basic string without quotes'''
        result: set[str] = split_quoted_string('onetwothree')
        expected: set[str] = {'onetwothree'}
        self.assertEqual(result, expected)

    def test_basic_comma_separated_with_quotes(self) -> None:
        '''Test basic comma-separated values with quotes'''
        result: set[str] = split_quoted_string('foo, bar, "hello world", baz')
        expected: set[str] = {'foo', 'bar', 'hello world', 'baz'}
        self.assertEqual(result, expected)

    def test_space_separated_with_double_quotes(self) -> None:
        '''Test space-separated with double quotes'''
        result: set[str] = split_quoted_string('"test one" test2 "test three"')
        expected: set[str] = {'test one', 'test2', 'test three'}
        self.assertEqual(result, expected)

    def test_single_quotes(self) -> None:
        '''Test single quotes'''
        result: set[str] = split_quoted_string(
            "'single' and 'double quotes' work"
        )
        expected: set[str] = {'single', 'and', 'double quotes', 'work'}
        self.assertEqual(result, expected)

    def test_mixed_quotes(self) -> None:
        '''Test mixed single and double quotes'''
        result: set[str] = split_quoted_string(
            '''foo, "bar baz", 'qux quux' '''
        )
        expected: set[str] = {'foo', 'bar baz', 'qux quux'}
        self.assertEqual(result, expected)

    def test_empty_string(self) -> None:
        '''Test empty string'''
        result: set[str] = split_quoted_string('')
        expected: set[str] = set()
        self.assertEqual(result, expected)

    def test_no_quotes(self) -> None:
        '''Test string without quotes'''
        result: set[str] = split_quoted_string('one, two, three')
        expected: set[str] = {'one', 'two', 'three'}
        self.assertEqual(result, expected)

    def test_multiple_consecutive_delimiters(self) -> None:
        '''Test multiple consecutive delimiters'''
        result: set[str] = split_quoted_string('one,,  ,two,   three')
        expected: set[str] = {'one', 'two', 'three'}
        self.assertEqual(result, expected)

    def test_quotes_at_beginning_and_end(self) -> None:
        '''Test quotes at the beginning and end'''
        result: set[str] = split_quoted_string('"first", "second", "third"')
        expected: set[str] = {'first', 'second', 'third'}
        self.assertEqual(result, expected)

    def test_custom_delimiter(self) -> None:
        '''Test custom delimiter (semicolon)'''
        result: set[str] = split_quoted_string(
            'one;two;"three four";five', delimiters=';'
        )
        expected: set[str] = {'one', 'two', 'three four', 'five'}
        self.assertEqual(result, expected)

    def test_complex_youtube_keywords(self) -> None:
        '''Test complex real-world case with YouTube keywords'''
        keywords_str = (
            '"legal analysis" "big law" lsat "personal injury lawyer" '
            '"supreme court" "law firm" "law school" "law and order" '
            'lawyers "legal eagle" "lawyer reacts" "ace attorney" '
            '"phoenix wright" lawyer attorney trial court "fair use" '
            'reaction law legal judge suits objection LegalEagle'
        )
        result: set[str] = split_quoted_string(keywords_str)
        expected: set[str] = {
            'legal analysis', 'big law', 'lsat', 'personal injury lawyer',
            'supreme court', 'law firm', 'law school', 'law and order',
            'lawyers', 'legal eagle', 'lawyer reacts', 'ace attorney',
            'phoenix wright', 'lawyer', 'attorney', 'trial', 'court',
            'fair use', 'reaction', 'law', 'legal', 'judge', 'suits',
            'objection', 'LegalEagle'
        }
        self.assertEqual(result, expected)

    def test_only_spaces(self) -> None:
        '''Test string with only spaces'''
        result: set[str] = split_quoted_string('   ')
        expected: set[str] = set()
        self.assertEqual(result, expected)

    def test_nested_quotes_different_types(self) -> None:
        '''Test nested quotes of different types'''
        result: set[str] = split_quoted_string(
            '''one, "two 'nested' three", four'''
        )
        expected: set[str] = {'one', "two 'nested' three", 'four'}
        self.assertEqual(result, expected)

    def test_trailing_delimiter(self) -> None:
        '''Test string with trailing delimiter'''
        result: set[str] = split_quoted_string('one, two, three,')
        expected: set[str] = {'one', 'two', 'three'}
        self.assertEqual(result, expected)

    def test_leading_delimiter(self) -> None:
        '''Test string with leading delimiter'''
        result: set[str] = split_quoted_string(', one, two, three')
        expected: set[str] = {'one', 'two', 'three'}
        self.assertEqual(result, expected)


if __name__ == '__main__':
    unittest.main()
