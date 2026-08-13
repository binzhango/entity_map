"""Relationship grouping and deterministic catalog search."""

from __future__ import annotations

from typing import Iterable

import pandas as pd

from .schema import CANONICAL_FIELDS, MAPPING_METADATA_FIELDS, NORMALIZED_FIELDS

RELATIONSHIP_KEYS: tuple[str, ...] = (
    "legacy_model",
    "legacy_table",
    "legacy_column",
    "current_model",
    "current_table",
    "current_column",
)

DISPLAY_FIELDS: tuple[str, ...] = (
    "legacy_model",
    "legacy_database",
    "legacy_schema",
    "legacy_data_type",
    "legacy_table",
    "legacy_column",
    "legacy_description",
    "current_table",
    "current_column",
    "current_description",
    "current_model",
    "current_database",
    "current_schema",
    "current_data_type",
    "mapping_state",
    "unmapped_side",
    "provenance_count",
    "source_files",
)


def _first_nonempty(values: Iterable[object]) -> str:
    for value in values:
        text = str(value).strip()
        if text:
            return text
    return ""


def group_relationships(normalized: pd.DataFrame) -> pd.DataFrame:
    """Group duplicate relationships and retain complete row provenance."""

    required = (*CANONICAL_FIELDS, "source_file", "source_sheet", "source_row")
    missing = [field for field in required if field not in normalized.columns]
    if missing:
        raise ValueError(f"Normalized data is missing fields: {', '.join(missing)}")
    normalized = normalized.copy()
    for field in MAPPING_METADATA_FIELDS:
        if field not in normalized.columns:
            normalized[field] = ""
    if normalized.empty:
        return pd.DataFrame(columns=(*DISPLAY_FIELDS, "_provenance"))

    rows: list[dict[str, object]] = []
    grouped = normalized.groupby(list(RELATIONSHIP_KEYS), dropna=False, sort=False)
    for keys, group in grouped:
        legacy_model, legacy_table, legacy_column, current_model, current_table, current_column = (
            str(value).strip() for value in keys
        )
        provenance = [
            {
                "source_file": str(record.source_file),
                "source_sheet": str(record.source_sheet),
                "source_row": int(record.source_row),
            }
            for record in group[["source_file", "source_sheet", "source_row"]].itertuples(
                index=False
            )
        ]
        source_files = sorted({item["source_file"] for item in provenance})
        legacy_present = bool(legacy_table and legacy_column)
        current_present = bool(current_table and current_column)
        rows.append(
            {
                "legacy_table": legacy_table,
                "legacy_column": legacy_column,
                "legacy_description": _first_nonempty(group["legacy_description"]),
                "legacy_model": _first_nonempty(group["legacy_model"]),
                "legacy_database": _first_nonempty(group["legacy_database"]),
                "legacy_schema": _first_nonempty(group["legacy_schema"]),
                "legacy_data_type": _first_nonempty(group["legacy_data_type"]),
                "current_table": current_table,
                "current_column": current_column,
                "current_description": _first_nonempty(group["current_description"]),
                "current_model": _first_nonempty(group["current_model"]),
                "current_database": _first_nonempty(group["current_database"]),
                "current_schema": _first_nonempty(group["current_schema"]),
                "current_data_type": _first_nonempty(group["current_data_type"]),
                "mapping_state": "Mapped" if legacy_present and current_present else "Unmapped",
                "unmapped_side": "legacy" if legacy_present and not current_present else ("current" if current_present and not legacy_present else ""),
                "provenance_count": len(provenance),
                "source_files": ", ".join(source_files),
                "_provenance": provenance,
            }
        )
    return pd.DataFrame(rows, columns=(*DISPLAY_FIELDS, "_provenance"))


def _normalized(series: pd.Series) -> pd.Series:
    return series.fillna("").astype(str).str.strip().str.casefold()


