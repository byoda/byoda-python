# Nested data filters

Read requests accept one comparison or an explicit expression made from
`$and`, `$or` and `$not`. Each expression object has one key, and every comparison
has one field and one operator.

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

`$not` negates exactly one expression, which may be a comparison or a
group. Its value is an object, not a list:

```json
{
  "$and": [
    {"published_timestamp": {"atafter": "2026-01-01T00:00:00Z"}},
    {"$not": {"creator": {"eq": "alice"}}}
  ]
}
```

`$not` counts towards the same depth and node limits as `$and` and `$or`.
A comparison against a NULL column counts as false, so `$not` of it matches
the row. SQL-backed reads compile `$not` to `NOT COALESCE(<expression>, FALSE)`
to get this behaviour instead of SQL's three-valued logic. Likewise, `ne`
matches rows where the field is NULL, both in SQL and in memory.

Several fields in one object, or several operators for one field, are no
longer implicit AND. Use an explicit `$and` instead. Empty groups, null
values, unknown operators, unsafe field names, and expressions beyond the
configured complexity limits are rejected.

`get()` and recursive reads support expressions. `update()`, `delete()`,
update subscriptions, and counter subscriptions require a single comparison;
counter subscriptions also require `eq`. This keeps mutation and notification
side effects unambiguous.

Nested recursive requests use signature format version 2. Flat requests keep
the existing version 1 signature format.
