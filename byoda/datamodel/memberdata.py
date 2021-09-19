'''
Class for modeling an element of data of a member
:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import logging
import json

from typing import Dict, TypeVar
from collections import UserDict

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

    def load(self):
        try:
            self.unvalidated_data = self.document_store.read(
                self.paths.get(
                    self.paths.MEMBER_DATA_FILE,
                    service_id=self.member.service_id
                )
            )
            self.validate()
        except OSError:
            _LOGGER.error(
                'Unable to read data file for service %s',
                self.member.service_id
            )

    def save(self):
        if not self.data:
            raise ValueError(
                'No member data for service %s available to save',
                self.member.service_id
            )

        try:
            # Let's double check the data is valid
            self.schema.validate(self.data)

            serialized_data = json.dumps(self.data, indent=4, sort_keys=True)
            self.document_store.write(
                self.paths.get(
                    self.paths.MEMBER_DATA_FILE,
                    service_id=self.member.service_id
                ),
                serialized_data
            )
        except OSError:
            _LOGGER.error(
                'Unable to write data file for service %s',
                self.member.service_id
            )

    def load_from_file(self, filename: str):
        '''
        This function should only be used by test cases
        '''
        with open(filename) as file_desc:
            raw_data = file_desc.read(MAX_FILE_SIZE)

        self.unvalidated_data = json.loads(raw_data)

    def validate(self):
        try:
            self.data = self.schema.validate(self.unvalidated_data)
        except Exception:
            raise
