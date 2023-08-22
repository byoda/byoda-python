'''
Twitter functions for podworker

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

import logging

from uuid import UUID
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

    moderation_fqdn: str = os.environ.get('MODERATION_FQDN')
    moderation_url: str = f'https://{moderation_fqdn}'
    moderation_request_url: str = \
        moderation_url + YouTube.MODERATION_REQUEST_API
    moderation_claim_url = moderation_url + YouTube.MODERATION_CLAIM_URL

    moderation_app_id: str | UUID = os.environ.get('MODERATION_APP_ID')
    if moderation_app_id:
        moderation_app_id = UUID(moderation_app_id)

    data_store: DataStore = server.data_store
    storage_driver: FileStorage = server.storage_driver
    network: Network = server.network

    if moderation_app_id:
        jwt = JWT.create(
            member.member_id, IdType.MEMBER, member.data_secret, network.name,
            ADDRESSBOOK_SERVICE_ID, IdType.APP, moderation_app_id,
            expiration_days=3
        )
        jwt_header: str | None = jwt.encoded
    else:
        jwt_header: str | None = None

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
            moderate_request_url=moderation_request_url,
            moderate_jwt_header=jwt_header,
            moderation_claim_url=moderation_claim_url
        )
        os.remove(LOCK_FILE)

    except Exception as exc:
        _LOGGER.exception(f'Exception during Youtube metadata update: {exc}')
