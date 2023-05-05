'''
request_auth

provides helper functions to authenticate the client making the request

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re
import logging

from byoda.datatypes import IdType

from byoda.requestauth.requestauth import RequestAuth

_LOGGER = logging.getLogger(__name__)

url_service_regex = re.compile('''data\/service-(\d+)$''')

class AnonymousRequestAuth(RequestAuth):
    async def authenticate(self, url: str):
        '''
        Get the authentication info for the client that made the API call.
        :returns: whether the client successfully authenticated
        :raises: HTTPException
        '''

        self.is_authenticated = False
        self.id_type = IdType.ANONYMOUS

        return self.is_authenticated
