"""Spreadsheet inspection and normalization."""

from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from pathlib import Path
import re
from typing import Mapping, Sequence

import pandas as pd

from .schema import CANONICAL_FIELDS, MAPPING_FIELDS, NORMALIZED_FIELDS

CSV_SHEET_NAME = "CSV"


class ImportFormatError(ValueError):
    """Raised when an uploaded file cannot be inspected or normalized."""


@dataclass(frozen=True)
class NormalizationResult:
    """Valid and invalid rows produced from one spreadsheet sheet."""

    valid: pd.DataFrame
    invalid: pd.DataFrame


@dataclass(frozen=True)
class InventoryResult:
    """Valid and invalid rows produced from a field inventory."""

    valid: pd.DataFrame
    invalid: pd.DataFrame


_HEADER_ALIASES: dict[str, tuple[str, ...]] = {
    "legacy_model": ("legacy model", "source model", "old model", "from model"),
    "legacy_database": ("legacy database", "source database", "old database", "from database", "database"),
    "legacy_schema": ("legacy schema", "source schema", "old schema", "from schema", "schema"),
    "legacy_data_type": ("legacy data type", "source data type", "old data type", "from data type", "legacy type"),
    "legacy_table": (
        "legacy table",
        "source table",
        "old table",
        "legacy table name",
        "source table name",
        "from table",
    ),
    "legacy_column": (
        "legacy column",
        "source column",
        "old column",
        "legacy column name",
        "source column name",
        "from column",
    ),
    "legacy_description": (
        "legacy description",
        "source description",
        "old description",
        "legacy column description",
        "source column description",
        "from description",
    ),
    "current_table": (
        "current table",
        "target table",
        "new table",
        "current table name",
        "target table name",
        "to table",
    ),
    "current_column": (
        "current column",
        "target column",
        "new column",
        "current column name",
        "target column name",
        "to column",
    ),
    "current_description": (
        "current description",
        "target description",
        "new description",
        "current column description",
        "target column description",
        "to description",
    ),
    "current_database": ("current database", "target database", "new database", "to database"),
    "current_schema": ("current schema", "target schema", "new schema", "to schema"),
    "current_data_type": ("current data type", "target data type", "new data type", "to data type", "current type"),
    "current_model": ("current model", "target model", "new model", "to model"),
}

_INVENTORY_ALIASES: dict[str, tuple[str, ...]] = {
    "database_name": ("database", "database name", "db", "catalog"),
    "schema_name": ("schema", "schema name", "owner"),
    "table_name": ("table", "table name", "entity", "entity name"),
    "column_name": (
        "column",
        "column name",
        "field",
        "field name",
        "attribute",
        "attribute name",
    ),
    "description": ("description", "field description", "column description", "definition"),
    "data_type": ("data type", "datatype", "type", "column type", "field type"),
}

INVENTORY_FIELDS: tuple[str, ...] = (
    "database_name",
    "schema_name",
    "table_name",
    "column_name",
    "description",
    "data_type",
    "source_file",
    "source_sheet",
    "source_row",
)


def _extension(filename: str) -> str:
    return Path(filename).suffix.casefold()


def _assert_supported(filename: str) -> str:
    extension = _extension(filename)
    if extension not in {".csv", ".xlsx"}:
        raise ImportFormatError(
            f"Unsupported file type for {filename!r}; upload a .csv or .xlsx file."
        )
    return extension


def list_sheets(content: bytes, filename: str) -> list[str]:
    """Return selectable sheet names for an uploaded file."""

    extension = _assert_supported(filename)
    if extension == ".csv":
        return [CSV_SHEET_NAME]
    try:
        with pd.ExcelFile(BytesIO(content), engine="openpyxl") as workbook:
            return list(workbook.sheet_names)
    except Exception as exc:  # pandas/openpyxl expose several parse exceptions
        raise ImportFormatError(f"Could not read Excel workbook {filename!r}: {exc}") from exc


