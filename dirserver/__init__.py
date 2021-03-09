'''
API server for Bring Your Own Data and Algorithms

Steven Hessing <stevenhessing@live.com>

Copyright 2021, distributed under GPLv3
'''

try:
    # This fails when we do not run under UWSGI
    # as UWSGI makes the uwsgi module 'virtuallly'
    # available to the app
    from uwsgidecorators import *               # noqa
except ModuleNotFoundError:
    # So we create a dummy decorator
    def postfork(func):
        def wrapper(*args, **kwargs):
            func(*args, **kwargs)

        return wrapper

import os
import sys
import yaml

from flask import Flask

from opentelemetry import trace
from opentelemetry.exporter import jaeger
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchExportSpanProcessor
from opentelemetry.instrumentation.flask import FlaskInstrumentor

from prometheus_flask_exporter.multiprocess import (
    UWsgiPrometheusMetrics
)

from byoda.util.logger import Logger
from byoda import config

# from byoda.datamodel import Server
from byoda.datamodel import Network

from dirserver.api import api


_LOGGER = None


def create_app(config_file='config.yml'):
    '''
    Entry point for launching app with Flask
    '''
    with open(config_file) as file_desc:
        config.app_config = yaml.load(file_desc, Loader=yaml.SafeLoader)

    debug = config.app_config['application']['debug']
    verbose = not debug
    global _LOGGER
    _LOGGER = Logger.getLogger(
       sys.argv[0], debug=debug, verbose=verbose,
       logfile=config.app_config['application'].get('logfile')
    )

    config.network = Network(
        config.app_config['dirserver'], config.app_config['application']
    )

    if not os.environ.get('SERVER_NAME') and config.network.name:
        os.environ['SERVER_NAME'] = config.network.name

    app = Flask(__name__)

    api.init_app(app)
    os.environ['prometheus_multiproc_dir'] = '/var/tmp'
    metrics = UWsgiPrometheusMetrics(app)
    metrics.register_endpoint('/metrics')

    FlaskInstrumentor().instrument_app(app)

    setup_tracing(
        env_config=config.app_config['application'].get('env', 'dev')
    )

    return app


@postfork
def setup_tracing(env_config='production', jaeger_server='127.0.0.1'):
    trace.set_tracer_provider(TracerProvider())

    _LOGGER.debug(
        'Setting up tracing for %s to server %s',
        env_config, jaeger_server
    )
    jaeger_exporter = jaeger.JaegerSpanExporter(
        service_name='byoda-appserver-' + env_config,
        agent_host_name=jaeger_server,
        agent_port=6831,
    )
    trace.get_tracer_provider().add_span_processor(
        BatchExportSpanProcessor(jaeger_exporter)
    )
