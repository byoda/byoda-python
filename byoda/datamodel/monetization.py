'''
Class for monetizing content

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''



from uuid import UUID
from enum import Enum
from typing import Self
from datetime import UTC
from datetime import date
from datetime import time
from datetime import datetime
from logging import getLogger

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)


class MonetizationType(Enum):
    FREE                        = 'free'                        # noqa: E221
    SERVICE_SUBSCRIPTION        = 'service_subscription'        # noqa: E221
    LIFETIME                    = 'lifetime'                    # noqa: E221
    SUBSCRIPTION                = 'subscription'                # noqa: E221
    PAY_PER_VIEW                = 'pay_per_view'                # noqa: E221
    SUBSCRIPTION_PAY_PER_VIEW   = 'subscription_pay_per_view'   # noqa: E221
    AD_SUPPORTED                = 'ad_supported'                # noqa: E221
