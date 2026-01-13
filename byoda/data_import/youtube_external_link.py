'''
Model an external link of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''


class YouTubeExternalLink:
    def __init__(self, name: str, url: str, priority: int) -> None:
        self.name: str = name
        self.url: str = url
        self.priority: int = priority

    def as_dict(self) -> dict:
        return {
            'name': self.name,
            'url': self.url,
            'priority': self.priority,
        }

    def __hash__(self) -> int:
        return hash(self.url)

    def __eq__(self, other) -> bool:
        return self.url == other.url
