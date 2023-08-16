'''
Twitter functions for podworker

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

import logging

from time import gmtime
from calendar import timegm

from byoda.datamodel.member import Member
from byoda.datamodel.network import Network

from byoda.datatypes import IdType

from byoda.requestauth.jwt import JWT

from byoda.datastore.data_store import DataStore

from byoda.storage.filestorage import FileStorage

from byoda.data_import.youtube import YouTube

from byoda.servers.pod_server import PodServer

from tests.lib.defines import ADDRESSBOOK_SERVICE_ID
from tests.lib.defines import MODTEST_URL, MODTEST_API_ID

_LOGGER = logging.getLogger(__name__)

LOCK_FILE: str = '/var/lock/youtube_ingest.lock'
LOCK_TIMEOUT: int = 60 * 60 * 24 * 3


async def youtube_update_task(server: PodServer):
    await server.account.load_memberships()
    member: Member = server.account.memberships.get(ADDRESSBOOK_SERVICE_ID)

    if not member:
        _LOGGER.info('Not a member of the address book service')
        return

    youtube: YouTube = server.youtube_client
    if YouTube.youtube_integration_enabled() and not server.youtube_client:
        _LOGGER.debug('Enabling YouTube integration')
        youtube: YouTube = YouTube()

    if not youtube:
        _LOGGER.debug('Skipping YouTube update as it is not enabled')
        return

    data_store: DataStore = server.data_store
    storage_driver: FileStorage = server.storage_driver
    network: Network = server.network
    jwt = JWT.create(
        member.member_id, IdType.MEMBER, member.data_secret, network.name,
        ADDRESSBOOK_SERVICE_ID, IdType.SERVICE, MODTEST_API_ID,
        expiration_days=3
    )

    ingested_videos = await YouTube.load_ingested_videos(
        member.member_id, data_store
    )

    try:
        if os.path.exists(LOCK_FILE):
            ctime: int = os.path.getctime(LOCK_FILE)
            now: int = timegm(gmtime())
            if ctime < now - LOCK_TIMEOUT:
                _LOGGER.debug(
                    f'Removing state lock file, created {now - ctime} '
                    'seconds ago'
                )
                os.remove(LOCK_FILE)
            else:
                _LOGGER.info(
                    'YouTube ingest lock file exists, skipping this run'
                )
                return

        with open(LOCK_FILE, 'w') as lock_file:
            lock_file.write('1')
        _LOGGER.debug('Running YouTube metadata update')
        await youtube.get_videos(ingested_videos, max_api_requests=210)
        await youtube.persist_videos(
            member, data_store, storage_driver, ingested_videos,
            moderate_url=MODTEST_URL, moderate_jwt_header=jwt.encoded
        )
        os.remove(LOCK_FILE)

    except Exception as exc:
        _LOGGER.exception(f'Exception during Youtube metadata update: {exc}')
