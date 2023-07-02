'''
Definitions for the tracks containing audio and video of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

# flake8: noqa: E501

# These are the MPEG-DASH AV1 and H.264 streams that we want to download. We
# try to download streams that have 'wanted' == True. If a video does not
# have one of the wanted streams, then we will try to download the replacement.
# We are currently not attempting to download 8k streams
TARGET_VIDEO_STREAMS = {
    '701': {'resolution': '2160p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '401'},
    '700': {'resolution': '1440p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '400'},
    '699': {'resolution': '1080p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '399'},
    '698': {'resolution': '720p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '398'},
    '697': {'resolution': '480p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '397'},
    '696': {'resolution': '360p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '396'},
    '695': {'resolution': '240p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '395'},
    '694': {'resolution': '144p', 'codec': 'AV1 HFR High', 'wanted': True, 'replacement': '394'},
    '398': {'resolution': '720p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '298'},
    '402': {'resolution': '4320p', 'codec': 'AV1 HFR', 'wanted': False, 'replacement': None},
    '571': {'resolution': '4320p', 'codec': 'AV1 HFR', 'wanted': False, 'replacement': None},
    '401': {'resolution': '2160p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '305'},
    '400': {'resolution': '1440p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '304'},
    '399': {'resolution': '1080p', 'codec': 'AV1 HFR', 'wanted': True, 'replacement': '299'},
    '397': {'resolution': '480p', 'codec': 'AV1', 'wanted': True, 'replacement': '135'},
    '396': {'resolution': '360p', 'codec': 'AV1', 'wanted': True, 'replacement': '134'},
    '395': {'resolution': '240p', 'codec': 'AV1', 'wanted': True, 'replacement': '133'},
    '394': {'resolution': '144p', 'codec': 'AV1', 'wanted': True, 'replacement': '160'},
    '305': {'resolution': '2160p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '266'},
    '304': {'resolution': '1440p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '264'},
    '299': {'resolution': '1080p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '137'},
    '298': {'resolution': '720p', 'codec': 'H.264 HFR', 'wanted': True, 'replacement': '136'},
    '266': {'resolution': '2160p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '264': {'resolution': '1440p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '137': {'resolution': '1080p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '136': {'resolution': '720p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '135': {'resolution': '480p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '134': {'resolution': '360p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '133': {'resolution': '240p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
    '160': {'resolution': '144p', 'codec': 'H.264', 'wanted': True, 'replacement': None},
}

# These are the MPEG-DASH MP4 audio streams that we want to download.
TARGET_AUDIO_STREAMS = {
    '599': {'codec': 'mp4a HE v1 32kbps', 'wanted': True, 'replacement': None},
    '139': {'codec': 'mp4a HE v1 48kbps', 'wanted': True, 'replacement': None},
    '140': {'codec': 'mp4a AAC-LC 128kbps', 'wanted': True, 'replacement': None},
    '141': {'codec': 'mp4a AAC-LC 256kbps', 'wanted': True, 'replacement': None},
}
