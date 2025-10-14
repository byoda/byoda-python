'''
YouTube functions for pod_worker

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025
:license    : GPLv3
'''

import os

from uuid import UUID
from time import gmtime
from random import random
from calendar import timegm
from logging import Logger
from logging import getLogger

from anyio import sleep

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.network import Network
from byoda.datamodel.schema import Schema
from byoda.datamodel.dataclass import SchemaDataItem
from byoda.datamodel.table import Table

from byoda.datatypes import IdType

from byoda.requestauth.jwt import JWT

from byoda.datastore.data_store import DataStore

from byoda.storage.filestorage import FileStorage

from byoda.data_import.youtube import YouTube
from byoda.data_import.youtube_video import YouTubeVideo

from byoda.servers.pod_server import PodServer


_LOGGER: Logger = getLogger(__name__)

LOCK_FILE: str = '/var/lock/youtube_ingest.lock'
LOCK_TIMEOUT: int = 127 * 60


# Default setting, can be overriden with
# environment variable YOUTUBE_IMPORT_INTERVAL
YOUTUBE_IMPORT_INTERVAL: int = 3 * 60 * 60


async def run_youtube_startup_tasks(server: PodServer,
                                    youtube_import_service_id: int) -> None:
    '''
    Sets up task for importing YouTube videos

    :param account: the account of this pod
    :param youtube_import_service_id: The service to run the Youtube import on
    :returns: (none)
    :raises: (none)
    '''

    account: Account = server.account
    data_store: DataStore = server.data_store

    youtube_member: Member = await account.get_membership(
        youtube_import_service_id, with_pubsub=False
    )
    log_extra: dict[str, any] = {
        'member_id': youtube_member.member_id,
        'youtube_import_service_id': youtube_import_service_id
    }
    if youtube_member:
        try:
            _LOGGER.debug(
                'Running YouTube startup tasks for membership', extra=log_extra
            )
            schema: Schema = youtube_member.schema
            schema.get_data_classes(with_pubsub=False)
            await data_store.setup_member_db(
                youtube_member.member_id, youtube_import_service_id,
                youtube_member.schema
            )
        except Exception as exc:
            _LOGGER.exception(f'Exception during startup: {exc}')
            raise

        if YouTube.youtube_integration_enabled():
            if ':' in os.environ.get(YouTube.ENVIRON_CHANNEL, ''):
                _LOGGER.debug('Running YouTube import as startup task')
                await youtube_update_task(server, youtube_import_service_id)
    else:
        _LOGGER.debug(
            f'Did not find membership of service {youtube_import_service_id} '
            'for import of YouTube videos'
        )


async def youtube_update_task(server: PodServer, service_id: int) -> None:
    account: Account = server.account
    member: Member = await account.get_membership(service_id)
    schema: Schema = member.schema
    data_classes: dict[str, SchemaDataItem] = schema.data_classes

    log_extra: dict[str, any] = {
        'member_id': member.member_id,
        'service_id': service_id
    }
    if not member:
        _LOGGER.info('Not a member of service', extra=log_extra)
        return

    youtube: YouTube = server.youtube_client
    if YouTube.youtube_integration_enabled() and not server.youtube_client:
        _LOGGER.debug('Enabling YouTube integration', extra=log_extra)
        youtube: YouTube = YouTube(lock_file=LOCK_FILE)

    if not youtube:
        _LOGGER.debug(
            'Skipping YouTube update as it is not enabled', extra=log_extra
            )
        return

    if os.path.exists(LOCK_FILE):
        ctime: int = os.path.getctime(LOCK_FILE)
        now: int = timegm(gmtime())
        if ctime < now - LOCK_TIMEOUT:
            _LOGGER.debug(
                f'Removing stale lock file, created {now - ctime} '
                'seconds ago', extra=log_extra
            )
            os.remove(LOCK_FILE)
        else:
            _LOGGER.info(
                f'YouTube ingest lock file {LOCK_FILE} exists, '
                'skipping this run', extra=log_extra
            )
            return

    with open(LOCK_FILE, 'w') as lock_file:
        lock_file.write('1')

    moderation_fqdn: str = os.environ.get('MODERATION_FQDN')
    moderation_url: str = f'https://{moderation_fqdn}'
    moderation_request_url: str = \
        moderation_url + YouTube.MODERATION_REQUEST_API
    moderation_claim_url: str = moderation_url + YouTube.MODERATION_CLAIM_URL

    moderation_app_id: str | UUID = os.environ.get('MODERATION_APP_ID')
    if moderation_app_id and isinstance(moderation_app_id, str):
        moderation_app_id = UUID(moderation_app_id)

    data_store: DataStore = server.data_store
    storage_driver: FileStorage = server.storage_driver
    network: Network = server.network

    if moderation_app_id:
        jwt: JWT = JWT.create(
            member.member_id, IdType.MEMBER, member.data_secret, network.name,
            service_id, IdType.APP, moderation_app_id,
            expiration_seconds=3 * 24 * 60 * 60
        )
        jwt_header: str | None = jwt.encoded
    else:
        jwt_header: str | None = None

    data_class: SchemaDataItem = \
        data_classes[YouTubeVideo.DATASTORE_CLASS_NAME]
    video_table: Table = data_store.get_table(
        member.member_id, data_class.name
    )
    # Add a random delay between import runs to avoid overloading YouTube
    interval: int = int(
        os.environ.get('YOUTUBE_IMPORT_INTERVAL', YOUTUBE_IMPORT_INTERVAL)
    )

    random_delay: int = int(random() * interval / 4)
    _LOGGER.debug(
        'Sleeping to randomize runs',
        extra=log_extra | {'seconds': random_delay}
    )
    await sleep(random_delay)

    try:
        _LOGGER.debug('Running YouTube metadata update', extra=log_extra)

        await youtube.import_videos(
            member, data_store,  video_table, storage_driver,
            moderate_request_url=moderation_request_url,
            moderate_jwt_header=jwt_header,
            moderate_claim_url=moderation_claim_url,
            custom_domain=server.custom_domain
        )
        os.remove(LOCK_FILE)

    except Exception as exc:
        _LOGGER.debug(
            'Exception during Youtube metadata update',
            extra=log_extra | {'exception': str(exc)}
        )

    # Release memory used by the import run
    youtube.channels = []
