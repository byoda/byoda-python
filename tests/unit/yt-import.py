#!/usr/bin/env python3

import re
import sys

import orjson

from bs4 import BeautifulSoup

from byoda.util.logger import Logger

_LOGGER = None


def main():
    with open('/tmp/yt-gmhikaru.html') as file_desc:
        soup = BeautifulSoup(file_desc, 'html.parser')

    pattern = re.compile(r'var ytInitialData = (.*?);')
    script = soup.find('script', string=pattern)

    data_raw = pattern.search(script.text).group(1)

    data = orjson.loads(data_raw)
    tabs = data['contents']['twoColumnBrowseResultsRenderer']['tabs']
    section_contents = tabs[0]['tabRenderer']['content']['sectionListRenderer']['contents']

    titles = {}
    find_videos(section_contents, titles)

    print(f'Titles found: {len(titles)}')


def find_videos(data: dict | list | int | str | float, titles: dict):
    if isinstance(data, list):
        for item in data:
            if type(item) in (dict, list):
                find_videos(item, titles)
    elif isinstance(data, dict):
        if 'videoId' in data:
            titles[data['videoId']] = data
            if 'title' in data and 'simpleText' in data['title']:
                print(
                    f'Found {data["title"]["simpleText"]} with ID '
                    f'{data["videoId"]}'
                )
            elif data['videoId'] not in titles:
                print(f'Found {data["videoId"]} without title')

            return

        for value in data.values():
            if type(value) in (dict, list):
                find_videos(value, titles)


if __name__ == '__main__':
    _LOGGER = Logger.getLogger(sys.argv[0], debug=True, json_out=False)
    main()
