'''
Definitions for the tracks containing audio and video of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

# flake8: noqa: E501

from enum import Enum
from typing import Self



class EncodingCategory(Enum):
    '''
    We use numbering so that we can include all tracks with category <= 3
    for an upto and including HD manifest
    '''
    SD          = 1
    SEVENTWENTY = 2
    TENEIGHTY   = 3
    FOURK       = 4
    EIGHTK      = 5

    def __lt__(self, other: Self) -> bool:
        return self.value < other.value

    def label(self) -> str:
        if self == EncodingCategory.SD:
            return 'SD'
        elif self == EncodingCategory.SEVENTWENTY:
            return '720p'
        elif self == EncodingCategory.TENEIGHTY:
            return '1080p'
        elif self == EncodingCategory.FOURK:
            return '4K'
        elif self == EncodingCategory.EIGHTK:
            return '8K'
        else:
            return 'Unknown'

# Formats documented by yt-dlp, line 1184+ from
# https://github.com/yt-dlp/yt-dlp/blob/master/yt_dlp/extractor/youtube.py
# Also: https://gist.github.com/MartinEesmaa/2f4b261cb90a47e9c41ba115a011a4aa
# These are the MPEG-DASH AV1 and H.264 streams that we want to download. We
# try to download streams that have 'wanted' == True. If a video does not
# have one of the wanted streams, then we will try to download the replacement.
# We are currently not attempting to download 8k streams
# We want
# AV1: everything
# VP9: everything
# H.264: 1080p and 720p, but not HFR
# VP8: nothing
TARGET_VIDEO_STREAMS: dict[str, dict[str, str | bool |  None]] = {
    '701': {'resolution': '2160p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '401', 'category': EncodingCategory.FOURK},
    '700': {'resolution': '1440p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '400', 'category': EncodingCategory.FOURK},
    '699': {'resolution': '1080p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '399', 'category': EncodingCategory.TENEIGHTY},
    '698': {'resolution': '720p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '398', 'category': EncodingCategory.SEVENTWENTY},
    '697': {'resolution': '480p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '397', 'category': EncodingCategory.SD},
    '696': {'resolution': '360p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '396', 'category': EncodingCategory.SD},
    '695': {'resolution': '240p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '395', 'category': EncodingCategory.SD},
    '694': {'resolution': '144p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '394', 'category': EncodingCategory.SD},
    '402': {'resolution': '4320p', 'codec': 'AV1 HFR', 'wanted': False, 'replacement': None, 'category': EncodingCategory.EIGHTK},
    '571': {'resolution': '4320p', 'codec': 'AV1 HFR', 'wanted': False, 'replacement': None, 'category': EncodingCategory.EIGHTK},
    '401': {'resolution': '2160p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '305', 'category': EncodingCategory.FOURK},
    '400': {'resolution': '1440p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '304', 'category': EncodingCategory.FOURK},
    '399': {'resolution': '1080p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '299', 'category': EncodingCategory.TENEIGHTY},
    '398': {'resolution': '720p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '298', 'category': EncodingCategory.SEVENTWENTY},
    '397': {'resolution': '480p', 'codec': 'AV1', 'wanted': True, 'replacement': '135', 'category': EncodingCategory.SD},
    '396': {'resolution': '360p', 'codec': 'AV1', 'wanted': True, 'replacement': '134', 'category': EncodingCategory.SD},
    '395': {'resolution': '240p', 'codec': 'AV1', 'wanted': True, 'replacement': '133', 'category': EncodingCategory.SD},
    '394': {'resolution': '144p', 'codec': 'AV1', 'wanted': True, 'replacement': '160', 'category': EncodingCategory.SD},
    '625': {'resolution': '4320p', 'codec': 'VP9', 'wanted': False, 'replacement': None, 'category': EncodingCategory.EIGHTK},
    '620': {'resolution': '1440p', 'codec': 'VP9', 'wanted': False, 'replacement': '271', 'category': EncodingCategory.FOURK},
    '617': {'resolution': '1080p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.TENEIGHTY},
    '614': {'resolution': '1080p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.TENEIGHTY},
    '612': {'resolution': '720p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.SEVENTWENTY},
    '272': {'resolution': '4320p', 'codec': 'VP9', 'wanted': False, 'replacement': None, 'category': EncodingCategory.EIGHTK},
    '271': {'resolution': '1440', 'codec': 'VP9', 'wanted': False, 'replacement': '313', 'category': EncodingCategory.FOURK},
    '315': {'resolution': '2160p', 'codec': 'VP9 HFR', 'wanted': False, 'replacement': '401', 'category': EncodingCategory.FOURK},
    '313': {'resolution': '2160p', 'codec': 'VP9', 'wanted': False, 'replacement': '400', 'category': EncodingCategory.FOURK},
    '308': {'resolution': '1440', 'codec': 'VP9 HFR', 'wanted': False, 'replacement': '399', 'category': EncodingCategory.FOURK},
    '303': {'resolution': '1080p', 'codec': 'VP9 HFR', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.TENEIGHTY},
    '302': {'resolution': '720p', 'codec': 'VP9 HFR', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SEVENTWENTY},
    '248': {'resolution': '1920x1080', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.TENEIGHTY},
    '247': {'resolution': '720p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SEVENTWENTY},
    '246': {'resolution': '480p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '245', 'category': EncodingCategory.SD},
    '245': {'resolution': '480p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SD},
    '244': {'resolution': '480p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SD},
    '243': {'resolution': '360p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SD},
    '242': {'resolution': '240p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SD},
    '278': {'resolution': '144p', 'codec': 'VP9', 'wanted': False, 'target': 'DASH', 'replacement': '', 'category': EncodingCategory.SD},
    '609': {'resolution': '1080p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.TENEIGHTY},
    '606': {'resolution': '480p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.SD},
    '605': {'resolution': '360p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.SD},
    '604': {'resolution': '240p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.SD},
    '603': {'resolution': '144p', 'codec': 'VP9', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.SD},
    '602': {'resolution': '144p', 'codec': 'VP9 15fps', 'wanted': False, 'target': 'HLS', 'replacement': '', 'category': EncodingCategory.SD},
    '305': {'resolution': '2160p', 'codec': 'H.264 HFR', 'wanted': False, 'replacement': '266', 'category': EncodingCategory.FOURK},
    '304': {'resolution': '1440p', 'codec': 'H.264 HFR', 'wanted': False, 'replacement': '264', 'category': EncodingCategory.FOURK},
    '299': {'resolution': '1080p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '137', 'category': EncodingCategory.TENEIGHTY},
    '298': {'resolution': '720p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '136', 'category': EncodingCategory.SEVENTWENTY},
    '266': {'resolution': '2160p', 'codec': 'H.264', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '264': {'resolution': '1440p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.FOURK},
    '232': {'resolution': '720p', 'codec': 'H.264', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '231': {'resolution': '480p', 'codec': 'H.264', 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '230': {'resolution': '360p', 'codec': 'H.264', 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '229': {'resolution': '240p', 'codec': 'H.264', 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '212': {'resolution': '480p', 'codec': 'H.264', 'wanted': True, 'replacement': '135', 'category': EncodingCategory.SD},
    '137': {'resolution': '1080p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '136': {'resolution': '720p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.SEVENTWENTY},
    '135': {'resolution': '480p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.SD},
    '134': {'resolution': '360p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.SD},
    '133': {'resolution': '240p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.SD},
    '160': {'resolution': '144p', 'codec': 'H.264', 'wanted': True, 'replacement': None, 'category': EncodingCategory.SD},
    '151': {'resolution': '72', 'codec': 'H.264', 'wanted': False, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SD},
    '132': {'resolution': '240p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SD},
    '96': {'resolution': '1080p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '95': {'resolution': '720p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SEVENTWENTY},
    '94': {'resolution': '480p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SD},
    '93': {'resolution': '360p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SD},
    '92': {'resolution': '240p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SD},
    '91': {'resolution': '144p', 'codec': 'H.264', 'wanted': True, 'target': 'HLS', 'replacement': None, 'category': EncodingCategory.SD},
}



# These are the MPEG-DASH MP4 audio streams that we want to download.
TARGET_AUDIO_STREAMS: dict[str, dict[str, str | int]] = {
    '139': {'codec': 'mp4a HE v1 48kbps', 'bitrate': 48, 'wanted': True, 'replacement': None, 'category': EncodingCategory.SD},
    '140': {'codec': 'mp4a AAC-LC 128kbps', 'bitrate': 128, 'wanted': True, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '141': {'codec': 'mp4a AAC-LC 256kbps', 'bitrate': 256, 'wanted': True, 'replacement': None, 'category': EncodingCategory.FOURK},
    '249': {'codec': 'Opus 50kbps', 'bitrate': 50, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '250': {'codec': 'Opus 70kbps', 'bitrate': 70, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '251': {'codec': 'Opus 160kbps', 'bitrate': 160, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '256': {'codec': 'mp4a AAC-LC 192kbps', 'bitrate': 192, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '258': {'codec': 'mp4a AAC-LC 384kbps', 'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '325': {'codec': 'mp4a AAC-LC 256kbps', 'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '327': {'codec': 'mp4a AAC-LC 256kbps', 'bitrate': 256, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '328': {'codec': 'EAC3', 'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '338': {'codec': 'Opus', 'bitrate': 480, 'channels': '4', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '380': {'codec': 'AC3', 'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '599': {'codec': 'mp4a HE v1 32kbps', 'bitrate': 32, 'wanted': True, 'replacement': None, 'category': EncodingCategory.SD},
    '600': {'codec': 'Opus', 'bitrate': 35, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '774': {'codec': 'Opus', 'bitrate': 256, 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '171': {'codec': 'vorbis 128kbps', 'bitrate': 128, 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '172': {'codec': 'vorbis 256kbps', 'bitrate': 256, 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
}


# We are not interested in these VP8 & H.264 formats:
# 139: Audio only, m4a.40.5, mp4a_dash, m4a, asr 22050, abr 48.782
# 597, resolution: 256x144, 'AVC1.4d400b, 15fps
# 602, resoltion: 256x144, VP9, 15fps, HLS
# 598, resolution: 256x144, VP9, 15fps, DASH
# 278, resolution: 256x144, VO8, 30fps, DASH
# 269, resolution: 256x144, AVC1.4D400C', 30fps, HLS
# 229, resolution: 426x240, AVC1.4D4015, 30fps, HLS
# 230: resolution: 640x360, AVC1.4D401E, 30fps, HLS
# 18: video + audio, resolution: 640x360, AVC1.42001E, 30fps, MP4 + AAC-LC 44.1khz  
# 231: resolution: 854x480, AVC1.4D401f, 30fps, HLS
# 606: resolution: 854x480, AVC1, 30fps, HLS
# 22: resolution: 1280x720, AVC1.64001F, 30fps, MP4, audio: mp4a.40.2, channels: 2, ASR: 44100
# 394: resolution: 1280x720, AV1.0.08M.08, 60fps, DASH
# 311: resolution: 1280x720, AVC1.4D4020, 60fps, HLS
# 298: resolution: 1280x720, AVC1.4D4020, 60fps, DASH
# 312: resolution: 1920x1080, AVC1.64002A, 60fps, HLS

# sb3, storyboard, 48x27, fps 0.0134
# sb2, storyboard, 80x45, fps: 0.1001617 mhtml
# sb1, storyboard, 160x90, fps: 0.1001617 mhtml
# sb0, storyboard, 320x180, fps: 0.1001617, mhtml