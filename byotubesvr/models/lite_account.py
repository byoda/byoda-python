'''
Class for BYO.Tube Lite accounts


:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2024
:license    : GPLv3
'''

from uuid import UUID
from uuid import uuid4
from typing import Self
from hashlib import sha256
from datetime import UTC
from datetime import datetime

from pydantic import BaseModel
from pydantic import EmailStr
from pydantic import SecretStr
from pydantic import Field
from pydantic import HttpUrl

from byoda import config

from byotubesvr.auth.password import hash_password
from byotubesvr.database.sql import SqlStorage


class LiteAuthApiModel(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8, max_length=128)


class LiteAuthApiResponseModel(BaseModel):
    auth_token: str


class LiteAppAuthApiResponseModel(BaseModel):
    auth_token: str
    token_type: str
    app_id: UUID


class LiteStatusApiResponseModel(BaseModel):
    status: str
    is_funded: bool
    balance_points: int


class LiteAccountApiModel(BaseModel):
    email: EmailStr
    password: SecretStr = Field(min_length=8, max_length=128)
    handle: str | None = None


class LiteAccountApiResponseModel(BaseModel):
    lite_id: UUID
    email: EmailStr
    verification_url: HttpUrl

    @staticmethod
    def from_sql_model(sql_model, verification_url: str) -> Self:
        '''
        Create an API response model from a SQL model
        '''

        verification_token: str = sql_model.generate_verification_token()
        return LiteAccountApiResponseModel(
            lite_id=sql_model.lite_id,
            email=sql_model.email,
            verification_url=(
                f'{verification_url}?lite_id={sql_model.lite_id}'
                f'&token={verification_token}'
            )
        )


class LiteAccountVerifyModel(BaseModel):
    pass


