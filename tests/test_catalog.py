from __future__ import annotations

import time

import pandas as pd

from entity_map.catalog import (
    group_relationships,
    relationships_for_legacy_field,
    search_relationships,
)


def normalized_rows() -> pd.DataFrame:
    rows = [
        ("CLIENT", "CLINETN_ID", "Unique client identifier", "CUSTOMER", "ID", "Primary key", "one.xlsx", "Map", 2),
        ("CLIENT", "CLINETN_ID", "Unique client identifier", "CUSTOMER", "ID", "Primary key", "two.xlsx", "Data", 8),
        ("CLIENT", "CLINETN_ID", "Unique client identifier", "CUSTOMER", "EXTERNAL_ID", "External key", "one.xlsx", "Map", 3),
        ("CLIENT", "CLIENT_NAME", "Name", "CUSTOMER", "FULL_NAME", "Full name", "one.xlsx", "Map", 4),
        ("TRANS", "TRAN_AMT", "Amount", "TRANSACTION", "AMOUNT", "Money", "one.xlsx", "Map", 5),
        ("TRANS", "TRAN_DT", "Date", "TRANSACTION", "TX_DATE", "Date", "one.xlsx", "Map", 6),
        ("CLIENT", "OLD_CODE", "Old code", "", "", "", "one.xlsx", "Map", 7),
    ]
    return pd.DataFrame(
        rows,
        columns=[
            "legacy_table",
            "legacy_column",
            "legacy_description",
            "current_table",
            "current_column",
            "current_description",
            "source_file",
            "source_sheet",
            "source_row",
        ],
    )


def test_grouping_retains_duplicate_provenance_and_one_to_many() -> None:
    grouped = group_relationships(normalized_rows())
    client_id = relationships_for_legacy_field(grouped, "client", "clinetn_id")
    assert len(client_id) == 2
    primary = client_id.loc[client_id["current_column"].eq("ID")].iloc[0]
    assert primary["provenance_count"] == 2
    assert {record["source_file"] for record in primary["_provenance"]} == {
        "one.xlsx",
        "two.xlsx",
    }


def test_acceptance_searches_return_expected_targets() -> None:
    grouped = group_relationships(normalized_rows())
    expected = {
        "CLINETN_ID": {"ID", "EXTERNAL_ID"},
        "CLIENT_NAME": {"FULL_NAME"},
        "TRAN_AMT": {"AMOUNT"},
        "TRAN_DT": {"TX_DATE"},
    }
    for query, current_columns in expected.items():
        result = search_relationships(grouped, query)
        assert set(result["current_column"]) == current_columns


def test_search_is_case_insensitive_qualified_and_exact_first() -> None:
    grouped = group_relationships(normalized_rows())
    partial = search_relationships(grouped, "id")
    assert partial.iloc[0]["legacy_column"] == "CLINETN_ID"
    qualified = search_relationships(grouped, " client.clinetn_id ")
    assert set(qualified["current_column"]) == {"ID", "EXTERNAL_ID"}
    assert search_relationships(grouped, "trans.clinetn_id").empty


def test_search_scope_can_query_current_schema() -> None:
    grouped = group_relationships(normalized_rows())
    qualified = search_relationships(grouped, "customer.id", scope="current")
    assert qualified.iloc[0]["current_column"] == "ID"
    assert qualified["legacy_column"].tolist() == ["CLINETN_ID", "CLINETN_ID"]
    partial = search_relationships(grouped, "amount", scope="current")
    assert partial.iloc[0]["legacy_column"] == "TRAN_AMT"
    assert search_relationships(grouped, "OLD_CODE", scope="current").empty


def test_filters_keep_mapped_unmapped_and_provenance_sources() -> None:
    grouped = group_relationships(normalized_rows())
    unmapped = search_relationships(grouped, mapping_states=["Unmapped"])
    assert unmapped["legacy_column"].tolist() == ["OLD_CODE"]
    from_second_file = search_relationships(grouped, source_files=["two.xlsx"])
    assert len(from_second_file) == 1
    assert from_second_file.iloc[0]["current_column"] == "ID"
    current = search_relationships(grouped, current_tables=["transaction"])
    assert set(current["legacy_column"]) == {"TRAN_AMT", "TRAN_DT"}


def test_search_100k_rows_under_one_second() -> None:
    size = 100_000
    relationships = pd.DataFrame(
        {
            "legacy_table": [f"TABLE_{i % 100}" for i in range(size)],
            "legacy_column": [f"COLUMN_{i}" for i in range(size)],
            "legacy_description": [""] * size,
            "current_table": ["TARGET"] * size,
            "current_column": [f"FIELD_{i}" for i in range(size)],
            "current_description": [""] * size,
            "mapping_state": ["Mapped"] * size,
            "provenance_count": [1] * size,
            "source_files": ["large.csv"] * size,
            "_provenance": [[{"source_file": "large.csv", "source_sheet": "CSV", "source_row": i + 2}] for i in range(size)],
        }
    )
    started = time.perf_counter()
    result = search_relationships(relationships, "TABLE_99.COLUMN_99999")
    elapsed = time.perf_counter() - started
    assert len(result) == 1
    assert elapsed < 1.0, f"Search took {elapsed:.3f}s"
