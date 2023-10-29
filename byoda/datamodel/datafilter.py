'''
Classes for data filters for filtering results a Data API query based
on the filter conditions defined in the query

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re
from logging import getLogger

from uuid import UUID
from datetime import datetime, date, time, timezone

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from dateutil import parser as iso8601_parser

from byoda.datamodel.dataclass import SchemaDataScalar
from byoda.datamodel.dataclass import SchemaDataObject
from byoda.datamodel.dataclass import SchemaDataArray

from byoda.datatypes import AnyScalarType

from byoda.util.logger import Logger

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)


class DataFilter:
    '''
    Implements the logic to support filters in Data queries
    '''

    __slots__ = [
        'field', 'operator', 'value', 'compare_functions', 'sql_functions'
    ]

    def __init__(self, field: str, operator: str):
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

    def __str__(self):
        if type(self.value) in (str, UUID, datetime, date, time):
            return f"{self.operator} '{self.value}'"
        return f'{self.operator} {self.value}'

    @staticmethod
    def create(field: str, operator: str,
               value: str | int | float | UUID | datetime | date | time,
               data_class: SchemaDataScalar = None):
        '''
        Factory for classes derived from DataFilter
        '''

        if ((data_class and data_class.python_type == 'UUID')
                or isinstance(value, UUID)):
            return UuidDataFilter(field, operator, value)

        date_types = ('datetime', 'time', 'date')
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

        compare_function = self.compare_functions[self.operator]
        return compare_function(data)

    def sql_filter(self, where: bool = False, is_meta_filter: bool = False
                   ) -> tuple[str, str, str | int | float]:
        '''
        Gets the SQL verb clause for the filter

        Returns tuple of the comparison operator annd the value
        '''
        compare_function: callable = self.sql_functions[self.operator]

        if is_meta_filter:
            return compare_function(
                f'{self.field}', where, is_meta_filter=is_meta_filter
            )
        else:
            return compare_function(
                f'_{self.field}', where, is_meta_filter=is_meta_filter
            )

    def sql_field_placeholder(self, field: str, where: bool = False,
                              is_meta_filter: bool = False) -> str:
        '''
        Returns string to be used for the named placeholder for SqlLite,
        ie. '_created_timestamp' becomes ':_created_timestamp'

        If the 'where' parameter is True, then ':_where_created_timestamp'
        will be returned

        '''

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
    def __init__(self, field: str, operator: str, value: str):
        super().__init__(field, operator)

        if not isinstance(value, str):
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
        not-equal operator
        '''

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
               is_meta_filter: bool = False) -> str:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_ne(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> str:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_vin(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False) -> str:
        '''

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        SQL code for 'IN' operator
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} IN :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_nin(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False) -> str:
        '''
        SQL code for 'NOT IN' operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} NOT IN :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_regex(self, sql_field: str, where: bool = False,
                  is_meta_filter: bool = False) -> str:
        '''
        SQL code for regular expression operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} ~ :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_glob(self, sql_field: str, where: bool = False,
                 is_meta_filter: bool = False) -> str:
        '''
        SQL code for glob operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} GLOB :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )


class NumberDataFilter(DataFilter):
    '''
    Class for filters for numbers as ints or floats
    '''
    def __init__(self, field: str, operator: str, value: int | float):
        super().__init__(field, operator)

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

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: int | float) -> bool:
        '''
        not-equal operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def gt(self, data: int | float) -> bool:
        '''
        greater-than operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data > self.value

    def lt(self, data: int | float) -> bool:
        '''
        less-than operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data < self.value

    def egt(self, data: int | float) -> bool:
        '''
        equal-or-greater operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data >= self.value

    def elt(self, data: int | float) -> bool:
        '''
        equal or lesser operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data < self.value

    def sql_eq(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> tuple[str, str, int | float]:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_ne(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> str:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_gt(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> str:
        '''
        SQL code for greater-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} > :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_lt(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> str:
        '''
        SQL code for less-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} < :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_egt(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False) -> str:
        '''
        SQL code for equal-or-greater-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} >= :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_elt(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False) -> str:
        '''
        SQL code for equal-or-less-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} <= :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )


class UuidDataFilter(DataFilter):
    def __init__(self, field: str,  operator: str, value: UUID):
        super().__init__(field, operator)

        if isinstance(value, str):
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
        not-equal operator
        '''

        if not isinstance(data, UUID):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def sql_eq(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> tuple[str, str, str]:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, str(self.value)
        )

    def sql_ne(self, sql_field: str, where: bool = False,
               is_meta_filter: bool = False) -> tuple[str, str, str]:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, str(self.value)
        )


