'''
Gunicorn acts as process manager for uvicorn. Gunicorn does not support ASGI,
uvicorn does

Supported environment variables:
  - WORKERS: number of processes to be launched by gunicorn, defaults to 2.
    Setting it to 0 will cause workers to be launched based on the number of
    cores in the pod

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024
:license    : GPLv3
'''

import os
import multiprocessing

from tempfile import mkdtemp

# Sample config file:
# https://gist.github.com/HacKanCuBa/275bfca09d614ee9370727f5f40dab9e


# ===============================================
#           Server Socket
# ===============================================

# BIND parameter is set in systemd file for the dirserver and svcserver
# but we set it here for the podserver.
bind: str = '0.0.0.0:8000'

# backlog - The maximum number of pending connections
# Generally in range 64-2048
backlog = 2048

# ===============================================
#           Worker Processes
# ===============================================

# workers - The number of worker processes for handling requests.
# A positive integer generally in the 2-4 x $(NUM_CORES) range
workers: int = int(os.environ.get('WORKERS', 2))

if workers == 0:
    workers = multiprocessing.cpu_count() * 2 + 1

# worker_class - The type of workers to use
# A string referring to one of the following bundled classes:
# 1. sync
# 2. eventlet - Requires eventlet >= 0.9.7
# 3. gevent - Requires gevent >= 0.13
# 4. tornado - Requires tornado >= 0.2
# 5. gthread - Python 2 requires the futures package to be installed (or
# install it via pip install gunicorn[gthread])
# 6. uvicorn - uvicorn.workers.UvicornWorker
#
# You’ll want to read http://docs.gunicorn.org/en/latest/design.html
# for information on when you might want to choose one of the other
# worker classes.
# See also: https://www.uvicorn.org/deployment/
worker_class: str = "uvicorn.workers.UvicornWorker"

# threads - The number of worker threads for handling requests. This will
# run each worker with the specified number of threads.
# A positive integer generally in the 2-4 x $(NUM_CORES) range
threads = 1

# keep_alive - The number of seconds to wait for requests on a
# Keep-Alive connection
# Generally set in the 1-5 seconds range.
keep_alive: int = 3600

# max_requests - the number of requests processed by a worker
# after which the worker will restart to avoid memory leaks
max_requests: int = 1024
max_requests_jitter: int = 64

# ===============================================
#           Security
# ===============================================

# limit_request_line - The maximum size of HTTP request line in bytes
# Value is a number from 0 (unlimited) to 8190.
# This parameter can be used to prevent any DDOS attack.
limit_request_line: int = 256

# limit_request_fields - Limit the number of HTTP headers fields in a request
# This parameter is used to limit the number of headers in a request to
# prevent DDOS attack. Used with the limit_request_field_size it allows
# more safety.
# By default this value is 100 and can’t be larger than 32768.
limit_request_fields: int = 32

# limit_request_field_size - Limit the allowed size of an HTTP request
# header field.
# Value is a number from 0 (unlimited) to 8190.
limit_request_field_size = 1024

# ===============================================
#           Debugging
# ===============================================

# reload - Restart workers when code changes
reload = False

# reload_engine - The implementation that should be used to power reload.
# Valid engines are:
#     ‘auto’ (default)
#     ‘poll’
#     ‘inotify’ (requires inotify)
reload_engine: str = 'auto'

# reload_extra_files - Extends reload option to also watch and reload on
# additional files (e.g., templates, configurations, specifications, etc.).
reload_extra_files: list[str] = []

# spew - Install a trace function that spews every line executed by the server
spew: bool = False

# check_config - Check the configuration
check_config: bool = False

# ===============================================
#           Server Mechanics
# ===============================================

# preload_app - Load application code before the worker processes are forked
# By preloading an application you can save some RAM resources as well as
# speed up server boot times. Although, if you defer application loading to
# each worker process, you can reload your application code easily by
# restarting workers.
preload_app: bool = True

# sendfile - Enables or disables the use of sendfile()
sendfile: bool = True

# reuse_port - Set the SO_REUSEPORT flag on the listening socket.
reuse_port: bool = False

# chdir - Chdir to specified directory before apps loading
chdir: str = ''

# daemon - Daemonize the Gunicorn process.
# Detaches the server from the controlling terminal and enters the background.
daemon: bool = False

