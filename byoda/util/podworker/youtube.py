'''
Twitter functions for podworker

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import logging

from byoda.servers.pod_server import PodServer

from byoda.datamodel.member import Member

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID

_LOGGER = logging.getLogger(__name__)

NEWEST_TWEET_FILE = 'newest_tweet.txt'


async def youtube_update_task(server: PodServer):
    await server.account.load_memberships()
    member: Member = server.account.memberships.get(ADDRESSBOOK_SERVICE_ID)
    if not member:
        _LOGGER.info('Not a member of the address book service')
        
    try:
        if server.youtube_client:
            _LOGGER.debug('Running YouTube metadata update')
            server.youtube_client.get_videos(
                member.member_id, server.data_store
            )
        else:
            _LOGGER.debug('Skipping YouTube update as it is not enabled')

    except Exception:
        _LOGGER.exception('Exception during Youtube metadata update')
