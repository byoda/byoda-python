'''
Monetization data model, creates and parses monetization data for assets

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from uuid import uuid4
from typing import Self
from datetime import UTC
from datetime import datetime
from datetime import timedelta
from logging import getLogger

import orjson

from byoda.datamodel.claim import AppClaim

from byoda.models.content_key import Claim as ClaimModel
from byoda.models.content_key import BurstAttestModel

from byoda.datatypes import IdType
from byoda.datatypes import MonetizationType

from byoda.util.logger import Logger


_LOGGER: Logger = getLogger(__name__)

MIN_BURST_POINTS: int = 100


class Monetizations:
    def __init__(self) -> None:
        self.monetizations: list[Monetization] = []

    @staticmethod
    def from_dict(data: list[dict]) -> Self:
        self = Monetizations()

        item: dict
        for item in data or []:
            monetization: Monetization = Monetization.from_dict(item)
            if monetization:
                self.monetizations.append(monetization)

        return self

    @staticmethod
    def from_monetization_instance(inst) -> Self:
        if not isinstance(inst, list):
            inst = [inst]
        self = Monetizations()
        self.monetizations.extend(inst)
        return self

    def __len__(self) -> int:
        return len(self.monetizations)

    def as_dict(self) -> list[dict[str, any]]:
        items: list[dict[str, any]] = []

        monetization: Monetization
        for monetization in self.monetizations:
            item: dict[str, str] = monetization.as_dict()
            if item:
                items.append(item)

        return items

    def as_json(self) -> bytes:
        return orjson.dumps(self.as_dict())

    async def evaluate(self, service_id: int, member_id: UUID, id_type: IdType,
                       attestation: BurstAttestModel,
                       min_burst_points: int = MIN_BURST_POINTS) -> bool:
        '''
        Evaluate whether the conditions of at least one
        monetization is met

        :return: True if the monetization requirements are met, False otherwise
        :raises: (none)
        '''

        if not self.monetizations:
            _LOGGER.debug('Approving asset without monetization')
            return True, 'Not monetized'

        reason: str | None = None
        monetization: Monetization
        for monetization in self.monetizations:
            evaluate: bool
            evaluate, reason = await monetization.evaluate(
                service_id, member_id, id_type, attestation, min_burst_points
            )
            if evaluate:
                return True, reason

        return False, reason


class Monetization:
    @staticmethod
    def from_dict(monetization_data: list[dict]) -> Self | None:
        '''
        Parse the monetization data from the data store.

        :param monetization_data: the data to parse
        :return: the parsed data or None if the data coulkdn't be parsed
        :raises: (none)
        '''

        if not monetization_data or not isinstance(monetization_data, dict):
            _LOGGER.debug('Monetization data is empty or not a dict')
            return []

        monetization_type: MonetizationType | str = monetization_data.get(
            'monetization_type'
        )
        if isinstance(monetization_type, MonetizationType):
            monetization_type = monetization_type.value

        if not monetization_type:
            _LOGGER.warning(f'Missing monetization type: {monetization_data}')
            return None

        if not isinstance(monetization_type, str):
            _LOGGER.warning(
                f'Invalid monetization type: {type(monetization_type)}'
            )
            return None

        if monetization_type == MonetizationType.FREE.value:
            monetization: FreeMonetization = FreeMonetization.from_dict(
                monetization_data
            )
            return monetization
        elif monetization_type == MonetizationType.BURSTPOINTS.value:
            monetization: BurstMonetization = BurstMonetization.from_dict(
                monetization_data
            )
            return monetization
        elif monetization_type == MonetizationType.SUBSCRIPTION.value:
            monetization: SubscriptionMonetization = \
                SubscriptionMonetization.from_dict(monetization_data)
            return monetization
        elif monetization_type == MonetizationType.PPV.value:
            monetization: PayPerViewMonetization = \
                PayPerViewMonetization.from_dict(monetization_data)
            return monetization
        elif monetization_type == MonetizationType.SPPV.value:
            monetization: SubscriptionPayPerViewMonetization = \
                SubscriptionPayPerViewMonetization.from_dict(monetization_data)
            return monetization
        else:
            _LOGGER.warning(
                f'Monetization type not implemented: {monetization_type}'
            )
            return None

    @staticmethod
    def as_dict() -> dict:
        return {
            'created_timestamp': datetime.now(tz=UTC),
            'monetization_id': uuid4(),
            'monetization_type': None,
            'require_burst_points': False,
            'network_relations': [],
            'payment_options': []
        }


class FreeMonetization(Monetization):
    @staticmethod
    def from_dict(_: dict | None = None) -> Self:
        return FreeMonetization()

    @staticmethod
    def as_dict() -> dict:
        data: dict[str, any] = Monetization.as_dict() | {
            'monetization_type': MonetizationType.FREE.value
        }
        return data

    async def evaluate(self, service_id: int, member_id: UUID, id_type: UUID,
                       attestation: BurstAttestModel, min_burst_points
                       ) -> bool:
        _LOGGER.debug('Approving access to free asset')
        return True, 'Free asset'


class BurstMonetization(Monetization):
    @staticmethod
    def from_dict(data: dict) -> Self:
        self = BurstMonetization()
        return self

    @staticmethod
    def as_dict() -> dict:
        data: dict[str, any] = Monetization.as_dict() | {
            'monetization_type': MonetizationType.BURSTPOINTS.value,
            'require_burst_points': True,
        }

        return data

    @staticmethod
    async def evaluate(
            service_id: int, member_id: UUID, member_id_type: IdType,
            attestation: BurstAttestModel, min_burst_points: int
            ) -> tuple[bool, str]:
        '''
        Evaluate the attestation to see if the member has sufficient burst
        points

        :param service_id: the service_id the token is requested for
        :param member_id: the member_id requesting the token
        :param member_id_type: the type of the member_id
        :param min_burst_points: the minimum number of burst points required to
        be attested
        :param attestation: the signed attestation to evaluate
        :return: True & None if the attestation is valid, otherwise False and
        the reason why the evaluation failed
        :raises: (none)
        '''

        log_data: dict[str, any] = {
            'service_id': service_id,
            'member_id': member_id,
            'member_id_type': member_id_type,
            'min_burst_points': min_burst_points,
        }

        if not attestation:
            _LOGGER.debug('No attestation', extra=log_data)
            return False, 'No token because no burst points attestation'

        if not isinstance(attestation, BurstAttestModel):
            _LOGGER.debug(
                f'Invalid attestation type: {type(attestation)}',
                extra=log_data
            )
            return False, 'Invalid attestation data'

        log_data |= {
            'attest_id': attestation.attest_id,
            'attestation_member_id': attestation.member_id,
            'attestation_member_type': attestation.member_type,
            'attestation_burst_points': attestation.burst_points_greater_equal,
            'created_timestamp': attestation.created_timestamp,
        }

        if attestation.member_id != member_id:
            _LOGGER.debug(
                'Attestation member_id does not match requesting member_id',
                extra=log_data
            )
            return False, 'Attestion is not for requesting member_id'

        if attestation.member_type != member_id_type:
            _LOGGER.debug(
                'Attestation member_type does not match requesting '
                'member_id_type', extra=log_data
            )
            return False, 'Attestion is not for requesting member type'

        if attestation.burst_points_greater_equal < min_burst_points:
            _LOGGER.debug(
                'Attestation points less than required', extra=log_data
            )
            return False, 'Unsufficient burst points in attestation'

        deadline: datetime = datetime.now(tz=UTC) - timedelta(hours=4)
        if attestation.created_timestamp < deadline:
            _LOGGER.debug('Attestation expired', extra=log_data)
            return False, 'Attestation expired'

        if not attestation.claims or len(attestation.claims) == 0:
            _LOGGER.debug('No claims in attestation', extra=log_data)
            return False, 'Attestation missing claims'

        claim_model: ClaimModel
        for claim_model in attestation.claims:
            log_data['claim_issuer_id'] = claim_model.issuer_id
            log_data['claim_issuer_type'] = claim_model.issuer_type
            if claim_model.issuer_type != IdType.APP:
                _LOGGER.debug('Issuer not an app', extra=log_data)
                return False, 'Invalid issuer type'

            claim: AppClaim = AppClaim.from_model(claim_model)
            await claim.get_secret(
                claim.issuer_id, service_id, claim.cert_fingerprint
            )

            burst_points: int = attestation.burst_points_greater_equal
            data: dict[str, any] = {
                'created_timestamp': attestation.created_timestamp,
                'attest_id': attestation.attest_id,
                'service_id': attestation.service_id,
                'member_id': attestation.member_id,
                'member_type': attestation.member_type,
                'burst_points_greater_equal': burst_points,
                'claims': claim_model.claims
            }
            result: bool = claim.verify_signature(data)
            # TODO: Test for revocation of the claim

            if not result:
                _LOGGER.debug('Claim signature invalid')
                return False, 'Claim signature invalid'

            prefix: str = 'burst_points_greater_equal: '
            if (not claim_model.claims
                    or not isinstance(claim_model.claims, list)
                    or not len(claim_model.claims) == 1
                    or not isinstance(claim_model.claims[0], str)
                    or not claim_model.claims[0].startswith(prefix)):
                _LOGGER.debug('Invalid claim data: {claim_model.claims}')
                return False, 'Invalid claim data'

            number_val: str = claim_model.claims[0][len(prefix):]
            try:
                number: int = int(number_val)
                log_data['claim_points'] = number
                if number < min_burst_points:
                    _LOGGER.debug(
                        'Insufficient claim value for burst: {number}',
                        extra=log_data
                    )
                    return False, 'Insufficient Burst points in claim'
            except ValueError:
                _LOGGER.debug('Invalid claim value for burst: {number}')

        return True, None


class SubscriptionMonetization(Monetization):
    @staticmethod
    def from_dict(data: dict) -> Self:
        return SubscriptionMonetization()

    async def evaluate(self, service_id: int, member_id: UUID, id_type: UUID,
                       attestation: BurstAttestModel, min_burst_points
                       ) -> bool:
        _LOGGER.debug('Subscriptions not implemented')
        return False, 'Subscriptions not implemented'

    @staticmethod
    def as_dict() -> dict:
        data: dict[str, any] = Monetization.as_dict() | {
            'monetization_type': MonetizationType.SUBSCRIPTION.value,
            'network_relations': [],
        }

        return data


class PayPerViewMonetization(Monetization):
    @staticmethod
    def from_dict(data: dict) -> Self:
        return PayPerViewMonetization()

    async def evaluate(self, service_id: int, member_id: UUID, id_type: UUID,
                       attestation: BurstAttestModel, min_burst_points
                       ) -> bool:
        _LOGGER.debug('PPV not implemented')
        return False, 'Pay Per View not implemented'

    @staticmethod
    def as_dict() -> dict:
        data: dict[str, any] = Monetization.as_dict() | {
            'monetization_type': MonetizationType.PPV.value,
            'payment_options': [],
        }

        return data


class SubscriptionPayPerViewMonetization(Monetization):
    @staticmethod
    def from_dict(data: dict) -> Self:
        return SubscriptionPayPerViewMonetization()

    async def evaluate(self, service_id: int, member_id: UUID, id_type: UUID,
                       attestation: BurstAttestModel, min_burst_points
                       ) -> bool:
        _LOGGER.debug('SPPV not implemented')
        return False, 'Subscription Pay Per View not implemented'

    @staticmethod
    def as_dict() -> dict:
        data: dict[str, any] = Monetization.as_dict() | {
            'monetization_type': MonetizationType.SPPV.value,
            'network_relations': [],
            'payment_options': [],
        }

        return data
