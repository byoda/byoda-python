'''
Model a Youtube video/audio/storyboard etc. format

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

from typing import Self


class YouTubeFragment:
    '''
    Models a fragment of a YouTube video or audio track
    '''

    def __init__(self) -> None:
        self.url: str | None = None
        self.duration: float | None = None
        self.path: str | None = None

    def as_dict(self) -> dict[str, str | float]:
        '''
        Returns a dict representation of the fragment
        '''

        return {
            'url': self.url,
            'duration': self.duration,
            'path': self.path
        }

    @staticmethod
    def from_dict(data: dict[str, str | float]) -> Self:
        '''
        Factory for YouTubeFragment, parses data are provided
        by yt-dlp
        '''

        fragment = YouTubeFragment()
        fragment.url = data.get('url')
        fragment.path = data.get('path')
        fragment.duration = data.get('duration')
        return fragment


class YouTubeFormat:
    '''
    Models a track (audio, video, or storyboard of YouTube video
    '''

    def __init__(self) -> None:
        self.format_id: str | None = None
        self.format_note: str | None = None
        self.ext: str | None = None
        self.audio_ext: str | None = None
        self.video_ext: str | None = None
        self.protocol: str | None = None
        self.audio_codec: str | None = None
        self.video_codec: str | None = None
        self.container: str | None = None
        self.url: str | None = None
        self.width: int | None = None
        self.height: int | None = None
        self.fps: float | None = None
        self.quality: float | None = None
        self.dynamic_range: str | None = None
        self.has_drm: bool | None = None
        self.tbr: float | None = None
        self.abr: float | None = None
        self.asr: int | None = None
        self.audio_channels: int | None = None
        self.rows: int | None = None
        self.cols: int | None = None
        self.fragments: list[YouTubeFragment] = []
        self.resolution: str | None = None
        self.aspect_ratio: str | None = None
        self.format: str | None = None

    def __str__(self) -> str:
        return (
            f'YouTubeFormat('
            f'{self.format_id}, {self.format_note}, {self.ext}, '
            f'{self.protocol}, {self.audio_codec}, {self.video_codec}, '
            f'{self.container}, {self.width}, {self.height}, {self.fps}, '
            f'{self.resolution}, '
            f'{self.audio_ext}, {self.video_ext}'
            ')'
        )

    def as_dict(self) -> dict[str, any]:
        '''
        Returns a dict representation of the video
        '''

        data: dict[str, any] = {
            'format_id': self.format_id,
            'format_note': self.format_note,
            'ext': self.ext,
            'audio_ext': self.audio_ext,
            'video_ext': self.video_ext,
            'protocol': self.protocol,
            'audio_codec': self.audio_codec,
            'video_codec': self.video_codec,
            'container': self.container,
            'url': self.url,
            'width': self.width,
            'height': self.height,
            'fps': self.fps,
            'quality': self.quality,
            'dynamic_range': self.dynamic_range,
            'has_drm': self.has_drm,
            'tbr': self.tbr,
            'abr': self.abr,
            'asr': self.asr,
            'audio_channels': self.audio_channels,
            'rows': self.rows,
            'cols': self.cols,
            'fragments': [],
            'resolution': self.resolution,
            'aspect_ratio': self.aspect_ratio,
            'format': self.format,
        }

        for fragment in self.fragments:
            data['fragments'].append(fragment.as_dict())

        return data

    def from_dict(data: dict[str, any]) -> Self:
        '''
        Factory using data retrieved using the 'yt-dlp' tool
        '''

        format = YouTubeFormat()
        format.format_id = data['format_id']
        format.format_note = data.get('format_note')
        format.ext = data.get('ext')
        format.protocol = data.get('protocol')
        format.audio_codec = data.get('acodec')
        if format.audio_codec and format.audio_codec.lower() == 'none':
            format.audio_codec = None

        format.video_codec = data.get('vcodec')
        if format.video_codec and format.video_codec.lower() == 'none':
            format.video_codec = None

        format.container = data.get('container')
        format.audio_ext = data.get('audio_ext')
        format.video_ext = data.get('video_ext')
        format.url = data.get('url')
        format.width = data.get('width')
        format.height = data.get('height')
        format.fps = data.get('fps')
        format.tbr = data.get('tbr')
        format.asr = data.get('asr')
        format.abr = data.get('abr')
        format.rows = data.get('rows')
        format.cols = data.get('cols')
        format.audio_channels = data.get('audio_channels')
        format.dynamic_range = data.get('dynamic_range')

        format.resolution = data.get('resolution')
        format.aspect_ratio = data.get('aspect_ratio')
        format.audio_ext = data.get('audio_ext')
        format.video_ext = data.get('video_ext')
        format.format = data.get('format')

        for fragment_data in data.get('fragments', []):
            fragment: YouTubeFragment = YouTubeFragment.from_dict(
                fragment_data
            )
            format.fragments.append(fragment)

        return format

    def get_filename(self, video_id: str) -> str:
        '''
        Returns the filename of the video
        '''

        return f'{self.format_id}.{self.ext}'
