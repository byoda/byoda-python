'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import orjson

from datetime import datetime, timezone
from typing import Dict, TypeVar

from byoda.storage import FileMode

from byoda.util.paths import Paths

from byoda.datastore.document_store import DocumentStore

from jsonschema import validate as jsonschema_validate
# from .schema import JsonSchemaValueException

# These imports are only used for typing
from .schema import Schema
from .dataclass import SchemaDataItem

_LOGGER = logging.getLogger(__name__)

MAX_FILE_SIZE = 65536

Member = TypeVar('Member')


class MemberData(Dict):
    '''
    Generic data object for the storing data as defined
    by the schema of services
    '''

    def __init__(self, member: Member, paths: Paths,
                 doc_store: DocumentStore):
        self.member: Member = member
        self.unvalidated_data: Dict = None

        self.paths: Paths = paths

        self.document_store: DocumentStore = doc_store

    def initalize(self):
        '''
        Initializes the data for a new membership. Every service
        contract must include
        '''

        if 'member' in self:
            if self['member'].get('member_id'):
                raise ValueError('Member structure already exists')
        else:
            self['member'] = {}

        self['member']['member_id'] = str(self.member.member_id)
        self['member']['joined'] = datetime.now(timezone.utc).isoformat()

    async def load(self):
        '''
        Load the data from the data store
        '''

        filepath = self.paths.get(
            self.paths.MEMBER_DATA_PROTECTED_FILE,
            service_id=self.member.service_id
        )

        try:
            self.unvalidated_data = await self.document_store.read(
                filepath, self.member.data_secret
            )

        except FileNotFoundError:
            _LOGGER.error(
                'Unable to read data file for service '
                f'{self.member.service_id} from {filepath}'
            )
            return

        self.normalize()

    def normalize(self):
        '''
        Updates data values to match data type as defined in JSON-Schema,
        ie. for UUIDs and datetime
        '''

        schema: Schema = self.member.schema

        if not schema:
            raise ValueError('Schema has not yet been loaded')

        data_classes: Dict[str, SchemaDataItem] = schema.data_classes
        for field, value in self.items():
            if field not in data_classes:
                raise ValueError(
                    f'Found data field {field} not in the data classes '
                    'for the schema'
                )

            data = data_classes[field].normalize(value)
            self[field] = data

    async def save(self, data=None):
        '''
        Save the data to the data store
        '''

        # MemberData inherits from dict so has a length
        if not len(self):
            raise ValueError(
                'No member data for service %s available to save',
                self.member.service_id
            )

        try:
            if data:
                self.unvalidated_data = data
                self.validate()
            else:
                # Let's double check the data is valid
                # self.member.schema.validate(self)
                jsonschema_validate(
                    self.unvalidated_data, self.member.schema.json_schema
                )

            # TODO: properly serialize data
            await self.document_store.write(
                self.paths.get(
                    self.paths.MEMBER_DATA_PROTECTED_FILE,
                    service_id=self.member.service_id
                ),
                self,
                self.member.data_secret
            )
        except OSError:
            _LOGGER.error(
                'Unable to write data file for service %s',
                self.member.service_id
            )

    def _load_from_file(self, filename: str):
        '''
        This function should only be used by test cases
        '''

        with open(filename) as file_desc:
            raw_data = file_desc.read(MAX_FILE_SIZE)

        self.unvalidated_data = orjson.loads(raw_data)

    def validate(self):
        '''
        Validates the unvalidated data against the schema
        '''

        try:
            if self.unvalidated_data:
                # self = self.member.schema.validate(self.unvalidated_data)
                jsonschema_validate(
                    self.unvalidated_data, self.member.schema.json_schema
                )
        except Exception as exc:
            _LOGGER.warning(
                'Failed to validate data for service_id '
                f'{self.member.service_id}: {exc}'
            )
            raise

    async def load_protected_shared_key(self):
        '''
        Reads the protected symmetric key from file storage. Support
        for changing symmetric keys is currently not supported.
        '''

        filepath = self.paths.get(
            self.paths.MEMBER_DATA_SHARED_SECRET_FILE
        )

        try:
            protected = await self.member.storage_driver.read(
                filepath, file_mode=FileMode.BINARY
            )
            self.member.data_secret.load_shared_key(protected)
        except OSError:
            _LOGGER.error(
                'Can not read the protected shared key for service %s from %s',
                self.member.service_id, filepath
            )
            raise

    async def save_protected_shared_key(self):
        '''
        Saves the protected symmetric key
        '''

        filepath = self.paths.get(self.paths.MEMBER_DATA_SHARED_SECRET_FILE)
        await self.member.storage_driver.write(
            filepath, self.member.data_secret.protected_shared_key,
            file_mode=FileMode.BINARY
        )
