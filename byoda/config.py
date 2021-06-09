'''
config

provides global variables

:maintainer : Steven Hessing <stevenhessing@live.com>
:copyright  : Copyright 2021
:license    : GPLv3
'''

import requests

# This stores the contents of the config.yml file
app_config = None

# The networks known by this server, as defined in the
# server config.yml file. The keys for the networks
# are the 'network identifiers' (so an integer number),
# the values are the name of those net
networks = {}

# The configuration of the server, its peers and the networks
# it is supporting
server = None

#
# The pod access the document store to read and write
# data for the subscribed services
document_store = None

# global session manager, apparently not 100% thread-safe if
# using different headers, cookies etc.
request = requests.Session()
