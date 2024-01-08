###
### Start of variables that you can configure
###

# Which release train do we want to be on?
export TAG=latest

# How often should backups be created? This only applies to pods
# running in public clouds. As it incurs some (fairly minor) traffic
# costs, we set the interval to 4 hours (= 240 minutes)
export BACKUP_INTERVAL=240

# Set to "IGNORE" when not using cloud storage
export PRIVATE_BUCKET="changeme"
export RESTRICTED_BUCKET="changeme"
export PUBLIC_BUCKET="changeme"

# Set the following two variables to long random strings
export ACCOUNT_SECRET="changeme"
export PRIVATE_KEY_SECRET="changeme"

# These variables need to be set only for pods on AWS:
export AWS_ACCESS_KEY_ID="changeme"
export AWS_SECRET_ACCESS_KEY="changeme"

# The pod will join the command-separated services listed in the following
# variable
export JOIN_SERVICE_IDS=""

# To import the metadata of your YouTube videos, edit the following variables.
# Use quotes "" if the name of the channel contains whitespace
export YOUTUBE_CHANNEL=

# To import using the YouTube Data API instead of scraping youtube.com, set
# the this variable to your API key:
export YOUTUBE_API_KEY=

# The service for which Youtube videos should be imported
export YOUTUBE_IMPORT_SERVICE_ID=4294929430

# To manage how often the import process runs, set the following variable
export YOUTUBE_IMPORT_INTERVAL=$(echo $((180 + RANDOM % 120)))

# The moderation app to send requests for videos imported from YouTube
export MODERATION_FQDN="modtest.byoda.io"
export MODERATION_APP_ID="3eb0f7e5-c1e1-49b4-9633-6a6aa2a9fa22"

# To import your Twitter public tweets, sign up for Twitter Developer
# program at https://developer.twitter.com/ and set the following three
# environment variables (more instructions in
# https://github.com/byoda/byoda-python/README.md)
export TWITTER_API_KEY=
export TWITTER_KEY_SECRET=
export TWITTER_USERNAME=

# To use a custom domain, follow the instructions in the section
# 'Certificates and browsers' in the README.md file.
export CUSTOM_DOMAIN=

# To install the pod on a (physical) server that already has nginx running,
# set the SHARED_WEBSERVER variable to 'SHARED_WEBSERVER'
export SHARED_WEBSERVER=

# To install the pod on a (physical) server that already has nginx running,
# and listens to port 80, and you want to use a CUSTOM_DOMAIN, unset the
# MANAGE_CUSTOM_DOMAIN_CERT variable
export MANAGE_CUSTOM_DOMAIN_CERT="MANAGE_CUSTOM_DOMAIN_CERT"

# If you are running on a shared webserver with a custom domain and can't
# make port 80 avaible then you'll have to generate the SSL cert yourself
# and store it in a directory that follows the Let's Encrypt directory
# lay-out and set the below variable to that directory
export LETSENCRYPT_DIRECTORY="/var/www/letsencrypt"

# With this option set to a directory, you can access the logs from the pod
# on the host VM or server as it will be volume mounted in the pod.
export LOCAL_WWWROOT_DIRECTORY=/var/www/wwwroot

# If you are not running in a cloud VM then you can change this to the
# directory where all data of the pod should be stored
export BYODA_ROOT_DIR=/byoda

export LOGDIR=/var/log/byoda

# set DEBUG if you are interested in debug logs and troubleshooting the
# processes in the pod.
export DEBUG=
export LOGLEVEL=CRITICAL

# Workers write their logs to a file so this will increase the disk
# usage of the pod, at some point filling up the disk of the host.
export WORKER_LOGLEVEL=CRITICAL

# Set up tracing (for debugging purposes). Requires a Jaeger server
export TRACE_SERVER="127.0.0.1"
