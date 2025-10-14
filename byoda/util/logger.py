'''
Python module for standardized logging

:maintainer : Steven Hessing (steven@byoda.org)
:copyright  : Copyright 2020, 2021
:license    : GPLv3
'''

import os
import sys
import logging

from typing import Self
from datetime import datetime
from datetime import timezone

from pythonjsonlogger import jsonlogger

from starlette_context import context


class Logger(logging.Logger):
    '''
    Enables settings for logging, reducing the amount of
    boilerplate code in scripts
    '''

    @staticmethod
    def getLogger(appname, loglevel: int = None, json_out: bool = True,
                  extra: bool = None, logfile: str = None,
                  debug: bool = False, verbose: bool = False) -> Self:
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
        appname: str = os.path.splitext(
            os.path.basename(appname)
        )[0].rstrip('.py')

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
        root_logger: logging.Logger = logging.getLogger()
        root_logger.setLevel(loglevel)

        if not logfile:
            logging_handler = logging.StreamHandler(sys.stdout)
        else:
            logging_handler = logging.FileHandler(logfile)

        logging_handler.setLevel(loglevel)

        if json_out:
            if extra is None:
                extra = {}
            formatter = ByodaJsonFormatter(
                '%(asctime) %(name) %(process) %(processName) %(filename) '
                '%(funcName) %(levelname) %(lineno) %(module) '
                '%(threadName) %(message)'
            )
        else:
            formatter = logging.Formatter(
                fmt=(
                    '%(asctime)s %(levelname)s %(name)s %(module)s '
                    '%(funcName)s %(lineno)d %(message)s'
                )
            )

        logging_handler.setFormatter(formatter)
        root_logger.addHandler(logging_handler)

        # TODO: manage log levels for various SDKs
        logging.getLogger('asyncio').setLevel(logging.WARNING)

        logging.getLogger('httpcore').setLevel(logging.INFO)
        logging.getLogger('urllib3').setLevel(logging.WARNING)
        logging.getLogger('hpack').setLevel(logging.WARNING)
        logging.getLogger('httpx').setLevel(logging.ERROR)

        logging.getLogger('websockets').setLevel(logging.ERROR)
        logging.getLogger('gql').setLevel(logging.WARNING)

        logging.getLogger('pynng.nng').setLevel(logging.INFO)

        logging.getLogger('aiosqlite').setLevel(logging.WARNING)

        logging.getLogger('passlib').setLevel(logging.ERROR)

        logging.getLogger('opentelemetry.exporter').setLevel(logging.ERROR)

        logging.getLogger('azure').setLevel(logging.WARNING)
        logging.getLogger('google').setLevel(logging.WARNING)

        logging.getLogger('byoda.storage.azure').setLevel(logging.INFO)
        logging.getLogger('byoda.storage.aws').setLevel(logging.INFO)
        logging.getLogger('byoda.storage.gcp').setLevel(logging.INFO)
        logging.getLogger('byoda.storage.filestorage').setLevel(
            logging.INFO
        )

        logging.getLogger('byoda.datamodel.account').setLevel(logging.INFO)
        logging.getLogger('byoda.datamodel.dataclass').setLevel(logging.INFO)
        logging.getLogger('byoda.datastore.memberdb').setLevel(logging.INFO)
        logging.getLogger('byoda.storage.sqlite').setLevel(logging.INFO)
        logging.getLogger('byoda.storage.sqlstorage').setLevel(logging.INFO)

        # YouTube import logging settings
        # logging.getLogger('byoda.data_import.youtube').setLevel(logging.INFO)
        # logging.getLogger('byoda.data_import.youtube_video').setLevel(
        #     logging.INFO
        # )
        #logging.getLogger('byoda.data_import.youtube_thumbnail').setLevel(
        #     logging.INFO
        #)
        # logging.getLogger('byoda.data_import.youtube_channel').setLevel(
        #     logging.INFO
        # )
        # Now create a child logger for the caller, which inherits
        # from the root logger
        logger: logging.Logger = logging.getLogger(appname)
        return logger


class ByodaJsonFormatter(jsonlogger.JsonFormatter):
    def __init__(self, logger, extra: dict[str, any] | None = None) -> None:

        if extra is None:
            extra = {}

        self.extra: dict[str, any] = extra
        super(ByodaJsonFormatter, self).__init__(logger, extra)

    def add_fields(self, log_record, record, message_dict) -> None:
        super(ByodaJsonFormatter, self).add_fields(
            log_record, record, message_dict
        )
        if not log_record.get('timestamp'):
            # this doesn't use record.created, so it is slightly off
            now: str = datetime.now(timezone.utc).strftime(
                '%Y-%m-%dT%H:%M:%S.%fZ'
            )
            log_record['timestamp'] = now
        if log_record.get('level'):
            log_record['level'] = log_record['level'].upper()
        else:
            log_record['level'] = record.levelname

        extra: dict[str, any] = self.extra.copy()
        try:
            extra.update(context.data)
        except RuntimeError:
            # We called context outside of a FastAPI request
            pass

        log_record.update(extra)
