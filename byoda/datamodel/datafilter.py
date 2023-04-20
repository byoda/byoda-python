'''
Classes for data filters for filtering results a GraphQL query based
on the filter conditions defined in the query

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022, 2023
:license    : GPLv3
'''

import re
import logging
from uuid import UUID
from datetime import datetime, date, time

from dateutil import parser as iso8601_parser

_LOGGER = logging.getLogger(__name__)


class DataFilter:
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
        return f'{self.operator} {self.value}'

    @staticmethod
    def create(field: str, operator: str,
               value: str | int | float | UUID | datetime | date | time):
        '''
        Factory for classes derived from DataFilter
        '''

        if isinstance(value, str):
            return StringDataFilter(field, operator, value)

        if isinstance(value, UUID):
            return UuidDataFilter(field, operator, value)

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

    def sql_filter(self, where: bool = False
                   ) -> tuple[str, str, str | int | float]:
        '''
        Gets the SQL verb clause for the filter

        Returns tuple of the comparison operator annd the value
        '''
        compare_function: callable = self.sql_functions[self.operator]
        return compare_function(f'_{self.field}', where)

    def sql_field_placeholder(self, field: str, where: bool = False) -> str:
        '''
        Returns string to be used for the named placeholder for SqlLite,
        ie. '_created_timestamp' becomes ':_created_timestamp'

        If the 'where' parameter is True, then ':_where_created_timestamp'
        will be returned

        '''

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

        return self.value in data

    def nin(self, data: str) -> bool:
        '''
        not-in operator
        '''
        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return self.value not in data

    def regex(self, data: str) -> bool:
        '''
        regex operator
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return re.match(self.value, data)

    def glob(self, data: str) -> bool:
        '''
        Glob matching TODO: find python module for it that doesn't just
        work on files in a directory
        '''

        # TODO: glob text filter
        raise NotImplementedError('Glob matching is not yet supported')

    def sql_eq(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_ne(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_vin(self, sql_field: str, where: bool = False) -> str:
        '''

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        SQL code for 'IN' operator
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} IN :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_nin(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for 'NOT IN' operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} NOT IN :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_regex(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for regular expression operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} ~ :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_glob(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for glob operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        raise NotImplementedError


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

    def sql_eq(self, sql_field: str, where: bool = False
               ) -> tuple[str, str, int | float]:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_ne(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_gt(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for greater-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} > :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_lt(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for less-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} < :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_egt(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for equal-or-greater-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} >= :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )

    def sql_elt(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for equal-or-less-than operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} <= :{sql_field_placeholder}',
            sql_field_placeholder, self.value
        )


class UuidDataFilter(DataFilter):
    def __init__(self, field: str,  operator: str, value: UUID):
        super().__init__(field, operator)

        if not isinstance(value, UUID):
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

    def sql_eq(self, sql_field: str, where: bool = False) -> str:
        '''
        SQL code for equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, str(self.value)
        )

    def sql_ne(self, sql_field: str, where: bool = False
               ) -> tuple[str, str, str]:
        '''
        SQL code for not equal operator

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_member_id)
                 and the normalized value for the placeholder
        '''

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, str(self.value)
        )


class DateTimeDataFilter(DataFilter):
    def __init__(self, field: str,
                 operator: str, value: datetime | date | time):
        super().__init__(field, operator)

        if isinstance(value, str):
            value = iso8601_parser(str)

        if type(value) not in (datetime, date, time):
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

    def at(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time at comparison
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

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data == self.value

    def nat(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time not-at comparison
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

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data != self.value

    def after(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time after comparison
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

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data > self.value

    def before(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time before comparison
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

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data < self.value

    def atafter(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time at-or-after comparison
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

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data >= self.value

    def atbefore(self, data: str | datetime | date | time) -> bool:
        '''
        Datetime/date/time at or before comparison
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

        if type(data) not in (datetime, date, time):
            raise ValueError(
                f'Data {data} is not of type datetime, date or time'
            )

        return data <= self.value

    def sql_at(self, sql_field: str, where: bool = False
               ) -> tuple[str, str, float]:
        '''
        Compare date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} = :{sql_field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_nat(self, sql_field: str, where: bool = False
                ) -> tuple[str, str, float]:
        '''
        Compare not equal date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} != :{sql_field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_after(self, sql_field: str, where: bool = False
                  ) -> tuple[str, str, float]:
        '''
        Compare after date/time.

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} > :{sql_field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_before(self, sql_field: str, where: bool = False
                   ) -> tuple[str, str, float]:
        '''
        Datetime/date/time before comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} < :{sql_field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_atafter(self, sql_field: str, where: bool = False
                    ) -> tuple[str, str, float]:
        '''
        Datetime/date/time at-or-after comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} >= :{sql_field_placeholder}',
            sql_field_placeholder, timestamp
        )

    def sql_atbefore(self, sql_field: str, where: bool = False
                     ) -> tuple[str, str, float]:
        '''
        Datetime/date/time at or before comparison

        Returns: tuple of the SQL string with the placeholder included,
                 the name of the placeholder (ie, :_created_timestamp)
                 and the normalized value for the placeholder
        '''

        if isinstance(self.value, str):
            timestamp = datetime.fromisoformat(self.value).timestamp()
        elif isinstance(self.value, datetime):
            timestamp = self.value.timestamp()
        elif isinstance(self.value, int):
            timestamp = self.value
        else:
            raise ValueError(f'Unexpected type for operator: {self.value}')

        sql_field_placeholder = self.sql_field_placeholder(sql_field, where)
        return (
            f'{sql_field} <= :{sql_field_placeholder}',
            sql_field_placeholder, timestamp
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

    def __init__(self, filters: object | dict):
        '''
        :param filters: is an instance of one of the input filters in the
        Strawberry code, generated from the Jinja2 template for the service
        contract. For test cases, we also support filters to be provided as
        dict
        '''

        self.filters = {}

        if not filters:
            return

        if isinstance(filters, dict):
            # For test cases we support filters as dict
            filter_items = filters.items()
        else:
            filter_items = filters.__dict__.items()

        for field, conditions in filter_items:
            if conditions:
                self.filters[field] = []
                if isinstance(conditions, dict):
                    condition_items = conditions.items()
                else:
                    condition_items = conditions.__dict__.items()
                for operator, value in condition_items:
                    if value:
                        self.filters[field].append(
                            DataFilter.create(field, operator, value)
                        )

    def __str__(self) -> str:
        filter_texts: list[str] = []
        for field in self.filters.keys():
            for filter in self.filters[field]:
                filter_texts.append(f'{field}{str(filter)}')

        text = ', '.join(filter_texts)
        return text

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
                    where=True
                )

                filter_texts.append(filter_text)
                filter_values[sql_placeholder_field] = value

        text = 'WHERE ' + ' AND '.join(filter_texts)
        return text, filter_values

    @staticmethod
    def filter(filters: list, data: list) -> list[object]:
        '''
        Filters the data against the list of filters to include the matching
        data
        '''

        _LOGGER.debug(f'Applying filters: {filters}')
        filter_set = DataFilterSet(filters)
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
