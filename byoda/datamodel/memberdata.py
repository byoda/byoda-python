'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import json

from typing import Dict, TypeVar
from collections import UserDict

from byoda.storage import FileMode

from byoda.util.paths import Paths

from byoda.datastore.document_store import DocumentStore

from .schema import Schema

_LOGGER = logging.getLogger(__name__)

MAX_FILE_SIZE = 65536

Member = TypeVar('Member', bound='Member')


class MemberData(UserDict):
    '''
    Generic data object for the storing data as defined
    by the schema of services
    '''

    def __init__(self, member: Member, schema: Schema, paths: Paths,
                 doc_store: DocumentStore):
        self.member: Member = member
        self.unvalidated_data: Dict = None
        self.schema: Schema = schema

        self.paths: Paths = paths

        self.document_store: DocumentStore = doc_store

        self.data_secret = member.data_secret
        self.load_protected_shared_key()

    def load(self):
        '''
        Load the data from the data store
        '''

        try:
            self.unvalidated_data = self.document_store.read(
                self.paths.get(
                    self.paths.MEMBER_DATA_PROTECTED_FILE,
                    service_id=self.member.service_id
                ),
                self.data_secret
            )
        except OSError:
            _LOGGER.error(
                'Unable to read data file for service %s',
                self.member.service_id
            )
            raise

        self.validate()

    def save(self):
        '''
        Save the data to the data store
        '''

        if not self.data:
            raise ValueError(
                'No member data for service %s available to save',
                self.member.service_id
            )

        try:
            # Let's double check the data is valid
            self.schema.validate(self.data)

            self.document_store.write(
                self.paths.get(
                    self.paths.MEMBER_DATA_PROTECTED_FILE,
                    service_id=self.member.service_id
                ),
                self.data,
                self.data_secret
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
            self.data = self.schema.validate(self.unvalidated_data)
        except Exception:
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
        except OSError:
            _LOGGER.error(
                'Can not read the protected shared key for service %s from %s',
                self.member.service_id, filepath
            )

        self.data_secret.load_shared_key(protected)

    def save_protected_shared_key(self):
        '''
        Saves the protected symmetric key
        '''

        filepath = self.paths.get(self.paths.MEMBER_DATA_SHARED_SECRET_FILE)
        self.member.storage_driver.write(
            filepath, self.data_secret.protected_shared_key,
            file_mode=FileMode.BINARY
        )