class DateTimeDataFilter(DataFilter):
    OPERATORS: list[str] = [
        'at', 'nat', 'after', 'before', 'atbefore', 'atafter'
    ]

    def __init__(self, field: str,
                 operator: str, value: datetime | date | time | int | float):
        super().__init__(field, operator)

        if isinstance(value, str):
            value = iso8601_parser.parse(value)
        elif isinstance(value, (int, float)):
            value = datetime.fromtimestamp(value, tz=timezone.utc)
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
            if isinstance(self.value) == datetime:
                data = datetime.fromisoformat(data)
            elif isinstance(self.value) == date:
                data = date.fromisoformat(data)
            elif isinstance(self.value) == time:
                data = time.fromisoformat(data)
            else:
                raise ValueError(f'Unexpected type of operator: {self.value}')
        elif type(data) in (int, float):
            data = datetime.fromtimestamp(data, tz=timezone.utc)

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
               is_meta_filter: bool = False) -> tuple[str, str, float]:
        '''
        Compare date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp = self._get_sql_date_type()

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'round({sql_field}, 5) = :{sql_field_placeholder}',
            sql_field_placeholder, round(timestamp, 5)
        )

    def sql_nat(self, sql_field: str, where: bool = False,
                is_meta_filter: bool = False) -> tuple[str, str, float]:
        '''
        Compare not equal date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp = self._get_sql_date_type()

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'round({sql_field}, 5) != :{sql_field_placeholder}',
            sql_field_placeholder, round(timestamp, 5)
        )

    def sql_after(self, sql_field: str, where: bool = False,
                  is_meta_filter: bool = False) -> tuple[str, str, float]:
        '''
        Compare after date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp = self._get_sql_date_type()

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'round({sql_field}, 5) > :{sql_field_placeholder}',
            sql_field_placeholder, round(timestamp, 5)
        )

    def sql_before(self, sql_field: str, where: bool = False,
                   is_meta_filter: bool = False) -> tuple[str, str, float]:
        '''
        Datetime/date/time before comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp = self._get_sql_date_type()

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'round({sql_field}, 5) < :{sql_field_placeholder}',
            sql_field_placeholder, round(timestamp, 5)
        )

    def sql_atafter(self, sql_field: str, where: bool = False,
                    is_meta_filter: bool = False) -> tuple[str, str, float]:
        '''
        Datetime/date/time at-or-after comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp = self._get_sql_date_type()

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'round({sql_field}, 5) >= :{sql_field_placeholder}',
            sql_field_placeholder, round(timestamp, 5)
        )

    def sql_atbefore(self, sql_field: str, where: bool = False,
                     is_meta_filter: bool = False) -> tuple[str, str, float]:
        '''
        Datetime/date/time at or before comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        timestamp = self._get_sql_date_type()

        sql_field_placeholder = self.sql_field_placeholder(
            sql_field, where, is_meta_filter
        )

        return (
            f'round({sql_field}, 5) <= :{sql_field_placeholder}',
            sql_field_placeholder, round(timestamp, 5)
        )