# raw_env - Set environment variable (key=value)
# Pass variables to the execution environment.
raw_env: list[str] = []

# pidfile - A filename to use for the PID file
# If not set, no PID file will be written.
# Note, this is set on the command line by startup.sh script
pidfile: str | None = '/var/run/podserver.pid'

# worker_tmp_dir - A directory to use for the worker heartbeat temporary file
# If not set, the default temporary directory will be used.
worker_tmp_dir: str = mkdtemp(prefix='gunicorn_')

# user - Switch worker processes to run as this user
# A valid user id (as an integer) or the name of a user that can be retrieved
# with a call to pwd.getpwnam(value) or None to not change the worker process
# user
user: str | None = None

# group - Switch worker process to run as this group.
# A valid group id (as an integer) or the name of a user that can be retrieved
# with a call to pwd.getgrnam(value) or None to not change the worker
# processes group.
group: str | None = None

# umask - A bit mask for the file mode on files written by Gunicorn
# Note that this affects unix socket permissions.
# A valid value for the os.umask(mode) call or a string compatible with
# int(value, 0) (0 means Python guesses the base, so values like “0”, “0xFF”,
# “0022” are valid for decimal, hex, and octal representations)
umask: int = 0o007

# initgroups - If true, set the worker process’s group access list with all of
# the groups of which the specified username is a member, plus the specified
# group id.
initgroups: bool = False

# tmp_upload_dir - Directory to store temporary request data as they are read
# This path should be writable by the process permissions set for Gunicorn
# workers. If not specified, Gunicorn will choose a system generated temporary
# directory.
tmp_upload_dir: str = None

# secure_scheme_headers - A dictionary containing headers and values that the
# front-end proxy uses to indicate HTTPS requests. These tell gunicorn to set
# wsgi.url_scheme to “https”, so your application can tell that the request is
# secure.
secure_scheme_headers = {
    'X-FORWARDED-PROTOCOL': 'ssl',
    'X-FORWARDED-PROTO': 'https',
    'X-FORWARDED-SSL': 'on',
}

# forwarded_allow_ips - Front-end’s IPs from which allowed to handle set
# secure headers (comma separate)
# Set to “*” to disable checking of Front-end IPs (useful for setups where
# you don’t know in advance the IP address of Front-end, but you still trust
# the environment)
forwarded_allow_ips: str = os.environ.get('TRUSTED_IP', '127.0.0.1')


# pythonpath - A comma-separated list of directories to add to the Python path.
# e.g. '/home/djangoprojects/myproject,/home/python/mylibrary'.
pythonpath: str = None

# paste - Load a PasteDeploy config file. The argument may contain a # symbol
# followed by the name of an app section from the config file,
# e.g. production.ini#admin.
# At this time, using alternate server blocks is not supported. Use the command
# line arguments to control server configuration instead.
paste: str | None = None

# proxy_protocol - Enable detect PROXY protocol (PROXY mode).
# Allow using Http and Proxy together. It may be useful for work with stunnel
# as https frontend and gunicorn as http server.
# PROXY protocol: http://haproxy.1wt.eu/download/1.5/doc/proxy-protocol.txt
proxy_protocol: bool = False

# proxy_allow_ips - Front-end’s IPs from which allowed accept proxy requests
# (comma separate)
# Set to “*” to disable checking of Front-end IPs (useful for setups where you
# don’t know in advance the IP address of Front-end, but you still trust the
# environment)
proxy_allow_ips: str = '127.0.0.1'

# raw_paste_global_conf - Set a PasteDeploy global config variable in key=value
# form.
# The option can be specified multiple times.
# The variables are passed to the the PasteDeploy entrypoint. Example:
# $ gunicorn -b 127.0.0.1:8000 --paste development.ini --paste-global FOO=1
# --paste-global BAR=2
raw_paste_global_conf: list[str] = []

# strip_header_spaces - Strip spaces present between the header name and
# the `:`. This is known to induce vulnerabilities and is not compliant with
# the HTTP/1.1 standard. See
# https://portswigger.net/research/http-desync-attacks-request-smuggling-reborn
# Use with care and only if necessary.
strip_header_spaces: bool = False

# ===============================================
#           Logging
# ===============================================

