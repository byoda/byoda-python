"""Bounded explicit filter grammar shared by requests and execution."""

import re
from dataclasses import dataclass
from datetime import date, datetime, time
from uuid import UUID

from byoda.limits import MAX_FIELD_NAME_LENGTH

MAX_FILTER_DEPTH = 16
MAX_FILTER_NODES = 256
MAX_FILTER_PREDICATES = 128
OPERATORS = frozenset(
    {
        "eq",
        "ne",
        "vin",
        "nin",
        "regex",
        "glob",
        "gt",
        "lt",
        "egt",
        "elt",
        "at",
        "nat",
        "after",
        "before",
        "atafter",
        "atbefore",
    }
)
FIELD_NAME = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
SCALAR_TYPES = (str, bytes, int, float, bool, UUID, datetime, date, time)
LOGICAL_OPERATORS = frozenset({"$and", "$or", "$not"})


def validate_filter_structure(raw, *, allow_groups=True, required=False):
    """Validate before recursive Pydantic conversion or schema parsing."""
    if raw is None or raw == {}:
        if required:
            raise ValueError("filter: one comparison is required")
        return raw
    nodes = predicates = 0
    stack = [(raw, 0, "filter")]
    while stack:
        item, depth, path = stack.pop()
        nodes += 1
        if nodes > MAX_FILTER_NODES:
            raise ValueError(f"{path}: too many expression nodes")
        if not isinstance(item, dict) or len(item) != 1:
            raise ValueError(
                f"{path}: specify one field or logical group; "
                "use explicit $and/$or for multiple comparisons"
            )
        field, condition = next(iter(item.items()))
        if field in LOGICAL_OPERATORS:
            if not allow_groups:
                raise ValueError(
                    f"{path}: logical groups are only allowed for read queries"
                )
            if depth >= MAX_FILTER_DEPTH:
                raise ValueError(f"{path}: maximum filter depth exceeded")
            if field == "$not":
                # $not negates exactly one expression, so it takes an
                # object rather than a list
                if not isinstance(condition, dict):
                    raise ValueError(f"{path}.$not: expected one expression")
                stack.append((condition, depth + 1, f"{path}.$not"))
                continue
            if not isinstance(condition, list) or not condition:
                raise ValueError(f"{path}.{field}: expected nonempty list")
            if len(condition) > MAX_FILTER_NODES:
                raise ValueError(f"{path}: too many expression nodes")
            stack.extend(
                (child, depth + 1, f"{path}.{field}[{index}]")
                for index, child in enumerate(condition)
            )
            continue
        if (
            not isinstance(field, str)
            or not FIELD_NAME.fullmatch(field)
            or len(field) >= MAX_FIELD_NAME_LENGTH
        ):
            raise ValueError(f"{path}: invalid field name {field!r}")
        if not isinstance(condition, dict) or len(condition) != 1:
            raise ValueError(f"{path}.{field}: expected one comparison")
        operator, value = next(iter(condition.items()))
        if operator not in OPERATORS:
            raise ValueError(f"{path}.{field}: unsupported operator {operator}")
        if not isinstance(value, SCALAR_TYPES):
            raise ValueError(f"{path}.{field}.{operator}: expected scalar value")
        predicates += 1
        if predicates > MAX_FILTER_PREDICATES:
            raise ValueError(f"{path}: too many comparison predicates")
    return raw


def validate_single_filter(raw, *, required=False):
    return validate_filter_structure(raw, allow_groups=False, required=required)


def validate_counter_filter(raw):
    validate_single_filter(raw)
    if raw:
        condition = next(iter(raw.values()))
        if next(iter(condition)) != "eq":
            raise ValueError("counter filter: only equality is supported")
    return raw


def has_logical_groups(raw) -> bool:
    """Return whether a validated wire expression contains a group."""
    if not raw:
        return False
    field = next(iter(raw))
    return field in LOGICAL_OPERATORS


@dataclass(frozen=True)
class Predicate:
    comparison: object

    def matches(self, record):
        data = record[self.comparison.field]
        # Mirror SQL: only 'ne' matches a NULL value, other comparisons
        # against NULL are false
        if data is None and self.comparison.operator != "ne":
            return False
        return self.comparison.compare(data)

    def __str__(self):
        return f"{self.comparison.field} {self.comparison}"


@dataclass(frozen=True)
class Group:
    operator: str
    children: tuple

    def matches(self, record):
        results = (child.matches(record) for child in self.children)
        return all(results) if self.operator == "$and" else any(results)

    def __str__(self):
        separator = " and " if self.operator == "$and" else " or "
        return "(" + separator.join(str(child) for child in self.children) + ")"


@dataclass(frozen=True)
class Not:
    child: object

    def matches(self, record):
        return not self.child.matches(record)

    def __str__(self):
        return f"not ({self.child})"


def parse_filter(raw, make_comparison):
    if not raw:
        return None
    field, condition = next(iter(raw.items()))
    if field == "$not":
        return Not(parse_filter(condition, make_comparison))
    if field in ("$and", "$or"):
        return Group(
            field, tuple(parse_filter(child, make_comparison) for child in condition)
        )
    operator, value = next(iter(condition.items()))
    return Predicate(make_comparison(field, operator, value))


def validate_required_single_filter(raw):
    return validate_single_filter(raw, required=True)
