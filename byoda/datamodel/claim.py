'''
Class for modeling claims, signing them and verifying their signature.

Content keys do not affect the content but are used to
restrict streaming & download access to the content.

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import base64
import logging

from uuid import uuid4
from uuid import UUID
from datetime import datetime
from datetime import timezone

import orjson

from byoda.datamodel.datafilter import DataFilterSet

from byoda.datastore.data_store import DataStore

from byoda.secrets.data_secret import DataSecret
from byoda.secrets.data_secret import InvalidSignature

from byoda.datatypes import IdType


_LOGGER = logging.getLogger(__name__)

CLAIM_FORMAT_VERSION = [
    None,
    {
        'hash_algorithm': 'SHA256',
        'additional_claim_fields': [
            'claim_id', 'claims', 'issuer', 'issuer_type',
            'object_type', 'keyfield',
            'keyfield_id', 'requester_id',
            'requester_type', 'object_fields',
            'signature_timestamp', 'signature_format_version',
            'signature_url', 'renewal_url', 'confirmation_url',
            'cert_fingerprint', 'cert_expiration'
        ]
    }
]

CLAIM_FIELDS = {
    'claim_id': {'type': UUID},
    'claims': {'type': list[str]},
    'issuer': {'type': str},
    'issuer_type': {'type': IdType},
    'object_type': {'type': str},
    'keyfield': {'type': str},
    'keyfield_id': {'type': UUID},
    'requester_id': {'type': UUID},
    'requester_type': {'type': IdType},
    'object_fields': {'type': list[str]},
    'signature': {'type': bytes},
    'signature_timestamp': {'type': datetime},
    'signature_format_version': {'type': int},
    'signature_url': {'type': str},
    'renewal_url': {'type': str},
    'confirmation_url': {'type': str},
    'cert_fingerprint': {'type': str},
    'cert_expiration': {'type': datetime},
}


class Claim:
    '''
    Class for managing claims and their signatures
    '''

    __slots__ = [
        'claim_id', 'claims', 'issuer', 'issuer_type', 'object_type',
        'keyfield', 'keyfield_id', 'object_fields', 'requester_id',
        'requester_type', 'signature', 'signature_timestamp',
        'signature_format_version', 'signature_url', 'renewal_url',
        'confirmation_url', 'cert_fingerprint', 'cert_expiration',
        'secret', 'verified'
    ]

    def __init__(self):
        self.claim_id: UUID | None = None
        self.claims: list[str] | None = None
        self.issuer: str | None = None
        self.issuer_type: IdType | None

        self.object_type: str | None = None
        self.keyfield: str | None = None
        self.keyfield_id: UUID | None = None
        self.object_fields: list[str] | None = None

        self.requester_id: UUID | None = None
        self.requester_type: IdType | None = None

        self.signature: bytes | None = None
        self.signature_timestamp: datetime | None = None
        self.signature_format_version: int | None = None

        self.signature_url: str | None = None
        self.renewal_url: str | None = None
        self.confirmation_url: str | None = None

        self.cert_fingerprint: str | None = None
        self.cert_expiration: datetime | None = None

        # The secret used to create the signature
        self.secret: DataSecret | None = None

        # Did we verify the signature?
        self.verified: bool | None = None

    def as_dict(self):
        claim_data = {}
        for fieldname in CLAIM_FIELDS:
            claim_data[fieldname] = getattr(self, fieldname)

        return claim_data

    @staticmethod
    def from_dict(claim_data: dict[str, str]) -> None:
        '''
        Factory for creating an instance of the class from claim data
        retrieved from the data store
        '''
        claim = Claim()

        claim.claim_id = claim_data['claim_id']
        if isinstance(claim.claim_id, str):
            claim.claim_id = UUID(claim.claim_id)

        claim.claims = claim_data['claims']
        claim.issuer = claim_data['issuer']

        claim.issuer_type = claim_data['issuer_type']
        if isinstance(claim.issuer_type, str):
            claim.issuer_type = IdType(claim.issuer_type)

        claim.object_type = claim_data['object_type']
        claim.keyfield = claim_data['keyfield']
        claim.keyfield_id = claim_data['keyfield_id']
        if isinstance(claim.keyfield_id, str):
            claim.keyfield_id = UUID(claim.keyfield_id)

        claim.object_fields = claim_data['object_fields']

        claim.requester_id = claim_data['requester_id']
        if isinstance(claim.requester_id, str):
            claim.requester_id = UUID(claim.requester_id)

        claim.requester_type = claim_data['requester_type']
        if isinstance(claim.requester_type, str):
            claim.requester_type = IdType(claim.requester_type)

        claim.signature = claim_data['signature']

        claim.signature_timestamp = claim_data['signature_timestamp']
        if isinstance(claim.signature_timestamp, str):
            datetime.fromisoformat(claim_data['signature_timestamp'])

        claim.signature_format_version = claim_data['signature_format_version']

        claim.signature_url = claim_data['signature_url']
        claim.renewal_url = claim_data['renewal_url']
        claim.confirmation_url = claim_data['confirmation_url']

        claim.cert_fingerprint = claim_data['cert_fingerprint']
        claim.cert_expiration = claim_data['cert_expiration']
        if isinstance(claim.cert_expiration, str):
            claim.cert_expiration = datetime.fromisoformat(
                claim_data['cert_expiration']
            )

        return claim

    @staticmethod
    def build(claims: list[str], issuer: str, issuer_type: IdType,
              object_type: str, keyfield: str, keyfield_id: UUID,
              object_fields: list[str],
              requester_id: UUID, requester_type: IdType,
              signature_url: str, renewal_url: str,
              confirmation_url, claim_id: UUID | None = None) -> None:
        '''
        Factory for creating an instance of the class
        '''

        claim = Claim()
        if claim_id:
            claim.claim_id = claim_id
        else:
            claim.claim_id = uuid4()

        claim.claims = claims
        claim.issuer = issuer
        claim.issuer_type = issuer_type

        claim.object_type = object_type
        claim.keyfield = keyfield
        claim.keyfield_id = keyfield_id
        claim.object_fields = object_fields

        claim.requester_id = requester_id
        claim.requester_type = requester_type

        claim.signature_url = signature_url
        claim.renewal_url = renewal_url
        claim.confirmation_url = confirmation_url

        return claim

    async def get_claim_data(self, member_id: UUID, data_store: DataStore
                             ) -> list:
        '''
        Gets the data covered by the signature from the data store

        :returns: a list of Claim instances
        '''

        if (not self.object_type or not self.keyfield_id
                or not self.keyfield or not self.object_fields):
            raise ValueError('Claim is missing required fields')

        filter_set = DataFilterSet(
            {
                self.keyfield: {
                    'eq': self.keyfield_id
                }
            }
        )
        data = await data_store.query(member_id, self.object_type, filter_set)

        claims = []
        for item in data or []:
            claim = Claim.from_claim_data(item)
            claims.append(claim)

        return claims

    async def store_claim(self, member_id: UUID, data_store: DataStore,
                          table_name: str) -> None:
        '''
        Stores the claim data in the data store
        '''

        for field in CLAIM_FIELDS:
            if not getattr(self, field):
                raise ValueError(f'Claim field has no data: {field}')

        await data_store.append(member_id, table_name, self.as_dict())

    def create_signature(self, data: dict[str, any],
                         secret: DataSecret = None) -> str:
        '''
        Creates a signature for the fields in the data parameter.

        :returns: base64-encoded signature
        '''

        for field in CLAIM_FIELDS:
            if not getattr(self, field):
                if field not in ['signature', 'signature_timestamp',
                                 'signature_format_version',
                                 'cert_expiration', 'cert_fingerprint']:
                    raise ValueError(f'Claim field has no data: {field}')

        if not (secret or self.secret):
            raise ValueError('No secret available to create signature')

        if not secret:
            secret = self.secret

        self.signature_timestamp = datetime.now(timezone.utc)
        self.cert_expiration = secret.cert.not_valid_after
        self.cert_fingerprint = secret.fingerprint().hex()
        self.signature_format_version = 1

        sig_data = self._get_bytes(data, format_version=1)
        signature = secret.sign_message(sig_data)
        self.signature = base64.b64encode(signature).decode('utf-8')
        self.verified = True

        return self.signature

    def verify_signature(self, data: dict[str, any], secret: DataSecret = None
                         ) -> bool:
        '''
        Verifies the signature
        '''

        if (not self.claim_id or not self.claims
                or not self.issuer or not self.issuer_type
                or not self.object_type or not self.keyfield
                or not self.keyfield_id or not self.object_fields):
            raise ValueError('Claim is missing required fields')

        if not (secret or self.secret):
            raise ValueError('No secret available to create signature')

        if not secret:
            secret = self.secret

        sig_data = self._get_bytes(data)

        try:
            signature = base64.b64decode(self.signature)
            secret.verify_message_signature(sig_data, signature)
            self.verified = True
        except InvalidSignature as exc:
            _LOGGER.info(f'Failed to verify signature: {exc}')
            self.verified = False

        return self.verified

    def _get_bytes(self, data: dict[str, any], format_version: int = 1
                   ) -> bytes:
        '''
        Creates the data that is subject to a signature

        :param data: the data of the target class covered by the signature
        :returns: the bytes encoding the data covered by the signature
        '''

        if format_version != 1:
            raise ValueError(
                f'Unsupported signature format version: {format_version}'
            )

        sig_data = b''

        for field in CLAIM_FORMAT_VERSION[1]['additional_claim_fields']:
            value = getattr(self, field)
            if isinstance(field, list):
                value = ','.join(value)
            elif isinstance(field, dict):
                raise ValueError(
                    'Dicts are not supported for additional claim fields'
                )

            sig_data += str(value).encode('utf-8')

        for field in sorted(self.object_fields):
            value = data.get(field)
            if not value:
                raise ValueError(f'Object data is missing field {field}')

            if type(value) in (str, int, float, UUID, datetime):
                sig_data += str(value).encode('utf-8')
            else:
                sig_data += orjson.dumps(value, orjson.OPT_SORT_KEYS)

        return sig_data
