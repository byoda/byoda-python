'''
Class for handling BYO.Tube Lite passwords

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from passlib.context import CryptContext


# Used to hash passwords
PASSWORD_HASH_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    '''
    Hash a password
    '''

    return PASSWORD_HASH_CONTEXT.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    '''
    Verifies the plain-text password with the hashed password

    :param plain_password: The plain-text password
    :param hashed_password: The hashed password
    :returns: True if the plain-text password matches the hashed password
    '''
    return PASSWORD_HASH_CONTEXT.verify(
        plain_password, hashed_password
    )
