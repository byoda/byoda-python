'''
DataApiClient, derived from ApiClient for calling REST Data APIs

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

from uuid import UUID
from uuid import uuid4
from ssl import SSLContext
from ssl import PROTOCOL_TLS_CLIENT

import orjson

from logging import getLogger

import websockets

from byoda.datatypes import DATA_WS_API_URL
from byoda.datatypes import DATA_API_PROXY_URL
from byoda.datatypes import DATA_WS_API_INTERNAL_URL

from byoda.models.data_api_models import DataFilterType

from byoda.storage.filestorage import FileStorage

from byoda.requestauth.jwt import JWT

from byoda.util.api_client.api_client import HttpResponse

from byoda.datatypes import DataRequestType

from byoda.secrets.secret import Secret
from byoda.secrets.member_secret import MemberSecret

from byoda.servers.pod_server import PodServer

from byoda.util.logger import Logger

from byoda import config

from .api_client import ApiClient
from .data_api_client import DataApiClient

_LOGGER: Logger = getLogger(__name__)


class DataWsApiClient(DataApiClient):
    SUPPORTED_REQUEST_TYPES: list[DataRequestType] = [
        DataRequestType.UPDATES, DataRequestType.COUNTER
    ]

    @staticmethod
    async def call(service_id: int, class_name: str, action: DataRequestType,
                   secret: Secret = None, jwt: JWT = None,
                   use_proxy: bool = False,
                   custom_domain: str | None = None,
                   network: str = 'byoda.net',
                   member_id: UUID = None,
                   headers: dict[str, str] | None = None,
                   query_id: UUID | None = None,
                   fields: set[str] = None,
                   depth: int = None, relations: list[str] = None,
                   data_filter: DataFilterType | None = None,
                   internal: bool = False
                   ) -> HttpResponse:

        '''
        Calls an API using the right credentials and accepted CAs

        :param service_id: ID of service to call the API from
        :param class_name: name of class to call the API for
        :param action: the type of action to request
        :param secret: secret to use for client M-TLS, must be None if JWT
        is provided
        :param jwt: JWT to use for authentication
        :param use_proxy: call API via proxy
        :param custom_domain: custom domain to use for the API call
        :param network: network to use for the API call, required
        if use_proxy is False and custom_domain is not set
        :param member_id: target member_id, required if use_proxy is False
        and custom_domain is not set
        :param headers: a list of HTTP headers to add to the request
        :param query_id: query ID to use for the request
        :param fields: which fields of the object to return
        :param depth: max (recursive) depth of updates received from
        connected pods to return (recursive websockets not currently
        implemented)
        :param relations: objects of which relations to return
        (recursive websockets not currently implemented)
        :param data_filter: only receive updates for objects that match
        :param internal: whether to use the internal API or not, also used
        for test cases
        '''

        if action not in DataWsApiClient.SUPPORTED_REQUEST_TYPES:
            raise ValueError(f'Unsupported action: {action.value}')

        if secret and (jwt or (headers and 'Authorization' in headers)):
            raise ValueError('Cannot use both JWT and secret')

        if jwt and headers and 'Authorization' in headers:
            raise ValueError(
                'Cannot specify JWT and if the headers contain '
                'the key "Authorization"'
            )

        if jwt:
            headers['Authorization'] = jwt.encoded

        data_url: str
        ssl_context: SSLContext

        data_url, ssl_context = await DataWsApiClient.get_url(
            service_id, class_name, action, secret, use_proxy, custom_domain,
            network, member_id, internal
        )

        _LOGGER.debug(f'Using data URL {data_url}')

        model: dict[str, UUID | int] = {
            'query_id': query_id or uuid4(),
            'depth': depth or 0,
            # 'fields': fields,
            # 'data_filter': data_filter,
            # 'relations': relations,
        }

        async with websockets.connect(
                data_url, ping_timeout=50, ping_interval=20,
                extra_headers=headers, ssl=ssl_context) as webs:
            body = orjson.dumps(model)
            await webs.send(body)
            _LOGGER.debug(f'Send model to WS-API: {body.decode("utf-8")}')
            while True:
                resp = await webs.recv()
                yield resp

    @staticmethod
    async def get_url(service_id: int, class_name: str,
                      action: DataRequestType | str,
                      secret: Secret | None,
                      use_proxy: bool, custom_domain: str | None,
                      network: str, member_id: UUID,
                      internal: bool) -> str:

        '''
        Calls an API using the right credentials and accepted CAs

        :param service_id: ID of service to call the API from
        :param class_name: name of class to call the API for
        :param action: the type of action to request
        :param secret: secret to use for client M-TLS, must be None if JWT
        is provided
        :param jwt: JWT to use for authentication
        :param use_proxy: call API via proxy
        :param custom_domain: custom domain to use for the API call
        :param jwt: JWT to use for authentication, must be None if the
        secret is provided
        :param params: HTTP query parameters
        :param data: data to send in both of the request
        :param member_id: the member_id of the pod you want to call, required
        if use_proxy is set to True
        :param headers: a list of HTTP headers to add to the request
        :param timeout: timeout in seconds
        :param internal: whether to use the internal API or not, also used
        :param app: FastAPI app to use for the request, used for test cases
        for test cases
        '''

        if internal:
            if not config.debug:
                raise ValueError('Not running test cases')
        elif use_proxy:
            if not (member_id and network):
                raise ValueError(
                    'Member ID and network must be provided when using proxy'
                )

            if custom_domain:
                raise ValueError(
                    'Cannot use custom domain and proxy at the same time'
                )
        elif not custom_domain and (not member_id or not network):
            raise ValueError(
                'Member ID and network must be provided when '
                'not using proxy or custom domain'
            )
        if isinstance(action, str):
            action = DataRequestType(action)

        if action not in (DataRequestType.UPDATES, DataRequestType.COUNTER):
            raise ValueError(
                'Websckets only supports UPDATES and COUNTER APIs'
            )

        port: int = 443
        if secret:
            _LOGGER.debug('Setting TCP port to 444 because We have a secret')
            port = 444

        api_url: str
        ssl_context: SSLContext | None = None
        if internal:
            _LOGGER.debug('Calling Data API from test case')
            api_url = DATA_WS_API_INTERNAL_URL.format(
                port=PodServer.HTTP_PORT, service_id=service_id,
                class_name=class_name, action=action.value
            )
        elif custom_domain:
            api_url = DATA_WS_API_URL.format(
                fqdn=custom_domain, port=port, service_id=service_id,
                class_name=class_name, action=action.value
            )
        elif use_proxy:
            api_url = DATA_API_PROXY_URL.format(
                protocol='wss', network=network, service_id=service_id,
                member_id=member_id, class_name=class_name, action=action.value
            )
        else:
            fqdn: str = MemberSecret.create_commonname(
                member_id, service_id, network
            )

            api_url = DATA_WS_API_URL.format(
                fqdn=fqdn, port=port,
                service_id=service_id, class_name=class_name,
                action=action.value
            )

            ssl_context = await _get_ssl_context(network, secret)
        return api_url, ssl_context

    @staticmethod
    async def close_all():
        await ApiClient.close_all()


async def _get_ssl_context(network: str, secret: Secret) -> SSLContext:
    '''
    Create an SSL context

    :returns: ssl.SSLContext
    '''

    server: PodServer = config.server
    storage: FileStorage = server.local_storage

    ca_file: str = (
        f'{storage.local_path}/network-{network}'
        f'/network-{network}-root-ca-cert.pem'
    )

    ssl_context = SSLContext(PROTOCOL_TLS_CLIENT)
    ssl_context.load_verify_locations(ca_file)
    if secret:
        cert_file: str = f'{storage.local_path}/{secret.cert_file}'
        key_file: str = secret.get_tmp_private_key_filepath()
        ssl_context.load_cert_chain(certfile=cert_file, keyfile=key_file)

    return ssl_context
