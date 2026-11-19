'''
Classes for data filters for filtering results a Data API query based
on the filter conditions defined in the query

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023, 2024, 2025, 2026
:license    : GPLv3
'''

import re

from uuid import UUID
from typing import Self
from datetime import UTC
from datetime import date
from datetime import time
from datetime import datetime
from logging import Logger
from logging import getLogger

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from dateutil import parser as iso8601_parser

from byoda.datamodel.dataclass import SchemaDataScalar
from byoda.datamodel.dataclass import SchemaDataObject
from byoda.datamodel.dataclass import SchemaDataArray

from byoda.datatypes import AnyScalarType
from byoda.datamodel.filter_expression import (
    Predicate,
    Group,
    Not,
    parse_filter,
    validate_filter_structure,
)

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)


class DataFilter:
    '''
    Implements the logic to support filters in Data queries
    '''

    __slots__: list[str] = [
        'field', 'operator', 'value', 'compare_functions', 'sql_functions'
    ]

    def __init__(self, field: str, operator: str) -> None:
        '''
        Base class for data filters for strings, UUIDs, datetimes and numbers
        '''

        if not isinstance(operator, str):
            raise ValueError(
                f'Operator {operator} is a {type(operator)} instead of str'
            )

        self.field: str = field
        self.operator: str = operator
        self.value: str | None = None
        self.compare_functions: dict[str, callable] = {}
        self.sql_functions: dict[str, callable] = {}

    def __str__(self) -> str:
        if type(self.value) in (str, UUID, datetime, date, time):
            return f"{self.operator} '{self.value}'"
        return f'{self.operator} {self.value}'

    @staticmethod
    def create(field: str, operator: str,
               value: str | int | float | UUID | datetime | date | time,
               data_class: SchemaDataScalar = None) -> Self:
        '''
        Factory for classes derived from DataFilter
        '''

        if ((data_class and data_class.python_type == 'UUID')
                or isinstance(value, UUID)):
            return UuidDataFilter(field, operator, value)

        date_types: tuple[str] = ('datetime', 'time', 'date')
        if ((data_class and data_class.python_type in date_types)
                or type(value) in (datetime, date, time)):
            return DateTimeDataFilter(field, operator, value)

        if isinstance(value, str):
            return StringDataFilter(field, operator, value)

        if type(value) in (int, float):
            return NumberDataFilter(field, operator, value)

        if type(value) in (datetime, date, time):
            return DateTimeDataFilter(field, operator, value)

        raise ValueError(f'Value has type {type(value)}')

    def compare(self, data: str | int | float | UUID | datetime | date | time
                ) -> bool:
        '''
        Compares the data against the value for the filter
        '''

        compare_function: list[callable] = \
            self.compare_functions[self.operator]

        return compare_function(data)

    def sql_filter(self, where: bool = False, is_meta_filter: bool = False,
                   placeholder_function: callable = None,
                   parameter_name: str | None = None
                   ) -> tuple[str, str, str | int | float]:
        '''
        Gets the SQL verb clause for the filter

        Returns tuple of the comparison operator annd the value
        '''

        compare_function: callable = self.sql_functions[self.operator]

        if is_meta_filter:
            return compare_function(
                f'{self.field}', where, is_meta_filter=is_meta_filter,
                placeholder_function=placeholder_function,
                parameter_name=parameter_name
            )
        else:
            return compare_function(
                f'_{self.field}', where, is_meta_filter=is_meta_filter,
                placeholder_function=placeholder_function,
                parameter_name=parameter_name
            )

    def sql_field_placeholder(self, field: str, where: bool = False,
                              is_meta_filter: bool = False,
                              parameter_name: str | None = None) -> str:
        '''
        Returns string to be used for the named placeholder for SqlLite,
        ie. '_created_timestamp' becomes ':_created_timestamp'

        If the 'where' parameter is True, then ':_where_created_timestamp'
        will be returned

        '''

        if parameter_name is not None:
            return parameter_name

        if is_meta_filter:
            if where:
                return f'_METAWHERE{field}'
            else:
                return f'META{field}'
        else:
            if where:
                return f'_WHERE{field}'
            else:
                return f'{field}'


