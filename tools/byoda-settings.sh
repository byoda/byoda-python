###
### Start of variables that you can configure
###

# Set to "IGNORE" when not using cloud storage
export BUCKET_PREFIX="changeme"
# Set the following two variables to long random strings
export ACCOUNT_SECRET="changeme"
export PRIVATE_KEY_SECRET="changeme"

# These variables need to be set only for pods on AWS:
export AWS_ACCESS_KEY_ID="changeme"
export AWS_SECRET_ACCESS_KEY="changeme"

# To import your Twitter public tweets, sign up for Twitter Developer
# program at https://developer.twitter.com/ and set the following three
# environment variables (more instructions in
# https://github.com/StevenHessing/byoda-python/README.md)
export TWITTER_API_KEY=
export TWITTER_KEY_SECRET=
export TWITTER_USERNAME=

# To import the metadata of YouTube videos, set:
export YOUTUBE_CHANNEL=

# If you provide an API key, your pod can import all the videos of the
# channel you specify. Without an API key, the pod can only import the
# metadata of approx 100 of the most recent videos of each channel.
export YOUTUBE_API_KEY=

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

# set DEBUG if you are interested in debug logs and troubleshooting the
# processes in the pod
export DEBUG=
