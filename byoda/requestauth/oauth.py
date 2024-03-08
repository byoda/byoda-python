'''
OAUTH Authentication functions for 'BYO.Tube-lite' service

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from fastapi.security import OAuth2PasswordBearer
from fastapi.security import OAuth2PasswordRequestForm      # noqa: F401

from jose import jwt
from jose import JWTError

from passlib.context import CryptContext

# Used to hash passwords
PASSWORD_HASH_CONTEXT = CryptContext(schemes=["bcrypt"], deprecated="auto")

ALGORITHM: str = "HS256"

ACCESS_TOKEN_EXPIRE_MINUTES: int = 18008        # 7 days

oauth2_scheme = OAuth2PasswordBearer(tokenUrl="token")


class LiteAccountDb:
    '''
    The database for accounts not hosted on a pod
    '''
    def __init__(self, connection_string: str) -> None:
        self.connection_string: str = connection_string

class LiteAccount:
    '''
    An account not hosted on a pod
    '''
    def __init__(self, email: str, hashed_password: str, is_enabled: bool):
        self.email: str = email
        self.hashed_password: str = hashed_password
        self.is_enabled: bool = is_enabled


async def get_account(email: str) -> LiteAccount | None:

    account: LiteAccount = await sql_db.get_account_by_email(email)

    return account


async def authenticate_account(email: str, password: str) -> LiteAccount:
    account: LiteAccount = await get_account(email)

    if not account:
        return False

    if not verify_password(password, account.hashed_password):
        return False

    return account


def verify_password(plain_password: str, hashed_password: str) -> bool:
    '''
    Verifies the plain-text password with the hashed password

    :param plain_password: The plain-text password
    :param hashed_password: The hashed password
    '''
    return PASSWORD_HASH_CONTEXT.verify(
        plain_password, hashed_password
    )


def create_access_token(data: dict, secret_key: str, is_refresh_token: bool
                        ) -> str:
    '''
    Creates JWT token for user authentication
    '''

    to_encode: dict = data.copy()

    expire: datetime
    if not is_refresh_token:
        expire = datetime.now(tz=timezone.utc) + timedelta(days=1)
    else:
        expire = datetime.now(tz=timezone.utc) + timedelta(days=365)

    to_encode.update({"exp": expire})

    encoded_jwt: str = jwt.encode(to_encode, secret_key, algorithm=ALGORITHM)

    return encoded_jwt


async def get_current_account(token: Annotated[str, Depends(oauth2_scheme)]
                              ) -> dbAccount:
    '''
    '''
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        jwt_payload: dict[str, str | int | bool] = jwt.decode(
            token, config.secret_key, algorithms=[ALGORITHM]
        )
        username: str = jwt_payload.get("sub")

        if username is None:
            raise credentials_exception

        token_data = TokenData(username=username)
    except JWTError:
        raise credentials_exception

    account: dbAccount = await get_account(email=token_data.username)

    if account is None or not account.is_enabled:
        raise credentials_exception

    return account


async def get_current_active_account(
        current_account: Annotated[dbAccount, Depends(get_current_account)]
        ) -> dbAccount:
    '''
    Checks whether the user is active
    '''

    if not current_account.is_enabled:
        raise HTTPException(status_code=400, detail="Inactive user")

    return current_account
