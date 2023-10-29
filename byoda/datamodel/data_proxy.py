'''
Class for modeling REST Data API requests that are proxied by a pod to other
pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import base64
import asyncio

from uuid import UUID
from copy import copy
from typing import TypeVar
from logging import getLogger
from byoda.util.logger import Logger
from datetime import datetime

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer


from byoda.util.api_client.api_client import ApiClient
from byoda.util.api_client.api_client import HttpResponse

from byoda.datatypes import DataRequestType
from byoda.datatypes import NetworkLink

from byoda.datatypes import DATA_API_URL

from byoda.datamodel.dataclass import SchemaDataItem

from byoda.models.data_api_models import QueryModel
from byoda.models.data_api_models import QueryResponseModel
from byoda.models.data_api_models import AppendModel

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda import config

from ..exceptions import ByodaRuntimeError

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)

POD_TO_POD_PORT = 444

Network = TypeVar('Network')
Member = TypeVar('Member')
Schema = TypeVar('Schema')


class DataProxy:
    __slots__ = [
        'member', 'schema', 'class_name',
        'incoming_depth', 'updated_depth',
        'incoming_query', 'updated_query',
        'request_type', 'data_request_type',
    ]

    def __init__(self, member: Member):
        self.member: Member = member

        if not member.schema:
            raise ValueError('Schema has not yet been loaded')

        self.schema: Schema = member.schema

        self.data_request_type: DataRequestType | None = None
        self.clear()

    def clear(self):
        '''
        Clear state from previous queries
        '''

        self.incoming_depth: int = None
        self.updated_depth: int = None

        self.incoming_query: QueryModel = None
        self.updated_query: QueryModel = None

        self.class_name: str | None = None

    @TRACER.start_as_current_span('DataProxy.request')
    async def proxy_request(self, class_name: str,
                            query: QueryModel | AppendModel,
                            data_request_type: DataRequestType,
                            sending_member_id: UUID) -> list[dict]:
        '''
        Manipulates the original request to decrement the query depth by 1,
        sends the updated request to all network links that have one of the
        provided relations

        :param class_name: the object requested in the query
        :param query: the original query string received by the pod
        :param data_request_type:
        :param sending_member_id: member ID of the pod that sent the request
        :returns: the results
        '''

        if query.depth < 1:
            raise ValueError('Requests with depth < 1 are not proxied')

        self.clear()
        self.class_name = class_name

        self.incoming_query: QueryModel | AppendModel = query
        self.incoming_depth: int = query.depth
        self.updated_query: QueryModel | AppendModel = copy(
            self.incoming_query
        )
        self.updated_depth: int = self.incoming_depth - 1
        self.updated_query.depth: int = self.updated_depth

        self.data_request_type: DataRequestType = data_request_type

        network_data = await self._proxy_request(sending_member_id)

        if not network_data:
            return []

        if data_request_type == DataRequestType.QUERY:
            all_data = self._process_network_query_data(network_data)
        else:
            all_data = self._process_network_append_data(network_data)

        return all_data

    async def _get_proxy_targets(self, sending_member_id: UUID) -> list[UUID]:
        '''
        Gets a list of targets that the Data request should be proxied to
        '''
        if self.incoming_query.remote_member_id:
            return [self.incoming_query.remote_member_id]

        relations: list[str] = self.incoming_query.relations or []
        network_links: list[NetworkLink] = \
            await self.member.data.load_network_links(relations) or []

        _LOGGER.debug(
            f'Filtering {len(network_links)} network links on '
            f'relations: {", ".join(relations)}'
        )

        if not relations:
            targets = [
                target.member_id for target in network_links
                if target.member_id != sending_member_id
            ]
            _LOGGER.debug(
                f'Adding all {len(network_links)} network_links as targets'
            )
            return targets

        targets = []
        for target in network_links:
            # Matching relations is case insensitive
            relation: str = target.relation.lower()

            member_id: UUID
            if not target.member_id:
                continue
            elif isinstance(target.member_id, str):
                member_id = UUID(target.member_id)
            else:
                member_id = target.member_id

            if relation in relations:
                if str(member_id).startswith('aaaaaaaa'):
                    _LOGGER.debug(
                        f'We do not proxy to test UUIDs: {member_id}'
                    )
                elif member_id == sending_member_id:
                    _LOGGER.debug(
                        f'Not adding target {member_id} as it is the '
                        f'sending pod'
                    )
                else:
                    _LOGGER.debug(
                        f'Adding target {member_id} as a {relation}'
                    )
                    targets.append(member_id)

        return targets

    async def _proxy_request(self, sending_member_id: UUID
                             ) -> list[tuple[UUID, dict | None | Exception]]:
        '''
        Sends the REST Data query to remote pods. If remote_member_id is
        specified then the request will only be proxied to that member.
        Otherwise, the request will be proxided to all members that
        are in our network with one of the specified relations, or,
        if no relations ar especified, to every member in our network.

        :param query: the original request that was received
        :param relations: the relations that the query should be send to
        :param remote_member_id: the member ID of the pod to send the query to
        :returns: list of responses per pod member ID
        '''

        targets: list[UUID] = await self._get_proxy_targets(sending_member_id)

        _LOGGER.debug(
            f'Pods to proxy request to: {",".join([str(t) for t in targets])}'
        )

        tasks = set()

        if not targets:
            return []

        for target in targets:
            _LOGGER.debug(f'Creating task to proxy request to {target}')
            task = asyncio.create_task(
                self._exec_data_query(target)
            )
            tasks.add(task)

        network_data = await asyncio.gather(*tasks, return_exceptions=True)

        processed_data: list[tuple[UUID, dict | None | Exception]] = []
        pod_responses: int = 0
        for target_data in network_data:
            if isinstance(target_data, ByodaRuntimeError):
                _LOGGER.debug(
                    f'Got error from upstream pod: {str(network_data)}'
                )
                processed_data.append((target, target_data))
            else:
                pod_responses += 1
                try:
                    target, data = target_data
                    processed_data.append((target, data))
                    _LOGGER.debug(f'Target {target} returned {data}')
                except TypeError:
                    _LOGGER.debug(
                        f'Got error from upstream pod: {str(network_data)}'
                    )

        _LOGGER.debug(
            f'Received data from {pod_responses} pods out of {len(targets)} '
            f'total items received: {len(processed_data or [])}'
        )

        return processed_data

    async def _exec_data_query(self, target: UUID) -> tuple[UUID, list[dict]]:
        '''
        Execute the REST Data query

        :param target: the member ID of the pod to send the query to
        :param query: the query to send
        :returns:
        '''

        member: Member = self.member
        network: Network = member.network
        service_id: int = member.service_id

        fqdn: str = MemberSecret.create_commonname(
            target, service_id, network.name
        )

        url = DATA_API_URL.format(
            protocol='https', fqdn=fqdn, port=POD_TO_POD_PORT,
            service_id=service_id, class_name=self.class_name,
            action=self.data_request_type.value
        )

        data_query: dict[str, object] = self.updated_query.model_dump()
        resp: HttpResponse = await ApiClient.call(
            url, method='POST', secret=member.tls_secret,
            data=data_query
        )

        data = resp.json()

        if not data:
            _LOGGER.debug(f'Did not get data back from target {target}')
            return (target, None)

        if type(data) in (str, int, float, bool):
            _LOGGER.debug(
                f'Data API request affected {data} item(s) at {target}'
            )
        else:
            _LOGGER.debug(
                f'Data API request returned {len(data)} data class: {data}'
            )

        return (target, data)

    def _process_network_query_data(self,
                                    network_data: list[QueryResponseModel]
                                    ) -> list[dict]:
        '''
        Processes the data collected from all the queried pods

        :param class_name: The name of the object class requested in the query
        :param network_data: the data collected from the remote pods
        '''

        data_class: SchemaDataItem = self.schema.data_classes[self.class_name]
        if data_class.referenced_class:
            data_class = data_class.referenced_class
            self.class_name = data_class.name

        proxied_query_exceptions: int = 0
        all_edges: list = []
        for target_id, target_data in network_data:
            # Do not process errors returned via asyncio.gather
            if isinstance(target_data, Exception):
                proxied_query_exceptions += 1
                continue
            elif not target_data:
                _LOGGER.debug(f'POD {target_id} returned no data')
                continue

            edges = target_data['edges']

            _LOGGER.debug(
                f'Got {len(edges)} items from remote pod {target_id}'
            )
            all_edges.extend(edges)

        _LOGGER.debug(
            f'Collected {len(all_edges)} items after cleaning up the '
            f'results. Got {proxied_query_exceptions} exceptions'
        )
        return all_edges

    def _process_network_append_data(self, network_data: list[
                                         tuple[UUID, dict | None | Exception]
                                     ]) -> int:
        '''
        Processes the data collected from all the queried pods

        :param network_data: the data collected from the remote pods
        Lreturns: the number of records appended
        '''

        # We only support to append to 1 remote pod
        target_id, target_data = network_data[0]
        if not target_data:
            raise ValueError('Append for proxied Data query has no data')

        if isinstance(target_data, Exception):
            _LOGGER.debug('Appending to remote pod failed')
            return 0

        return 1

    @staticmethod
    @TRACER.start_as_current_span('DataProxy.verify_signature')
    async def verify_signature(service_id: int, relations: list[str] | None,
                               filters: dict[str, str] | None,
                               timestamp: datetime,
                               origin_member_id: UUID, origin_signature: str,
                               signature_format_version: int) -> None:
        '''
        Verifies the signature of the recursive request

        :param service_id: the service ID of the request
        :param relations: the relations specified in the request
        :param filters: the filters specified in the request
        :param timestamp: the timestamp of the request
        :param origin_member_id: the member ID of the pod that sent the request
        :param origin_signature: the signature of the request
        :param signature_format_version: the format version of the signature
        :returns: (none)
        :raises: byoda.secrets.secret.InvalidSignature if the verification of
        the signature fails
        '''

        network: Network = config.server.network

        if signature_format_version != 1:
            raise NotImplementedError(
                f'Signature format {signature_format_version} not supported'
            )

        plaintext = DataProxy._create_plaintext(
            service_id, relations, filters, timestamp, origin_member_id
        )
        secret = await MemberDataSecret.download(
            origin_member_id, service_id, network.name
        )

        origin_signature_decoded = base64.b64decode(origin_signature)

        secret.verify_message_signature(plaintext, origin_signature_decoded)

    @staticmethod
    def _create_plaintext(service_id: int, relations: list[str] | None,
                          filters: dict[str, str] | None, timestamp: datetime,
                          origin_member_id: UUID | str) -> str:

        plaintext: str = f'{service_id}'

        if relations:
            plaintext += f'{" ".join(relations)}{timestamp.isoformat()}'

        plaintext += f'{origin_member_id}'

        if filters:
            for key in sorted(vars(filters)):
                plaintext += f'{key}{filters[key]}'

        return plaintext

    @TRACER.start_as_current_span('DataProxy.create_signature')
    def create_signature(self, service_id: int, relations: list[str] | None,
                         filters: dict[str, str] | None,
                         timestamp: datetime, origin_member_id: UUID | str,
                         member_data_secret: MemberDataSecret = None) -> str:
        '''
        Creates a signature for a recurisve request. This function returns
        the signature as a base64 encoded string so it can be included in
        a Data query
        '''

        plaintext = DataProxy._create_plaintext(
            service_id, relations, filters, timestamp, origin_member_id
        )

        if not member_data_secret:
            member_data_secret: MemberDataSecret = self.member.data_secret

        signature = member_data_secret.sign_message(plaintext)
        signature_encoded = base64.b64encode(signature).decode('utf-8')

        return signature_encoded