class StringDataFilter(DataFilter):
    def __init__(self, field: str, operator: str, value: str) -> None:
        super().__init__(field, operator)

        if value is None:
            raise ValueError('Must provide a value to match against')
        elif not isinstance(value, str):
            raise ValueError(
                f'Value {value} is a {type(value)} instead of a str'
            )

        self.value: str = value

        self.compare_functions = {
            'eq': self.eq,
            'ne': self.ne,
            'vin': self.vin,
            'nin': self.nin,
            'regex': self.regex,
            'glob': self.glob,
        }

        self.sql_functions = {
            'eq': self.sql_eq,
            'ne': self.sql_ne,
            'vin': self.sql_vin,
            'nin': self.sql_nin,
            'regex': self.sql_regex,
            'glob': self.sql_glob,
        }

    def eq(self, data: str) -> bool:
        '''
        equal operator
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: str) -> bool:
        '''
        not-equal operator, NULL values are not equal to any value
        '''

        if data is None:
            return True

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def vin(self, data: str) -> bool:
        '''
        value-in operator ('in' can not be used as it is a Python keyword)
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data in self.value

    def nin(self, data: str) -> bool:
        '''
        not-in operator
        '''
        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data not in self.value

    def regex(self, data: str) -> bool:
        '''
        regex operator
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        res = re.match(self.value, data)
        return bool(res)

    def glob(self, data: str) -> bool:
        '''
        glob matching
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        regex = _glob2regex(self.value)
        res = re.match(regex, data)
        return bool(res)

    def sql_eq(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None
               ) -> tuple[str, str, str]:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)
        return (
            f'{sql_field} = {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_ne(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None
               ) -> tuple[str, str, str]:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'({sql_field} != {field_placeholder} OR {sql_field} IS NULL)',
            sql_field_placeholder, self.value
        )

    def sql_vin(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False,
                placeholder_function: callable = None,
                parameter_name: str | None = None
                ) -> tuple[str, str, str]:
        '''

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        SQL code for 'IN' operator
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} IN {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_nin(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False,
                placeholder_function: callable = None,
                parameter_name: str | None = None
                ) -> tuple[str, str, str]:
        '''
        SQL code for 'NOT IN' operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} NOT IN {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_regex(self, sql_field: str, where: bool = False,
                  is_meta_filter: bool = False,
                  placeholder_function: callable = None,
                  parameter_name: str | None = None
                  ) -> tuple[str, str, str]:
        '''
        SQL code for regular expression operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} ~ {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_glob(self, sql_field: str, where: bool = False,
                 is_meta_filter: bool = False,
                 placeholder_function: callable = None,
                 parameter_name: str | None = None
                 ) -> tuple[str, str, str]:
        '''
        SQL code for glob operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} GLOB {field_placeholder}',
            sql_field_placeholder, self.value
        )


class NumberDataFilter(DataFilter):
    '''
    Class for filters for numbers as ints or floats
    '''
    def __init__(self, field: str, operator: str, value: int | float) -> None:
        super().__init__(field, operator)

        if value is None:
            raise ValueError('Must provide a value to match against')
        elif type(value) not in (int, float):
            raise ValueError(
                f'Value {value} is a {type(value)} instead of a number'
            )

        self.value: int | float = value

        self.compare_functions = {
            'eq': self.eq,
            'ne': self.ne,
            'gt': self.gt,
            'lt': self.lt,
            'egt': self.egt,
            'elt': self.elt,
        }

        self.sql_functions = {
            'eq': self.sql_eq,
            'ne': self.sql_ne,
            'gt': self.sql_gt,
            'lt': self.sql_lt,
            'egt': self.sql_egt,
            'elt': self.sql_elt,
        }

    def eq(self, data: int | float) -> bool:
        '''
        equal operator
        '''

        if type(data) not in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: int | float) -> bool:
        '''
        not-equal operator, NULL values are not equal to any value
        '''

        if data is None:
            return True

        if type(data) not in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def gt(self, data: int | float) -> bool:
        '''
        greater-than operator
        '''

        if type(data) not in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data > self.value

    def lt(self, data: int | float) -> bool:
        '''
        less-than operator
        '''

        if type(data) not in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data < self.value

    def egt(self, data: int | float) -> bool:
        '''
        equal-or-greater operator
        '''

        if type(data) not in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data >= self.value

    def elt(self, data: int | float) -> bool:
        '''
        equal or lesser operator
        '''

        if type(data) not in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data < self.value

    def sql_eq(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None
               ) -> tuple[str, str, int | float]:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} = {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_ne(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None) -> tuple[str, str, str]:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'({sql_field} != {field_placeholder} OR {sql_field} IS NULL)',
            sql_field_placeholder, self.value
        )

    def sql_gt(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None) -> tuple[str, str, str]:
        '''
        SQL code for greater-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} > {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_lt(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None) -> tuple[str, str, str]:
        '''
        SQL code for less-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} < {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_egt(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False,
                placeholder_function: callable = None,
                parameter_name: str | None = None) -> tuple[str, str, str]:
        '''
        SQL code for equal-or-greater-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} >= {field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_elt(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False,
                placeholder_function: callable = None,
                parameter_name: str | None = None) -> tuple[str, str, str]:
        '''
        SQL code for equal-or-less-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} <= {field_placeholder}',
            sql_field_placeholder, self.value
        )