def read_preview(
    content: bytes,
    filename: str,
    sheet_name: str = CSV_SHEET_NAME,
    *,
    rows: int = 12,
) -> pd.DataFrame:
    """Read raw rows without interpreting any row as a header."""

    extension = _assert_supported(filename)
    try:
        if extension == ".csv":
            frame = pd.read_csv(
                BytesIO(content),
                header=None,
                nrows=rows,
                dtype=str,
                keep_default_na=False,
            )
        else:
            frame = pd.read_excel(
                BytesIO(content),
                sheet_name=sheet_name,
                header=None,
                nrows=rows,
                dtype=str,
                keep_default_na=False,
                engine="openpyxl",
            )
    except Exception as exc:
        raise ImportFormatError(
            f"Could not preview {filename!r}, sheet {sheet_name!r}: {exc}"
        ) from exc
    return frame.fillna("")


def read_sheet(
    content: bytes,
    filename: str,
    sheet_name: str = CSV_SHEET_NAME,
    *,
    header_row: int = 0,
) -> pd.DataFrame:
    """Read a complete sheet using a zero-based header row."""

    if header_row < 0:
        raise ImportFormatError("Header row must be zero or greater.")
    extension = _assert_supported(filename)
    try:
        if extension == ".csv":
            frame = pd.read_csv(
                BytesIO(content),
                header=header_row,
                dtype=str,
                keep_default_na=False,
            )
        else:
            frame = pd.read_excel(
                BytesIO(content),
                sheet_name=sheet_name,
                header=header_row,
                dtype=str,
                keep_default_na=False,
                engine="openpyxl",
            )
    except Exception as exc:
        raise ImportFormatError(
            f"Could not read {filename!r}, sheet {sheet_name!r}: {exc}"
        ) from exc

    frame = frame.fillna("")
    frame.columns = [str(column).strip() for column in frame.columns]
    return frame


def _normalize_header(value: object) -> str:
    words = re.sub(r"[^a-z0-9]+", " ", str(value).casefold()).strip()
    return " ".join(words.split())


def suggest_header_assignments(columns: Sequence[object]) -> dict[str, str | None]:
    """Suggest canonical assignments using conservative, deterministic aliases."""

    normalized_columns = {str(column): _normalize_header(column) for column in columns}
    suggestions: dict[str, str | None] = {field: None for field in MAPPING_FIELDS}
    used: set[str] = set()

    for field in MAPPING_FIELDS:
        aliases = {_normalize_header(field), *(_normalize_header(a) for a in _HEADER_ALIASES[field])}
        exact = [
            column
            for column, normalized in normalized_columns.items()
            if normalized in aliases and column not in used
        ]
        if exact:
            suggestions[field] = exact[0]
            used.add(exact[0])
    return suggestions


def guess_header_row(preview: pd.DataFrame) -> int:
    """Choose the preview row containing the most recognizable mapping headers."""

    if preview.empty:
        return 0
    best_row = 0
    best_score = -1
    for position, (_, row) in enumerate(preview.iterrows()):
        suggestions = suggest_header_assignments([value for value in row.tolist() if str(value).strip()])
        score = sum(value is not None for value in suggestions.values())
        if score > best_score:
            best_score = score
            best_row = position
    return best_row


def suggest_inventory_assignments(columns: Sequence[object]) -> dict[str, str | None]:
    """Detect table, column, and optional description headers in an inventory."""

    normalized_columns = {str(column): _normalize_header(column) for column in columns}
    suggestions: dict[str, str | None] = {field: None for field in _INVENTORY_ALIASES}
    used: set[str] = set()
    for field, aliases in _INVENTORY_ALIASES.items():
        accepted = {_normalize_header(field), *(_normalize_header(alias) for alias in aliases)}
        match = next(
            (
                column
                for column, normalized in normalized_columns.items()
                if column not in used and normalized in accepted
            ),
            None,
        )
        if match is not None:
            suggestions[field] = match
            used.add(match)
    return suggestions


def guess_inventory_header_row(preview: pd.DataFrame) -> int:
    """Choose the row that most resembles a table/column inventory header."""

    if preview.empty:
        return 0
    best_row = 0
    best_score = -1
    for position, (_, row) in enumerate(preview.iterrows()):
        suggestions = suggest_inventory_assignments(
            [value for value in row.tolist() if str(value).strip()]
        )
        score = sum(value is not None for value in suggestions.values())
        if suggestions["table_name"] and suggestions["column_name"]:
            score += 3
        if score > best_score:
            best_score = score
            best_row = position
    return best_row


