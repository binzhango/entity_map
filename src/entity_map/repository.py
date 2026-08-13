"""Persistent SQLite catalog for multi-model field mappings."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sqlite3
from threading import Lock
from typing import Any, Literal

import pandas as pd

from .schema import NORMALIZED_FIELDS

FieldKind = Literal["legacy", "current"]

SCHEMA = """
CREATE TABLE IF NOT EXISTS legacy_fields (
    id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_key TEXT NOT NULL,
    database_name TEXT NOT NULL DEFAULT '',
    schema_name TEXT NOT NULL DEFAULT '',
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    data_type TEXT NOT NULL DEFAULT '',
    table_key TEXT NOT NULL,
    column_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(model_key, table_key, column_key)
);
CREATE TABLE IF NOT EXISTS current_fields (
    id INTEGER PRIMARY KEY,
    model_name TEXT NOT NULL,
    model_key TEXT NOT NULL,
    database_name TEXT NOT NULL DEFAULT '',
    schema_name TEXT NOT NULL DEFAULT '',
    table_name TEXT NOT NULL,
    column_name TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    data_type TEXT NOT NULL DEFAULT '',
    table_key TEXT NOT NULL,
    column_key TEXT NOT NULL,
    created_at TEXT NOT NULL,
    UNIQUE(model_key, table_key, column_key)
);
CREATE TABLE IF NOT EXISTS mappings (
    id INTEGER PRIMARY KEY,
    legacy_field_id INTEGER NOT NULL REFERENCES legacy_fields(id) ON DELETE CASCADE,
    current_field_id INTEGER NOT NULL REFERENCES current_fields(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    UNIQUE(legacy_field_id, current_field_id)
);
CREATE TABLE IF NOT EXISTS legacy_sources (
    id INTEGER PRIMARY KEY,
    legacy_field_id INTEGER NOT NULL REFERENCES legacy_fields(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    UNIQUE(legacy_field_id, source_file, source_sheet, source_row)
);
CREATE TABLE IF NOT EXISTS current_sources (
    id INTEGER PRIMARY KEY,
    current_field_id INTEGER NOT NULL REFERENCES current_fields(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    UNIQUE(current_field_id, source_file, source_sheet, source_row)
);
CREATE TABLE IF NOT EXISTS mapping_sources (
    id INTEGER PRIMARY KEY,
    mapping_id INTEGER NOT NULL REFERENCES mappings(id) ON DELETE CASCADE,
    source_file TEXT NOT NULL,
    source_sheet TEXT NOT NULL,
    source_row INTEGER NOT NULL,
    UNIQUE(mapping_id, source_file, source_sheet, source_row)
);
CREATE TABLE IF NOT EXISTS imports (
    id INTEGER PRIMARY KEY,
    kind TEXT NOT NULL,
    filename TEXT NOT NULL,
    legacy_model TEXT NOT NULL DEFAULT '',
    current_model TEXT NOT NULL DEFAULT '',
    imported_at TEXT NOT NULL,
    valid_count INTEGER NOT NULL,
    invalid_count INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_legacy_fields_model ON legacy_fields(model_key);
CREATE INDEX IF NOT EXISTS idx_current_fields_model ON current_fields(model_key);
CREATE INDEX IF NOT EXISTS idx_legacy_fields_column_key ON legacy_fields(column_key);
CREATE INDEX IF NOT EXISTS idx_current_fields_column_key ON current_fields(column_key);
CREATE INDEX IF NOT EXISTS idx_mappings_current_field ON mappings(current_field_id);
CREATE INDEX IF NOT EXISTS idx_mappings_legacy_field ON mappings(legacy_field_id);
"""


def _key(value: object) -> str:
    return str(value or "").strip().casefold()


def _text(value: object) -> str:
    return str(value or "").strip()


def _now() -> str:
    return datetime.now(UTC).isoformat(timespec="seconds")


class CatalogRepository:
    """SQLite-backed catalog with model-aware relationship and metadata views."""

    def __init__(self, path: str | Path) -> None:
        self.path = Path(path).expanduser()
        self._initialized = False
        self._lock = Lock()
        self._relationships_cache: pd.DataFrame | None = None

    def _connect(self) -> sqlite3.Connection:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        connection = sqlite3.connect(self.path, timeout=15)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        return connection

    def _migrate_legacy_schema(self, connection: sqlite3.Connection) -> None:
        """Upgrade the v0.3 two-table identity model without losing mappings."""

        connection.execute("PRAGMA foreign_keys = OFF")
        for index in (
            "idx_legacy_fields_column_key",
            "idx_current_fields_column_key",
            "idx_mappings_current_field",
            "idx_mappings_legacy_field",
        ):
            connection.execute(f"DROP INDEX IF EXISTS {index}")
        for table in (
            "mapping_sources",
            "legacy_sources",
            "current_sources",
            "mappings",
            "imports",
            "legacy_fields",
            "current_fields",
        ):
            connection.execute(f"ALTER TABLE {table} RENAME TO __old_{table}")
        connection.executescript(SCHEMA)
        connection.execute(
            """
            INSERT INTO legacy_fields
                (id, model_name, model_key, table_name, column_name, description,
                 table_key, column_key, created_at)
            SELECT id, 'Legacy', 'legacy', table_name, column_name, description,
                   table_key, column_key, created_at
            FROM __old_legacy_fields
            """
        )
        connection.execute(
            """
            INSERT INTO current_fields
                (id, model_name, model_key, table_name, column_name, description,
                 table_key, column_key, created_at)
            SELECT id, 'Current', 'current', table_name, column_name, description,
                   table_key, column_key, created_at
            FROM __old_current_fields
            """
        )
        connection.execute(
            "INSERT INTO mappings(id, legacy_field_id, current_field_id, created_at) "
            "SELECT id, legacy_field_id, current_field_id, created_at FROM __old_mappings"
        )
        connection.execute(
            "INSERT INTO legacy_sources SELECT * FROM __old_legacy_sources"
        )
        connection.execute(
            "INSERT INTO current_sources SELECT * FROM __old_current_sources"
        )
        connection.execute(
            "INSERT INTO mapping_sources SELECT * FROM __old_mapping_sources"
        )
        connection.execute(
            """
            INSERT INTO imports(id, kind, filename, imported_at, valid_count, invalid_count)
            SELECT id, kind, filename, imported_at, valid_count, invalid_count
            FROM __old_imports
            """
        )
        for table in (
            "mapping_sources",
            "legacy_sources",
            "current_sources",
            "mappings",
            "imports",
            "legacy_fields",
            "current_fields",
        ):
            connection.execute(f"DROP TABLE __old_{table}")
        connection.execute("PRAGMA foreign_keys = ON")

    def _ensure(self) -> None:
        if self._initialized:
            return
        with self._lock:
            if self._initialized:
                return
            with self._connect() as connection:
                table = connection.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='legacy_fields'"
                ).fetchone()
                if table:
                    columns = {
                        str(row["name"])
                        for row in connection.execute("PRAGMA table_info(legacy_fields)")
                    }
                    if "model_key" not in columns:
                        self._migrate_legacy_schema(connection)
                    else:
                        connection.executescript(SCHEMA)
                else:
                    connection.executescript(SCHEMA)
                connection.execute("PRAGMA optimize")
            self._initialized = True

    def _invalidate(self) -> None:
        self._relationships_cache = None

    @staticmethod
    def _upsert_field(
        connection: sqlite3.Connection,
        kind: FieldKind,
        model_name: object,
        database_name: object,
        schema_name: object,
        table_name: object,
        column_name: object,
        description: object = "",
        data_type: object = "",
    ) -> int:
        model = _text(model_name) or ("Legacy" if kind == "legacy" else "Current")
        table = _text(table_name)
        column = _text(column_name)
        if not table or not column:
            raise ValueError(f"{kind.capitalize()} table and column are required")
        fields_table = f"{kind}_fields"
        connection.execute(
            f"""
            INSERT INTO {fields_table}
                (model_name, model_key, database_name, schema_name, table_name, column_name,
                 description, data_type, table_key, column_key, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(model_key, table_key, column_key) DO UPDATE SET
                model_name = excluded.model_name,
                database_name = CASE WHEN excluded.database_name <> '' THEN excluded.database_name ELSE {fields_table}.database_name END,
                schema_name = CASE WHEN excluded.schema_name <> '' THEN excluded.schema_name ELSE {fields_table}.schema_name END,
                table_name = excluded.table_name,
                column_name = excluded.column_name,
                description = CASE WHEN excluded.description <> '' THEN excluded.description ELSE {fields_table}.description END,
                data_type = CASE WHEN excluded.data_type <> '' THEN excluded.data_type ELSE {fields_table}.data_type END
            """,
            (
                model,
                _key(model),
                _text(database_name),
                _text(schema_name),
                table,
                column,
                _text(description),
                _text(data_type),
                _key(table),
                _key(column),
                _now(),
            ),
        )
        row = connection.execute(
            f"SELECT id FROM {fields_table} WHERE model_key = ? AND table_key = ? AND column_key = ?",
            (_key(model), _key(table), _key(column)),
        ).fetchone()
        assert row is not None
        return int(row["id"])

    @staticmethod
    def _add_field_source(
        connection: sqlite3.Connection,
        kind: FieldKind,
        field_id: int,
        source_file: object,
        source_sheet: object,
        source_row: object,
    ) -> None:
        connection.execute(
            f"INSERT OR IGNORE INTO {kind}_sources ({kind}_field_id, source_file, source_sheet, source_row) VALUES (?, ?, ?, ?)",
            (field_id, _text(source_file) or "Catalog", _text(source_sheet) or "Inventory", int(source_row or 0)),
        )

    def import_inventory(self, kind: FieldKind, rows: pd.DataFrame, model_name: str) -> int:
        self._ensure()
        if rows.empty:
            return 0
        with self._connect() as connection:
            for row in rows.itertuples(index=False):
                field_id = self._upsert_field(
                    connection, kind, model_name, row.database_name, row.schema_name,
                    row.table_name, row.column_name, row.description, row.data_type,
                )
                self._add_field_source(connection, kind, field_id, row.source_file, row.source_sheet, row.source_row)
        self._invalidate()
        return len(rows)

    def import_mappings(self, rows: pd.DataFrame, legacy_model: str, current_model: str) -> int:
        self._ensure()
        if rows.empty:
            return 0
        with self._connect() as connection:
            for row in rows.itertuples(index=False):
                legacy_id = self._upsert_field(
                    connection, "legacy", legacy_model, row.legacy_database, row.legacy_schema,
                    row.legacy_table, row.legacy_column, row.legacy_description, row.legacy_data_type,
                )
                self._add_field_source(connection, "legacy", legacy_id, row.source_file, row.source_sheet, row.source_row)
                if not _text(row.current_table) or not _text(row.current_column):
                    continue
                current_id = self._upsert_field(
                    connection, "current", current_model, row.current_database, row.current_schema,
                    row.current_table, row.current_column, row.current_description, row.current_data_type,
                )
                self._add_field_source(connection, "current", current_id, row.source_file, row.source_sheet, row.source_row)
                connection.execute(
                    "INSERT OR IGNORE INTO mappings(legacy_field_id, current_field_id, created_at) VALUES (?, ?, ?)",
                    (legacy_id, current_id, _now()),
                )
                mapping = connection.execute(
                    "SELECT id FROM mappings WHERE legacy_field_id = ? AND current_field_id = ?",
                    (legacy_id, current_id),
                ).fetchone()
                assert mapping is not None
                connection.execute(
                    "INSERT OR IGNORE INTO mapping_sources(mapping_id, source_file, source_sheet, source_row) VALUES (?, ?, ?, ?)",
                    (int(mapping["id"]), _text(row.source_file), _text(row.source_sheet), int(row.source_row)),
                )
        self._invalidate()
        return len(rows)

    def record_import(self, kind: str, filename: str, valid_count: int, invalid_count: int, *, legacy_model: str = "", current_model: str = "") -> None:
        self._ensure()
        with self._connect() as connection:
            connection.execute(
                "INSERT INTO imports(kind, filename, legacy_model, current_model, imported_at, valid_count, invalid_count) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (kind, filename, _text(legacy_model), _text(current_model), _now(), valid_count, invalid_count),
            )

    def summary(self, legacy_model: str = "", current_model: str = "") -> dict[str, Any]:
        self._ensure()
        legacy_filter = "AND model_key = ?" if _text(legacy_model) else ""
        current_filter = "AND model_key = ?" if _text(current_model) else ""
        args_legacy = (_key(legacy_model),) if _text(legacy_model) else ()
        args_current = (_key(current_model),) if _text(current_model) else ()
        with self._connect() as connection:
            legacy_count = int(connection.execute(f"SELECT COUNT(*) FROM legacy_fields WHERE 1=1 {legacy_filter}", args_legacy).fetchone()[0])
            current_count = int(connection.execute(f"SELECT COUNT(*) FROM current_fields WHERE 1=1 {current_filter}", args_current).fetchone()[0])
            mapping_count = int(connection.execute(
                f"""SELECT COUNT(*) FROM mappings m JOIN legacy_fields l ON l.id=m.legacy_field_id JOIN current_fields c ON c.id=m.current_field_id WHERE 1=1 {legacy_filter.replace('model_key','l.model_key')} {current_filter.replace('model_key','c.model_key')}""",
                args_legacy + args_current,
            ).fetchone()[0])
            matched = int(connection.execute(
                f"""SELECT COUNT(DISTINCT l.id) FROM legacy_fields l JOIN mappings m ON m.legacy_field_id=l.id JOIN current_fields c ON c.id=m.current_field_id WHERE 1=1 {legacy_filter.replace('model_key','l.model_key')} {current_filter.replace('model_key','c.model_key')}""",
                args_legacy + args_current,
            ).fetchone()[0])
            current_matched = int(connection.execute(
                f"""SELECT COUNT(DISTINCT c.id) FROM current_fields c JOIN mappings m ON m.current_field_id=c.id JOIN legacy_fields l ON l.id=m.legacy_field_id WHERE 1=1 {legacy_filter.replace('model_key','l.model_key')} {current_filter.replace('model_key','c.model_key')}""",
                args_legacy + args_current,
            ).fetchone()[0])
            models = {
                "legacy": [str(row[0]) for row in connection.execute("SELECT model_name FROM legacy_fields GROUP BY model_key ORDER BY model_key")],
                "current": [str(row[0]) for row in connection.execute("SELECT model_name FROM current_fields GROUP BY model_key ORDER BY model_key")],
            }
            latest = connection.execute("SELECT imported_at FROM imports ORDER BY id DESC LIMIT 1").fetchone()
            import_count = int(connection.execute("SELECT COUNT(*) FROM imports").fetchone()[0])
        unmatched = max(legacy_count - matched, 0)
        current_unmatched = max(current_count - current_matched, 0)
        return {
            "ready": legacy_count > 0 or current_count > 0,
            "legacyFieldCount": legacy_count,
            "currentFieldCount": current_count,
            "mappingCount": mapping_count,
            "matchedCount": matched,
            "unmatchedCount": unmatched,
            "matchedPercent": round((matched / legacy_count) * 100, 1) if legacy_count else 0,
            "unmatchedPercent": round((unmatched / legacy_count) * 100, 1) if legacy_count else 0,
            "currentMatchedCount": current_matched,
            "currentUnmatchedCount": current_unmatched,
            "currentUnmatchedPercent": round((current_unmatched / current_count) * 100, 1) if current_count else 0,
            "importCount": import_count,
            "lastImportedAt": str(latest["imported_at"]) if latest else None,
            "legacyModels": models["legacy"],
            "currentModels": models["current"],
        }

    def imports(self, limit: int = 25) -> list[dict[str, Any]]:
        self._ensure()
        with self._connect() as connection:
            rows = connection.execute("SELECT id, kind, filename, legacy_model, current_model, imported_at, valid_count, invalid_count FROM imports ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
        return [
            {"id": int(row["id"]), "kind": str(row["kind"]), "filename": str(row["filename"]), "legacyModel": str(row["legacy_model"]), "currentModel": str(row["current_model"]), "importedAt": str(row["imported_at"]), "validCount": int(row["valid_count"]), "invalidCount": int(row["invalid_count"])}
            for row in rows
        ]

    def relationships(self) -> pd.DataFrame:
        self._ensure()
        if self._relationships_cache is not None:
            return self._relationships_cache.copy(deep=False)
        with self._connect() as connection:
            rows = connection.execute(
                """
                SELECT CASE WHEN m.id IS NULL THEN -l.id ELSE m.id END AS relationship_id,
                    l.id AS legacy_id, l.model_name AS legacy_model, l.table_name AS legacy_table,
                    l.column_name AS legacy_column, l.description AS legacy_description,
                    l.database_name AS legacy_database, l.schema_name AS legacy_schema, l.data_type AS legacy_data_type,
                    COALESCE(c.model_name, '') AS current_model, COALESCE(c.table_name, '') AS current_table,
                    COALESCE(c.column_name, '') AS current_column, COALESCE(c.description, '') AS current_description,
                    COALESCE(c.database_name, '') AS current_database, COALESCE(c.schema_name, '') AS current_schema,
                    COALESCE(c.data_type, '') AS current_data_type,
                    CASE WHEN m.id IS NULL THEN 'Unmapped' ELSE 'Mapped' END AS mapping_state, m.id AS mapping_id
                FROM legacy_fields l LEFT JOIN mappings m ON m.legacy_field_id=l.id LEFT JOIN current_fields c ON c.id=m.current_field_id
                ORDER BY l.model_key, l.table_key, l.column_key, c.model_key, c.table_key, c.column_key
                """
            ).fetchall()
            current_only_rows = connection.execute(
                """
                SELECT -1000000000 - c.id AS relationship_id,
                    NULL AS legacy_id, '' AS legacy_model, '' AS legacy_table,
                    '' AS legacy_column, '' AS legacy_description,
                    '' AS legacy_database, '' AS legacy_schema, '' AS legacy_data_type,
                    c.id AS current_id, c.model_name AS current_model, c.table_name AS current_table,
                    c.column_name AS current_column, c.description AS current_description,
                    c.database_name AS current_database, c.schema_name AS current_schema,
                    c.data_type AS current_data_type,
                    'Unmapped' AS mapping_state, NULL AS mapping_id
                FROM current_fields c
                WHERE NOT EXISTS (
                    SELECT 1 FROM mappings m WHERE m.current_field_id = c.id
                )
                ORDER BY c.model_key, c.table_key, c.column_key
                """
            ).fetchall()
            rows = [*rows, *current_only_rows]
            mapping_sources = connection.execute("SELECT mapping_id, source_file, source_sheet, source_row FROM mapping_sources ORDER BY source_file, source_sheet, source_row").fetchall()
            legacy_sources = connection.execute("SELECT legacy_field_id, source_file, source_sheet, source_row FROM legacy_sources ORDER BY source_file, source_sheet, source_row").fetchall()
            current_sources = connection.execute("SELECT current_field_id, source_file, source_sheet, source_row FROM current_sources ORDER BY source_file, source_sheet, source_row").fetchall()
        by_mapping: dict[int, list[dict[str, Any]]] = {}
        for row in mapping_sources:
            by_mapping.setdefault(int(row["mapping_id"]), []).append({"source_file": str(row["source_file"]), "source_sheet": str(row["source_sheet"]), "source_row": int(row["source_row"])})
        by_legacy: dict[int, list[dict[str, Any]]] = {}
        for row in legacy_sources:
            by_legacy.setdefault(int(row["legacy_field_id"]), []).append({"source_file": str(row["source_file"]), "source_sheet": str(row["source_sheet"]), "source_row": int(row["source_row"])})
        by_current: dict[int, list[dict[str, Any]]] = {}
        for row in current_sources:
            by_current.setdefault(int(row["current_field_id"]), []).append({"source_file": str(row["source_file"]), "source_sheet": str(row["source_sheet"]), "source_row": int(row["source_row"])})
        records = []
        for row in rows:
            mapping_id = row["mapping_id"]
            if mapping_id is not None:
                provenance = by_mapping.get(int(mapping_id), [])
            elif row["legacy_id"] is not None:
                provenance = by_legacy.get(int(row["legacy_id"]), [])
            else:
                provenance = by_current.get(int(row["current_id"]), [])
            records.append({
                "relationship_id": int(row["relationship_id"]),
                **{field: str(row[field]) for field in (
                    "legacy_model", "legacy_table", "legacy_column", "legacy_description", "legacy_database", "legacy_schema", "legacy_data_type",
                    "current_model", "current_table", "current_column", "current_description", "current_database", "current_schema", "current_data_type", "mapping_state",
                )},
                "unmapped_side": "current" if row["legacy_id"] is None else ("legacy" if mapping_id is None else ""),
                "provenance_count": len(provenance),
                "source_files": ", ".join(sorted({item["source_file"] for item in provenance}, key=str.casefold)),
                "_provenance": provenance,
            })
        columns = list(records[0].keys()) if records else [
            "relationship_id", "legacy_model", "legacy_table", "legacy_column", "legacy_description",
            "legacy_database", "legacy_schema", "legacy_data_type", "current_model", "current_table",
            "current_column", "current_description", "current_database", "current_schema", "current_data_type",
            "mapping_state", "unmapped_side", "provenance_count", "source_files", "_provenance",
        ]
        frame = pd.DataFrame(records, columns=columns)
        self._relationships_cache = frame
        return frame.copy(deep=False)

    def current_fields(self, query: str = "", model_name: str = "", limit: int = 100) -> list[dict[str, Any]]:
        return self._fields("current", query, model_name, limit)

    def legacy_fields(self, query: str = "", model_name: str = "", limit: int = 50) -> list[dict[str, Any]]:
        return self._fields("legacy", query, model_name, limit)

    def _fields(self, kind: FieldKind, query: str, model_name: str, limit: int) -> list[dict[str, Any]]:
        self._ensure()
        text = _key(query)
        pattern = f"%{text}%"
        table = f"{kind}_fields"
        model_clause = "AND model_key = ?" if _text(model_name) else ""
        args: tuple[Any, ...] = (text, pattern, pattern, pattern, pattern)
        if _text(model_name):
            args += (_key(model_name),)
        args += (text, text, limit)
        with self._connect() as connection:
            fields = connection.execute(
                f"""SELECT id, model_name, database_name, schema_name, table_name, column_name, description, data_type
                    FROM {table}
                    WHERE (? = '' OR table_key LIKE ? OR column_key LIKE ? OR (table_key || '.' || column_key) LIKE ? OR lower(description) LIKE ?) {model_clause}
                    ORDER BY CASE WHEN column_key = ? OR (table_key || '.' || column_key) = ? THEN 0 ELSE 1 END, model_key, table_key, column_key LIMIT ?""",
                args,
            ).fetchall()
            output = []
            for field in fields:
                mapped = []
                if kind == "current":
                    rows = connection.execute(
                        "SELECT m.id AS mapping_id, l.id, l.model_name, l.database_name, l.schema_name, l.table_name, l.column_name, l.description, l.data_type FROM mappings m JOIN legacy_fields l ON l.id=m.legacy_field_id WHERE m.current_field_id=? ORDER BY l.model_key,l.table_key,l.column_key",
                        (int(field["id"]),),
                    ).fetchall()
                    mapped = [{"mappingId": int(row["mapping_id"]), "id": int(row["id"]), "model": str(row["model_name"]), "database": str(row["database_name"]), "schema": str(row["schema_name"]), "table": str(row["table_name"]), "column": str(row["column_name"]), "description": str(row["description"]), "dataType": str(row["data_type"])} for row in rows]
                output.append({"id": int(field["id"]), "model": str(field["model_name"]), "database": str(field["database_name"]), "schema": str(field["schema_name"]), "table": str(field["table_name"]), "column": str(field["column_name"]), "description": str(field["description"]), "dataType": str(field["data_type"]), "legacyFields": mapped, "mappingCount": len(mapped)})
        return output

    def add_field(self, kind: FieldKind, model_name: str, metadata: dict[str, Any]) -> int:
        self._ensure()
        with self._connect() as connection:
            field_id = self._upsert_field(connection, kind, model_name, metadata.get("database"), metadata.get("schema"), metadata.get("table"), metadata.get("column"), metadata.get("description"), metadata.get("dataType"))
            self._add_field_source(connection, kind, field_id, "Manual entry", "Mapping workspace", 0)
        self._invalidate()
        return field_id

    def add_mapping(self, current_field_id: int, legacy_field_id: int) -> int:
        self._ensure()
        with self._connect() as connection:
            if connection.execute("SELECT id FROM current_fields WHERE id=?", (current_field_id,)).fetchone() is None or connection.execute("SELECT id FROM legacy_fields WHERE id=?", (legacy_field_id,)).fetchone() is None:
                raise KeyError("Current or legacy field was not found")
            connection.execute("INSERT OR IGNORE INTO mappings(legacy_field_id,current_field_id,created_at) VALUES(?,?,?)", (legacy_field_id, current_field_id, _now()))
            row = connection.execute("SELECT id FROM mappings WHERE legacy_field_id=? AND current_field_id=?", (legacy_field_id, current_field_id)).fetchone()
            assert row is not None
            mapping_id = int(row["id"])
            connection.execute("INSERT OR IGNORE INTO mapping_sources(mapping_id,source_file,source_sheet,source_row) VALUES(?,'Manual mapping','Mapping workspace',0)", (mapping_id,))
        self._invalidate()
        return mapping_id

    def delete_mapping(self, mapping_id: int) -> bool:
        self._ensure()
        with self._connect() as connection:
            deleted = connection.execute("DELETE FROM mappings WHERE id=?", (mapping_id,)).rowcount > 0
        if deleted:
            self._invalidate()
        return deleted

    def normalized(self) -> pd.DataFrame:
        relationships = self.relationships()
        records: list[dict[str, Any]] = []
        for row in relationships.to_dict(orient="records"):
            provenance = row["_provenance"] or [{"source_file": "Catalog", "source_sheet": "Inventory", "source_row": 0}]
            for source in provenance:
                records.append({
                    "legacy_model": row["legacy_model"], "legacy_database": row["legacy_database"], "legacy_schema": row["legacy_schema"], "legacy_table": row["legacy_table"], "legacy_column": row["legacy_column"], "legacy_description": row["legacy_description"], "legacy_data_type": row["legacy_data_type"],
                    "current_database": row["current_database"], "current_schema": row["current_schema"], "current_table": row["current_table"], "current_column": row["current_column"], "current_description": row["current_description"], "current_data_type": row["current_data_type"], "current_model": row["current_model"], **source,
                })
        return pd.DataFrame(records, columns=NORMALIZED_FIELDS)

    def clear(self) -> None:
        self._ensure()
        with self._connect() as connection:
            for table in ("mapping_sources", "legacy_sources", "current_sources", "mappings", "legacy_fields", "current_fields", "imports"):
                connection.execute(f"DELETE FROM {table}")
        self._invalidate()
