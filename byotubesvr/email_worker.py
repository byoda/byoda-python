'''
Sends email verification and password reset emails.

Info about setting up Azure Email CS and connect it to an Azure Communication
Service:
https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/email/connect-email-communication-resource?pivots=azure-portal

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys

from logging import Logger

from yaml import safe_load as yaml_safe_loader

from anyio import run
from anyio import sleep

from azure.communication.email import EmailClient
from azure.core.polling._poller import LROPoller

from prometheus_client import start_http_server
from prometheus_client import Counter

from byoda.storage.message_queue import Queue

from byoda.util.logger import Logger as ByodaLogger

from byotubesvr.datamodel.email import EmailMessage

from byoda import config

_LOGGER: Logger | None = None

PROMETHEUS_EXPORTER_PORT: int = 5020


async def main(args: list[str]) -> None:
    config_file: str = os.environ.get('CONFIG_FILE', 'config-byotube.yml')
    with open(config_file) as file_desc:
        svc_config: dict[str, str | int | bool | None] = yaml_safe_loader(
            file_desc
        )

    debug: bool = svc_config['application'].get('debug', False)
    global _LOGGER
    _LOGGER = ByodaLogger.getLogger(
        args[0], json_out=True, debug=debug, verbose=not debug,
        logfile=svc_config['svcserver']['email_worker_logfile']
    )
    _LOGGER.debug(f'Read configuration file: {config_file}')

    email_endpoint: str = svc_config['svcserver']['azure_emailcs_endpoint']
    email_access_key: str = svc_config['svcserver']['azure_emailcs_access_key']
    connection_string: str = \
        f'endpoint=https://{email_endpoint};accessKey={email_access_key}'
    email_client: EmailClient = EmailClient.from_connection_string(
        connection_string
    )

    listen_port: int = os.environ.get(
        'WORKER_METRICS_PORT', PROMETHEUS_EXPORTER_PORT
    )
    start_http_server(listen_port)

    metric: str = 'mail_worker_sent_emails'
    config.metrics[metric] = Counter(
        metric, 'Number of emails sent by the mail worker',
        ['sender', 'sender_address', 'mail_type']
    )
    metric: str = 'mail_worker_failed_emails'
    config.metrics[metric] = Counter(
        metric, 'Number of email failures by the mail worker',
        ['sender', 'sender_address', 'mail_type']
    )

    queue = await Queue.setup(svc_config['svcserver']['message_queue'])

    while True:
        message: EmailMessage
        try:
            message = await EmailMessage.from_queue(queue)
        except Exception as exc:
            _LOGGER.error(f'Failed to get message from queue: {exc}')
            await sleep(1)
            continue

        try:
            email: dict = message.to_dict()
            poller: LROPoller = email_client.begin_send(email)
            result: dict = poller.result()
            _LOGGER.debug(
                f'Sucessfully sent email with Azure ECS ID {result["id"]} '
                f'to {message.recipient_email}: {result["status"]}'
            )
            config.metrics['mail_worker_sent_emails'].labels(
                sender=message.sender, sender_address=message.sender_address,
                mail_type=message.mail_type.value
            ).inc()
        except Exception as exc:
            config.metrics['mail_worker_failed_emails'].labels(
                sender=message.sender, sender_address=message.sender_address,
                mail_type=message.mail_type.value
            ).inc()
            _LOGGER.exception(f'Error processing message: {exc}')

if __name__ == '__main__':
    run(main, sys.argv)
