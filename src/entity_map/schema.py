"""Shared schema constants for normalized mappings."""

from __future__ import annotations

CANONICAL_FIELDS: tuple[str, ...] = (
    "legacy_table",
    "legacy_column",
    "legacy_description",
    "current_table",
    "current_column",
    "current_description",
)

MAPPING_METADATA_FIELDS: tuple[str, ...] = (
    "legacy_model",
    "legacy_database",
    "legacy_schema",
    "legacy_data_type",
    "current_database",
    "current_schema",
    "current_data_type",
    "current_model",
)

IDENTIFIER_FIELDS: tuple[str, ...] = (
    "legacy_table",
    "legacy_column",
    "current_table",
    "current_column",
)

PROVENANCE_FIELDS: tuple[str, ...] = (
    "source_file",
    "source_sheet",
    "source_row",
)

MAPPING_FIELDS: tuple[str, ...] = CANONICAL_FIELDS + MAPPING_METADATA_FIELDS
NORMALIZED_FIELDS: tuple[str, ...] = MAPPING_FIELDS + PROVENANCE_FIELDS

FIELD_LABELS: dict[str, str] = {
    "legacy_table": "Legacy table",
    "legacy_column": "Legacy column",
    "legacy_description": "Legacy description",
    "current_table": "Current table",
    "current_column": "Current column",
    "current_description": "Current description",
    "legacy_database": "Legacy database",
    "legacy_model": "Legacy model",
    "legacy_schema": "Legacy schema",
    "legacy_data_type": "Legacy data type",
    "current_database": "Current database",
    "current_schema": "Current schema",
    "current_data_type": "Current data type",
    "current_model": "Current model",
    "source_file": "Source file",
    "source_sheet": "Source sheet",
    "source_row": "Source row",
    "mapping_state": "Status",
    "provenance_count": "Sources",
}
