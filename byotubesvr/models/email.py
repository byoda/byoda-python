
'''
Models emails and their recipients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from prometheus_client import Counter

from byoda.datatypes import MailType

from byoda.storage.message_queue import Queue
from byoda.storage.message_queue import QueueMessage

from byoda.util.logger import Logger

from byoda import config

_LOGGER: Logger | None = None

EMAIL_QUEUE: str = 'email'


class EmailMessage:
    '''
    Models a message received from a byoda.datamodel.Queue
    '''
    def __init__(self, version: int, sender: str, contents: dict[str, any]
                 ) -> None:
        # The version of the message
        self.version: int = version

        # The sender is the name of the application that sent the message
        self.sender: str = sender

        # This is the payload of the message
        self.contents: dict[str, any] = contents

        # str version is used by the Prometheus metrics
        self.mail_type: str | None = None

        # Body and HTML body are set by the subclass
        self.body: str | None = None
        self.html_body: str | None = None

        self.subject: str = self.contents['subject']
        self.recipient_name: str = self.contents.get('recipient_name')
        self.recipient_email: str = self.contents['recipient_email']
        self.sender_address: str = self.contents['sender_address']

        self._setup_metrics()

    @staticmethod
    async def from_queue(queue: Queue) -> None:
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

        _LOGGER.debug(f'Received message from queue {queue}: {sender}')

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
            mail_type = MailType(message.contents['mail_type']).value
        except ValueError:
            metric = 'email_message_invalid_mail_type'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version,
                mail_type=message.contents['mail_type']
            ).inc()
            raise

        if mail_type == MailType.EMAIL_VERIFICATION:
            verification_message = EmailVerificationMessage(
                message.sender, message.contents
            )
            verification_message.mail_type = mail_type
            return verification_message
        else:
            metric = 'email_message_unsupported_mail_type'
            config.metrics[metric].labels(
                sender=sender, message_version=message.version,
                mail_type=message.contents['mail_type']
            ).inc()
            raise RuntimeError(f'Unsupported mail type: {message.version}')

    def to_dict(self) -> dict[str, str | list[dict[str, str]]]:
        if self.body is None or self.html_body is None:
            metric = 'email_message_no_bodies'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type
            ).inc()
            raise ValueError('EmailMessage body and html_body are not set')

        if not self.subject:
            metric = 'email_message_no_subject'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type
            ).inc()
            raise ValueError('EmailMessage subject is not set')

        if not self.recipient_email:
            metric = 'email_message_no_recipient'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type
            ).inc()
            raise ValueError('EmailMessage recipient not set')

        if not self.sender_address:
            metric = 'email_message_no_sender'
            config.metrics[metric].labels(
                sender=self.sender, message_version=self.version,
                mail_type=self.mail_type
            ).inc()
            raise ValueError('EmailMessage sender address not set')

        return {
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

    def _setup_metrics(self) -> None:
        metric: str = 'email_message_verification_emails_sent'
        if metric not in config.metrics:
            config.metrics[metric] = Counter(
                metric, 'Number of verification emails sent'
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
    def __init__(self, version: int, sender: str, contents: dict[str, any]
                 ) -> None:
        super().__init__(version, sender, contents)

        url: str = contents['verification_url']
        self.body: str = (
            f'Hi, click the link to verify your email address '
            f'with the BYO.Tube service: {url}'
        )

        self.html_body: str = f'''
<HTML>
    <h1>Email verification</h1>
    <p>Hi!</p>
    <p>
    Thank you for registering your email address {self.recipient_email} with
    BYO.Tube. Please click this link <a href="{url}">{url}</a> to verify your
    email address
    </p>
</HTML>
'''
