'''
Definitions for the tracks containing audio and video of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
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


# Resolution identifiers
RES_4320P    = '4320p'
RES_2160P    = '2160p'
RES_1440P    = '1440p'
RES_1080P    = '1080p'
RES_720P     = '720p'
RES_608P     = '608p'
RES_480P     = '480p'
RES_360P     = '360p'
RES_240P     = '240p'
RES_144P     = '144p'
RES_72P      = '72p'

# Streaming protocol identifiers
PROTO_DASH = 'DASH'
PROTO_M3U8 = 'M3U8'
PROTO_HLS  = 'HLS'

# Video codec identifiers
CODEC_AV1_HFR_HIGH = 'AV1 HFR High'
CODEC_AV1_HFR      = 'AV1 HFR'
CODEC_AV1          = 'AV1'
CODEC_VP9_HFR      = 'VP9 HFR'
CODEC_VP9          = 'VP9'
CODEC_VP9_15FPS    = 'VP9 15fps'
CODEC_VP9_2_HDR    = 'VP9.2 HDR'
CODEC_H264_HFR     = 'H.264 HFR'
CODEC_H264         = 'H.264'

# Audio codec identifiers
CODEC_MP4A_HE_V1_48   = 'mp4a HE v1 48kbps'
CODEC_MP4A_HE_V1_30   = 'mp4a HE v1 30kbps'
CODEC_MP4A_AAC_LC_128 = 'mp4a AAC-LC 128kbps'
CODEC_OPUS_50         = 'Opus ~50kbps'
CODEC_OPUS_70         = 'Opus ~70kbps'
CODEC_OPUS_128        = 'Opus ~128kbps'
CODEC_OPUS_35         = 'Opus ~35kbps'


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
TARGET_VIDEO_STREAMS: dict[str, dict[str, str | bool | None]] = {
    # AV1 HFR High (HDR) — DASH  (tbr varies by content; not documented in gist)
    '702': {'resolution': RES_4320P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': False, 'replacement': '402', 'category': EncodingCategory.EIGHTK},
    '701': {'resolution': RES_2160P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '401', 'category': EncodingCategory.FOURK},
    '700': {'resolution': RES_1440P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '400', 'category': EncodingCategory.FOURK},
    '699': {'resolution': RES_1080P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '399', 'category': EncodingCategory.TENEIGHTY},
    '698': {'resolution': RES_720P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '398', 'category': EncodingCategory.SEVENTWENTY},
    '697': {'resolution': RES_480P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '397', 'category': EncodingCategory.SD},
    '696': {'resolution': RES_360P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '396', 'category': EncodingCategory.SD},
    '695': {'resolution': RES_240P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '395', 'category': EncodingCategory.SD},
    '694': {'resolution': RES_144P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR_HIGH, 'tbr': None, 'wanted': True,  'replacement': '394', 'category': EncodingCategory.SD},
    # AV1 HFR — DASH
    '402': {'resolution': RES_4320P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.EIGHTK},
    '571': {'resolution': RES_4320P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.EIGHTK},
    '401': {'resolution': RES_2160P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': True,  'replacement': '305', 'category': EncodingCategory.FOURK},
    '400': {'resolution': RES_1440P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': True,  'replacement': '304', 'category': EncodingCategory.FOURK},
    '399': {'resolution': RES_1080P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': True,  'replacement': '299', 'category': EncodingCategory.TENEIGHTY},
    '721': {'resolution': RES_1080P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': True,  'replacement': '299', 'category': EncodingCategory.TENEIGHTY},
    '398': {'resolution': RES_720P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1_HFR, 'tbr': None, 'wanted': True,  'replacement': '298', 'category': EncodingCategory.SEVENTWENTY},
    # AV1 — DASH
    '397': {'resolution': RES_480P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1, 'tbr': None, 'wanted': True, 'replacement': '135', 'category': EncodingCategory.SD},
    '396': {'resolution': RES_360P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1, 'tbr': None, 'wanted': True, 'replacement': '134', 'category': EncodingCategory.SD},
    '395': {'resolution': RES_240P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1, 'tbr': None, 'wanted': True, 'replacement': '133', 'category': EncodingCategory.SD},
    '394': {'resolution': RES_144P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_AV1, 'tbr': None, 'wanted': True, 'replacement': '160', 'category': EncodingCategory.SD},
    # VP9 — M3U8  (tbr from gist HLS playlist; includes muxed audio)
    '625': {'resolution': RES_2160P, 'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,     'tbr': 18661, 'wanted': False, 'replacement': '313', 'category': EncodingCategory.FOURK},
    '620': {'resolution': RES_1440P, 'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,     'tbr':  8745, 'wanted': False, 'replacement': '271', 'category': EncodingCategory.FOURK},
    '617': {'resolution': RES_1080P, 'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9_HFR, 'tbr':  6443, 'wanted': False, 'replacement': '303', 'category': EncodingCategory.TENEIGHTY},
    '614': {'resolution': RES_1080P, 'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,     'tbr':  2940, 'wanted': False, 'replacement': '248', 'category': EncodingCategory.TENEIGHTY},
    '612': {'resolution': RES_720P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9_HFR, 'tbr':  None, 'wanted': False, 'replacement': '302', 'category': EncodingCategory.SEVENTWENTY},
    # VP9 — DASH
    '272': {'resolution': RES_4320P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.EIGHTK},
    '271': {'resolution': RES_1440P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '313', 'category': EncodingCategory.FOURK},
    '315': {'resolution': RES_2160P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_HFR, 'tbr': None, 'wanted': False, 'replacement': '401', 'category': EncodingCategory.FOURK},
    '313': {'resolution': RES_2160P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '400', 'category': EncodingCategory.FOURK},
    '308': {'resolution': RES_1440P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_HFR, 'tbr': None, 'wanted': False, 'replacement': '399', 'category': EncodingCategory.FOURK},
    '303': {'resolution': RES_1080P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_HFR, 'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.TENEIGHTY},
    '302': {'resolution': RES_720P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_HFR, 'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.SEVENTWENTY},
    '248': {'resolution': RES_1080P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.TENEIGHTY},
    '247': {'resolution': RES_720P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.SEVENTWENTY},
    '246': {'resolution': RES_480P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '245', 'category': EncodingCategory.SD},
    '245': {'resolution': RES_480P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.SD},
    '244': {'resolution': RES_480P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.SD},
    '243': {'resolution': RES_360P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.SD},
    '242': {'resolution': RES_240P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '',    'category': EncodingCategory.SD},
    '278': {'resolution': RES_144P,      'codec': CODEC_VP9,               'tbr': None, 'wanted': False, 'target': PROTO_DASH, 'replacement': '',    'category': EncodingCategory.SD},
    '598': {'resolution': RES_144P,      'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.SD},
    '356': {'resolution': RES_1080P,     'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9,     'tbr': None, 'wanted': False, 'replacement': '248', 'category': EncodingCategory.TENEIGHTY},
    # VP9.2 HDR streams (HDR10 / HLG) — DASH
    '337': {'resolution': RES_2160P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '315', 'category': EncodingCategory.FOURK},
    '336': {'resolution': RES_1440P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '308', 'category': EncodingCategory.FOURK},
    '335': {'resolution': RES_1080P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '303', 'category': EncodingCategory.TENEIGHTY},
    '334': {'resolution': RES_720P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '302', 'category': EncodingCategory.SEVENTWENTY},
    '333': {'resolution': RES_480P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '244', 'category': EncodingCategory.SD},
    '332': {'resolution': RES_360P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '243', 'category': EncodingCategory.SD},
    '331': {'resolution': RES_240P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '242', 'category': EncodingCategory.SD},
    '330': {'resolution': RES_144P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_VP9_2_HDR, 'tbr': None, 'wanted': False, 'replacement': '278', 'category': EncodingCategory.SD},
    # VP9 — M3U8  (tbr from gist HLS playlist; includes muxed audio)
    '609': {'resolution': RES_720P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,       'tbr': 1705, 'wanted': False, 'replacement': '247', 'category': EncodingCategory.SEVENTWENTY},
    '606': {'resolution': RES_480P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,       'tbr':  926, 'wanted': False, 'replacement': '244', 'category': EncodingCategory.SD},
    '605': {'resolution': RES_360P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,       'tbr':  567, 'wanted': False, 'replacement': '243', 'category': EncodingCategory.SD},
    '604': {'resolution': RES_240P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,       'tbr':  289, 'wanted': False, 'replacement': '242', 'category': EncodingCategory.SD},
    '603': {'resolution': RES_144P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9,       'tbr':  156, 'wanted': False, 'replacement': '278', 'category': EncodingCategory.SD},
    '602': {'resolution': RES_144P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_VP9_15FPS, 'tbr':   87, 'wanted': False, 'replacement': '598', 'category': EncodingCategory.SD},
    # H.264 — DASH
    '138': {'resolution': RES_4320P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.EIGHTK},
    '305': {'resolution': RES_2160P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264_HFR, 'tbr': None, 'wanted': False, 'replacement': '266', 'category': EncodingCategory.FOURK},
    '304': {'resolution': RES_1440P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264_HFR, 'tbr': None, 'wanted': False, 'replacement': '264', 'category': EncodingCategory.FOURK},
    '299': {'resolution': RES_1080P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264_HFR, 'tbr': None, 'wanted': True,  'replacement': '137', 'category': EncodingCategory.TENEIGHTY},
    '298': {'resolution': RES_720P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264_HFR, 'tbr': None, 'wanted': True,  'replacement': '136', 'category': EncodingCategory.SEVENTWENTY},
    '266': {'resolution': RES_2160P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.FOURK},
    '264': {'resolution': RES_1440P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.FOURK},
    '212': {'resolution': RES_480P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': '135', 'category': EncodingCategory.SD},
    '137': {'resolution': RES_1080P, 'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.TENEIGHTY},
    '136': {'resolution': RES_720P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SEVENTWENTY},
    '135': {'resolution': RES_480P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '134': {'resolution': RES_360P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '133': {'resolution': RES_240P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '160': {'resolution': RES_144P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '597': {'resolution': RES_144P,  'streaming_protocol': PROTO_DASH, 'codec': CODEC_H264,     'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.SD},
    # H.264 — M3U8  (tbr from gist HLS playlist; includes muxed audio)
    '312': {'resolution': RES_1080P, 'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264_HFR, 'tbr': 7987, 'wanted': False, 'replacement': '299', 'category': EncodingCategory.TENEIGHTY},
    '311': {'resolution': RES_720P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264_HFR, 'tbr': 4842, 'wanted': False, 'replacement': '298', 'category': EncodingCategory.SEVENTWENTY},
    '379': {'resolution': RES_720P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr': None, 'wanted': False, 'replacement': '214', 'category': EncodingCategory.SEVENTWENTY},
    '270': {'resolution': RES_1080P, 'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr': 4694, 'wanted': False, 'replacement': '137', 'category': EncodingCategory.TENEIGHTY},
    '232': {'resolution': RES_720P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr': 2640, 'wanted': False, 'replacement': '136', 'category': EncodingCategory.SEVENTWENTY},
    '231': {'resolution': RES_480P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr': 1358, 'wanted': False, 'replacement': '135', 'category': EncodingCategory.SD},
    '230': {'resolution': RES_360P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr':  812, 'wanted': False, 'replacement': '134', 'category': EncodingCategory.SD},
    '229': {'resolution': RES_240P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr':  327, 'wanted': False, 'replacement': '133', 'category': EncodingCategory.SD},
    '269': {'resolution': RES_144P,  'streaming_protocol': PROTO_M3U8, 'codec': CODEC_H264,     'tbr':  175, 'wanted': False, 'replacement': '160', 'category': EncodingCategory.SD},
    # H.264 — HLS (livestream)
    '301': {'resolution': RES_1080P, 'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264_HFR, 'tbr': None, 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '300': {'resolution': RES_720P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264_HFR, 'tbr': None, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SEVENTWENTY},
    '214': {'resolution': RES_720P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': False, 'replacement': '136', 'category': EncodingCategory.SEVENTWENTY},
    '151': {'resolution': RES_72P,   'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': False, 'replacement': None,  'category': EncodingCategory.SD},
    '132': {'resolution': RES_240P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '96':  {'resolution': RES_1080P, 'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.TENEIGHTY},
    '95':  {'resolution': RES_720P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SEVENTWENTY},
    '94':  {'resolution': RES_480P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '93':  {'resolution': RES_360P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '92':  {'resolution': RES_240P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '91':  {'resolution': RES_144P,  'streaming_protocol': PROTO_HLS, 'codec': CODEC_H264,     'tbr': None, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
}


# These are the MPEG-DASH MP4 audio streams that we want to download.
TARGET_AUDIO_STREAMS: dict[str, dict[str, str | int]] = {
    # DASH stereo — MP4/AAC
    '139':     {'codec': CODEC_MP4A_HE_V1_48,   'bitrate':  48, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '139-drc': {'codec': CODEC_MP4A_HE_V1_48,   'bitrate':  48, 'wanted': True,  'replacement': None,  'category': EncodingCategory.SD},
    '140':     {'codec': CODEC_MP4A_AAC_LC_128,  'bitrate': 128, 'wanted': True,  'replacement': None,  'category': EncodingCategory.TENEIGHTY},
    '140-drc': {'codec': CODEC_MP4A_AAC_LC_128,  'bitrate': 128, 'wanted': True,  'replacement': None,  'category': EncodingCategory.TENEIGHTY},
    '141':     {'codec': 'mp4a AAC-LC 256kbps',  'bitrate': 256, 'wanted': True,  'replacement': None,  'category': EncodingCategory.FOURK},
    # DASH stereo — WebM/Opus
    '249':     {'codec': CODEC_OPUS_50,  'bitrate':  50, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '249-drc': {'codec': CODEC_OPUS_50,  'bitrate':  50, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '250':     {'codec': CODEC_OPUS_70,  'bitrate':  70, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '250-drc': {'codec': CODEC_OPUS_70,  'bitrate':  70, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '251':     {'codec': CODEC_OPUS_128, 'bitrate': 128, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '251-drc': {'codec': CODEC_OPUS_128, 'bitrate': 128, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    # DASH surround — MP4
    '256':     {'codec': 'mp4a HE v1 192kbps',  'bitrate': 192, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '258':     {'codec': 'mp4a AAC-LC 384kbps',  'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '325':     {'codec': 'DTSE 384kbps',         'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '327':     {'codec': 'mp4a AAC-LC 256kbps',  'bitrate': 256, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '328':     {'codec': 'EAC3 384kbps',         'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '380':     {'codec': 'AC3 384kbps',          'bitrate': 384, 'channels': '5.1', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    # DASH ambisonic / spatial — WebM
    '338':     {'codec': 'Opus ~480kbps',        'bitrate': 480, 'channels': '4',     'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '773':     {'codec': 'IAMF Opus ~900kbps',   'bitrate': 900, 'channels': '7.1.4', 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    '774':     {'codec': 'Opus ~256kbps',        'bitrate': 256,                       'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
    # DASH mobile-restricted (requires POT token on mobile web)
    '599':     {'codec': CODEC_MP4A_HE_V1_30, 'bitrate': 30, 'wanted': True,  'replacement': None, 'category': EncodingCategory.SD},
    '599-drc': {'codec': CODEC_MP4A_HE_V1_30, 'bitrate': 30, 'wanted': True,  'replacement': None, 'category': EncodingCategory.SD},
    '600':     {'codec': CODEC_OPUS_35,        'bitrate': 35, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    '600-drc': {'codec': CODEC_OPUS_35,        'bitrate': 35, 'wanted': False, 'replacement': None, 'category': EncodingCategory.SD},
    # M3U8 audio-only (HLS duplicates of DASH equivalents)
    '233':     {'codec': CODEC_MP4A_HE_V1_48,  'bitrate':  48, 'wanted': False, 'replacement': '139', 'category': EncodingCategory.SD},
    '234':     {'codec': CODEC_MP4A_AAC_LC_128, 'bitrate': 128, 'wanted': False, 'replacement': '140', 'category': EncodingCategory.TENEIGHTY},
    # Legacy WebM/Vorbis
    '171':     {'codec': 'vorbis 128kbps', 'bitrate': 128, 'wanted': False, 'replacement': None, 'category': EncodingCategory.TENEIGHTY},
    '172':     {'codec': 'vorbis 256kbps', 'bitrate': 256, 'wanted': False, 'replacement': None, 'category': EncodingCategory.FOURK},
}


# Storyboard formats
TARGET_STORYBOARD_STREAMS: dict[str, dict] = {
    'sb0': {'width': 320, 'height': 180, 'fps': 0.1001617, 'ext': 'mhtml'},
    'sb1': {'width': 160, 'height':  90, 'fps': 0.1001617, 'ext': 'mhtml'},
    'sb2': {'width':  80, 'height':  45, 'fps': 0.1001617, 'ext': 'mhtml'},
    'sb3': {'width':  48, 'height':  27, 'fps': 0.0134,    'ext': None},
}

# Progressive (muxed video+audio) formats. These contain both video and audio
# in a single stream and are downloaded as a single file (not DASH/HLS segments).
# Most are discontinued on YouTube but may still appear on Google Drive previews.
TARGET_PROGRESSIVE_STREAMS: dict[str, dict] = {
    '17': {'resolution': RES_144P,  'fps': 7.5, 'codec': 'MPEG-4 AAC-LC', 'video_codec': 'MPEG-4',   'audio_codec': 'AAC-LC', 'audio_bitrate': 24,  'container': '3gp', 'wanted': False, 'replacement': '160', 'category': EncodingCategory.SD},
    '18': {'resolution': RES_360P,  'fps': 30,  'codec': 'H.264 AAC-LC', 'video_codec': CODEC_H264, 'audio_codec': 'AAC-LC', 'audio_bitrate': 128, 'container': 'mp4', 'wanted': False, 'replacement': '134', 'category': EncodingCategory.SD},
    '37': {'resolution': RES_1080P, 'fps': 30,  'codec': 'H.264 AAC-LC', 'video_codec': CODEC_H264, 'audio_codec': 'AAC-LC', 'audio_bitrate': 128, 'container': 'mp4', 'wanted': False, 'replacement': '137', 'category': EncodingCategory.TENEIGHTY},
    '59': {'resolution': RES_480P,  'fps': 30,  'codec': 'H.264 AAC-LC', 'video_codec': CODEC_H264, 'audio_codec': 'AAC-LC', 'audio_bitrate': 128, 'container': 'mp4', 'wanted': False, 'replacement': '135', 'category': EncodingCategory.SD},
    # Discontinued June 2024, listed for completeness
    '22': {'resolution': RES_720P,  'fps': 30,  'codec': 'H.264 AAC-LC', 'video_codec': CODEC_H264, 'audio_codec': 'AAC-LC', 'audio_bitrate': 128, 'container': 'mp4', 'wanted': False, 'replacement': '136', 'category': EncodingCategory.SEVENTWENTY},
}