class DataFilterSet:
    '''
    A data filter set consists of a Dict with keys the name of the field to
    which the filter applies and one or more comparison functions with a value
    to compare against. For example:
    {
        'timestamp': {
            'atbefore': '2022-05-01T01:33:54.78925+00:00'
        },
        'relation': {
            'ne': 'colleague',
            'ne': 'friend'
        }
    }
    When multiple comparison functions are defined for a field then both
    comparison conditions must be true for the data to be included in the
    result
    '''

    @TRACER.start_as_current_span('FilterSet.constructor')
    def __init__(self, filters: object | dict,
                 data_class: SchemaDataObject | SchemaDataArray = None,
                 is_meta_filter: bool = False):
        '''
        :param filters: is an instance of one of the input filters in the
        Strawberry code, generated from the Jinja2 template for the service
        contract. For test cases, we also support filters to be provided as
        dict
        '''

        self.filters: dict[str, list[DataFilter]] = {}

        self.is_meta_filter: bool = is_meta_filter

        self.data_class: SchemaDataObject
        if data_class and isinstance(data_class, SchemaDataArray):
            self.data_class = data_class.referenced_class
        else:
            self.data_class = data_class

        if not filters:
            return

        for field, conditions in filters.items():
            if conditions is None:
                raise ValueError(
                    f'No conditions specified for parameter {field}'
                )

            self.filters[field] = []
            for operator, value in conditions.items():
                if value is None:
                    continue

                data_class_item: SchemaDataScalar | None = None
                if self.data_class and field in self.data_class.fields:
                    data_class_item = self.data_class.fields[field]

                self.filters[field].append(
                    DataFilter.create(
                        field, operator, value, data_class_item
                    )
                )

    def __str__(self) -> str:
        filter_texts: list[str] = []
        for field in self.filters.keys():
            for filter in self.filters[field]:
                filter_texts.append(f'{field} {str(filter)}')

        text = ' and '.join(filter_texts)
        return text

    @staticmethod
    def from_data_class_data(data_class: SchemaDataObject,
                             data: dict[str, object]):
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

        return DataFilterSet(filter_data, data_class)

    def sql_where_clause(self) -> tuple[str, dict[str, str]]:
        '''
        Returns the SQL 'WHERE' clause for the filter set
        '''

        if not self.filters:
            return '', {}

        filter_texts: list[str] = []
        filter_values: dict[str, str | int | float] = {}
        for field in self.filters.keys():
            for filter in self.filters[field]:
                filter_text, sql_placeholder_field, value = filter.sql_filter(
                    where=True, is_meta_filter=self.is_meta_filter
                )

                filter_texts.append(filter_text)
                filter_values[sql_placeholder_field] = value

        text = 'WHERE ' + ' AND '.join(filter_texts)
        return text, filter_values

    @staticmethod
    @TRACER.start_as_current_span('FilterSet.array')
    def filter(filter_set, data: list[dict[str, object]],
               data_class: SchemaDataObject) -> list[object]:
        '''
        Filters the data against the list of filters to include the matching
        data

        :param filters: list of dicts or DataFilterSet to filter content
        :param data: data to filter
        :param data_class: the data class for each item in the data
        :param
        '''

        _LOGGER.debug(f'Applying filters: {filter_set}')

        if not isinstance(filter_set, DataFilterSet):
            filter_set = DataFilterSet(filter_set, data_class)

        results = []
        for item in data:
            include = True
            for field, filters in filter_set.filters.items():
                for filter in filters:
                    if not filter.compare(item[field]):
                        include = False
                        break

            if include:
                results.append(item)

        return results

    @staticmethod
    @TRACER.start_as_current_span('FilterSet.filter_exclude')
    def filter_exclude(filters: list, data: list) -> tuple[list, list]:
        '''
        Filters the data against the list of filters to exclude the matching
        data

        returns: list of items not excluded and list of items excluded
        '''

        filter_set = DataFilterSet(filters)
        remaining = []
        removed = []
        for item in data:
            include = True
            for field, filters in filter_set.filters.items():
                for filter in filters:
                    if filter.compare(item[field]):
                        include = False
                        break

            if include:
                remaining.append(item)
            else:
                removed.append(item)

        return (remaining, removed)


def _glob2regex(value: str) -> str:
    '''
    Converts a glob pattern to a regular expression

    Only supports '?' and '*' pattern-matches
    '''

    i, n = 0, len(value)
    res = '^'
    while i < n:
        c = value[i]
        i = i+1
        if c == '*':
            res = res + '.*'
        elif c == '?':
            res = res + '.'
        else:
            res = res + re.escape(c)

    return res + '$'
