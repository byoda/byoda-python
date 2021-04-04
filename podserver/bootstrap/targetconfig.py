'''
TargetConfig is an abstract base class that describes a target configuration
and provides methods to check whether the the target configuration is in place,
and if not, methods to implement the target configuration

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''


import logging
from abc import ABC, abstractmethod

_LOGGER = logging.getLogger(__name__)


class TargetConfig(ABC):
    @abstractmethod
    def __init__(self):
        return NotImplementedError

    @abstractmethod
    def exists(self):
        return NotImplementedError

    @abstractmethod
    def create(self):
        return NotImplementedError
