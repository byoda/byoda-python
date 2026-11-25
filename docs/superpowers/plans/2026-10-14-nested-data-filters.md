# Nested Data Filters Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

> **Superseded scope:** This pre-implementation plan was narrowed by the
> accepted design. The implementation is a breaking API change: nested AND/OR
> expressions are read-only, and update/delete/update-subscription/counter
> filters each accept one comparison. See the linked specification for the
> authoritative behavior.

**Original goal:** Add backward-compatible nested AND/OR filters across data queries,
updates, deletes, and update subscriptions.

**Architecture:** Parse wire filters into a shared immutable expression tree.
Reuse existing comparison leaves, and evaluate or compile the same tree.
Keep DataFilterSet as the adapter and retain asynchronous orchestration in Python.

**Tech Stack:** Python 3.14, Pydantic 2, unittest, SQLite, Postgres; no new runtime dependencies.

**Spec:** [Proposed design](../specs/2026-10-14-nested-data-filters-design.md).

## Global Constraints

- Logical keys are `$and` and `$or`; mixed object keys use implicit AND.
- Logical-group depth at most 16, total expression nodes at most 256,
  total comparison predicates at most 128.
- Preserve legacy flat filters, operators, version 1 signatures, and flat exclusion behavior.
- No NOT, new comparison operators, dotted paths, or Rust migration.
- Counter subscriptions reject logical groups in this release.
- Mutation selection must contain at least one effective predicate.

## Review Focus

- Same field/operator repeated in OR branches must have distinct SQL values (Task 3).
- Metadata and pagination must constrain every OR branch (Task 4).
- Null-only or malformed groups must never broaden mutations (Tasks 1, 4, 5).
- Signature normalization and forwarding must not modify a signed request (Task 6).
- Nested mutations must not corrupt cached field counters or counter notifications (Task 5).

### Task 1: Characterize legacy behavior and define the expression parser

**Files:** Create `byoda/datamodel/filter_expression.py`,
`tests/unit/filter_expression_test.py`; extend `tests/unit/datafilter_test.py`.

**Interfaces:** Immutable `Predicate(filter: DataFilter)`,
`And(children: tuple[FilterNode, ...])`, `Or(children: tuple[FilterNode, ...])`;
`FilterNode = Predicate | And | Or`.
`parse_filter(raw: dict | None, data_class=None, is_meta_filter=False) -> FilterNode | None`;
`validate_filter_structure(raw: object) -> None` raises path-qualified ValueError.

- [ ] Write characterization tests for legacy multiple fields/operators,
  ignored None values, empty root, UUID/date conversion, logging, missing
  record fields, null record values, and filter_exclude's ANY semantics.
- [ ] Run `.venv/bin/python -m unittest tests.unit.datafilter_test` and record baseline.
- [ ] Write parser tests for nested/mixed groups, real fields named and/or,
  duplicate-field branches, unknown operators, invalid identifiers, and
  invalid child shapes. Assert empty/null-only explicit children fail.
  Test depth 16 accepted/17 rejected and node/predicate limits at boundaries.
- [ ] Run new tests to observe failures; implement the parser and bounded
  structural validator with schema-aware leaves using DataFilter.create.
- [ ] Run both unit modules; commit the parser and characterization coverage.

### Task 2: Integrate in-memory evaluation and the compatibility adapter

**Files:** Modify `byoda/datamodel/datafilter.py`,
`byoda/datamodel/filter_expression.py`; extend both unit test modules.

**Interfaces:** `evaluate_filter(node: FilterNode, record: dict) -> bool`;
`DataFilterSet.root: FilterNode | None`, `has_predicates: bool`,
`matches(record: dict) -> bool`, `has_logical_groups: bool`.
Existing constructor, filter, filter_exclude, and from_data_class_data remain callable.

- [ ] Write failing truth-table tests, nested short-circuit tests, and
  result-order tests. Assert empty root matches all on read paths.
  Assert nested exclusion complements the expression while flat exclusion
  retains its characterized behavior.
- [ ] Implement root storage and evaluator; preserve existing comparison
  exceptions and coercions. Retain flat `.filters` as a compatibility view,
  and reject access for logical-group inputs rather than silently flatten.
- [ ] Preserve legacy string output and add parenthesized nested rendering.
- [ ] Run both unit modules; commit adapter and evaluator.

### Task 3: Compile expressions to parameterized SQL

**Files:** Modify `byoda/datamodel/datafilter.py`,
`byoda/datamodel/filter_expression.py`; create `tests/unit/filter_sql_test.py`.

**Interfaces:** `SqlParameterAllocator(namespace: str)` with
`next_name() -> str`; `compile_filter(node, placeholder_function,
allocator, is_meta_filter=False) -> tuple[str, dict[str, object]]` returns
an expression without WHERE. `DataFilter.sql_filter(..., parameter_name:
str | None = None)` and each sql_* leaf method accept an explicit bind name.
`DataFilterSet.sql_expression(placeholder_function, allocator)` delegates;
existing sql_where_clause remains as an adapter.

- [ ] Write failing tests for two creator/eq OR branches retaining alice
  and bob separately, two same-field ranges, nested mixed precedence,
  quotes in values, metadata columns, and unsupported schema fields.
- [ ] Implement unique parameter allocation and recursive parenthesized
  groups; reuse existing SQL operators and normalization. Never rewrite SQL
  by replacing parameter substrings.
- [ ] Verify SQLite `:df_0` and Postgres `%(df_0)s` styles and noncollision
  with mutation SET bindings, metadata bindings, and pagination bindings.
