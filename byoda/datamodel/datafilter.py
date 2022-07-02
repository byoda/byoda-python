'''
Classes for data filters for filtering results a GraphQL query based
on the filter conditions defined in the query

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2021, 2022
:license    : GPLv3
'''

import logging
import re
from uuid import UUID
from datetime import datetime, date, time

from dateutil import parser as iso8601_parser

from typing import List, Dict, Callable, Union, Tuple

_LOGGER = logging.getLogger(__name__)


class DataFilter:
    def __init__(self, operator: str):
        '''
        Base class for data filters for strings, UUIDs, datetimes and numbers
        '''
        if not isinstance(operator, str):
            raise ValueError(
                f'Operator {operator} is a {type(operator)} instead of str'
            )

        self.operator: str = operator

        self.compare_functions: Dict[str, Callable] = {}

    @staticmethod
    def create(operator: str, value: Union[str, int, float, UUID, datetime,
               date, time]):
        '''
        Factory for classes derived from DataFilter
        '''

        if isinstance(value, str):
            return StringDataFilter(operator, value)

        if isinstance(value, UUID):
            return UuidDataFilter(operator, value)

        if type(value) in (int, float):
            return NumberDataFilter(operator, value)

        if type(value) in (datetime, date, time):
            return DateTimeDataFilter(operator, value)

        raise ValueError(f'Value has type {type(value)}')

    def compare(self, data: Union[str, int, float, UUID, datetime, date, time]
                ) -> bool:
        '''
        Compares the data against the value for the filter
        '''

        return self.compare_functions[self.operator](data)


class StringDataFilter(DataFilter):
    def __init__(self, operator: str, value: str):
        super().__init__(operator)

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

    def eq(self, data: str):
        '''
        equal operator
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: str):
        '''
        not-equal operator
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def vin(self, data: str):
        '''
        value-in operator ('in' can not be used as it is a Python keyword)
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return self.value in data

    def nin(self, data: str):
        '''
        not-in operator
        '''
        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return self.value not in data

    def regex(self, data: str):
        '''
        regex operator
        '''

        if not isinstance(data, str):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return re.match(self.value, data)

    def glob(self, data: str):
        '''
        Glob matching TODO: find python module for it that doesn't just
        work on files in a directory
        '''

        # TODO: glob text filter
        raise NotImplementedError('Glob matching is not yet supported')


class NumberDataFilter(DataFilter):
    '''
    Class for filters for numbers as ints or floats
    '''
    def __init__(self, operator: str, value: Union[int, float]):
        super().__init__(operator)

        self.value: Union[int, float] = value

    def eq(self, data: Union[int, float]):
        '''
        equal operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: Union[int, float]):
        '''
        not-equal operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value

    def gt(self, data: Union[int, float]):
        '''
        greater-than operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data > self.value

    def lt(self, data: Union[int, float]):
        '''
        less-than operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data < self.value

    def egt(self, data: Union[int, float]):
        '''
        equal-or-greater operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data >= self.value

    def elt(self, data: Union[int, float]):
        '''
        equal or lesser operator
        '''

        if not type(data) in (int, float):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data < self.value


class UuidDataFilter(DataFilter):
    def __init__(self, operator: str, value: UUID):
        super().__init__(operator)

        if not isinstance(value, UUID):
            raise ValueError(
                f'Value {value} is a {type(value)} instead of a UUID'
            )
        self.value: UUID = value

        self.compare_functions = {
            'eq': self.eq,
            'ne': self.ne,
        }

    def eq(self, data: UUID):
        '''
        equal operator
        '''

        if isinstance(data, str):
            data = UUID(data)

        if not isinstance(data, UUID):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data == self.value

    def ne(self, data: UUID):
        '''
        not-equal operator
        '''

        if not isinstance(data, UUID):
            raise ValueError(f'Data {data} is of type {type(data)}')

        return data != self.value


class DateTimeDataFilter(DataFilter):
    def __init__(self, operator: str, value: Union[datetime, date, time]):
        super().__init__(operator)

        if isinstance(value, str):
            value = iso8601_parser(str)

        if type(value) not in (datetime, date, time):
            raise ValueError(
                f'Value {value} is a {type(value)} instead of a datetime, '
                'date or time'
            )
        self.value: Union[datetime, date, time] = value

        self.compare_functions = {
            'at': self.at,
            'nat': self.nat,
            'after': self.after,
            'before': self.before,
            'atafter': self.atafter,
            'atbefore': self.atbefore,
        }

    def at(self, data: Union[str, datetime, date, time]):
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

    def nat(self, data: Union[str, datetime, date, time]):
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

    def after(self, data: Union[str, datetime, date, time]):
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

    def before(self, data: Union[str, datetime, date, time]):
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

    def atafter(self, data: Union[str, datetime, date, time]):
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

    def atbefore(self, data: Union[str, datetime, date, time]):
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

    def __init__(self, filters):
        '''
        :param filter: is one of the input filters in the Strawberry code,
        generated from the Jinja2 template for the service contract
        '''

        self.filters = {}
        for field, conditions in filters.__dict__.items():
            if conditions:
                self.filters[field] = []
                for operator, value in conditions.__dict__.items():
                    if value:
                        self.filters[field].append(
                            DataFilter.create(operator, value)
                        )

    @staticmethod
    def filter(filters: List, data: List) -> List:
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
    def filter_exclude(filters: List, data: List) -> Tuple[List, List]:
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
