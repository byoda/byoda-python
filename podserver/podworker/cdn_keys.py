'''
Various utility classes, variables and functions

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import os

from logging import getLogger

from byoda.datamodel.account import Account
from byoda.datamodel.member import Member
from byoda.datamodel.schema import Schema
from byoda.datamodel.network import Network
from byoda.datamodel.content_key import ContentKey
from byoda.datamodel.table import Table

from byoda.datastore.data_store import DataStore

from byoda.servers.pod_server import PodServer

from byoda.util.paths import Paths

from byoda.util.api_client.restapi_client import RestApiClient
from byoda.util.api_client.restapi_client import HttpMethod
from byoda.util.api_client.restapi_client import HttpResponse

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)

# The data class of the schema where, if it exists for theservice,
# we store the content keys
DATA_CLASS_RESTRICTED_CONTENT_KEYS: str = 'restricted_content_keys'

# In-memory storage of the content keys that we have previously uploaded
CONTENT_KEYS: dict[int, list[ContentKey]] = {}


async def upload_content_keys(server: PodServer) -> None:
    '''
    Uploads content keys to the CDN Keys API for all services that have
    a table 'restricted_content_keys' in their schema

    :returns: (none)
    :raises: (none)
    '''

    server: PodServer = server
    account: Account = server.account
    data_store: DataStore = server.data_store

    _LOGGER.info('Uploading content keys')

    member: Member
    for member in account.memberships.values():
        cdn_app_id: str | None = os.environ.get('CDN_APP_ID')
        if not cdn_app_id:
            _LOGGER.debug('No CDN App ID defined, skipping')
            return

        schema: Schema = member.schema
        if DATA_CLASS_RESTRICTED_CONTENT_KEYS not in schema.data_classes:
            _LOGGER.debug(
                f'Service {member.service_id} does not have content keys'
            )
            continue

        content_keys: list[ContentKey] = await get_current_content_keys(
            member, data_store
        )
        if member.service_id in CONTENT_KEYS:
            known_keys: list[ContentKey] = CONTENT_KEYS[member.service_id]

            if content_keys == known_keys:
                _LOGGER.debug(
                    f'Cached content keys for service {member.service_id} are '
                    'still up to date'
                )
                continue

        await call_content_keys_api(cdn_app_id, member, content_keys)

        CONTENT_KEYS[member.service_id] = content_keys


async def get_current_content_keys(member: Member, data_store: DataStore
                                   ) -> None:

    table: Table = data_store.get_table(
        member.member_id, DATA_CLASS_RESTRICTED_CONTENT_KEYS
    )
    content_keys: list[ContentKey] = await ContentKey.get_content_keys(table)

    return content_keys


async def call_content_keys_api(cdn_app_id: str, member: Member,
                                content_keys: list[ContentKey]) -> None:

    _LOGGER.debug(f'Uploading content keys for service {member.service_id}')

    network: Network = member.network
    cdn_keys_fqdn: str = \
        f'{cdn_app_id}.apps-{member.service_id}.{network.name}'

    url: str = Paths.CDN_KEYS_API.format(fqdn=cdn_keys_fqdn)

    data: list[dict[str, str | int]] = [key.as_dict() for key in content_keys]

    try:
        resp: HttpResponse = await RestApiClient.call(
            url, HttpMethod.POST, secret=member.tls_secret,
            service_id=member.service_id, data=data
        )

        if resp.status_code == 200:
            _LOGGER.debug(f'Uploaded content keys to CDN Keys API: {url}')
        else:
            _LOGGER.error(
                f'Failed to upload content keys '
                f'for service {member.service_id} to {url}: '
                f'{resp.status_code}: {resp.text}'
            )
    except Exception as exc:
        _LOGGER.error(f'Failed to upload content keys to CDN Keys API: {exc}')
