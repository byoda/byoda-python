# Nested data filters: proposed design

Status: accepted for implementation.

## Goal and scope

Support nested conjunctions and disjunctions only in Data API reads,
including recursive reads. Updates, deletes, update subscriptions, and
counter subscriptions accept at most one comparison. This is a breaking API
change: implicit AND is removed everywhere. Preserve comparison operators.

## Wire format

Use `$and` and `$or` keys, each with a nonempty array of filter objects.
Each expression object has exactly one key. Ordinary keys are field names
with exactly one operator/value pair. `$and` and `$or` are reserved keys.

```json
{
  "$and": [
    {"published_timestamp": {"atafter": "2026-01-01T00:00:00Z"}},
    {"$or": [
      {"creator": {"eq": "alice"}},
      {"creator": {"eq": "bob"}}
    ]}
  ]
}
```

`{ "field": { "gt": 10, "lt": 20 } }` and objects with multiple fields
are invalid. Repeated conditions belong in explicit group children; JSON
duplicate keys are not a representation of repeated clauses.
Do not add new comparison operators or dotted paths in this change. (NOT was
added later as `{"$not": <expression>}`; see docs/nested-data-filters.md.)

## Parsing and execution

Parse once into immutable Predicate, And, and Or nodes. A Predicate wraps
an existing DataFilter, retaining type coercion and comparison behavior.
DataFilterSet remains the public adapter and owns a root expression.
Never flatten OR into the legacy field dictionary.

Provide has_predicates and matches(record). SQL and in-memory evaluation
traverse the same structure, preserve child order, and parenthesize every
logical group. Memory evaluation short-circuits. Existing missing-field,
null, operator, and regex behavior stays unchanged; this feature does not
promise to repair pre-existing SQL/Python comparison discrepancies.
Parity tests use valid, non-null values for shared operators; additional
characterization tests explicitly pin existing null/missing behavior.

Preserve None and empty root filters as no filter on read paths. Reject
empty explicit groups, empty group children, and None values. Mutations
require exactly one effective predicate. Unsupported operators, malformed
groups, and unsafe field identifiers fail validation.
Validate fields against schema when available; without schema, validate
identifier syntax and retain the existing scalar-type inference.

Limits: logical-group depth at most 16, total expression nodes at most
256, and total comparison predicates at most 128. A node is each logical
group or comparison predicate. Validate
bounds before executing or signing and before recursive Pydantic conversion
can consume an unbounded nested payload. HTTP errors are 422 with a path
to the invalid node; WebSocket validation uses the existing protocol's
validation/error mechanism.

## SQL compilation

Separate SQL identifiers from bind parameter names. Allocate a distinct
parameter for each predicate: df_0, df_1, etc. Pass an explicit parameter
name through DataFilter.sql_filter and every leaf SQL implementation.
Share one allocator across data, metadata, cursor lookup, and rowid
pagination predicates, with separate namespaces for SET values.
Values remain parameters; schema field names become existing mapped
column names, never literal user-supplied SQL fragments.

Compose (data expression) AND (metadata expression) AND (pagination)
structurally. Replace sqltable's string surgery and .filters truth checks
with explicit predicate composition. Both SQLite and Postgres placeholder
styles must work. No predicate should accidentally escape its OR group.

## Compatibility and side effects

Keep `.filters` as a compatibility view for one comparison only. A group
cannot expose a misleading flat mapping, so access raises a clear error.
Migrate internal consumers to has_predicates. Render nested logs with
parentheses.

filter_exclude removes a row iff the complete expression matches.

No logical expression reaches update/delete, so existing single-condition
counter handling remains in place. Counter and updates subscriptions reject
logical groups. Internal cache refreshes use explicit groups for remote
reads and select their local cached row by its cursor.

## Recursive signatures

Version 1 plaintext/signatures remain byte-for-byte unchanged for flat
filters. Add signature format 2 with deterministic JSON encoding of an
explicit envelope containing service_id, relations, timestamp,
origin_member_id, filters, and signature_format_version. Sort object keys,
preserve array order, use normalized existing scalar serialization, and
include timestamp even without relations. Sign and verify identical bytes.

Originating nested recursive queries use version 2. Verification rejects
nested filters under version 1 and unknown signature versions. Proxying
preserves the original filter payload; AST normalization is internal.
Older pods cannot handle this feature: nested recursive queries require
upgraded destinations, with no flattening or silent fallback to version 1.

## Acceptance

Single-condition filters retain their results and version 1 signature bytes.
Nested filters select the intended rows in memory, SQLite, and Postgres.
Same-field OR alternatives and ranges never overwrite bind values.
Pagination and metadata constraints apply to all OR branches. Invalid
expressions cannot turn into unfiltered update/delete operations. Nested
filters survive request validation, proxy forwarding, and signatures.
Counter and updates endpoints reject unsupported groups clearly.
