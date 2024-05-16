'''
Definitions for the tracks containing audio and video of a Youtube video

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

# flake8: noqa: E501

# These are the MPEG-DASH AV1 and H.264 streams that we want to download. We
# try to download streams that have 'wanted' == True. If a video does not
# have one of the wanted streams, then we will try to download the replacement.
# We are currently not attempting to download 8k streams
TARGET_VIDEO_STREAMS: dict[str, dict[str, str | bool |  None]] = {
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
TARGET_AUDIO_STREAMS: dict[str, dict[str, str | bool |  None]] = {
    '599': {'codec': 'mp4a HE v1 32kbps', 'wanted': True, 'replacement': None},
    '139': {'codec': 'mp4a HE v1 48kbps', 'wanted': True, 'replacement': None},
    '140': {'codec': 'mp4a AAC-LC 128kbps', 'wanted': True, 'replacement': None},
    '141': {'codec': 'mp4a AAC-LC 256kbps', 'wanted': True, 'replacement': None},
}

# We are not interested in formats:
# 600: Audio-oly, opus, webm, abr 32.101, asr 48000
# 139: Audio only, m4a.40.5, mp4a_dash, m4a, asr 22050, abr 48.782
# 249: Audio only: opus, webm, abr: 47.456, asr: 48000
# 250: Audio-only, opus, webm, abr: 61.891, asr: 48000
# 251: Audio-only, opus, webm, abr: 123.182, asr: 48000
# 597, resolution: 256x144, 'AVC1.4d400b, 15fps
# 602, resoltion: 256x144, VP9, 15fps, HLS
# 598, resolution: 256x144, VP9, 15fps, DASH
# 269, resoltion: 256x144, AVC1.4D400C', 30fps, HLS
# 603, resolution:  256x144: VP9, 30fps, HLS
# 278, resolution: 256x144, VO8, 30fps, DASH
# 229, resolution: 426x240, AVC1.4D4015, 30fps, HLS
# 604: resolution: 426x240, VP9, 30fps, HLS
# 242: resolution: 426x240, VP9, 30fps, DASH
# 230: resolution: 640x360, AVC1.4D401E, 30fps, HLS
# 18: resolution: 640x360, AVC1.42001E, 30fps, MP4
# 605: resolution: 640x360, VP9, 30fps, HLS
# 243: resolution: 640x360, VP9, 30fps, DASH
# 231: resolution: 854x480, AVC1.4D401f, 30fps, HLS
# 606: resolution: 854x480, AVC1, 30fps, HLS
# 244: resolution: 854x480, VP9, 30fps, DASH
# 22: resolution: 1280x720, AVC1.64001F, 30fps, MP4, audio: mp4a.40.2, channels: 2, ASR: 44100
# 247: resolution: 1280x720, VP9, 30fps, DASH
# 394: resolution: 1280x720, AV1.0.08M.08, 60fps, DASH
# 311: resolution: 1280x720, AVC1.4D4020, 60fps, HLS
# 298: resolution: 1280x720, AVC1.4D4020, 60fps, DASH
# 612: resolution: 1280x720, VP9, 60fps, HLS
# 302: resolution: 1280x720, VP9, 60fps, DASH
# 312: resolution: 1920x1080, AVC1.64002A, 60fps, HLS
# 617: resolution: 1920x1080, VP9, 60fps, HLS
# 303: resolution: 1920x1080, VP9, 60fps, DASH

# sb3, storyboard, 48x27, fps 0.0134
# sb2, storyboard, 80x45, fps: 0.1001617 mhtml
# sb1, storyboard, 160x90, fps: 0.1001617 mhtml
# sb0, storyboard, 320x180, fps: 0.1001617, mhtml