class UuidDataFilter(DataFilter):
    def __init__(self, field: str,  operator: str, value: UUID) -> None:
        super().__init__(field, operator)

        if not value:
            raise ValueError('Must provide a value to match against')
        elif isinstance(value, str):
            value = UUID(value)
        elif not isinstance(value, UUID):
            raise ValueError(
                f'Value {value} is a {type(value)} instead of a UUID'
            )

        self.value: UUID = value

        self.compare_functions = {
            'eq': self.eq,
            'ne': self.ne,
        }

        self.sql_functions = {
            'eq': self.sql_eq,
            'ne': self.sql_ne,
        }

    def eq(self, data: UUID) -> bool:
        '''
        equal operator
        '''

        if isinstance(data, str):
            data = UUID(data)

        if not isinstance(data, UUID):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: UUID) -> bool:
        '''
        not-equal operator, NULL values are not equal to any value
        '''

        if data is None:
            return True

        if not isinstance(data, UUID):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def sql_eq(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None
               ) -> tuple[str, str, str]:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} = {field_placeholder}',
            sql_field_placeholder, str(self.value)
        )

    def sql_ne(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None
               ) -> tuple[str, str, str]:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'({sql_field} != {field_placeholder} OR {sql_field} IS NULL)',
            sql_field_placeholder, str(self.value)
        )


