'''
Python module for standardized logging

:maintainer : Steven Hessing (stevenhessing@live.com)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import os
import sys
import logging
from datetime import datetime
from uuid import uuid4


from pythonjsonlogger import jsonlogger

from flask import request

import byoda.config as config


LOGFILE = '/var/tmp/byoda.log'


class Logger(logging.Logger, object):
    '''
    Enables settings for logging, reducing the amount of
    boilerplate code in scripts
    '''

    @staticmethod
    def getLogger(appname, loglevel=None,
                  json_out=True, extra=None, logfile=None,
                  debug=False, verbose=False):
        '''
        Factory for Logger class. Returns logger with specified
        name. The default log level is logging.WARNING. The debug flag
        has a double function: enable debug logging and send logs to
        STDERR.

        Typical invocations are:
        - Send WARNING and higher priority messages as JSON to log file
            getLogger(argv[0], BootstrapUtil())
        - Send INFO and higher priority as JSON to log file
            getLogger(argv[0], BootstrapUtil(), verbose=True)
        - Send DEBUG and higher priority as JSON to log file
            getLogger(argv[0], BootstrapUtil(), loglevel=logging.DEBUG)
        - Send debug lines to STDERR
            getLogger(argv[0], BootstrapUtil(), debug=True, json_out=False)

        :param appname   : name of the logger. If the name looks like
                           a filename, containing '/' and '.' then the
                           appname will be stripped using
                           os.path.basename
        :param loglevel  : optional logging level as defined by the
                           logging class, defaults to logging.WARN
        :param json_out  : optional bool on whether logs should be
                           generated in json format, defaults to True
        :param extra     : optional dict with additional key/value
                           pairs that should be written to the log
                           file. Only supported with json_out=True
        :param logfile   : optional string with the name of the log
                           file. Defaults to
                           /var/log/infrastructure.log
        :param debug     : optional bool for debug logging, takes
                           precedence over 'loglevel' parameter
        :param verbose   : optional bool for verbose logging, takes
                           precedence over 'loglevel' parameter
        :raises: ValueError
        :returns: instance of Logger class
        '''

        if verbose and debug:
            raise ValueError(
                'Verbose and debug can not be enabled at the same time'
            )

        if not json_out and extra:
            raise ValueError(
                'Extra log fields are only supported for JSON logs'
            )

        # For the logger, strip off any directory and any extension
        # from appname (for if appname=sys.argv[0])
        appname = os.path.splitext(os.path.basename(appname))[0].rstrip('.py')

        # loglevel takes precedence over debug and verbose
        if not loglevel:
            if debug:
                loglevel = logging.DEBUG
            elif verbose:
                loglevel = logging.INFO
            else:
                loglevel = logging.WARNING

        # We set up the root logger so that modules inherit
        # its settings
        root_logger = logging.getLogger()
        root_logger.setLevel(loglevel)

        if not logfile:
            if debug or verbose:
                logging_handler = logging.StreamHandler(sys.stderr)
            else:
                logfile = LOGFILE
                logging_handler = logging.FileHandler(logfile)
        else:
            logging_handler = logging.FileHandler(logfile)

        logging_handler.setLevel(loglevel)

        if json_out:
            if extra is None:
                extra = {}
            formatter = JsonFormatter(extra=extra)
        else:
            formatter = logging.Formatter(
                fmt=(
                    '%(asctime)s %(levelname)s %(name)s %(module)s '
                    '%(funcName)s %(lineno)d %(message)s'
                )
            )

        logging_handler.setFormatter(formatter)
        root_logger.addHandler(logging_handler)

        # Now create a child logger for the caller, which inherits
        # from the root logger
        logger = logging.getLogger(appname)
        return logger

    def process_log_record(self, log_record):
        # Enforce the presence of a timestamp
        if "asctime" in log_record:
            log_record["timestamp"] = log_record["asctime"]
        else:
            log_record["timestamp"] = int(
                datetime.timestamp(datetime.utcnow())
            )

        if self._extra is not None:
            for key, value in self._extra.items():
                log_record[key] = value
        return super(JsonFormatter, self).process_log_record(log_record)


class JsonFormatter(jsonlogger.JsonFormatter, object):
    '''
    Class to provide a formatter to logging.Logger that outputs JSON
    '''

    def __init__(
        self,
        fmt=(
            "%(asctime) %(name) %(process) %(processName) %(filename) "
            "%(funcName) %(levelname) %(lineno) %(module) "
            "%(threadName) %(message)"
        ),
        datefmt="%Y-%m-%dT%H:%M:%SZ%z",
        style='%',
        extra={},
        *args,
        **kwargs
    ):
        self._extra = extra
        self.datefmt = datefmt
        jsonlogger.JsonFormatter.__init__(
            self, fmt=fmt, datefmt=datefmt, *args, **kwargs
        )

    def process_log_record(self, log_record):
        # Enforce the presence of a timestamp
        if "asctime" in log_record:
            log_record["timestamp"] = log_record["asctime"]
        else:
            log_record["timestamp"] = \
                datetime.datetime.utcnow().strftime(self.datefmt)

        # Enabling the class construction to specify additional key/value
        # pairs that will be included in each log message
        if self._extra is not None:
            for key, value in self._extra.items():
                log_record[key] = value

        if config.extra_log_data:
            log_record.update(config.extra_log_data)

        return super(JsonFormatter, self).process_log_record(log_record)


def flask_log_fields(f):
    '''
    Adds a fields to the logs emitted via the global config.extra_log_data
    variable.

    - trace_id       : an UUID used to emit trace logs
    - client_addr    : the IP address of the source of the request
    - request_uri    : the URI used by the client
    - request_method : GET/PUT/POST/PATCH/DELETE
    '''
    def _flask_log_fields(*args, **kwargs):
        data = {
            'trace_id': str(uuid4())
        }
        client_ip = request.headers.get('X-Forwarded-For', '')
        if not client_ip:
            client_ip = request.remote_addr

        data['client_addr'] = client_ip
        data['request_uri'] = request.path
        data['request_method'] = request.method

        config.extra_log_data = data

        return f(*args, **kwargs)
    return _flask_log_fields
