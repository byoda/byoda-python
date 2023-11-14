'''
Pydantic model used for REST Data API queries

:maintainer : Steven Hessing <steven@byoda.org>
:copyright  : Copyright 2023
:license    : GPLv3
'''


from uuid import UUID
from typing import Generic
from typing import TypeVar

from logging import getLogger
from datetime import datetime
from datetime import timezone
from typing_extensions import Annotated

from opentelemetry.trace import get_tracer
from opentelemetry.sdk.trace import Tracer

from pydantic import Field
from pydantic import FieldValidationInfo
from pydantic.functional_validators import AfterValidator
from pydantic import Base64Str
from pydantic import BaseModel as PydanticBaseModel

from byoda.datatypes import IdType
from byoda.datatypes import DataFilterType

from byoda.util.logger import Logger

from byoda.limits import MAX_FIELD_NAME_LENGTH
from byoda.limits import MAX_OBJECT_FIELD_COUNT
from byoda.limits import MAX_RELATIONS_QUERY_COUNT
from byoda.limits import MAX_RELATIONS_QUERY_LEN

_LOGGER: Logger = getLogger(__name__)
TRACER: Tracer = get_tracer(__name__)

DEFAULT_PAGE_LENGTH: int = 40


class BaseModel(PydanticBaseModel):
    class Config:
        extra = 'forbid'


def check_positive(v: int) -> FieldValidationInfo:
    assert v >= 0
    return v


def check_positive_or_none(v: int | None) -> FieldValidationInfo:
    assert v is None or v >= 0
    return v


def check_field_string_length(v: str) -> FieldValidationInfo:
    assert len(v or '') < MAX_FIELD_NAME_LENGTH
    return v


def check_fields(v: set[str]) -> FieldValidationInfo:
    assert len(v or []) <= MAX_OBJECT_FIELD_COUNT
    for field in v or []:
        assert len(field) < MAX_FIELD_NAME_LENGTH
    return v


def check_hash(v: str) -> FieldValidationInfo:
    assert v is None or len(v) == 0 or len(v) == 8
    return v


def check_relations(v: str) -> FieldValidationInfo:
    assert len(v or []) <= MAX_RELATIONS_QUERY_COUNT
    for relation in v or []:
        assert len(relation) < MAX_RELATIONS_QUERY_LEN

    return v


def check_signature_format_version(v: int) -> FieldValidationInfo:
    assert v == 1
    return v


class QueryModel(BaseModel):
    fields: Annotated[set[str] | None, AfterValidator(check_fields)] = Field(
        default=None,
        description=(
            'Fields that must be included in the returned data. If this list '
            'is empty, data for all fields will be returned. If one or more'
            'fields are specified, the data for these fields will be included '
            'but the response may contain data for additional fields. The '
            'primary use case for this parameter is to leave out fields that '
            'are arrays of objects, which can be very large. Specification of '
            'fields not defined in schema will be ignored.'
        )
    )

    query_id: UUID | None = Field(
        default=None,
        description='query id, required for queries with depth > 0'
    )

    filter: DataFilterType | None = Field(
        default=None,
        description='filter to apply to the results of the query'
    )

    first: Annotated[int | None, AfterValidator(check_positive_or_none)] = \
        Field(
            default=DEFAULT_PAGE_LENGTH,
            description='number of records to return'
        )

    after: Annotated[str | None, AfterValidator(check_hash)] = Field(
        default=None, description='cursor to return records after'
    )

    depth: Annotated[int, AfterValidator(check_positive)] = Field(
        default=0,
        description='depth of (recursive) query, 0 means no recursion'
    )

    relations: Annotated[list[str] | None, AfterValidator(check_relations)] = \
        Field(
            default=None, description='relations to send recursive query to'
        )

    remote_member_id: UUID | None = Field(
        default=None, description='remote member id to send recursive query to'
    )

    timestamp: datetime | None = Field(
        default=datetime.now(tz=timezone.utc),
        description=(
            'timestamp of query, used for expiring queries that are too old'
        )
    )

    origin_member_id: UUID | None = Field(
        default=None, description='origin member id of a recursive query'
    )

    origin_signature: Base64Str | None = Field(
        default=None, description=(
            'signature of a recursive query, '
            'signed by the originater of the query'
        )
    )

    signature_format_version: Annotated[
        int | None, AfterValidator(
            check_signature_format_version
        )
    ] = Field(default=None, description='signature format version')