# accesslog - The Access log file to write to.
# “-” means log to stdout.
# accesslog = '-'
# accesslog = '/var/log/byoda/gunicorn-access.log'
accesslog = '/dev/null'

# access_log_format - The access log format
#
# Identifier  |  Description
# ------------------------------------------------------------
# h            ->  remote address
# l            -> ‘-‘
# u            -> user name
# t            -> date of the request
# r            -> status line (e.g. GET / HTTP/1.1)
# m            -> request method
# U            -> URL path without query string
# q            -> query string
# H            -> protocol
# s            -> status
# B            -> response length
# b            -> response length or ‘-‘ (CLF format)
# f            -> referer
# a            -> user agent
# T            -> request time in seconds
# D            -> request time in microseconds
# L            -> request time in decimal seconds
# p            -> process ID
# {header}i    -> request header
# {header}o    -> response header
# {variable}e  -> environment variable
# ---------------------------------------------------------------
#
# Use lowercase for header and environment variable names, and put {...}x names
# inside %(...)s. For example:
#
# %({x-forwarded-for}i)s
access_log_format: str = \
    '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s"'

# disable_redirect_access_to_syslog - Disable redirect access logs to syslog.
disable_redirect_access_to_syslog: bool = False

# errorlog - The Error log file to write to.
# “-” means log to stderr.
# errorlog = '-'
errorlog = os.environ.get('LOGDIR', '/var/log/byoda') + '/gunicorn-error.log'

# loglevel - The granularity of Error log outputs.
# Valid level names are:
# 1. debug
# 2. info
# 3. warning
# 4. error
# 5. critical
loglevel: str = 'warning'

# capture_output - Redirect stdout/stderr to specified file in errorlog.
capture_output: bool = False

# logger_class - The logger you want to use to log events in gunicorn.
# The default class (gunicorn.glogging.Logger) handle most of normal usages
# in logging. It provides error and access logging.
logger_class: str = 'gunicorn.glogging.Logger'

# logconfig - The log config file to use. Gunicorn uses the standard Python
# logging module’s Configuration file format.
logconfig: str | None = None

# logconfig_dict - The log config dictionary to use, using the standard
# Python logging module’s dictionary configuration format. This option
# takes precedence over the logconfig option, which uses the older file
# configuration format.
# Format:
# https://docs.python.org/3/library/logging.config.html#logging.config.dictConfig
logconfig_dict: dict[str] = {}

# syslog_addr - Address to send syslog messages.
#
# Address is a string of the form:
# ‘unix://PATH#TYPE’ : for unix domain socket. TYPE can be ‘stream’ for the
#                      stream driver or ‘dgram’ for the dgram driver.
#                      ‘stream’ is the default.
# ‘udp://HOST:PORT’ : for UDP sockets
# ‘tcp://HOST:PORT‘ : for TCP sockets
# syslog_addr = 'udp://localhost:514'
syslog_addr: str | None = None

# syslog - Send Gunicorn logs to syslog
syslog: bool = False

# syslog_prefix - Makes gunicorn use the parameter as program-name in the
# syslog entries.
# All entries will be prefixed by gunicorn.<prefix>. By default the program
# name is the name of the process.
syslog_prefix: str | None = None

# syslog_facility - Syslog facility name
syslog_facility: str = 'user'

# enable_stdio_inheritance - Enable stdio inheritance
# Enable inheritance for stdio file descriptors in daemon mode.
# Note: To disable the python stdout buffering, you can to set the user
# environment variable PYTHONUNBUFFERED .
enable_stdio_inheritance: bool = False

# statsd_host - host:port of the statsd server to log to
statsd_host: str | None = None

# statsd_prefix - Prefix to use when emitting statsd metrics (a trailing . is
# added, if not provided)
statsd_prefix: str = ''

# dogstatsd_tags - A comma-delimited list of datadog statsd (dogstatsd) tags to
# append to statsd metrics.
dogstatsd_tags: str = ''

# ===============================================
#           Process Naming
# ===============================================

# proc_name - A base to use with setproctitle for process naming.
# This affects things like `ps` and `top`.
# It defaults to ‘gunicorn’.
proc_name: str = 'gunicorn'
# proc_name: str = 'appserver'

# TODO: this is probably not working
ws_per_message_deflate: bool = False