def header_signature(columns: Sequence[object]) -> tuple[str, ...]:
    """Return a stable signature used to share assignments across like-shaped sheets."""

    return tuple(_normalize_header(column) for column in columns)


def validate_assignments(
    columns: Sequence[object], assignments: Mapping[str, str | None]
) -> list[str]:
    """Validate a canonical-to-spreadsheet column assignment."""

    errors: list[str] = []
    column_names = {str(column) for column in columns}
    assigned = [str(value) for value in assignments.values() if value]

    for required in ("legacy_table", "legacy_column"):
        if not assignments.get(required):
            errors.append(f"{required.replace('_', ' ').capitalize()} must be assigned.")

    if len(assigned) != len(set(assigned)):
        errors.append("A spreadsheet column cannot be assigned to more than one field.")

    unknown = sorted(set(assigned) - column_names)
    if unknown:
        errors.append(f"Assigned columns were not found: {', '.join(unknown)}.")
    return errors


def _clean_series(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip()


def normalize_frame(
    frame: pd.DataFrame,
    assignments: Mapping[str, str | None],
    *,
    source_file: str,
    source_sheet: str,
    header_row: int = 0,
) -> NormalizationResult:
    """Normalize one parsed sheet and split valid from invalid rows."""

    assignment_errors = validate_assignments(frame.columns, assignments)
    if assignment_errors:
        raise ImportFormatError(" ".join(assignment_errors))

    normalized = pd.DataFrame(index=frame.index)
    for field in MAPPING_FIELDS:
        source_column = assignments.get(field)
        if source_column:
            normalized[field] = _clean_series(frame[str(source_column)])
        else:
            normalized[field] = ""

    normalized["source_file"] = source_file
    normalized["source_sheet"] = source_sheet
    # The header is one-based header_row + 1; the first data row follows it.
    normalized["source_row"] = [header_row + position + 2 for position in range(len(frame))]

    blank_row = normalized[list(CANONICAL_FIELDS)].eq("").all(axis=1)
    normalized = normalized.loc[~blank_row].reset_index(drop=True)

    missing_legacy_table = normalized["legacy_table"].eq("")
    missing_legacy_column = normalized["legacy_column"].eq("")
    partial_target = normalized["current_table"].eq("") ^ normalized["current_column"].eq("")

    error_parts = pd.DataFrame(
        {
            "missing_legacy_table": missing_legacy_table,
            "missing_legacy_column": missing_legacy_column,
            "partial_target": partial_target,
        }
    )

    def describe_error(row: pd.Series) -> str:
        messages: list[str] = []
        if row["missing_legacy_table"]:
            messages.append("Legacy table is required")
        if row["missing_legacy_column"]:
            messages.append("Legacy column is required")
        if row["partial_target"]:
            messages.append("Current table and column must both be populated or both be empty")
        return "; ".join(messages)

    errors = error_parts.apply(describe_error, axis=1)
    invalid_mask = errors.ne("")
    valid = normalized.loc[~invalid_mask, list(NORMALIZED_FIELDS)].reset_index(drop=True)
    invalid = normalized.loc[invalid_mask, list(NORMALIZED_FIELDS)].copy()
    invalid["validation_error"] = errors.loc[invalid_mask].values
    invalid = invalid.reset_index(drop=True)
    return NormalizationResult(valid=valid, invalid=invalid)


def combine_results(results: Sequence[NormalizationResult]) -> NormalizationResult:
    """Combine sheet-level normalization results while preserving the schema."""

    valid_frames = [result.valid for result in results if not result.valid.empty]
    invalid_frames = [result.invalid for result in results if not result.invalid.empty]
    valid = (
        pd.concat(valid_frames, ignore_index=True)
        if valid_frames
        else pd.DataFrame(columns=NORMALIZED_FIELDS)
    )
    invalid_columns = (*NORMALIZED_FIELDS, "validation_error")
    invalid = (
        pd.concat(invalid_frames, ignore_index=True)
        if invalid_frames
        else pd.DataFrame(columns=invalid_columns)
    )
    return NormalizationResult(valid=valid, invalid=invalid)


def normalized_to_csv(frame: pd.DataFrame) -> bytes:
    """Serialize normalized data in a spreadsheet-friendly UTF-8 CSV."""

    missing = [field for field in NORMALIZED_FIELDS if field not in frame.columns]
    if missing:
        raise ValueError(f"Normalized data is missing fields: {', '.join(missing)}")
    return frame.loc[:, list(NORMALIZED_FIELDS)].to_csv(index=False).encode("utf-8-sig")


def auto_normalize_mapping(content: bytes, filename: str) -> NormalizationResult:
    """Normalize every sheet in a paired mapping file using detected headers."""

    results: list[NormalizationResult] = []
    for sheet_name in list_sheets(content, filename):
        preview = read_preview(content, filename, sheet_name, rows=15)
        header_row = guess_header_row(preview)
        frame = read_sheet(content, filename, sheet_name, header_row=header_row)
        assignments = suggest_header_assignments(frame.columns)
        if not assignments["legacy_table"] or not assignments["legacy_column"]:
            raise ImportFormatError(
                f"Could not find legacy table and legacy column headers in "
                f"{filename!r}, sheet {sheet_name!r}."
            )
        results.append(
            normalize_frame(
                frame,
                assignments,
                source_file=filename,
                source_sheet=sheet_name,
                header_row=header_row,
            )
        )
    return combine_results(results)


def auto_normalize_inventory(content: bytes, filename: str) -> InventoryResult:
    """Normalize all sheets in a legacy or current three-column inventory."""

    valid_frames: list[pd.DataFrame] = []
    invalid_frames: list[pd.DataFrame] = []
    for sheet_name in list_sheets(content, filename):
        preview = read_preview(content, filename, sheet_name, rows=15)
        header_row = guess_inventory_header_row(preview)
        frame = read_sheet(content, filename, sheet_name, header_row=header_row)
        assignments = suggest_inventory_assignments(frame.columns)
        if not assignments["table_name"] or not assignments["column_name"]:
            raise ImportFormatError(
                f"Could not find table and column headers in {filename!r}, "
                f"sheet {sheet_name!r}."
            )

        normalized = pd.DataFrame(index=frame.index)
        for field in _INVENTORY_ALIASES:
            source = assignments[field]
            normalized[field] = _clean_series(frame[str(source)]) if source else ""
        normalized["source_file"] = filename
        normalized["source_sheet"] = sheet_name
        normalized["source_row"] = [header_row + position + 2 for position in range(len(frame))]

        blank = normalized[["table_name", "column_name", "description"]].eq("").all(axis=1)
        normalized = normalized.loc[~blank].reset_index(drop=True)
        missing_table = normalized["table_name"].eq("")
        missing_column = normalized["column_name"].eq("")
        invalid_mask = missing_table | missing_column
        valid_frames.append(
            normalized.loc[~invalid_mask, list(INVENTORY_FIELDS)].reset_index(drop=True)
        )
        invalid = normalized.loc[invalid_mask, list(INVENTORY_FIELDS)].copy()
        invalid["validation_error"] = [
            "; ".join(
                message
                for condition, message in (
                    (bool(no_table), "Table is required"),
                    (bool(no_column), "Column is required"),
                )
                if condition
            )
            for no_table, no_column in zip(
                missing_table.loc[invalid_mask], missing_column.loc[invalid_mask], strict=True
            )
        ]
        invalid_frames.append(invalid.reset_index(drop=True))

    valid = (
        pd.concat(valid_frames, ignore_index=True)
        if valid_frames
        else pd.DataFrame(columns=INVENTORY_FIELDS)
    )
    invalid_columns = (*INVENTORY_FIELDS, "validation_error")
    invalid = (
        pd.concat(invalid_frames, ignore_index=True)
        if invalid_frames
        else pd.DataFrame(columns=invalid_columns)
    )
    return InventoryResult(valid=valid, invalid=invalid)
