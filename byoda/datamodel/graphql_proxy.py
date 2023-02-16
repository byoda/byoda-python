'''
Class for modeling GraphQL requests that are proxied by a pod to other pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re
import base64
import asyncio
import logging
from uuid import UUID
from typing import TypeVar
from datetime import datetime

import orjson

from strawberry.types import Info

from byoda.datatypes import GRAPHQL_API_URL_PREFIX
from byoda.datatypes import ORIGIN_KEY

from byoda.datamodel.dataclass import SchemaDataArray, SchemaDataItem

from byoda.secrets.member_secret import MemberSecret
from byoda.secrets.member_data_secret import MemberDataSecret

from byoda.util.api_client.graphql_client import GraphQlClient


from byoda import config

from ..exceptions import ByodaRuntimeError, ByodaValueError

_LOGGER = logging.getLogger(__name__)

POD_TO_POD_PORT = 444

Network = TypeVar('Network')
Member = TypeVar('Member')
Schema = TypeVar('Schema')


class GraphQlProxy:
    RX_RECURSIVE_QUERY = re.compile(b'''^({"query"\:".*?query.*?\(.*?\).*?"variables"\:{.*?).*?\s*,?\s*"depth"\s*?\:\s*(\d)(,?)(.*?}})\s*$''')   # noqa

    def __init__(self, member: Member):
        self.member: Member = member

        if not member.schema:
            raise ValueError('Schema has not yet been loaded')

        self.schema: Schema = member.schema

        self.clear()

    def clear(self):
        '''
        Clear state from previous queries
        '''

        self.incoming_depth: int = None
        self.updated_depth: int = None

        self.incoming_query: bytes = None
        self.updated_query: bytes = None

        self.class_name: str | None = None

    async def proxy_request(self, class_name: str, query: bytes, info: Info,
                            depth: int, relations: list[str],
                            remote_member_id: UUID = None,
                            origin_member_id: UUID | None = None,
                            origin_signature: str | None = None,
                            timestamp: datetime or None = None) -> list[dict]:
        '''
        Manipulates the original request to decrement the query depth by 1,
        sends the updated request to all network links that have one of the
        provided relations

        :param class_name: the object requested in the query
        :param query: the original query string received by the pod
        :param info: The GraphQL.Info object that was received by the pod
        :param depth: the level of requested recursion
        :param relations: requests should only be proxied to network links with
        one of the provided relations. If no relations are listed, the
        request will be proxied to all network links
        :param origin_member_id: only specificy a value for this parameter if
        the query currently doesn't specify origin_member_id and it needs to be
        added to the query
        :param origin_signature: only specificy a value for this parameter if
        the query currently doesn't specify origin_signature and it needs to be
        added to the query
        :param timestamp: only specifiy a value for this parameter if the query
        currently doesn't specifiy a timestamp and it needs to be added to the
        query
        :returns: the results
        '''

        if depth < 1:
            raise ValueError('Requests with depth < 1 are not proxied')

        self.clear()
        self.class_name = class_name

        self.incoming_query = query
        self._update_query(info, origin_member_id, origin_signature, timestamp)

        network_data = await self._proxy_request(relations, remote_member_id)

        if not remote_member_id:
            cleaned_data = self._process_network_query_data(network_data)
        else:
            cleaned_data = self._process_network_append_data(network_data)

        return cleaned_data

    def _update_query(self, info: Info, origin_member_id: UUID | None,
                      origin_signature: str | None,
                      timestamp: datetime | None = None) -> None:
        '''
        Manipulates the incoming GraphQL query so it can be used to query
        other pods

        :param info: the GraphQL.Info object for the incoming request
        :param origin_memberid: if defined, it will be inserted into the query
        :param origin_signature: if defined, it will be inserted into the query
        :param timestamp: if defined, it will be inserted into the query
        '''

        if ((origin_member_id or origin_signature or timestamp)
                and not (origin_member_id and origin_signature and timestamp)):
            raise ByodaValueError(
                'If origin_member_id is specified, origin_signature is also '
                'required and vice versa'
            )

        if origin_member_id and 'origin_member_id' in info.variable_values:
            raise NotImplementedError(
                'Updating existing values of "origin_member_id" in the query '
                'is not implemented'
            )

        # HACK: we update the query we received using a regex to decrement
        # the query depth by 1 and add needed fields to the query
        match = GraphQlProxy.RX_RECURSIVE_QUERY.match(self.incoming_query)
        if not match:
            raise ByodaValueError(
                'Could not parse value for "depth" from '
                f'request: {self.incoming_query}'
            )

        self.incoming_depth = int(match.group(2))
        self.updated_depth = str(self.incoming_depth - 1)

        self.updated_query = (
            match.group(1) + f'"depth": {self.updated_depth}'.encode('utf-8')
        )

        if origin_member_id:
            self.updated_query += (
                f', "origin_member_id": "{origin_member_id}"'
                f', "origin_signature": "{origin_signature}"'
                f', "timestamp": "{timestamp}"'
            ).encode('utf-8')

        self.updated_query += match.group(3) + match.group(4)

    async def _proxy_request(self, relations: list[str],
                             remote_member_id: UUID
                             ) -> list[tuple[UUID, dict | None | Exception]]:
        '''
        Sends the GraphQL query to remote pods. If remote_member_id is
        specified then the request will only be proxied to that member.
        Otherwise, the request will be proxided to all members that
        are in our network with one of the specified relations, or,
        if no relations ar especified, to every member in our network.

        :param query: the original GraphQL request that was received
        :param relations: the relations that the query should be send to
        :param remote_member_id: the member ID of the pod to send the query to
        :returns: list of responses per pod member ID
        '''

        if remote_member_id:
            targets = [remote_member_id]
        else:
            network_links = await self.member.data.load_network_links(
                relations
            )

            _LOGGER.debug(
                f'Filtering {len(network_links or [])} network links on '
                f'relations: {", ".join(relations or [])}'
            )
            if not relations:
                targets = [target['member_id'] for target in network_links]
                _LOGGER.debug(
                    f'Adding all {len(network_links)} network_links as targets'
                )
            else:
                targets = []
                for target in network_links or []:
                    if target['relation'].lower() in relations:
                        if str(target['member_id']).startswith('aaaaaaaa'):
                            _LOGGER.debug(
                                'We do not proxy to test UUIDs: '
                                f'{target["member_id"]}'
                            )
                        else:
                            _LOGGER.debug(
                                f'Adding target {target["member_id"]} as a '
                                f'{target["relation"]}'
                            )
                            targets.append(target['member_id'])

        _LOGGER.debug(
            f'Pods to proxy request to: {",".join([str(t) for t in targets])}'
        )

        tasks = set()

        if not targets:
            return []

        for target in targets:
            _LOGGER.debug(f'Creating task to proxy request to {target}')
            task = asyncio.create_task(
                self._exec_graphql_query(target)
            )
            tasks.add(task)

        network_data = await asyncio.gather(*tasks, return_exceptions=True)

        processed_data: list[tuple[UUID, dict | None | Exception]] = []
        for target_data in network_data:
            if isinstance(target_data, ByodaRuntimeError):
                _LOGGER.debug(
                    f'Got error from upstream pod: {str(network_data)}'
                )
                processed_data.append((target, target_data))
            else:
                target, data = target_data
                processed_data.append((target, data))
                _LOGGER.debug(f'Target {target} returned {data}')

        _LOGGER.debug(
            f'Collected data from {len(processed_data or [])} pods '
            f'in total: {processed_data}'
        )

        return processed_data

    async def _exec_graphql_query(self, target: UUID
                                  ) -> tuple[UUID, list[dict]]:
        '''
        Execute the GraphQL query

        :param target: the member ID of the pod to send the query to
        :param query: the query to send
        :returns:
        '''
        fqdn = MemberSecret.create_commonname(
            target, self.member.service_id, self.member.network.name
        )
        url = (
            f'https://{fqdn}:{POD_TO_POD_PORT}' +
            GRAPHQL_API_URL_PREFIX.format(service_id=self.member.service_id)
        )

        query_data = orjson.loads(self.updated_query)
        query_string = query_data['query']

        response = await GraphQlClient.call(
            url, query_string, vars=query_data['variables'],
            secret=self.member.tls_secret, timeout=10
        )

        body = await response.json()

        data = body.get('data')

        if not data:
            _LOGGER.debug(f'Did not get data back from target {target}')
            return (target, None)

        _LOGGER.debug(f'GraphQL query returned {len(data)} data class: {data}')

        return (target, data)

    def _process_network_query_data(self, network_data: list[
                                        tuple[UUID, dict | None | Exception]
                                    ]) -> list[dict]:
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
        cleaned_data: list = []
        for target_id, target_data in network_data:
            # Do not process errors returned via asyncio.gather
            if isinstance(target_data, Exception):
                proxied_query_exceptions += 1
                continue
            elif not target_data:
                _LOGGER.debug(f'POD {target_id} returned no data')
                continue

            key = list(target_data.keys())[0]
            edges = target_data[key]['edges']

            cleaned_data = []
            _LOGGER.debug(
                f'Got {len(edges)} items from remote pod {target_id}'
            )
            for edge in edges:
                data_item = edge[self.class_name]
                if data_item and isinstance(data_item, dict):
                    data_item = data_class.normalize(data_item)

                    data_item[ORIGIN_KEY] = target_id
                    cleaned_data.append(data_item)
                else:
                    _LOGGER.debug(f'Type for data_item: {type(data_item)}')

        _LOGGER.debug(
            f'Collected {len(cleaned_data)} items after cleaning up the '
            f'results. Got {proxied_query_exceptions} exceptions'
        )
        return cleaned_data

    def _process_network_append_data(self, network_data: list[
                                         tuple[UUID, dict | None | Exception]
                                     ]) -> dict:
        '''
        Processes the data collected from all the queried pods

        :param class_name: The name of the object class requested in the query
        :param network_data: the data collected from the remote pods
        '''

        data_class: SchemaDataArray = self.schema.data_classes[self.class_name]
        if data_class.referenced_class:
            data_class = data_class.referenced_class

        target_id, target_data = network_data[0]
        if not target_data:
            raise ValueError('Append for proxied GraphQl query has no data')

        key = list(target_data.keys())[0]
        data = target_data[key]
        for field, value in data.items():
            data[field] = data_class.fields[field].normalize(value)

        target_data[key][ORIGIN_KEY] = target_id

        return target_data[key]

    @staticmethod
    async def verify_signature(service_id: int, relations: list[str] | None,
                               filters: dict[str, str] | None,
                               timestamp: datetime,
                               origin_member_id: UUID, origin_signature: str
                               ) -> None:
        '''
        Verifies the signature of the recursive request
        :raises: byoda.secrets.secret.InvalidSignature if the verification of
        the signature fails
        '''

        network: Network = config.server.network

        plaintext = GraphQlProxy._create_plaintext(
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

    def create_signature(self, service_id: int, relations: list[str] | None,
                         filters: dict[str, str] | None,
                         timestamp: datetime, origin_member_id: UUID | str,
                         member_data_secret: MemberDataSecret = None) -> str:
        '''
        Creates a signature for a recurisve request. This function returns
        the signature as a base64 encoded string so it can be included in
        a GraphQL query
        '''

        plaintext = GraphQlProxy._create_plaintext(
            service_id, relations, filters, timestamp, origin_member_id
        )

        if not member_data_secret:
            member_data_secret: MemberDataSecret = self.member.data_secret

        signature = member_data_secret.sign_message(plaintext)
        signature_encoded = base64.b64encode(signature).decode('utf-8')

        return signature_encoded
