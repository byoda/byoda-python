'''
Non-specific data types

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''

# Limits applied to schemas
# Max length of the name of a data element in a schema
MAX_FIELD_NAME_LENGTH: int = 64

# Maximum number of data elements of an object
MAX_OBJECT_FIELD_COUNT: int = 1024

# Maximum number of relations that can be used in
# a query request
MAX_RELATIONS_QUERY_COUNT: int = 1024

# Maxmimum lenght of the relations in a query
MAX_RELATIONS_QUERY_LEN: int = 1024
