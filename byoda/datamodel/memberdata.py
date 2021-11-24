'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import json

from typing import Dict, TypeVar

from byoda.storage import FileMode

from byoda.util.paths import Paths

from byoda.datastore.document_store import DocumentStore

from .schema import JsonSchemaValueException

_LOGGER = logging.getLogger(__name__)

MAX_FILE_SIZE = 65536

Member = TypeVar('Member', bound='Member')


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

    def load(self):
        '''
        Load the data from the data store
        '''

        filepath = self.paths.get(
            self.paths.MEMBER_DATA_PROTECTED_FILE,
            service_id=self.member.service_id
        )

        try:
            self.unvalidated_data = self.document_store.read(
                filepath, self.member.data_secret
            )
        except FileNotFoundError:
            _LOGGER.error(
                'Unable to read data file for service'
                f'{self.member.service_id} from {filepath}'
            )
            return

        self.validate()

    def save(self):
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
            # Let's double check the data is valid
            self.member.schema.validate(self)

            self.document_store.write(
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

        self.unvalidated_data = json.loads(raw_data)

    def validate(self):
        '''
        Validates the unvalidated data against the schema
        '''

        try:
            if self.unvalidated_data is not None:
                self.update(
                    self.member.schema.validate(self.unvalidated_data)
                )
        except JsonSchemaValueException as exc:
            _LOGGER.warning(
                'Failed to validate data for service_id '
                f'{self.member.service_id}: {exc}'
            )
            raise

    def load_protected_shared_key(self):
        '''
        Reads the protected symmetric key from file storage. Support
        for changing symmetric keys is currently not supported.
        '''

        filepath = self.paths.get(
            self.paths.MEMBER_DATA_SHARED_SECRET_FILE
        )

        try:
            protected = self.member.storage_driver.read(
                filepath, file_mode=FileMode.BINARY
            )
            self.member.data_secret.load_shared_key(protected)
        except OSError:
            _LOGGER.error(
                'Can not read the protected shared key for service %s from %s',
                self.member.service_id, filepath
            )
            raise
        
    def save_protected_shared_key(self):
        '''
        Saves the protected symmetric key
        '''

        filepath = self.paths.get(self.paths.MEMBER_DATA_SHARED_SECRET_FILE)
        self.member.storage_driver.write(
            filepath, self.member.data_secret.protected_shared_key,
            file_mode=FileMode.BINARY
        )
