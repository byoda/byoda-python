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

# This stores the contents of the config.yml file
app_config = None

# The networks known by this server, as defined in the
# server config.yml file. The keys for the networks
# are the 'network identifiers' (so an integer number),
# the values are the name of those networks
networks = {}

# The services of a network. The source of this information
# will be the directory server of the network
services = {}

# The service memberships of an account
memberships = {}

# The configuration of the server, its peers and the networks
# it is supporting
server = None

# global session manager, apparently not 100% thread-safe if
# using different headers, cookies etc.
request = requests.Session()