def search_relationships(
    relationships: pd.DataFrame,
    query: str = "",
    *,
    scope: str = "legacy",
    legacy_tables: Iterable[str] | None = None,
    current_tables: Iterable[str] | None = None,
    mapping_states: Iterable[str] | None = None,
    source_files: Iterable[str] | None = None,
    legacy_models: Iterable[str] | None = None,
    current_models: Iterable[str] | None = None,
) -> pd.DataFrame:
    """Filter and rank relationships by a legacy or current field query."""

    if relationships.empty:
        return relationships.copy()

    result = relationships.copy()
    if scope not in {"legacy", "current"}:
        raise ValueError("Search scope must be 'legacy' or 'current'.")
    table_values = _normalized(result[f"{scope}_table"])
    column_values = _normalized(result[f"{scope}_column"])

    text = str(query).strip().casefold()
    if text:
        if "." in text:
            table_query, column_query = (part.strip() for part in text.rsplit(".", 1))
            table_contains = table_values.str.contains(table_query, regex=False)
            column_contains = column_values.str.contains(column_query, regex=False)
            matches = table_contains & column_contains
            exact = table_values.eq(table_query) & column_values.eq(column_query)
            column_exact = column_contains & column_values.eq(column_query)
            result = result.loc[matches].copy()
            result["_search_rank"] = 2
            result.loc[exact.loc[matches], "_search_rank"] = 0
            result.loc[(column_exact & ~exact).loc[matches], "_search_rank"] = 1
        else:
            matches = column_values.str.contains(text, regex=False)
            exact = column_values.eq(text)
            result = result.loc[matches].copy()
            result["_search_rank"] = 1
            result.loc[exact.loc[matches], "_search_rank"] = 0
    else:
        result["_search_rank"] = 0

    def apply_exact_filter(frame: pd.DataFrame, column: str, selected: Iterable[str] | None) -> pd.DataFrame:
        choices = {str(value).strip().casefold() for value in (selected or []) if str(value).strip()}
        if not choices:
            return frame
        return frame.loc[_normalized(frame[column]).isin(choices)]

    result = apply_exact_filter(result, "legacy_table", legacy_tables)
    result = apply_exact_filter(result, "current_table", current_tables)
    result = apply_exact_filter(result, "mapping_state", mapping_states)
    if "legacy_model" in result:
        result = apply_exact_filter(result, "legacy_model", legacy_models)
    if "current_model" in result:
        choices = {str(value).strip().casefold() for value in (current_models or []) if str(value).strip()}
        if choices:
            current_values = _normalized(result["current_model"])
            unmapped = _normalized(result["mapping_state"]).eq("unmapped")
            result = result.loc[current_values.isin(choices) | unmapped]

    selected_files = {str(value).strip().casefold() for value in (source_files or []) if str(value).strip()}
    if selected_files:
        result = result.loc[
            result["_provenance"].map(
                lambda records: any(
                    str(record["source_file"]).strip().casefold() in selected_files
                    for record in records
                )
            )
        ]

    scope_fields = [
        field
        for field in (f"{scope}_model", f"{scope}_table", f"{scope}_column")
        if field in result
    ]
    other_fields = [
        field
        for field in ("legacy_model", "legacy_table", "legacy_column", "current_model", "current_table", "current_column")
        if field in result and field not in scope_fields
    ]
    sort_fields = ["_search_rank", *scope_fields, *other_fields]
    result = result.sort_values(sort_fields, kind="stable")
    return result.drop(columns="_search_rank").reset_index(drop=True)


def relationships_for_legacy_field(
    relationships: pd.DataFrame, legacy_table: str, legacy_column: str, legacy_model: str | None = None
) -> pd.DataFrame:
    """Return every target for one exact legacy table/column pair."""

    if relationships.empty:
        return relationships.copy()
    table = str(legacy_table).strip().casefold()
    column = str(legacy_column).strip().casefold()
    mask = _normalized(relationships["legacy_table"]).eq(table) & _normalized(
        relationships["legacy_column"]
    ).eq(column)
    if legacy_model is not None and "legacy_model" in relationships:
        mask &= _normalized(relationships["legacy_model"]).eq(str(legacy_model).strip().casefold())
    return relationships.loc[mask].reset_index(drop=True)


def relationships_for_current_field(
    relationships: pd.DataFrame, current_table: str, current_column: str, current_model: str | None = None
) -> pd.DataFrame:
    """Return every legacy source for one exact current table/column pair."""

    if relationships.empty:
        return relationships.copy()
    table = str(current_table).strip().casefold()
    column = str(current_column).strip().casefold()
    mask = _normalized(relationships["current_table"]).eq(table) & _normalized(
        relationships["current_column"]
    ).eq(column)
    if current_model is not None and "current_model" in relationships:
        mask &= _normalized(relationships["current_model"]).eq(str(current_model).strip().casefold())
    return relationships.loc[mask].reset_index(drop=True)