- [ ] Execute SQLite fixtures and compare matching row IDs with memory for
  valid non-null values; characterize existing leaf discrepancies explicitly.
- [ ] Run `tests.unit.filter_sql_test` and existing filter tests; commit compiler.

### Task 4: Integrate SQL selection, metadata, and pagination

**Files:** Modify `byoda/datamodel/sqltable.py`,
`byoda/storage/sqlstorage.py`; create `tests/integration/nested_filters.py`.

**Interfaces:** One allocator and composed WHERE expression per statement.
`_add_cursor_to_query` receives actual predicate state rather than deriving
it from `.filters`; cursor lookup and final selection preserve all constraints.

- [ ] Write failing SQLite integration tests for query, update, and delete,
  including nested OR combined with metadata-only filters and after/first.
  Assert an OR branch cannot bypass the cursor or metadata constraints.
- [ ] Replace all `.filters` presence checks with has_predicates and compose
  expressions with AND; remove lstrip-based WHERE surgery.
- [ ] Preserve scalar/object-table restrictions. Require effective predicates
  for update/delete, including filters containing only ignored None values.
- [ ] Run the same integration fixtures against Postgres using configured
  test infrastructure; compare selected/mutated IDs and pagination order.
- [ ] Run filter units and backend integrations; commit SQL integration.

### Task 5: Expose recursive request types and handle subscriptions/counters

**Files:** Modify `byoda/datatypes.py`, `byoda/models/data_api_models.py`,
`byoda/datamodel/memberdata.py`, `byoda/datamodel/pubsub_message.py`,
`byoda/datacache/counter_cache.py`, and
`podserver/templates/pydantic-model-rest-apis.py.jinja` if generated handling needs changes.
Extend `tests/func/pod_rest_data_apis_arrays_test.py` and
`tests/func/pod_rest_data_api_websocket_test.py`;
create `tests/unit/filter_models_test.py`.

**Interfaces:** Retain `FlatDataFilterType` for restricted consumers;
recursive `DataFilterType` models field predicates and logical child lists.
Run validate_filter_structure before recursive type validation and use the
schema-aware parser at the service boundary. Preserve plain dictionaries
when request models are dumped for forwarding.

- [ ] Write failing request-model tests for accepted nested filters,
  malformed/oversized filters, flat round trips, and OpenAPI schemas.
  CounterModel rejects logical groups with a clear validation error.
- [ ] Update query/update/delete/updates models and generated handlers;
  retain counter endpoint's restricted semantics. Validate filters before
  mutations, logging side effects, or subscription setup.
- [ ] Batch update-message filtering where practical; preserve message
  metadata and PubSub mutation/delete filter trees in serialization.
- [ ] For nested updates/deletes, purge the member counter cache instead of
  interpreting OR branches as equality counter keys. Ensure counter reads
  supply the table to lazily recount and subscribers recount mutation/delete
  notifications rather than dereference nonexistent row data.
- [ ] Test OR-selected mutation effects, cache recounts, emitted update
  messages, and no writes on rejected input. Preserve old flat request tests.
- [ ] Run model units and API/WebSocket functional fixtures; commit integration.

### Task 6: Version recursive-query signatures and forwarding

**Files:** Modify `byoda/datamodel/data_proxy.py`,
`byoda/datamodel/memberdata.py`, `byoda/models/data_api_models.py`;
extend `tests/unit/apiproxy_test.py`, `tests/integration/proxy.py`.

**Interfaces:** Add optional trailing `signature_format_version=1` to signing
and plaintext generation; verification dispatches by the existing version
argument. Version 2 encodes the full envelope specified in the design.

- [ ] Pin current version 1 plaintext and signature-verification fixtures,
  including its unusual existing serialization; do not fix its format in place.
- [ ] Write failing version 2 tests: identical object-key reorderings produce
  identical bytes; changing a branch/operator/value/timestamp invalidates
  signatures; nested version 1 and unknown versions are rejected.
- [ ] Implement deterministic serialization and sign/verify dispatch;
  originating nested queries select version 2, while flat queries keep version 1.
- [ ] Test Pydantic dump/load and multi-hop proxying preserve the signed
  payload, including operator values and child-array order. Test an older
  destination rejects unsupported nested queries without silent fallback.
- [ ] Run proxy unit/integration fixtures; commit signature support.

### Task 7: Complete regression coverage and publish usage documentation

**Files:** Create `docs/nested-data-filters.md`; extend the unit and integration
fixtures from prior tasks.

- [ ] Generate bounded mixed expression trees and compare memory/SQLite/
  Postgres results for shared supported operators and non-null scalar rows.
  Keep explicit tests of characterized missing/null behavior.
- [ ] Run flat-filter regression suites, new expression/model/compiler units,
  SQL integrations, API/WebSocket functional tests, and recursive proxy tests.
- [ ] Measure representative SQL execution and subscription filtering for
  flat filters and nested trees at the size limits. Confirm validation occurs
  before database work and no unintended unfiltered mutations are possible.
- [ ] Document wire examples, implicit AND, limits, error responses,
  restricted counters, conservative counter invalidation, exclusion behavior,
  and upgraded-pod requirements for nested recursive queries.
- [ ] Run repository Python lint on changed files; review complete diff and
  commit tests/documentation. Report any infrastructure-blocked checks explicitly.

## Implementation order and rollout

Tasks 1–4 build and verify the engine without widening API acceptance.
Tasks 5–6 expose it and support signed federation; ship together so advertised
nested filters cannot fail midway through proxying. Task 7 is the release gate.
Do not deploy intermediate commits that advertise unsupported recursive filters.
Upgrade destination pods before clients send nested recursive queries.
