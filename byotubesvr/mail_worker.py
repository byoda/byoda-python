'''
Sends email verification and password reset emails.

Info about setting up Azure Email CS and connect it to an Azure Communication Service:
https://learn.microsoft.com/en-us/azure/communication-services/quickstarts/email/connect-email-communication-resource?pivots=azure-portal

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

import os
import sys

from yaml import safe_load as yaml_safe_loader

from anyio import run

from azure.communication.email import EmailClient

from prometheus_client import start_http_server
from prometheus_client import Counter

from byoda.storage.message_queue import Queue

from byoda.util.logger import Logger

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
    _LOGGER = Logger.getLogger(
        sys.argv[0], json_out=True, debug=debug, verbose=not debug,
        logfile=svc_config['svcserver']['mailworker_logfile']
    )
    _LOGGER.debug(f'Read configuration file: {config_file}')

    email_endpoint: str = svc_config['svcserver']['azure_emailcs_endpoint']
    email_access_key: str = svc_config['svcserver']['azure_emailcs_access_key']
    connection_string: str = \
        f'endpoint=https://{email_endpoint};accessKey={email_access_key}'
    email_client: EmailClient = EmailClient.from_connection_string(
        connection_string
    )

    listen_port: int = PROMETHEUS_EXPORTER_PORT
    start_http_server(listen_port)
    metric: str = 'mail_worker_sent_emails'
    config.metrics[metric] = Counter(
        metric, 'Number of emails sent by the mail worker',
        ['mail_version', 'sender', 'sender_address', 'mail_type']
    )
    metric: str = 'mail_worker_failed_emails'
    config.metrics[metric] = Counter(
        metric, 'Number of email failures by the mail worker',
        ['mail_version', 'sender', 'sender_address', 'mail_type']
    )

    queue = await Queue.setup(svc_config['svcserver']['message_queue'])

    while True:
        try:
            message = await EmailMessage.from_queue(queue)
            email = message.to_dict()
            poller = email_client.begin_send(email.to_dict())
            result = poller.result()
            _LOGGER.debug(
                f'Sucessfully sent email to {email.recipient_email}: {result}'
            )
            config.metrics['mail_worker_sent_emails'].labels(
                mail_version=message.version, sender=message.sender,
                sender_address=message.sender_address,
                mail_type=message.mail_type
            ).inc()
        except Exception as exc:
            config.metrics['mail_worker_failed_emails'].labels(
                mail_version=message.version, sender=message.sender,
                sender_address=message.sender_address,
                mail_type=message.mail_type
            ).inc()
            _LOGGER.exception(f'Error processing message: {exc}')

if __name__ == '__main__':
    run(main, sys.argv)
