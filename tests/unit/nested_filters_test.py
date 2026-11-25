"""Explicit read expressions and single-comparison API restrictions."""

import sqlite3
import unittest
from datetime import datetime, timezone
from uuid import UUID

from pydantic import ValidationError

from byoda.datamodel.datafilter import DataFilterSet
from byoda.models.data_api_models import (
    QueryModel,
    ProxyQueryModel,
    DeleteModel,
    UpdateModel,
    UpdatesModel,
    CounterModel,
)

EXPRESSION = {
    "$and": [
        {"score": {"gt": 10}},
        {"$or": [{"creator": {"eq": "alice"}}, {"creator": {"eq": "bob"}}]},
    ]
}
ROWS = [
    {"creator": "alice", "score": 20},
    {"creator": "bob", "score": 5},
    {"creator": "carol", "score": 30},
    {"creator": "bob", "score": 40},
]


class TestNestedFilters(unittest.TestCase):
    def test_nested_memory_and_sql(self):
        filters = DataFilterSet(EXPRESSION)
        self.assertEqual(DataFilterSet.filter(filters, ROWS, None), [ROWS[0], ROWS[3]])
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE items (_creator TEXT, _score INTEGER)")
        db.executemany(
            "INSERT INTO items VALUES (?, ?)",
            [(row["creator"], row["score"]) for row in ROWS],
        )
        sql, bindings = filters.sql_where_clause(lambda key: f":{key}")
        self.assertEqual(len(bindings), 3)
        result = db.execute(
            "SELECT _creator, _score FROM items " + sql, bindings
        ).fetchall()
        self.assertEqual(result, [("alice", 20), ("bob", 40)])
        pg_sql, pg_bindings = filters.sql_where_clause(lambda key: f"%({key})s")
        self.assertEqual(pg_bindings, bindings)
        for key in bindings:
            self.assertIn(f"%({key})s", pg_sql)

    def test_not_memory_and_sql(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE items (_creator TEXT, _score INTEGER)")
        db.executemany(
            "INSERT INTO items VALUES (?, ?)",
            [(row["creator"], row["score"]) for row in ROWS],
        )
        cases = [
            ({"$not": EXPRESSION}, [ROWS[1], ROWS[2]]),
            ({"$not": {"creator": {"eq": "bob"}}}, [ROWS[0], ROWS[2]]),
            ({"$not": {"$not": {"creator": {"eq": "bob"}}}}, [ROWS[1], ROWS[3]]),
            (
                {
                    "$and": [
                        {"score": {"gt": 10}},
                        {"$not": {"creator": {"eq": "alice"}}},
                    ]
                },
                [ROWS[2], ROWS[3]],
            ),
        ]
        for raw, expected in cases:
            with self.subTest(raw=raw):
                filters = DataFilterSet(raw)
                self.assertTrue(filters.has_logical_groups)
                self.assertEqual(DataFilterSet.filter(filters, ROWS, None), expected)
                sql, bindings = filters.sql_where_clause(lambda key: f":{key}")
                result = db.execute(
                    "SELECT _creator, _score FROM items " + sql, bindings
                ).fetchall()
                self.assertEqual(
                    result, [(row["creator"], row["score"]) for row in expected]
                )
        db.execute("INSERT INTO items VALUES (NULL, 50)")
        for raw in (
            {"$not": {"creator": {"eq": "bob"}}},
            {"$not": {"$and": [{"score": {"gt": 10}}, {"creator": {"eq": "bob"}}]}},
            {"$not": {"$not": {"$not": {"creator": {"eq": "bob"}}}}},
        ):
            with self.subTest(null_row=raw):
                sql, bindings = DataFilterSet(raw).sql_where_clause(
                    lambda key: f":{key}"
                )
                result = db.execute(
                    "SELECT _creator, _score FROM items " + sql, bindings
                ).fetchall()
                self.assertIn((None, 50), result)
        self.assertEqual(
            str(DataFilterSet({"$not": {"creator": {"eq": "bob"}}})),
            f"not ({DataFilterSet({'creator': {'eq': 'bob'}})})",
        )

    def test_ne_matches_null(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        db.execute("CREATE TABLE items (_creator TEXT, _score INTEGER)")
        db.executemany(
            "INSERT INTO items VALUES (?, ?)",
            [("alice", 20), ("bob", None), (None, 5)],
        )
        for raw, expected in (
            ({"creator": {"ne": "alice"}}, [("bob", None), (None, 5)]),
            ({"score": {"ne": 20}}, [("bob", None), (None, 5)]),
        ):
            with self.subTest(raw=raw):
                sql, bindings = DataFilterSet(raw).sql_where_clause(
                    lambda key: f":{key}"
                )
                result = db.execute(
                    "SELECT _creator, _score FROM items " + sql, bindings
                ).fetchall()
                self.assertEqual(result, expected)
        rows = [{"creator": None}, {"creator": "alice"}]
        self.assertEqual(
            DataFilterSet.filter({"creator": {"ne": "alice"}}, rows, None), [rows[0]]
        )
        self.assertEqual(
            DataFilterSet.filter({"creator": {"eq": "alice"}}, rows, None), [rows[1]]
        )
        self.assertEqual(
            DataFilterSet.filter({"$not": {"creator": {"eq": "alice"}}}, rows, None),
            [rows[0]],
        )

    def test_not_validation(self):
        invalid = [
            {"$not": []},
            {"$not": {}},
            {"$not": None},
            {"$not": {"score": {"gt": 1}, "creator": {"eq": "bob"}}},
            {"$not": {"$and": []}},
        ]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                DataFilterSet(raw)
        raw = {"score": {"eq": 1}}
        for _ in range(16):
            raw = {"$not": raw}
        DataFilterSet(raw)
        with self.assertRaises(ValueError):
            DataFilterSet({"$not": raw})

    def test_not_models_and_signature(self):
        from byoda.datamodel.data_proxy import DataProxy

        expression = {"$not": EXPRESSION}
        self.assertEqual(QueryModel(filter=expression).model_dump()["filter"], expression)
        for model in (DeleteModel, UpdatesModel, CounterModel):
            with self.subTest(model=model), self.assertRaises(ValidationError):
                model(filter={"$not": {"score": {"eq": 0}}})
        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        origin = UUID("00000000-0000-0000-0000-000000000001")
        text = DataProxy._create_plaintext(
            1, None, expression, now, origin, signature_format_version=2
        )
        self.assertIn('"$not"', text)
        with self.assertRaises(ValueError):
            DataProxy._create_plaintext(
                1, None, expression, now, origin, signature_format_version=1
            )

    def test_no_implicit_and(self):
        invalid = [
            {"creator": {"eq": "alice"}, "score": {"gt": 10}},
            {"score": {"gt": 10, "lt": 20}},
            {"$and": []},
            {"$or": [{}]},
            {"$and": [{"score": {"gt": None}}]},
            {"$not": [{"score": {"gt": 10}}]},
            {"score); DROP TABLE items;--": {"eq": 1}},
        ]
        for raw in invalid:
            with self.subTest(raw=raw), self.assertRaises(ValueError):
                DataFilterSet(raw)

    def test_models_allow_groups_only_for_reads(self):
        for model in (QueryModel, ProxyQueryModel):
            kwargs = {"data_class": "items"} if model is ProxyQueryModel else {}
            query = model(filter=EXPRESSION, **kwargs)
            self.assertEqual(query.model_dump()["filter"], EXPRESSION)
            self.assertTrue(model.model_json_schema())
        for model in (DeleteModel, UpdateModel[dict], UpdatesModel, CounterModel):
            kwargs = {"data": {}} if model is UpdateModel[dict] else {}
            with self.subTest(model=model), self.assertRaises(ValidationError):
                model(filter=EXPRESSION, **kwargs)
        for raw in ({}, {"score": {"gt": None}}):
            with self.assertRaises(ValidationError):
                DeleteModel(filter=raw)
        self.assertEqual(
            DeleteModel(filter={"score": {"eq": 0}}).filter, {"score": {"eq": 0}}
        )
        self.assertIsNone(UpdatesModel().filter)

    def test_group_limits(self):
        raw = {"score": {"eq": 1}}
        for _ in range(16):
            raw = {"$and": [raw]}
        DataFilterSet(raw)
        with self.assertRaises(ValueError):
            QueryModel(filter={"$or": [raw]})
        with self.assertRaises(ValueError):
            DataFilterSet({"$or": [{"score": {"eq": i}} for i in range(129)]})

    def test_exclusion_and_empty_reads(self):
        remaining, removed = DataFilterSet.filter_exclude(EXPRESSION, ROWS)
        self.assertEqual(removed, [ROWS[0], ROWS[3]])
        self.assertEqual(remaining, [ROWS[1], ROWS[2]])
        self.assertEqual(DataFilterSet.filter(None, ROWS, None), ROWS)

    def test_signature_v2_covers_nested_payload(self):
        from byoda.datamodel.data_proxy import DataProxy

        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        origin = UUID("00000000-0000-0000-0000-000000000001")
        args = (1, None, EXPRESSION, now, origin)
        text = DataProxy._create_plaintext(*args, signature_format_version=2)
        self.assertIn('"$or"', text)
        changed = DataProxy._create_plaintext(
            1,
            None,
            EXPRESSION,
            now.replace(day=15),
            origin,
            signature_format_version=2,
        )
        self.assertNotEqual(text, changed)
        with self.assertRaises(ValueError):
            DataProxy._create_plaintext(*args, signature_format_version=1)

    def test_flat_signature_keeps_version_one_default(self):
        from byoda.datamodel.data_proxy import DataProxy

        now = datetime(2026, 10, 14, tzinfo=timezone.utc)
        origin = UUID("00000000-0000-0000-0000-000000000001")
        flat = {"creator": {"eq": "alice"}}
        self.assertEqual(
            DataProxy._create_plaintext(1, None, flat, now, origin),
            DataProxy._create_plaintext(
                1, None, flat, now, origin, signature_format_version=1
            ),
        )


if __name__ == "__main__":
    unittest.main()


class SqliteFixtureStore:
    """Execute production query assembly against a real in-memory database."""

    def __init__(self):
        self.db = sqlite3.connect(":memory:")
        self.db.row_factory = sqlite3.Row
        self.db.execute(
            "CREATE TABLE items (_creator TEXT, _score INTEGER, "
            "cursor TEXT, expires INTEGER)"
        )
        self.db.executemany(
            "INSERT INTO items VALUES (?, ?, ?, ?)",
            [
                ("alice", 20, "a", 100),
                ("carol", 30, "b", 100),
                ("bob", 40, "c", 100),
                ("alice", 50, "d", 0),
            ],
        )
        self.executions = []

    @staticmethod
    def get_named_placeholder(key):
        return f":{key}"

    async def execute(self, statement, data=None, **kwargs):
        self.executions.append(statement)
        return self.db.execute(statement, data or {}).fetchall()


class TestSqlTableFilters(unittest.IsolatedAsyncioTestCase):
    async def test_groups_with_metadata_and_cursor(self):
        from byoda.datamodel.sqltable import ArraySqlTable

        table = object.__new__(ArraySqlTable)
        table.sql_store = SqliteFixtureStore()
        self.addCleanup(table.sql_store.db.close)
        table.storage_table_name = "items"
        table.member_id = UUID(int=1)
        table.columns = {}
        table._normalize_row = lambda row: (row, {"cursor": row["cursor"]})
        result = await table.query(
            DataFilterSet(EXPRESSION),
            after="a",
            first=10,
            meta_filters=DataFilterSet({"expires": {"gt": 0}}, is_meta_filter=True),
        )
        self.assertEqual([row.data["_creator"] for row in result], ["bob"])
        result = await table.query(
            after="a",
            meta_filters=DataFilterSet({"expires": {"gt": 0}}, is_meta_filter=True),
        )
        self.assertEqual([row.data["_creator"] for row in result], ["carol", "bob"])

    async def test_mutations_reject_groups_before_storage(self):
        from byoda.datamodel.sqltable import ArraySqlTable

        table = object.__new__(ArraySqlTable)
        table.sql_store = SqliteFixtureStore()
        self.addCleanup(table.sql_store.db.close)
        table.storage_table_name = "items"
        table.member_id = UUID(int=1)
        with self.assertRaises(ValueError):
            await table.delete(
                DataFilterSet(EXPRESSION), table.sql_store.get_named_placeholder
            )
        self.assertEqual(table.sql_store.executions, [])
