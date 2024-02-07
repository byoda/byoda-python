#!/usr/bin/env python3

'''
Tool to call Data APIs against a pod

This tool does not use the Byoda modules so has no dependency
on the 'byoda-python' repository to be available on the local
file system

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

import os
import sys
import csv
import argparse

from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

from byoda.data_import.youtube_channel import YouTubeChannel


def main(argv: list[str]) -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        '--csv-file', '-c', type=str,
        default='/mnt/c/Users/steve/OneDrive/BYODA/Tube/creators/creators.csv'
    )
    parser.add_argument(
        '--output', type=str,
        default='//mnt/c/Users/steve/OneDrive/BYODA/Tube/creators/creators-scraped.csv'     # noqa: E501
    )
    parser.add_argument('--rows', type=int, default=10000)
    parser.add_argument('--skip', type=int, default=3839)
    parser.add_argument(
        '--track', type=str, default='/tmp/creators-tracked.list'
    )
    parser.add_argument(
        '--api-key', type=str,
        default='/home/steven/.secrets/byoda/youtube_api.key'
    )
    parser.add_argument('--debug', default=False, action='store_true')

    args: argparse.Namespace = parser.parse_args(argv[1:])

    with open(args.api_key, 'r') as file_desc:
        api_key: str = file_desc.read().strip()
    youtube = build('youtube', 'v3', developerKey=api_key)

    creators_seen: set(str) = set()
    try:
        with open(args.track, 'r') as file_desc:
            lines: list[str] = file_desc.readlines()
            creator: str
            for creator in lines:
                creators_seen.add(creator.strip())
    except FileNotFoundError:
        pass

    if not os.path.exists(args.output):
        with open(args.output, 'w') as file_desc:
            print('Channel,URL,,Subs', file=file_desc)

    creators_track: sys.TextIOWrapper = open(args.track, 'a')
    creators_out: sys.TextIOWrapper = open(args.output, 'ab', buffering=0)

    with open(args.csv_file, encoding='utf-8-sig', newline='') as file_desc:
        reader = csv.DictReader(file_desc)

        rows = 0
        for row in reader:
            name: str | None = row.get('name')
            if not name:
                continue

            creators_track.write(f'{name}\n')
            creators_seen.add(name)
            
            if row['known'] or row['Ignore']:
                continue

            if 'vevo' in row['name'].lower():
                continue

            channel = YouTubeChannel.get_channel(name)
            if not channel:
                continue

            rows += 1
            if rows < args.skip:
                continue

            country: str = ''
            video_count: str = ''
            view_count: str = ''
            try:
                request = youtube.channels().list(
                    part='id,snippet,statistics',
                    maxResults=1, id=channel.channel_id
                )
                response = request.execute()
                if len(response.get('items', [])):
                    item: dict[str, any] = response['items'][0]
                    country = item['snippet'].get('country')
                    view_count = item['statistics'].get('viewCount')
                    video_count = item['statistics'].get('videoCount')
            except Exception as exc:
                print(f'Failed to get channel info: {exc}')

            line: str = (
                f'{channel.title},'
                f'"=HYPERLINK(""https://youtube.com/@{channel.name}"", ""{channel.name}"")",,'      # noqa: E501
                f'{channel.subs_count},{video_count},'
                f'{view_count},,,{country}\n'
            )
            creators_out.write(line.encode('utf-8'))

            if rows >= args.rows + args.skip:
                break

    creators_out.close()
    creators_track.close()


if __name__ == '__main__':
    main(sys.argv)
