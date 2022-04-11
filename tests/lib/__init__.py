'''
Functions used by test cases

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license
'''

from uuid import UUID, uuid4


def get_test_uuid() -> UUID:
    id = str(uuid4())
    id = 'aaaaaaaa' + id[8:]
    id = UUID(id)
    return id