class LiteAccountSqlModel:
    STMTS: dict[str, str] = {
        'create': '''
     CREATE TABLE IF NOT EXISTS accounts(
        lite_id uuid DEFAULT gen_random_uuid() PRIMARY KEY,
        email TEXT NOT NULL,
        handle TEXT,
        hashed_password TEXT NOT NULL,
        is_enabled BOOL DEFAULT FALSE,
        is_funded BOOL DEFAULT FALSE,
        created_timestamp TIMESTAMP WITHOUT TIME ZONE DEFAULT CURRENT_TIMESTAMP,
        nickname TEXT,
        UNIQUE(email),
        UNIQUE(nickname),
        UNIQUE(handle),
        CONSTRAINT c_lowercase_email CHECK (((email)::TEXT = LOWER((email)::TEXT)))
    );
    CREATE INDEX IF NOT EXISTS account_email_index ON accounts(email);
    CREATE INDEX IF NOT EXISTS account_handle_index ON accounts(handle);
''',
        'drop': '''
        DROP TABLE IF EXISTS accounts CASCADE;
''',
        'query': '''
    SELECT * FROM accounts WHERE lite_id = %(lite_id)s;
''',
        'query_by_email': '''
    SELECT * FROM accounts WHERE email = %(email)s;
''',
        'query_all': '''
    SELECT * FROM accounts;
''',
        'upsert': '''
    INSERT INTO accounts(lite_id, email, handle, hashed_password, is_enabled, is_funded, nickname)
    VALUES (%(lite_id)s, %(email)s, %(handle)s, %(hashed_password)s, %(is_enabled)s, %(is_funded)s, %(nickname)s)
    ON CONFLICT(lite_id) DO UPDATE SET email = %(email)s, handle = %(handle)s, hashed_password = %(hashed_password)s, is_enabled = %(is_enabled)s, is_funded = %(is_funded)s, nickname = %(nickname)s
''',
        'delete': '''
    DELETE FROM accounts WHERE lite_id = %(lite_id)s;
''',
    }

    def __init__(self, lite_db: SqlStorage, lite_id: UUID, email: str,
                 hashed_password: str, handle: str, is_enabled: bool | None,
                 is_funded: bool | None, nickname: str | None,
                 created_timestamp: datetime | None = None) -> None:
        '''
        Constructor

        :param lite_db: The SQL database to use
        :param lite_id:
        :param email:
        :param hashed_password:
        :param handle: unqiue alphanumeric value to identify the account
        :param is_enabled:
        :param is_funded:
        :param nickname:
        '''

        self.lite_db: SqlStorage = lite_db

        self.lite_id: UUID = lite_id
        self.email: str = email
        self.handle: str = handle or None

        self.hashed_password: str = hashed_password
        self.is_enabled: bool = is_enabled
        self.is_funded: bool = is_funded
        self.nickname: str | None = nickname
        self.created_timestamp: datetime = \
            created_timestamp or datetime.now(tz=UTC)

    def as_dict(self, with_values_only: bool = True
                ) -> dict[str, UUID | str | int | bool | None]:
        data: dict[str, any] = {}
        fields: list[str] = [
            'lite_id', 'email', 'handle', 'hashed_password', 'is_enabled',
            'is_funded', 'nickname', 'created_timestamp'
        ]
        for key in fields:
            value: any | None = getattr(self, key, None)
            if not with_values_only or value:
                data[key] = value

        return data

    @staticmethod
    def from_dict(data, lite_db: SqlStorage | None = None) -> Self:
        '''
        Create a new instance from a dictionary
        '''

        lite = LiteAccountSqlModel(
            lite_db=lite_db, lite_id=data['lite_id'], email=data['email'],
            hashed_password=data['hashed_password'], handle=data['handle'],
            is_enabled=data['is_enabled'], is_funded=data['is_funded'],
            nickname=data['nickname'],
            created_timestamp=data['created_timestamp']
        )

        return lite

    @staticmethod
    def from_api_model(data: LiteAccountApiModel,
                       lite_db: SqlStorage | None = None) -> Self:
        '''
        Create a new instance from an API model

        This function only associates the account with SQL storage but can not
        and does not persist it because the API model does not contain the
        lite_id field.

        :param data: The API model
        :param lite_db: The SQL database to associate the LiteAccountSqlModel
        with
        :returns: The new instance
        '''

        if data.handle is None:
            data.handle = data.email

        lite = LiteAccountSqlModel(
            lite_db=lite_db,
            lite_id=uuid4(),
            email=data.email.lower(),
            hashed_password=hash_password(data.password.get_secret_value()),
            handle=data.handle,
            is_enabled=None,
            is_funded=False,
            nickname=None,
            created_timestamp=datetime.now(tz=UTC)
        )

        return lite

    @staticmethod
    async def create_table(lite_db: SqlStorage) -> None:
        '''
        Create the accounts table

        :param lite_db: The SQL database to use
        '''

        await lite_db.query(LiteAccountSqlModel.STMTS['create'], {})

    @staticmethod
    async def drop_table(lite_db: SqlStorage) -> None:
        '''
        Drop the accounts table

        :param lite_db: The SQL database to use
        :returns:
        :raises: ValueError if config.debug is not set
        '''

        if not config.debug:
            raise ValueError('Not dropping the accounts table!')

        await lite_db.query('DROP TABLE IF EXISTS accounts;', {})

    @staticmethod
    async def create(email: str, password: str, handle: str,
                     lite_db: SqlStorage | None = None) -> Self:
        '''
        Create a new account

        :param email: The email address
        :param password: The password
        :param handle: The handle
        :param lite_db: The SQL database to use, if specified
        '''

        if len(password) < 8:
            raise ValueError('Password must be at least 8 characters')

        lite_id: UUID = uuid4()

        hashed_password: str = hash_password(password)

        lite = LiteAccountSqlModel(
            lite_db=lite_db, lite_id=lite_id, email=email,
            hashed_password=hashed_password, handle=handle,
            is_enabled=False, is_funded=False, nickname=None,
            created_timestamp=datetime.now(tz=UTC)
        )
        if lite_db:
            await lite.persist(lite_db, all_fields=True)

        return lite

    @staticmethod
    async def from_db(lite_db: SqlStorage, lite_id: UUID | str | None = None
                      ) -> Self | list[Self] | None:
        '''
        Load one account or all accounts from the database

        :param lite_id: The lite_id of the account
        '''

        if lite_id and not isinstance(lite_id, UUID):
            lite_id = UUID(lite_id)

        if lite_id:
            data: dict = await lite_db.query(
                LiteAccountSqlModel.STMTS['query'], {'lite_id': lite_id},
                fetch_some=False
            )
            lite: LiteAccountSqlModel = LiteAccountSqlModel.from_dict(
                data, lite_db
            )
            return lite
        else:
            data: list[dict] = await lite_db.query(
                LiteAccountSqlModel.STMTS['query_all'], {},
                fetch_some=True
            )
            results: list[LiteAccountSqlModel] = []
            for item in data:
                lite = LiteAccountSqlModel.from_dict(item, lite_db)
                results.append(lite)

            return results

    @staticmethod
    async def from_db_by_email(lite_db: SqlStorage, email: str) -> Self | None:
        '''
        Load one account or all accounts from the database

        :param lite_id: The lite_id of the account
        '''

        data: dict = await lite_db.query(
            LiteAccountSqlModel.STMTS['query_by_email'], {'email': email},
            fetch_some=False
        )
        if not data:
            return None

        lite: LiteAccountSqlModel = LiteAccountSqlModel.from_dict(
            data, lite_db
        )
        return lite

    async def persist(self, lite_db: SqlStorage | None = None,
                      all_fields: bool = False) -> None:
        '''
        Persist the account to the database. This function
        performs an upsert, meaning that if an account with the lite_id
        does exist, it will be updated. If it does not exist, it will be
        created.

        When updating an existing account and the all_fields parameter is
        False then it will only update the fields that are not None. This
        allows you to set fields to None to indicate that they should
        not be updated.

        :param lite_db: The SQL database to use
        :param all_fields: Should all fields be persisted or only the fields
        that have a value that is not None
        '''

        if not lite_db:
            if not self.lite_db:
                raise ValueError('No SQL database specified')
            lite_db = self.lite_db

        if all_fields:
            await lite_db.query(
                self.STMTS['upsert'], self.as_dict(with_values_only=False)
            )
            return

        data: dict[str, any] = self.as_dict(with_values_only=True)

        if not data:
            raise ValueError('No data to persist')

        # We have to generate the SQL query dynamically as we can only
        # specify the fields we plan to update
        query: str = 'INSERT INTO accounts('
        for field in data:
            query += field + ', '

        query = query[:-2] + ') VALUES('
        for field in data:
            query += f'%({field})s, '

        query = query[:-2] + ') ON CONFLICT(lite_id) DO UPDATE SET '

        for field in data:
            if field != 'lite_id':
                query += f'{field} = %({field})s, '

        query = query[:-2]

        await lite_db.query(query, data)

    async def delete(self) -> None:
        '''
        Delete the account from the database
        '''

        await self.lite_db.query(
            self.STMTS['delete'], {'lite_id': self.lite_id}
        )

    def generate_verification_token(self) -> str:
        '''
        Generate a verification URL for the account
        '''

        code: str = sha256(
            f'{self.lite_id}_{self.email}'.encode('utf-8')
        ).hexdigest()

        return code
