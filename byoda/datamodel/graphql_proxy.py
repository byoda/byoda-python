'''
Class for modeling GraphQL requests that are proxied by a pod to other pods

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import re
import asyncio
import logging
from uuid import UUID
from typing import TypeVar, List, Dict, Tuple

import orjson

from byoda.datatypes import GRAPHQL_API_URL_PREFIX
from byoda.datatypes import ORIGIN_KEY

from byoda.datamodel.dataclass import SchemaDataArray, SchemaDataItem

from byoda.secrets import MemberSecret

from byoda.util.api_client.graphql_client import GraphQlClient

_LOGGER = logging.getLogger(__name__)

POD_TO_POD_PORT = 444

Member = TypeVar('Member')
Schema = TypeVar('Schema')


class GraphQlProxy:
    RX_RECURSIVE_QUERY = re.compile(b'''^(.*?"?depth"?:\\s*?)(\\d+)(.*)$''')

    def __init__(self, member: Member):
        self.member: Member = member

        if not member.schema:
            raise ValueError('Schema has not yet been loaded')

        if not member.data:
            raise ValueError('Data for member has not been loaded')

        self.schema: Schema = member.schema

    async def proxy_request(self, class_name: str, query: bytes,
                            depth: int, relations: List[str],
                            remote_member_id: UUID = None) -> List[Dict]:
        '''
        Manipulates the original request to decrement the query depth by 1,
        sends the updated request to all network links that have one of the
        provided relations

        :param query: the original query string received by the pod
        :param depth: the level of requested recursion
        :param relations: requests should only be proxied to network links with
        one of the provided relations. If no relations are listed, the
        request will be proxied to all network links
        :returns: the results
        '''

        if depth < 1:
            raise ValueError('Requests with depth < 1 are not proxied')

        updated_query = self._update_query(query)

        network_data = await self._proxy_request(
            updated_query, relations, remote_member_id
        )

        if not remote_member_id:
            cleaned_data = self._process_network_query_data(
                class_name, network_data
            )
        else:
            cleaned_data = self._process_network_append_data(
                class_name, network_data
            )

        return cleaned_data

    def _update_query(self, query: bytes) -> bytes:
        '''
        Manipulates the incoming GraphQL query so it can be used to query
        other pods

        :param query: the original GraphQL request that was received
        :returns: the updated query
        '''

        # HACK: we update the query we received using a regex to decrement
        # the query depth by 1
        match = GraphQlProxy.RX_RECURSIVE_QUERY.match(query)
        if not match:
            _LOGGER.exception(
                f'Could not parse value for "depth" from request: {query}'
            )
            raise ValueError('Could not parse value for "depth" from request')

        previous_depth = int(match.group(2))
        new_depth = str(previous_depth - 1).encode('utf-8')
        updated_query = match.group(1) + new_depth + match.group(3)

        return updated_query

    async def _proxy_request(self, query: bytes, relations: List[str],
                             remote_member_id: UUID) -> List[Dict]:
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
            network_links = self.member.data['network_links']

            targets = [
                target['member_id'] for target in network_links
                if not relations or target['relation'] in relations
            ]

        tasks = set()
        for target in targets:
            task = asyncio.create_task(self._exec_graphql_query(target, query))
            tasks.add(task)

        network_data = await asyncio.gather(*tasks, return_exceptions=True)
        _LOGGER.debug(f'Collected data from {len(network_data)} pods in total')

        return network_data

    async def _exec_graphql_query(self, target: UUID, query: bytes
                                  ) -> Tuple[UUID, List[Dict]]:
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

        query_data = orjson.loads(query)
        query_string = query_data['query']

        response = await GraphQlClient.call(
            url, query_string, vars=query_data['variables'],
            secret=self.member.tls_secret, timeout=3
        )

        body = await response.json()

        data = body.get('data')

        if not data:
            return (target, None)

        _LOGGER.debug(f'GraphQL query returned {len(data)} data class')

        return (target, data)

    def _process_network_query_data(self, class_name: str,
                                    network_data: List[Dict]) -> List[Dict]:
        '''
        Processes the data collected from all the queried pods

        :param class_name: The name of the object class requested in the query
        :param network_data: the data collected from the remote pods
        '''
        data_class: SchemaDataItem = self.schema.data_classes[class_name]
        if data_class.referenced_class:
            data_class = data_class.referenced_class
            class_name = data_class.name

        cleaned_data = []
        for target in network_data:
            target_id, target_data = target
            if not target_data:
                _LOGGER.debug(f'POD {target_id} returned no data')
                continue

            key = list(target_data.keys())[0]
            edges = target_data[key]['edges']

            cleaned_data = []
            for edge in edges:
                data_item = edge[class_name]
                if data_item and isinstance(data_item, dict):
                    data_item = data_class.normalize(data_item)

                    data_item[ORIGIN_KEY] = target_id
                    cleaned_data.append(data_item)

        _LOGGER.debug(
            f'Collected {len(cleaned_data)} items after cleaning up the '
            'results'
        )
        return cleaned_data

    def _process_network_append_data(self, class_name: str,
                                     network_data: List[Dict]) -> Dict:
        '''
        Processes the data collected from all the queried pods

        :param class_name: The name of the object class requested in the query
        :param network_data: the data collected from the remote pods
        '''

        data_class: SchemaDataArray = self.schema.data_classes[class_name]
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

