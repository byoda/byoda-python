#!/usr/bin/env python3

'''
Hashes a plain-text password
'''

import sys

from passlib.context import CryptContext

password_hash_context = CryptContext(schemes=["bcrypt"], deprecated="auto")

for password in sys.argv[1:]:
    hashed_password: str = password_hash_context.hash(password)
    print(f'Password {password} hashed to {hashed_password}')
