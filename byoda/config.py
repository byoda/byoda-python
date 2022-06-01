'''
config

provides global variables

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import requests

DEFAULT_NETWORK = 'byoda.net'


# Enable various debugging options in the pod, including
# whether the GraphQL web page should be enabled.
debug = False

# Used by logging to add extra data to each log record,
# typically using the byoda.util.logger.flask_log_fields
# decorator
# After importing config, you can also set, for example,
# config.extra_log_data['remote_addr'] = client_ip
extra_log_data = {}

# The configuration of the server, its peers and the networks
# it is supporting
server = None

# global session manager, apparently not 100% thread-safe if
# using different headers, cookies etc.
request = requests.Session()

# Test cases set the value to True. Code may evaluate whether
# it is running as part of a test case to accept function parameters
test_case: bool = False

