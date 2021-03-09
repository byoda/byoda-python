'''
config

provides global variables

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import requests

# Used by logging to add extra data to each log record,
# typically using the byoda.util.logger.flask_log_fields
# decorator
# After importing config, you can also set, for example,
# config.extra_log_data['remote_addr'] = client_ip
extra_log_data = {}

# This stores the contents of the config.yml file
app_config = None

# This is the Network instance that tracks all information
# regarding the network that this server is a member of
network = None

# global session manager, apparently not 100% thread-safe if
# using different headers, cookies etc.
request = requests.Session()
