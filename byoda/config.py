'''
config

provides global variables

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import requests

DEFAULT_NETWORK = 'byoda.net'

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
