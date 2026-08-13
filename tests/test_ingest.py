from __future__ import annotations

from io import BytesIO
from pathlib import Path

import pandas as pd
import pytest

from entity_map.ingest import (
    CSV_SHEET_NAME,
    ImportFormatError,
    auto_normalize_inventory,
    auto_normalize_mapping,
    combine_results,
    guess_header_row,
    list_sheets,
    normalize_frame,
    normalized_to_csv,
    read_preview,
    read_sheet,
    suggest_header_assignments,
)
from entity_map.schema import CANONICAL_FIELDS, NORMALIZED_FIELDS

FIXTURES = Path(__file__).parent / "fixtures"


def canonical_assignment(columns: list[str]) -> dict[str, str | None]:
    suggestions = suggest_header_assignments(columns)
    assert all(suggestions[field] for field in CANONICAL_FIELDS)
    return suggestions


def test_csv_parse_suggest_normalize_and_provenance() -> None:
    content = (FIXTURES / "example_mapping.csv").read_bytes()
    assert list_sheets(content, "mapping.csv") == [CSV_SHEET_NAME]
    frame = read_sheet(content, "mapping.csv")
    result = normalize_frame(
        frame,
        canonical_assignment(list(frame.columns)),
        source_file="mapping.csv",
        source_sheet=CSV_SHEET_NAME,
    )
    assert result.invalid.empty
    assert result.valid["legacy_column"].tolist() == [
        "CLINETN_ID",
        "CLIENT_NAME",
        "TRAN_AMT",
        "TRAN_DT",
    ]
    assert result.valid["source_row"].tolist() == [2, 3, 4, 5]


def test_non_first_header_row_is_detected_and_preserves_excel_row_number() -> None:
    raw = pd.DataFrame(
        [
            ["Migration workbook", "", "", "", "", ""],
            ["Legacy Table", "Legacy Column", "Legacy Description", "Current Table", "Current Column", "Current Description"],
            ["CLIENT", "ID", "Old ID", "CUSTOMER", "ID", "New ID"],
        ]
    )
    buffer = BytesIO()
    raw.to_excel(buffer, index=False, header=False, sheet_name="Mappings")
    content = buffer.getvalue()
    assert list_sheets(content, "mapping.xlsx") == ["Mappings"]
    preview = read_preview(content, "mapping.xlsx", "Mappings")
    assert guess_header_row(preview) == 1
    frame = read_sheet(content, "mapping.xlsx", "Mappings", header_row=1)
    result = normalize_frame(
        frame,
        canonical_assignment(list(frame.columns)),
        source_file="mapping.xlsx",
        source_sheet="Mappings",
        header_row=1,
    )
    assert result.valid.loc[0, "source_row"] == 3


def test_sheet_selection_reads_only_requested_sheet() -> None:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        pd.DataFrame({"Legacy Table": ["A"], "Legacy Column": ["X"]}).to_excel(
            writer, sheet_name="One", index=False
        )
        pd.DataFrame({"Legacy Table": ["B"], "Legacy Column": ["Y"]}).to_excel(
            writer, sheet_name="Two", index=False
        )
    content = buffer.getvalue()
    assert list_sheets(content, "book.xlsx") == ["One", "Two"]
    assert read_sheet(content, "book.xlsx", "Two").iloc[0, 0] == "B"


def test_validation_allows_unmapped_and_rejects_partial_targets() -> None:
    frame = pd.DataFrame(
        {
            "old table": ["CLIENT", "CLIENT", ""],
            "old col": ["A", "B", "C"],
            "new table": ["", "CUSTOMER", "CUSTOMER"],
            "new col": ["", "", "ID"],
        }
    )
    assignments = {
        "legacy_table": "old table",
        "legacy_column": "old col",
        "legacy_description": None,
        "current_table": "new table",
        "current_column": "new col",
        "current_description": None,
    }
    result = normalize_frame(
        frame, assignments, source_file="rows.csv", source_sheet=CSV_SHEET_NAME
    )
    assert len(result.valid) == 1
    assert result.valid.loc[0, "current_table"] == ""
    assert len(result.invalid) == 2
    assert "both be populated" in result.invalid.loc[0, "validation_error"]
    assert "Legacy table is required" in result.invalid.loc[1, "validation_error"]


def test_assignment_errors_are_actionable() -> None:
    frame = pd.DataFrame({"A": [1]})
    with pytest.raises(ImportFormatError, match="Legacy table must be assigned"):
        normalize_frame(frame, {}, source_file="a.csv", source_sheet=CSV_SHEET_NAME)


def test_combine_and_normalized_csv_round_trip() -> None:
    content = (FIXTURES / "example_mapping.csv").read_bytes()
    frame = read_sheet(content, "mapping.csv")
    result = normalize_frame(
        frame,
        canonical_assignment(list(frame.columns)),
        source_file="mapping.csv",
        source_sheet=CSV_SHEET_NAME,
    )
    combined = combine_results([result, result])
    encoded = normalized_to_csv(combined.valid)
    round_trip = pd.read_csv(BytesIO(encoded), dtype=str, keep_default_na=False)
    assert list(round_trip.columns) == list(NORMALIZED_FIELDS)
    assert len(round_trip) == 8


def test_unsupported_file_type() -> None:
    with pytest.raises(ImportFormatError, match="Unsupported file type"):
        list_sheets(b"anything", "mapping.xls")


def test_automatic_inventory_import_detects_non_first_header() -> None:
    content = (
        b"Current schema export,,\n"
        b"Table Name,Column Name,Description\n"
        b"CUSTOMER,ID,Primary key\n"
        b"CUSTOMER,FULL_NAME,Full name\n"
    )
    result = auto_normalize_inventory(content, "current.csv")
    assert result.invalid.empty
    assert result.valid["column_name"].tolist() == ["ID", "FULL_NAME"]
    assert result.valid["source_row"].tolist() == [3, 4]


def test_automatic_mapping_import_uses_all_excel_sheets() -> None:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        for sheet, legacy_column in (("Customers", "CLIENT_ID"), ("Orders", "ORDER_ID")):
            pd.DataFrame(
                {
                    "Legacy Table": ["OLD"],
                    "Legacy Column": [legacy_column],
                    "Current Table": ["NEW"],
                    "Current Column": [legacy_column],
                }
            ).to_excel(writer, sheet_name=sheet, index=False)
    result = auto_normalize_mapping(buffer.getvalue(), "mappings.xlsx")
    assert result.invalid.empty
    assert set(result.valid["source_sheet"]) == {"Customers", "Orders"}
