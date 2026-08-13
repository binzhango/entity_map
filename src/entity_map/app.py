"""FastAPI application for the persistent Entity Map catalog."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Annotated, Any, Literal

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles
import pandas as pd
from pydantic import BaseModel, ConfigDict, Field, ValidationError

from .catalog import relationships_for_current_field, relationships_for_legacy_field, search_relationships
from .ingest import (
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
from .repository import CatalogRepository
from .schema import CANONICAL_FIELDS


class SheetConfiguration(BaseModel):
    """Compatibility model for the original configurable import endpoint."""

    model_config = ConfigDict(populate_by_name=True)

    file_index: int = Field(alias="fileIndex", ge=0)
    sheet_name: str = Field(alias="sheetName", min_length=1)
    header_row: int = Field(alias="headerRow", ge=0)
    assignments: dict[str, str | None]


class NormalizeRequest(BaseModel):
    sheets: list[SheetConfiguration] = Field(min_length=1)


class MappingRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    current_field_id: int = Field(alias="currentFieldId", gt=0)
    legacy_field_id: int = Field(alias="legacyFieldId", gt=0)


class FieldRequest(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    kind: Literal["legacy", "current"]
    model: str = Field(min_length=1)
    database: str = ""
    schema_name: str = Field(default="", alias="schema")
    table: str = Field(min_length=1)
    column: str = Field(min_length=1)
    description: str = ""
    data_type: str = Field(default="", alias="dataType")


def _default_database_path() -> Path:
    configured = os.environ.get("ENTITY_MAP_DB_PATH")
    if configured:
        return Path(configured).expanduser()
    return Path.home() / ".entity-map" / "catalog.db"


def _clean_json_value(value: Any) -> Any:
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return ""
    if hasattr(value, "item"):
        return value.item()
    return value


def _records(frame: pd.DataFrame, *, exclude: set[str] | None = None) -> list[dict[str, Any]]:
    excluded = exclude or set()
    return [
        {key: _clean_json_value(value) for key, value in row.items() if key not in excluded}
        for row in frame.to_dict(orient="records")
    ]


def _sorted_unique(series: pd.Series) -> list[str]:
    values = {str(value).strip() for value in series if str(value).strip()}
    return sorted(values, key=str.casefold)


def _repository(app: FastAPI) -> CatalogRepository:
    return app.state.catalog


def _filters(repository: CatalogRepository) -> dict[str, Any]:
    relationships = repository.relationships()
    if relationships.empty:
        return {
            "legacyTables": [],
            "currentTables": [],
            "mappingStates": ["Mapped", "Unmapped"],
            "sourceFiles": [],
            "legacyModels": [],
            "currentModels": [],
        }
    files = sorted(
        {
            str(record["source_file"])
            for provenance in relationships["_provenance"]
            for record in provenance
        },
        key=str.casefold,
    )
    return {
        "legacyTables": _sorted_unique(relationships["legacy_table"]),
        "currentTables": _sorted_unique(relationships["current_table"]),
        "mappingStates": ["Mapped", "Unmapped"],
        "sourceFiles": files,
        "legacyModels": sorted({str(value) for value in relationships["legacy_model"] if str(value).strip()}, key=str.casefold),
        "currentModels": sorted({str(value) for value in relationships["current_model"] if str(value).strip()}, key=str.casefold),
    }


def _search(
    repository: CatalogRepository,
    *,
    q: str,
    scope: str,
    legacy_table: list[str] | None,
    current_table: list[str] | None,
    mapping_state: list[str] | None,
    source_file: list[str] | None,
    legacy_model: list[str] | None,
    current_model: list[str] | None,
    offset: int,
    limit: int,
) -> dict[str, Any]:
    relationships = repository.relationships()
    try:
        results = search_relationships(
            relationships,
            q,
            scope=scope,
            legacy_tables=legacy_table,
            current_tables=current_table,
            mapping_states=mapping_state,
            source_files=source_file,
            legacy_models=legacy_model,
            current_models=current_model,
        )
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    page = results.iloc[offset : offset + limit]
    legacy_fields = results.loc[
        results["legacy_table"].astype(str).str.strip().ne("")
        & results["legacy_column"].astype(str).str.strip().ne("")
    ]
    current_fields = results.loc[
        results["current_table"].astype(str).str.strip().ne("")
        & results["current_column"].astype(str).str.strip().ne("")
    ]
    return {
        "total": len(results),
        "offset": offset,
        "limit": limit,
        "rows": _records(page, exclude={"_provenance"}),
        "legacyFieldCount": int(legacy_fields[["legacy_table", "legacy_column"]].drop_duplicates().shape[0]),
        "currentFieldCount": int(current_fields[["current_table", "current_column"]].drop_duplicates().shape[0]),
    }


def _relationship_detail(repository: CatalogRepository, relationship_id: int) -> dict[str, Any]:
    relationships = repository.relationships()
    matches = relationships.loc[relationships["relationship_id"].eq(relationship_id)]
    if matches.empty:
        raise HTTPException(status_code=404, detail="Relationship not found")
    selected = matches.iloc[0]
    source_side = "current" if not str(selected["legacy_table"]).strip() else "legacy"
    if source_side == "current":
        related = relationships_for_current_field(
            relationships,
            str(selected["current_table"]),
            str(selected["current_column"]),
            str(selected["current_model"]),
        )
    else:
        related = relationships_for_legacy_field(
            relationships,
            str(selected["legacy_table"]),
            str(selected["legacy_column"]),
            str(selected["legacy_model"]),
        )
    provenance_records = [record for records in related["_provenance"] for record in records]
    provenance = pd.DataFrame(provenance_records)
    if not provenance.empty:
        provenance = provenance.drop_duplicates().sort_values(
            ["source_file", "source_sheet", "source_row"], kind="stable"
        )
    if source_side == "current":
        targets = [
            {
                "relationshipId": int(row.relationship_id),
                "model": str(row.legacy_model),
                "database": str(row.legacy_database),
                "schema": str(row.legacy_schema),
                "table": str(row.legacy_table),
                "column": str(row.legacy_column),
                "description": str(row.legacy_description),
                "dataType": str(row.legacy_data_type),
                "state": str(row.mapping_state),
                "sourceCount": int(row.provenance_count),
            }
            for row in related.itertuples(index=False)
        ]
        source = {
            "model": str(selected["current_model"]),
            "database": str(selected["current_database"]),
            "schema": str(selected["current_schema"]),
            "table": str(selected["current_table"]),
            "column": str(selected["current_column"]),
            "description": str(selected["current_description"]),
            "dataType": str(selected["current_data_type"]),
        }
    else:
        targets = [
            {
                "relationshipId": int(row.relationship_id),
                "model": str(row.current_model),
                "database": str(row.current_database),
                "schema": str(row.current_schema),
                "table": str(row.current_table),
                "column": str(row.current_column),
                "description": str(row.current_description),
                "dataType": str(row.current_data_type),
                "state": str(row.mapping_state),
                "sourceCount": int(row.provenance_count),
            }
            for row in related.itertuples(index=False)
        ]
        source = {
            "model": str(selected["legacy_model"]),
            "database": str(selected["legacy_database"]),
            "schema": str(selected["legacy_schema"]),
            "table": str(selected["legacy_table"]),
            "column": str(selected["legacy_column"]),
            "description": str(selected["legacy_description"]),
            "dataType": str(selected["legacy_data_type"]),
        }
    return {
        "sourceSide": source_side,
        "source": source,
        "targets": targets,
        "provenance": _records(provenance),
    }


def create_app(db_path: str | Path | None = None) -> FastAPI:
    app = FastAPI(
        title="Entity Map",
        description="Local legacy-to-current field mapping catalog",
        version="0.3.0",
        docs_url="/api/docs",
        redoc_url=None,
    )
    app.state.catalog = CatalogRepository(db_path or _default_database_path())

    @app.get("/api/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/api/catalog/summary")
    def catalog_summary(legacy_model: str = "", current_model: str = "") -> dict[str, Any]:
        return _repository(app).summary(legacy_model, current_model)

    @app.get("/api/catalog/imports")
    def catalog_imports() -> dict[str, Any]:
        return {"imports": _repository(app).imports()}

    @app.post("/api/import/{kind}")
    async def import_files(
        kind: Literal["current", "legacy", "mappings"],
        files: Annotated[list[UploadFile], File()],
        model: Annotated[str, Form()] = "",
        legacy_model: Annotated[str, Form()] = "Legacy",
        current_model: Annotated[str, Form()] = "Current",
    ) -> dict[str, Any]:
        if not files:
            raise HTTPException(status_code=400, detail="Choose at least one CSV or XLSX file")
        repository = _repository(app)
        parsed: list[tuple[str, Any]] = []
        try:
            for index, upload in enumerate(files):
                filename = upload.filename or f"{kind}-{index + 1}.csv"
                content = await upload.read()
                result = (
                    auto_normalize_mapping(content, filename)
                    if kind == "mappings"
                    else auto_normalize_inventory(content, filename)
                )
                parsed.append((filename, result))
        except ImportFormatError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        valid_count = 0
        invalid_count = 0
        invalid_frames: list[pd.DataFrame] = []
        file_results: list[dict[str, Any]] = []
        for filename, result in parsed:
            if kind == "mappings":
                repository.import_mappings(result.valid, legacy_model, current_model)
            else:
                repository.import_inventory(kind, result.valid, model or ("Legacy" if kind == "legacy" else "Current"))
            repository.record_import(
                kind, filename, len(result.valid), len(result.invalid),
                legacy_model=legacy_model if kind == "mappings" else (model if kind == "legacy" else ""),
                current_model=current_model if kind == "mappings" else (model if kind == "current" else ""),
            )
            valid_count += len(result.valid)
            invalid_count += len(result.invalid)
            if not result.invalid.empty:
                invalid_frames.append(result.invalid)
            file_results.append(
                {
                    "filename": filename,
                    "validCount": len(result.valid),
                    "invalidCount": len(result.invalid),
                }
            )
        invalid = pd.concat(invalid_frames, ignore_index=True) if invalid_frames else pd.DataFrame()
        return {
            "validCount": valid_count,
            "invalidCount": invalid_count,
            "invalidRows": _records(invalid.head(100)),
            "invalidRowsTruncated": len(invalid) > 100,
            "files": file_results,
            "summary": repository.summary(),
        }

    @app.get("/api/catalog/filters")
    def catalog_filters() -> dict[str, Any]:
        return _filters(_repository(app))

    @app.get("/api/catalog/search")
    def search_catalog(
        q: str = "",
        scope: Literal["legacy", "current"] = "legacy",
        legacy_table: Annotated[list[str] | None, Query()] = None,
        current_table: Annotated[list[str] | None, Query()] = None,
        mapping_state: Annotated[list[str] | None, Query()] = None,
        source_file: Annotated[list[str] | None, Query()] = None,
        legacy_model: Annotated[list[str] | None, Query()] = None,
        current_model: Annotated[list[str] | None, Query()] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> dict[str, Any]:
        return _search(
            _repository(app),
            q=q,
            scope=scope,
            legacy_table=legacy_table,
            current_table=current_table,
            mapping_state=mapping_state,
            source_file=source_file,
            legacy_model=legacy_model,
            current_model=current_model,
            offset=offset,
            limit=limit,
        )

    @app.get("/api/catalog/relationships/{relationship_id}")
    def relationship_detail(relationship_id: int) -> dict[str, Any]:
        return _relationship_detail(_repository(app), relationship_id)

    @app.get("/api/current-fields")
    def current_fields(q: str = "", model: str = "", limit: Annotated[int, Query(ge=1, le=500)] = 100) -> dict[str, Any]:
        fields = _repository(app).current_fields(q, model, limit)
        return {"fields": fields, "count": len(fields)}

    @app.get("/api/legacy-fields")
    def legacy_fields(q: str = "", model: str = "", limit: Annotated[int, Query(ge=1, le=200)] = 50) -> dict[str, Any]:
        fields = _repository(app).legacy_fields(q, model, limit)
        return {"fields": fields, "count": len(fields)}

    @app.post("/api/fields", status_code=201)
    def create_field(request: FieldRequest) -> dict[str, int]:
        try:
            field_id = _repository(app).add_field(
                request.kind,
                request.model,
                {
                    "database": request.database,
                    "schema": request.schema_name,
                    "table": request.table,
                    "column": request.column,
                    "description": request.description,
                    "dataType": request.data_type,
                },
            )
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"fieldId": field_id}

    @app.post("/api/mappings", status_code=201)
    def add_mapping(request: MappingRequest) -> dict[str, int]:
        try:
            mapping_id = _repository(app).add_mapping(
                request.current_field_id, request.legacy_field_id
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        return {"mappingId": mapping_id}

    @app.delete("/api/mappings/{mapping_id}", status_code=204)
    def remove_mapping(mapping_id: int) -> Response:
        if not _repository(app).delete_mapping(mapping_id):
            raise HTTPException(status_code=404, detail="Mapping not found")
        return Response(status_code=204)

    @app.get("/api/catalog/download")
    def download_catalog() -> StreamingResponse:
        content = normalized_to_csv(_repository(app).normalized())
        return StreamingResponse(
            iter([content]),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": 'attachment; filename="entity_map_catalog.csv"'},
        )

    @app.delete("/api/catalog", status_code=204)
    def clear_catalog() -> Response:
        _repository(app).clear()
        return Response(status_code=204)

    # Compatibility endpoints for clients built against the original import wizard.
    @app.post("/api/inspect")
    async def inspect_files(files: Annotated[list[UploadFile], File()]) -> dict[str, Any]:
        inspected: list[dict[str, Any]] = []
        for file_index, upload in enumerate(files):
            filename = upload.filename or f"mapping-{file_index + 1}.csv"
            content = await upload.read()
            try:
                sheet_details = []
                for sheet_name in list_sheets(content, filename):
                    preview = read_preview(content, filename, sheet_name, rows=12)
                    header_row = guess_header_row(preview)
                    parsed = read_sheet(content, filename, sheet_name, header_row=header_row)
                    sheet_details.append(
                        {
                            "name": sheet_name,
                            "preview": [
                                [_clean_json_value(value) for value in row]
                                for row in preview.values.tolist()
                            ],
                            "suggestedHeaderRow": header_row,
                            "columns": [str(column) for column in parsed.columns],
                            "suggestions": suggest_header_assignments(parsed.columns),
                        }
                    )
            except ImportFormatError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            inspected.append(
                {
                    "fileIndex": file_index,
                    "name": filename,
                    "size": len(content),
                    "sheets": sheet_details,
                }
            )
        return {"files": inspected}

    @app.post("/api/normalize")
    async def normalize_files(
        files: Annotated[list[UploadFile], File()], config: Annotated[str, Form()]
    ) -> dict[str, Any]:
        try:
            request = NormalizeRequest.model_validate_json(config)
        except ValidationError as exc:
            raise HTTPException(status_code=422, detail=json.loads(exc.json())) from exc
        payloads = [
            (upload.filename or f"mapping-{index + 1}.csv", await upload.read())
            for index, upload in enumerate(files)
        ]
        results = []
        try:
            for sheet in request.sheets:
                if sheet.file_index >= len(payloads):
                    raise ImportFormatError(f"Uploaded file index {sheet.file_index} was not found.")
                filename, content = payloads[sheet.file_index]
                frame = read_sheet(
                    content, filename, sheet.sheet_name, header_row=sheet.header_row
                )
                results.append(
                    normalize_frame(
                        frame,
                        {field: sheet.assignments.get(field) for field in CANONICAL_FIELDS},
                        source_file=filename,
                        source_sheet=sheet.sheet_name,
                        header_row=sheet.header_row,
                    )
                )
        except ImportFormatError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        combined = combine_results(results)
        _repository(app).import_mappings(combined.valid, "Legacy", "Current")
        return {
            "datasetId": "catalog" if not combined.valid.empty else None,
            "validCount": len(combined.valid),
            "invalidCount": len(combined.invalid),
            "invalidRows": _records(combined.invalid.head(500)),
            "invalidRowsTruncated": len(combined.invalid) > 500,
        }

    @app.get("/api/datasets/{dataset_id}/filters")
    def compatibility_filters(dataset_id: str) -> dict[str, Any]:
        if dataset_id != "catalog":
            raise HTTPException(status_code=404, detail="Dataset not found")
        return _filters(_repository(app))

    @app.get("/api/datasets/{dataset_id}/search")
    def compatibility_search(
        dataset_id: str,
        q: str = "",
        scope: Literal["legacy", "current"] = "legacy",
        legacy_table: Annotated[list[str] | None, Query()] = None,
        current_table: Annotated[list[str] | None, Query()] = None,
        mapping_state: Annotated[list[str] | None, Query()] = None,
        source_file: Annotated[list[str] | None, Query()] = None,
        legacy_model: Annotated[list[str] | None, Query()] = None,
        current_model: Annotated[list[str] | None, Query()] = None,
        offset: Annotated[int, Query(ge=0)] = 0,
        limit: Annotated[int, Query(ge=1, le=500)] = 200,
    ) -> dict[str, Any]:
        if dataset_id != "catalog":
            raise HTTPException(status_code=404, detail="Dataset not found")
        return _search(
            _repository(app),
            q=q,
            scope=scope,
            legacy_table=legacy_table,
            current_table=current_table,
            mapping_state=mapping_state,
            source_file=source_file,
            legacy_model=legacy_model,
            current_model=current_model,
            offset=offset,
            limit=limit,
        )

    @app.get("/api/datasets/{dataset_id}/relationships/{relationship_id}")
    def compatibility_detail(dataset_id: str, relationship_id: int) -> dict[str, Any]:
        if dataset_id != "catalog":
            raise HTTPException(status_code=404, detail="Dataset not found")
        return _relationship_detail(_repository(app), relationship_id)

    @app.get("/api/datasets/{dataset_id}/download")
    def compatibility_download(dataset_id: str) -> StreamingResponse:
        if dataset_id != "catalog":
            raise HTTPException(status_code=404, detail="Dataset not found")
        content = normalized_to_csv(_repository(app).normalized())
        return StreamingResponse(iter([content]), media_type="text/csv; charset=utf-8")

    static_root = Path(__file__).with_name("static")
    assets = static_root / "assets"
    if assets.is_dir():
        app.mount("/assets", StaticFiles(directory=assets), name="assets")

    @app.get("/", include_in_schema=False, response_model=None)
    def frontend() -> Response:
        index = static_root / "index.html"
        if index.is_file():
            return FileResponse(index)
        return HTMLResponse(
            "<h1>Frontend build missing</h1><p>Run <code>npm run build</code> in the frontend directory.</p>",
            status_code=503,
        )

    return app


app = create_app()