class DateTimeDataFilter(DataFilter):
    OPERATORS: list[str] = [
        'at', 'nat', 'after', 'before', 'atbefore', 'atafter'
    ]

    def __init__(self, field: str,
                 operator: str, value: datetime | date | time | int | float
                 ) -> None:
        super().__init__(field, operator)

        if isinstance(value, str):
            value = iso8601_parser.parse(value)
        elif isinstance(value, (int, float)):
            value = datetime.fromtimestamp(value, tz=UTC)
        elif type(value) not in (datetime, date, time):
            raise ValueError(
                f'Value {value} is a {type(value)} instead of a datetime, '
                'date or time'
            )
        self.value: datetime | date | time = value

        self.compare_functions = {
            'at': self.at,
            'nat': self.nat,
            'after': self.after,
            'before': self.before,
            'atafter': self.atafter,
            'atbefore': self.atbefore,
        }

        self.sql_functions = {
            'at': self.sql_at,
            'nat': self.sql_nat,
            'after': self.sql_after,
            'before': self.sql_before,
            'atafter': self.sql_atafter,
            'atbefore': self.sql_atbefore,
        }

    def at(self, data: str | datetime | date | time | int | float) -> bool:
        '''
        Datetime/date/time at comparison
        '''

        data = self._adapt_date_type(data)

        return data == self.value

    def nat(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time not-at comparison
        '''

        data = self._adapt_date_type(data)

        return data != self.value

    def after(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time after comparison
        '''

        data = self._adapt_date_type(data)

        return data > self.value

    def before(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time before comparison
        '''

        data = self._adapt_date_type(data)

        return data < self.value

    def atafter(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time at-or-after comparison
        '''

        data = self._adapt_date_type(data)

        return data >= self.value

    def atbefore(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time at or before comparison
        '''

        data = self._adapt_date_type(data)

        return data <= self.value

    def _adapt_date_type(self, data: datetime | date | time | str | int | float
                         ) -> datetime | date | time:
        '''
        Adapts the provided value to the type of the value of the filter
        '''

        if isinstance(data, str):
            if isinstance(self.value, datetime):
                data = datetime.fromisoformat(data)
            elif isinstance(self.value, date):
                data = date.fromisoformat(data)
            elif isinstance(self.value, time):
                data = time.fromisoformat(data)
            else:
                raise ValueError(f'Unexpected type of operator: {self.value}')
        elif type(data) in (int, float):
            data = datetime.fromtimestamp(data, tz=UTC)

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data

    def _get_sql_date_type(self) -> int | float:
        '''
        '''

        timestamp: float
        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int) or isinstance(self.value, float):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        return timestamp

    def sql_at(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False,
               placeholder_function: callable = None,
               parameter_name: str | None = None
               ) -> tuple[str, str, float]:
        '''
        Compare date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp: int | float = self._get_sql_date_type()

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} = {field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_nat(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False,
                placeholder_function: callable = None,
                parameter_name: str | None = None
                ) -> tuple[str, str, float]:
        '''
        Compare not equal date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp: int | float = self._get_sql_date_type()

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        # return (
        #     f'round({sql_field}, 5) != {field_placeholder}',
        #     sql_field_placeholder, round(timestamp, 5)
        # )

        return (
            f'{sql_field} != {field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_after(self, sql_field: str, where: bool = False,
                  is_meta_filter: bool = False,
                  placeholder_function: callable = None,
                  parameter_name: str | None = None
                  ) -> tuple[str, str, float]:
        '''
        Compare after date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp: int | float = self._get_sql_date_type()

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        # return (
        #     f'round({sql_field}, 5) > {field_placeholder}',
        #     sql_field_placeholder, round(timestamp, 5)
        # )
        return (
            f'{sql_field} > {field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_before(self, sql_field: str, where: bool = False,
                   is_meta_filter: bool = False,
                   placeholder_function: callable = None,
                   parameter_name: str | None = None
                   ) -> tuple[str, str, float]:
        '''
        Datetime/date/time before comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp: int | float = self._get_sql_date_type()

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        # return (
        #     f'round({sql_field}, 5) < {field_placeholder}',
        #     sql_field_placeholder, round(timestamp, 5)
        # )

        return (
            f'{sql_field} < {field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_atafter(self, sql_field: str, where: bool = False,
                    is_meta_filter: bool = False,
                    placeholder_function: callable = None,
                    parameter_name: str | None = None
                    ) -> tuple[str, str, float]:
        '''
        Datetime/date/time at-or-after comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp: int | float = self._get_sql_date_type()

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)

        return (
            f'{sql_field} >= {field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_atbefore(self, sql_field: str, where: bool = False,
                     is_meta_filter: bool = False,
                     placeholder_function: callable = None,
                     parameter_name: str | None = None
                     ) -> tuple[str, str, float]:
        '''
        Datetime/date/time at or before comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp: int | float = self._get_sql_date_type()

        sql_field_placeholder: str = self.sql_field_placeholder(
            sql_field, where, is_meta_filter, parameter_name
        )

        field_placeholder: str = placeholder_function(sql_field_placeholder)


        return (
            f'{sql_field} <= {field_placeholder}',
            sql_field_placeholder, timestamp
        )


class DataFilterSet:
    '''One comparison or an explicit nested read expression.'''

    def __init__(
        self,
        filters: object | dict,
        data_class: SchemaDataObject | SchemaDataArray = None,
        is_meta_filter: bool = False,
    ) -> None:
        validate_filter_structure(filters)
        self.is_meta_filter = is_meta_filter
        self.data_class = (
            data_class.referenced_class
            if isinstance(data_class, SchemaDataArray)
            else data_class
        )

        def make_comparison(field, operator, value):
            item = None
            if self.data_class and not is_meta_filter:
                if field not in self.data_class.fields:
                    raise ValueError(f'Unknown filter field: {field}')
                item = self.data_class.fields[field]
            comparison = DataFilter.create(field, operator, value, item)
            if operator not in comparison.compare_functions:
                raise ValueError(
                    f'Unsupported operator {operator} for {field}'
                )
            return comparison

        self.root = parse_filter(filters, make_comparison)

    @property
    def has_predicates(self) -> bool:
        return self.root is not None

    @property
    def has_logical_groups(self) -> bool:
        return isinstance(self.root, (Group, Not))

    @property
    def filters(self):
        '''
        A single-predicate compatibility view; groups cannot be flattened.
        '''
        if self.has_logical_groups:
            raise ValueError('Use the expression root instead of flat filters')
        if self.root is None:
            return {}
        comparison = self.root.comparison
        return {comparison.field: [comparison]}

    def __bool__(self):
        return self.has_predicates

    def require_single(self, required=True):
        if self.has_logical_groups or (required and not self.has_predicates):
            raise ValueError('This operation requires one comparison')

    def matches(self, record) -> bool:
        return self.root is None or self.root.matches(record)

    def __str__(self) -> str:
        return str(self.root) if self.root else ''

    @staticmethod
    def from_data_class_data(
        data_class: SchemaDataObject, data: dict[str, object]
    ) -> Self:
        '''
        Factory for a DataFilterSet based on the values in the data
        for the fields that are required by the data_class

        :param data_class:
        :param data:
        :returns: DataFilterSet
        :raises: ValueError if none of the required fields is present in
        the data
        '''

        required_fields: list[str] = data_class.required_fields

        filter_data: dict[str, dict[str, AnyScalarType]] = {}

        field: str
        for field in required_fields:
            if field in data:
                data_class_item: SchemaDataScalar = data_class.fields[field]
                filter_data[field] = {
                    data_class_item.equal_operator: data[field]
                }
            else:
                _LOGGER.debug(
                    f'Required field {field} not present in data: {data}'
                )

        if len(filter_data) == 0:
            raise ValueError('No required fields present in data')

        predicates = [
            {field: condition} for field, condition in filter_data.items()
        ]
        expression = (
            predicates[0] if len(predicates) == 1 else {'$and': predicates}
        )
        return DataFilterSet(expression, data_class)

    def sql_expression(
        self, placeholder_function: callable, namespace: str = 'df'
    ) -> tuple[str, dict]:
        values = {}

        def compile_node(node):
            if isinstance(node, Predicate):
                name = f'{namespace}_{len(values)}'
                text, key, value = node.comparison.sql_filter(
                    where=True,
                    is_meta_filter=self.is_meta_filter,
                    placeholder_function=placeholder_function,
                    parameter_name=name,
                )
                values[key] = value
                return text
            if isinstance(node, Not):
                # A comparison against NULL is unknown in SQL; treat it as
                # false so that negating it matches the row
                return f'NOT COALESCE({compile_node(node.child)}, FALSE)'
            operator = ' AND ' if node.operator == '$and' else ' OR '
            return (
                '('
                + operator.join(compile_node(child) for child in node.children)
                + ')'
            )

        return (compile_node(self.root), values) if self.root else ('', {})

    def sql_where_clause(
        self, placeholder_function: callable
    ) -> tuple[str, dict]:
        expression, values = self.sql_expression(placeholder_function)
        return ('WHERE ' + expression, values) if expression else ('', {})

    @staticmethod
    def filter(
        filter_set, data: list[dict[str, object]], data_class: SchemaDataObject
    ) -> list[object]:
        if not isinstance(filter_set, DataFilterSet):
            filter_set = DataFilterSet(filter_set, data_class)
        return [item for item in data if filter_set.matches(item)]

    @staticmethod
    def filter_exclude(filters, data: list) -> tuple[list, list]:
        filter_set = (
            filters
            if isinstance(filters, DataFilterSet)
            else DataFilterSet(filters)
        )
        remaining, removed = [], []
        for item in data:
            (removed if filter_set.matches(item) else remaining).append(item)
        return remaining, removed


def _glob2regex(value: str) -> str:
    '''
    Converts a glob pattern to a regular expression

    Only supports '?' and '*' pattern-matches
    '''

    i: int
    n: int
    i, n = 0, len(value)
    res = '^'
    while i < n:
        c: str = value[i]
        i = i+1
        if c == '*':
            res: str = res + '.*'
        elif c == '?':
            res = res + '.'
        else:
            res = res + re.escape(c)

    return res + '$'
