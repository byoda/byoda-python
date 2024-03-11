
'''
Models emails and their recipients

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from byoda.datatypes import MailType

from byoda.storage.message_queue import Queue
from byoda.storage.message_queue import QueueMessage

from byoda.util.logger import Logger

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

        # Body and HTML body are set by the subclass
        self.body: str | None = None
        self.html_body: str | None = None

        self.subject: str = self.contents['subject']
        self.recipient_name: str = self.contents.get('recipient_name')
        self.recipient_email: str = self.contents['recipient_email']
        self.sender_address: str = self.contents['sender_address']

    @staticmethod
    async def from_queue(queue: Queue) -> None:
        '''
        Get a message from the queue
        '''

        queue_name: str = EMAIL_QUEUE
        message: QueueMessage = await queue.bpop(queue_name)
        sender: str = message.sender
        if message.version != 1:
            _LOGGER.error(
                f'Unknown message version: {message.version} {sender}'
            )
            raise RuntimeError(f'Unknown message version: {message.version}')

        _LOGGER.debug(f'Received message from queue {queue}: {sender}')

        if not message.contents or 'mail_type' not in message.contents:
            _LOGGER.error(
                f'No mail_type field in message from {sender}'
            )

        try:
            mail_type = MailType(message.contents['mail_type'])
        except ValueError:
            _LOGGER.error(
                f'Invalid mail_type: {message.contents["mail_type"]} '
                f'from {sender}'
            )
            raise

        if mail_type == MailType.EMAIL_VERIFICATION:
            verification_message = EmailVerificationMessage(
                message.sender, message.contents
            )
            return verification_message
        else:
            _LOGGER.error(f'Unsupported mail type: {mail_type} from {sender}')
            raise RuntimeError(f'Unsupported mail type: {message.version}')

    def to_dict(self) -> dict[str, str | list[Recipient]]:
        if self.body is None or self.html_body is None:
            _LOGGER.error(
                f'EmailMessage body and html_body are not set '
                f'by sender {self.sender}'
            )
            raise ValueError('EmailMessage body and html_body are not set')

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
