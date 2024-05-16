'''
Class for storing non-account info of BT Lite users, such as
- network_links
- asset_reactions
- comments

Account and billing related data is stored in byotubesvr.database.sqlstorage
class

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from uuid import uuid4
from datetime import UTC
from datetime import datetime
from logging import getLogger

from byoda.util.logger import Logger

from byotubesvr.models.lite_api_models import NetworkLinkResponseModel

from .lite_store import LiteStore

_LOGGER: Logger = getLogger(__name__)


ASSET_REACTIONS_KEY_PREFIX = 'asset_reactions'
NETWORK_LINKS_KEY_PREFIX = 'network_links'


class NetworkLinkStore(LiteStore):
    @staticmethod
    def get_key(lite_id: UUID) -> str:
        '''
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        return f'{NETWORK_LINKS_KEY_PREFIX}:{lite_id}'

    async def add_link(self, lite_id: UUID, remote_member_id: UUID,
                       relation: str, annotations: set[str] = None) -> None:
        '''
        Add a network link to the user's profile

        Because we can host multiple channels on a single pod, we use the
        'annotations' field to specify which channels on the remote pod we
        follow. This means that for 'add_link' we have two possibilities:
        1: We do not yet have a link to the remote member, in which case we
              create a new link with the relation and annotations
        2: We already have a link to the remote member, in which case we update
        the annotations for the existing link

        :param lite_id: UUID of the user
        :param remote_member_id: UUID of the remote member
        :param relation: The relation to the remote member
        :param annotations: Annotations for the network link
        :returns: network_link_id of the new link
        :raises: (none)
        '''

        if annotations is None:
            annotations = set()

        # See if there is an existing link with the relation to the remote
        # member
        network_link_id: UUID = await self.update_link(
            lite_id, remote_member_id, relation, annotations
        )
        if network_link_id:
            return network_link_id

        NetworkLinkStore._check_parameters(
            lite_id, remote_member_id=remote_member_id, relation=relation,
            annotations=annotations
        )

        # No existing link so we need to create a new one
        key: str = NetworkLinkStore.get_key(lite_id)
        if not await self.client.exists(key):
            await self.client.json().set(key, '$', [])

        network_link_id: UUID = uuid4()
        data: dict[str, str | list[str]] = {
            'created_timestamp': datetime.now(tz=UTC).timestamp(),
            'member_id': str(remote_member_id),
            'relation': relation,
            'annotations': list(annotations),
            'network_link_id': str(network_link_id)
        }
        await self.client.json().arrappend(key, '$', data)

        return network_link_id

    async def get_links(
        self, lite_id: str, remote_member_id: UUID | None = None,
        relation: str | None = None
    ) -> list[NetworkLinkResponseModel]:
        '''
        Get the network links of a user
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        if remote_member_id and not isinstance(remote_member_id, UUID):
            remote_member_id = UUID(remote_member_id)

        if relation and not isinstance(relation, str):
            raise ValueError('relation must be a string')

        key: str = NetworkLinkStore.get_key(lite_id)
        selector: str | None = None
        data: dict[str, str | list[str]]
        if remote_member_id or relation:
            selector = NetworkLinkStore._get_jsonpath_selector(
                remote_member_id=remote_member_id, relation=relation
            )
            data = await self.client.json().get(key, selector)
        else:
            data = await self.client.json().get(key)

        results: list[NetworkLinkResponseModel] = []
        item: dict[str, str | list[str]]
        for item in data or []:
            link = NetworkLinkResponseModel(**item)
            results.append(link)

        return results

    async def update_link(self, lite_id, remote_member_id: UUID, relation: str,
                          annotations: set[str]) -> bool:
        '''
        Update a network link

        :param lite_id:
        :param remote_member_id:
        :param relation:
        :param annotations:
        :returns: 'None' if there was not a link to update, 'network_link_id'
        if the link has been updated
        '''

        NetworkLinkStore._check_parameters(
            lite_id, remote_member_id=remote_member_id, relation=relation,
            annotations=annotations
        )

        links: list[NetworkLinkResponseModel] = await self.get_links(
            lite_id, remote_member_id, relation
        )

        link: NetworkLinkResponseModel
        if not links:
            return None
        elif len(links) > 1:
            new_annotations: set[str] = await self._dedupees(
                lite_id, remote_member_id=remote_member_id,
                relation=relation, links=links)
            if new_annotations:
                annotations |= new_annotations

        link = links[0]
        annotations |= link.annotations

        await self._set_link(
            lite_id=lite_id, created_timestamp=link.created_timestamp,
            remote_member_id=remote_member_id, relation=relation,
            annotations=annotations, network_link_id=link.network_link_id
        )

        return link.network_link_id

    async def remove_creator(self, lite_id: UUID, remote_member_id: UUID,
                             relation: str, annotation: str) -> int:
        '''
        Remove a creator from the network link to a remote member
        '''

        NetworkLinkStore._check_parameters(
            lite_id, remote_member_id=remote_member_id, relation=relation
        )

        links: list[NetworkLinkResponseModel] = await self.get_links(
            lite_id, remote_member_id, relation
        )
        if not links:
            return 0

        links = await self.get_links(lite_id, remote_member_id, relation)
        original_annotations: int = links[0].annotations

        # If the annotations are not changed then we do not need to update
        # the network link
        must_update: bool = False
        if not links:
            return False
        elif len(links) > 1:
            annotations: set[str] = await self._dedupees(
                lite_id, remote_member_id=remote_member_id,
                relation=relation, links=links)
            if annotations:
                links[0].annotations |= annotations
                if links[0].annotations != original_annotations:
                    must_update = True

        link: NetworkLinkResponseModel = links[0]

        try:
            link.annotations.remove(annotation)
        except KeyError:
            if not must_update:
                # No changes in the annotations so no work to do
                return 0

        result: int
        if not link.annotations:
            result = await self.remove_link(lite_id, link.network_link_id)
            return result

        else:
            await self._set_link(
                lite_id, link.created_timestamp, remote_member_id, relation,
                link.annotations, link.network_link_id
            )

    async def remove_link(self, lite_id: UUID, network_link_id: UUID) -> int:
        '''
        Remove a network link from the user's profile

        :param lite_id:
        :param network_link_id:
        :returns: 1 if the link was removed, 0 if the link was not found
        '''

        if not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        if not isinstance(network_link_id, UUID):
            network_link_id = UUID(network_link_id)

        key: str = NetworkLinkStore.get_key(lite_id)

        selector: str = f'$[?(@.network_link_id=="{network_link_id}")]'
        result: int = await self.client.json().delete(key, selector)

        return result

    async def _set_link(self, lite_id: UUID,
                        created_timestamp: datetime | int | float,
                        remote_member_id: UUID, relation: str,
                        annotations: set[str], network_link_id: UUID | None
                        ):
        '''
        Set link is hardcoded to set the link to the specified value, removing
        any existing link with the same network_link_id
        '''
        NetworkLinkStore._check_parameters(
            lite_id, remote_member_id=remote_member_id, relation=relation,
            annotations=annotations
        )

        if isinstance(created_timestamp, datetime):
            created_timestamp = created_timestamp.timestamp()

        if type(created_timestamp) not in (float, int):
            raise ValueError(
                f'created_timestamp {created_timestamp} must be a datetime or '
                f'an epoch value, not type {created_timestamp}'
            )

        if network_link_id:
            if not isinstance(network_link_id, UUID):
                network_link_id = UUID(network_link_id)

            await self.remove_link(lite_id, network_link_id)
        else:
            network_link_id = uuid4()

        data: dict[str, str | list[str]] = {
            'created_timestamp': created_timestamp,
            'member_id': str(remote_member_id),
            'relation': relation,
            'annotations': list(annotations),
            'network_link_id': str(network_link_id)
        }
        key: str = NetworkLinkStore.get_key(lite_id)
        await self.client.json().arrappend(key, '$', data)

    async def _dedupe(self, lite_id: UUID, remote_member_id: UUID,
                      relation: str, links: list[NetworkLinkResponseModel]
                      ) -> set[str]:
        '''
        Remove duplicate network links to the same remote

        :param lite_id:
        :param remote_member_id:
        :param relation:
        :param links: all existing links for the remote member/relation
        :returns: the set of annotations as a union from all network links
        :raises: ValueError
        '''

        NetworkLinkStore._check_parameters(
            lite_id, remote_member_id=remote_member_id, relation=relation
        )

        if not isinstance(links, list):
            raise ValueError('links must be a list')

        if len(links) == 0:
            raise ValueError('Must have at least 1 network link')

        if len(links) == 1:
            return links[0].annotations

        annotations: set[str] = links[0].annotations
        for link in links[1:]:
            if not isinstance(link, NetworkLinkResponseModel):
                raise ValueError(
                    'link must be a NetworkLinkResponseModel, '
                    f'not type {type(link)}'
                )

            annotations |= link.annotations
            await self.remove_link(lite_id, link.network_link_id)

        return annotations

    @staticmethod
    def _get_jsonpath_selector(remote_member_id: UUID | None = None,
                               relation: str | None = None,
                               network_link_id: UUID | None = None) -> str:
        '''
        Create a JSONPath selector for the network links
        '''

        if not (remote_member_id or relation or network_link_id):
            raise ValueError(
                'At least one of remote_member_id, relation, or '
                'network_link_id must be provided'
            )

        if remote_member_id and not isinstance(remote_member_id, UUID):
            remote_member_id = UUID(remote_member_id)

        if network_link_id and not isinstance(network_link_id, UUID):
            network_link_id = UUID(network_link_id)

        if relation and not isinstance(relation, str):
            raise ValueError('relation must be a string')

        selector = '$[?('
        if remote_member_id:
            selector += f'@.member_id=="{remote_member_id}"'
        if relation:
            if selector[-1] != '(':
                selector += '&&'
            selector += f'@.relation=="{relation}"'
        if network_link_id:
            if selector[-1] != '(':
                selector += '&&'

            selector += f'@.network_link_id=="{network_link_id}"'

        selector += ')]'

        _LOGGER.debug(f'Using JSONPath {selector}')

        return selector

    @staticmethod
    def _check_parameters(lite_id: UUID, remote_member_id: UUID,
                          relation: str | None = None,
                          annotations: str | set[str] | None = None) -> None:
        '''
        Check the parameters for validity

        :param lite_id: UUID of the user
        :param remote_member_id: UUID of the remote member
        :param relation: The relation to the remote member
        :param annotations: Annotations for the network link
        :returns: (none)
        :raises: ValueError
        '''

        if not isinstance(lite_id, UUID):
            raise ValueError('lite_id must be a UUID')

        if not isinstance(remote_member_id, UUID):
            raise ValueError('remote_member_id must be a UUID')

        if relation:
            if not isinstance(relation, str):
                raise ValueError(f'relation {relation}must be a string')

        if annotations:
            if isinstance(annotations, str):
                annotations = set([annotations])
            elif isinstance(annotations, list):
                annotations = set(annotations)
            elif not isinstance(annotations, set):
                raise ValueError('annotations must be a set')

            for annotation in annotations:
                if not isinstance(annotation, str):
                    raise ValueError(
                        f'annotation {annotation} must be a string, '
                        f'not type {type(annotation)}'
                    )
