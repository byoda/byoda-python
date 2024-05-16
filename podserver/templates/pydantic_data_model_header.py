'''
Imports for the pydantic data models we generate

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023, 2024
:license    : GPLv3
'''

# flake8: noqa: E501

from uuid import UUID
from datetime import datetime

from pydantic import Field

# We define our own BaseModel that inherits from pydantic's BaseModel
# so that we can add our own custom fields and methods to it.
from byoda.models.data_api_models import BaseModel