TypeX = TypeVar('TypeX')


class EdgeResponse(BaseModel, Generic[TypeX]):
    cursor: str
    origin: UUID
    node: TypeX


class PageInfoResponse(BaseModel):
    has_next_page: bool
    end_cursor: str | None


class QueryResponseModel(BaseModel):
    total_count: int
    edges: list[EdgeResponse]
    page_info: PageInfoResponse


class AppendModel(BaseModel, Generic[TypeX]):
    data: TypeX
    query_id: UUID | None = None
    depth: int = 0
    remote_member_id: UUID | None = None

    origin_class_name: str | None = Field(
        default=None, description=(
            'the class from which the data originates, can only be specified '
            'if the member of the request is the member of the pod'
        )
    )
    origin_id: UUID | None = Field(
        default=None, description=(
            'The UUID from which the data originates, can only be specified '
            'if the member of the request is the member of the pod'
        )
    )
    origin_id_type: IdType | None = Field(
        default=IdType.MEMBER, description=(
            'The IdType of the UUID from which the data originates, can only '
            'if the member of the request is the member of the pod'
        )
    )


class MutateModel(BaseModel, Generic[TypeX]):
    query_id: UUID | None = None
    data: TypeX


class UpdateModel(BaseModel, Generic[TypeX]):
    filter: DataFilterType = Field(
        description='filter to select what data to update'
    )
    query_id: UUID | None = None
    depth: int = 0
    remote_member_id: UUID | None = None
    data: TypeX


class DeleteModel(BaseModel):
    filter: DataFilterType = Field(
        description='filter to select what data to delete'
    )
    query_id: UUID | None = None
    depth: int = 0
    remote_member_id: UUID | None = None


class CounterModel(BaseModel):
    filter: DataFilterType | None = Field(
        default=None,
        description='filter to select what data to receive counters for'
    )
    query_id: UUID | None = None
    depth: int = Field(
        default=0,
        description='Placeholder for receiving counters for recursive queries'
    )
    relations: list[str] | None = Field(
        default=None,
        description='Placeholder for receiving counters for recursive queries'
    )


class UpdatesModel(BaseModel):
    filter: DataFilterType | None = Field(
        default=None,
        description='filter to select what data to receive counters for'
    )
    query_id: UUID | None = None
    depth: int = Field(
        default=0,
        description='Placeholder for receiving counters for recursive queries'
    )
    relations: list[str] | None = Field(
        default=None,
        description='Placeholder for receiving counters for recursive queries'
    )
    fields: list[str] | None = Field(
        default=None, description='List of fields to receive data for'
    )
    origin_id: UUID | None = Field(
        default=None, description='Origin for the data'
    )
    origin_id_type: UUID | None = Field(
        default=None, description='ID type for the origin ID'
    )
    origin_class_name: UUID | None = Field(
        default=None,
        description=(
            'Name of the "non-cache-only" class from which the data originates'
        )
    )


class UpdatesResponseModel(BaseModel):
    node: dict[str, object] = Field(description='The data that was updated')
    query_id: UUID | None = Field(
        default=None,
        description='The query ID of the original Updates API request'
    )
    origin_id: UUID = Field(
        description='The ID of the entity that originated the data'
    )
    origin_id_type: IdType = Field(
        description='The ID type of the entity that originated the data'
    )
    origin_class_name: str | None = Field(
        default=None, description='The class that the data originates from'
    )
    hops: int = Field(
        default=0,
        description='The number of hops the update response has traveled'
    )
    filter: DataFilterType | None = Field(
        default=None,
        description='The filter from the original Updates API request'
    )
