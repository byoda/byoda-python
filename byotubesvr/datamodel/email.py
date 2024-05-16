
'''
Models emails and their recipients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from typing import Self
from logging import getLogger

from prometheus_client import Counter

from byoda.datatypes import MailType

from byoda.storage.message_queue import Queue
from byoda.storage.message_queue import QueueMessage

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger = getLogger(__name__)

EMAIL_QUEUE: str = 'email'


class EmailMessage:
    '''
    Models a message received from a byoda.datamodel.Queue
    '''
    def __init__(
        self, sender: str, mail_type: MailType, subject: str,
        recipient_name: str, recipient_email: str, sender_address: str,
    ) -> None:
        '''
        :param sender: The process/application sending the message
        :param mail_type: The type of message
        :param contents: The payload of the email
        '''

        # Which process/application is sending the message
        self.sender: str = sender

        # str version is used by the Prometheus metrics
        self.mail_type: MailType = mail_type

        self.subject: str = subject
        self.recipient_name: str = recipient_name
        self.recipient_email: str = recipient_email
        self.sender_address: str = sender_address

        # Body and HTML body are set by the subclass
        self.body: str | None = None
        self.html_body: str | None = None

        if 'email_message_verification_emails_sent' not in config.metrics:
            self._setup_metrics()

    @staticmethod
    def from_dict(sender: str, mail_type: MailType,
                  message_contents: dict[str, any]) -> Self:
        '''
        Set the message contents from a dictionary

        Names of the keys of the dict are based on names required by
        Azure Email Message Communication Service Python APIs

        :param sender: this is the application sending the message
        :param mail_type: the type of message
        :param message_contents: the contents of the message
        '''

        if mail_type == MailType.EMAIL_VERIFICATION:
            mail_content: str = message_contents['content']
            to_recipients: str = message_contents['recipients']['to']
            message: EmailVerificationMessage = EmailVerificationMessage(
                sender=sender,
                subject=mail_content['subject'],
                recipient_name=to_recipients[0].get('displayName', ''),
                recipient_email=to_recipients[0]['address'],
                sender_address=message_contents['senderAddress']
            )

        message.body = mail_content['plainText']
        message.html_body = mail_content['html']

        return message

    def to_dict(self) -> dict[str, str | list[dict[str, str]]]:
        '''
        Generate a dictionary from the message contents

        Names of the keys of the dict are based on names required by
        Azure Email Message Communication Service Python APIs
        '''
        if self.body is None or self.html_body is None:
            metric = 'email_message_no_bodies'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type.value
            ).inc()
            raise ValueError('EmailMessage body and html_body are not set')

        if not self.subject:
            metric = 'email_message_no_subject'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type.value
            ).inc()
            raise ValueError('EmailMessage subject is not set')

        if not self.recipient_email:
            metric = 'email_message_no_recipient'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type.value
            ).inc()
            raise ValueError('EmailMessage recipient not set')

        if not self.sender_address:
            metric = 'email_message_no_sender'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type.value
            ).inc()
            raise ValueError('EmailMessage sender address not set')

        return {
            'mail_type': self.mail_type.value,
            'content': {
                'subject': self.subject,
                'plainText': self.body,
                'html': self.html_body
            },
            'recipients': {
                'to': [
                    {
                        'address': self.recipient_email,
                        'displayName': self.recipient_name
                    },
                ]
            },
            'senderAddress': self.sender_address
        }

    async def to_queue(self, queue: Queue) -> None:
        queue_name: str = EMAIL_QUEUE
        queue_message: QueueMessage = QueueMessage(
            1, self.sender, self.to_dict()
        )
        await queue.push(queue_name, queue_message)

    @staticmethod
    async def from_queue(queue: Queue) -> Self:
        '''
        Get a message from the queue
        '''

        queue_name: str = EMAIL_QUEUE
        message: QueueMessage = await queue.bpop(queue_name)
        sender: str = message.sender
        if message.version != 1:
            metric = 'email_message_unsupported_message_version'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version
            ).inc()
            raise RuntimeError(
                f'Unsupported message version: {message.version}'
            )

        _LOGGER.debug(f'Received message from queue {queue_name}: {sender}')

        if not message.contents:
            metric = 'email_message_no_contents'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version
            ).inc()
            raise RuntimeError('Received message without contents')

        if 'mail_type' not in message.contents:
            metric = 'email_message_unknown_mail_type'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version
            ).inc()
            raise RuntimeError('Received message without mail type')

        try:
            mail_type = MailType(message.contents['mail_type'])
        except ValueError:
            metric = 'email_message_invalid_mail_type'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version,
                mail_type=message.contents['mail_type']
            ).inc()
            raise

        if mail_type == MailType.EMAIL_VERIFICATION:
            verification_message: EmailVerificationMessage = \
                EmailVerificationMessage.from_dict(
                    message.sender, mail_type, message.contents
                )
            return verification_message
        else:
            metric = 'email_message_unsupported_mail_type'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version,
                mail_type=message.contents['mail_type']
            ).inc()
            raise RuntimeError(f'Unsupported mail type: {mail_type}')

    def _setup_metrics(self) -> None:
        metric: str = 'email_message_verification_emails_sent'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric, 'Number of verification emails sent',
                ['sender', 'message_type', 'message_version']
            )
        metric = 'email_message_unsupported_message_version'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue with unsupported version',
                ['sender', 'message_version']
            )
        metric = 'email_message_no_contents'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue without contents',
                ['sender', 'message_version']
            )
        metric = 'email_message_unknown_mail_type'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric, 'Messages received from queue with unknown mail type',
                ['sender', 'message_version']
            )
        metric = 'email_message_invalid_mail_type'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric, 'Messages received from queue with invalid mail type',
                ['sender', 'mail_type', 'message_version']
            )
        metric = 'email_message_unsupported_mail_type'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue with unsupported mail type',
                ['sender', 'message_version', 'mail_type']
            )
        metric = 'email_message_no_bodies'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue without body or html_body',
                ['sender', 'message_version', 'mail_type']
            )
        metric = 'email_message_no_subject'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue without subject',
                ['sender', 'message_version']
            )
        metric = 'email_message_no_recipient'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue without recipient address',
                ['sender', 'message_version']
            )
        metric = 'email_message_no_sender'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric,
                'Messages received from queue without sender address',
                ['sender', 'message_version']
            )


class EmailVerificationMessage(EmailMessage):
    def __init__(self, sender: str, subject: str, recipient_name: str,
                 recipient_email: str, sender_address: str,
                 verification_url: str | None = None) -> None:
        '''
        constructor

        :param sender: The process/application sending the message
        :param subject: The subject of the email
        :param recipient_name: The name of the recipient
        :param recipient_email: The email address of the recipient
        :param sender_address: The email address of the sender
        :param verification_url: The URL to call to confirm the email address
        '''
        super().__init__(
            sender=sender, mail_type=MailType.EMAIL_VERIFICATION,
            subject=subject, recipient_name=recipient_name,
            recipient_email=recipient_email, sender_address=sender_address
        )

        self.verification_url: str | None = verification_url
        if verification_url:
            self.add_body(verification_url)

    def add_body(self, verification_url: str) -> None:
        self.verification_url: str | None = verification_url

        self.body: str = (
            f'Hi, click the link to verify your email address '
            f'with the BYO.Tube service: {verification_url}'
        )

        self.html_body: str = f'''
<html>
    <h1>Email verification</h1>
    <p>Hi!</p>
    <p>
        Thank you for registering your email address {self.recipient_email}
        with BYO.Tube. Please click this link <a href="{verification_url}">
        {verification_url}</a> to verify your email address
    </p>
</html>
'''
