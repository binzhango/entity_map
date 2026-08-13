from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from entity_map.app import create_app

FIXTURES = Path(__file__).parent / "fixtures"


def upload_file() -> tuple[str, bytes, str]:
    return (
        "example_mapping.csv",
        (FIXTURES / "example_mapping.csv").read_bytes(),
        "text/csv",
    )


def test_health_and_frontend_are_available(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "catalog.db")) as client:
        assert client.get("/api/health").json() == {"status": "ok"}
        frontend = client.get("/")
        assert frontend.status_code == 200
        assert "Entity Map" in frontend.text


def test_inspect_suggests_all_example_fields(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "catalog.db")) as client:
        response = client.post("/api/inspect", files=[("files", upload_file())])
        assert response.status_code == 200
        sheet = response.json()["files"][0]["sheets"][0]
        assert sheet["name"] == "CSV"
        assert sheet["suggestedHeaderRow"] == 0
        assert sheet["suggestions"]["legacy_column"] == "Legacy Column"
        assert sheet["suggestions"]["current_column"] == "Current Column"


def test_import_search_detail_download_and_persistence(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    with TestClient(create_app(database)) as client:
        imported = client.post("/api/import/mappings", files=[("files", upload_file())])
        assert imported.status_code == 200, imported.text
        assert imported.json()["validCount"] == 4
        assert imported.json()["invalidCount"] == 0

        summary = client.get("/api/catalog/summary").json()
        assert summary["legacyFieldCount"] == 4
        assert summary["currentFieldCount"] == 4
        assert summary["mappingCount"] == 4

        legacy_search = client.get(
            "/api/catalog/search",
            params={"scope": "legacy", "q": "client.clinetn_id"},
        )
        assert legacy_search.status_code == 200
        row = legacy_search.json()["rows"][0]
        assert row["current_table"] == "CUSTOMER"
        assert row["current_column"] == "ID"

        current_search = client.get(
            "/api/catalog/search",
            params={"scope": "current", "q": "customer.id"},
        )
        assert current_search.status_code == 200
        assert current_search.json()["rows"][0]["legacy_column"] == "CLINETN_ID"

        detail = client.get(f"/api/catalog/relationships/{row['relationship_id']}")
        assert detail.status_code == 200
        assert detail.json()["source"]["column"] == "CLINETN_ID"
        assert detail.json()["targets"][0]["column"] == "ID"
        assert detail.json()["provenance"][0]["source_row"] == 2

        download = client.get("/api/catalog/download")
        assert download.status_code == 200
        assert "legacy_table" in download.text
        assert "CLINETN_ID" in download.text

    # A fresh app instance uses the same durable catalog without re-uploading.
    with TestClient(create_app(database)) as restarted:
        persisted = restarted.get(
            "/api/catalog/search", params={"scope": "current", "q": "TX_DATE"}
        )
        assert persisted.status_code == 200
        assert persisted.json()["rows"][0]["legacy_column"] == "TRAN_DT"


def test_current_first_manual_mapping_workflow(tmp_path: Path) -> None:
    current_csv = b"Table Name,Column Name,Description\nCUSTOMER,ID,Primary key\n"
    legacy_csv = b"Table Name,Column Name,Description\nCLIENT,CLIENT_ID,Old identifier\n"
    with TestClient(create_app(tmp_path / "catalog.db")) as client:
        current_import = client.post(
            "/api/import/current",
            files=[("files", ("current.csv", current_csv, "text/csv"))],
        )
        legacy_import = client.post(
            "/api/import/legacy",
            files=[("files", ("legacy.csv", legacy_csv, "text/csv"))],
        )
        assert current_import.status_code == legacy_import.status_code == 200

        current_gap = client.get(
            "/api/catalog/search",
            params={"scope": "current", "q": "customer.id"},
        ).json()["rows"]
        assert len(current_gap) == 1
        assert current_gap[0]["mapping_state"] == "Unmapped"
        assert current_gap[0]["unmapped_side"] == "current"
        current_gap_detail = client.get(
            f"/api/catalog/relationships/{current_gap[0]['relationship_id']}"
        ).json()
        assert current_gap_detail["sourceSide"] == "current"
        assert current_gap_detail["source"]["column"] == "ID"
        assert current_gap_detail["targets"][0]["state"] == "Unmapped"
        assert client.get("/api/catalog/summary").json()["currentUnmatchedCount"] == 1

        current = client.get("/api/current-fields", params={"q": "customer.id"}).json()[
            "fields"
        ][0]
        legacy = client.get("/api/legacy-fields", params={"q": "client_id"}).json()[
            "fields"
        ][0]
        assert current["legacyFields"] == []

        created = client.post(
            "/api/mappings",
            json={"currentFieldId": current["id"], "legacyFieldId": legacy["id"]},
        )
        assert created.status_code == 201
        mapping_id = created.json()["mappingId"]

        updated = client.get("/api/current-fields", params={"q": "customer.id"}).json()[
            "fields"
        ][0]
        assert updated["legacyFields"][0]["column"] == "CLIENT_ID"
        assert client.get("/api/catalog/summary").json()["currentUnmatchedCount"] == 0
        assert client.delete(f"/api/mappings/{mapping_id}").status_code == 204
        assert client.get("/api/current-fields").json()["fields"][0]["legacyFields"] == []


def test_clear_catalog_keeps_database_usable(tmp_path: Path) -> None:
    with TestClient(create_app(tmp_path / "catalog.db")) as client:
        assert client.post("/api/import/mappings", files=[("files", upload_file())]).status_code == 200
        assert client.delete("/api/catalog").status_code == 204
        summary = client.get("/api/catalog/summary").json()
        assert summary["ready"] is False
        assert summary["mappingCount"] == 0


def test_model_aliases_metadata_unmapped_and_summary(tmp_path: Path) -> None:
    database = tmp_path / "catalog.db"
    mapping_csv = (
        b"Legacy Database,Legacy Schema,Legacy Table,Legacy Column,Legacy Description,Legacy Data Type,"
        b"Current Database,Current Schema,Current Table,Current Column,Current Description,Current Data Type\n"
        b"old_db,public,CLIENT,CLIENT_ID,Old identifier,INTEGER,new_db,core,CUSTOMER,ID,Primary key,BIGINT\n"
        b"old_db,public,CLIENT,CLIENT_NAME,Client name,VARCHAR,,,,,,\n"
    )
    with TestClient(create_app(database)) as client:
        response = client.post(
            "/api/import/mappings",
            files=[("files", ("models.csv", mapping_csv, "text/csv"))],
            data={"legacy_model": "CRM v1", "current_model": "Customer API"},
        )
        assert response.status_code == 200, response.text
        summary = response.json()["summary"]
        assert summary["legacyModels"] == ["CRM v1"]
        assert summary["currentModels"] == ["Customer API"]
        assert summary["legacyFieldCount"] == 2
        assert summary["matchedCount"] == 1
        assert summary["unmatchedCount"] == 1
        assert summary["matchedPercent"] == 50.0

        search = client.get("/api/catalog/search", params={"legacy_model": "CRM v1"})
        assert search.status_code == 200
        rows = search.json()["rows"]
        assert len(rows) == 2
        unmapped = next(row for row in rows if row["mapping_state"] == "Unmapped")
        assert unmapped["legacy_database"] == "old_db"
        assert unmapped["legacy_schema"] == "public"
        assert unmapped["current_table"] == ""

        # Selecting a saved current model must not hide legacy fields that are
        # still awaiting a target; those rows are the ones users need to resolve.
        pair_rows = client.get(
            "/api/catalog/search",
            params={"legacy_model": "CRM v1", "current_model": "Customer API"},
        ).json()["rows"]
        assert {row["mapping_state"] for row in pair_rows} == {"Mapped", "Unmapped"}

        detail = client.get(f"/api/catalog/relationships/{unmapped['relationship_id']}").json()
        assert detail["source"]["model"] == "CRM v1"
        assert detail["source"]["database"] == "old_db"
        assert detail["targets"][0]["state"] == "Unmapped"

        current = client.get("/api/current-fields", params={"model": "Customer API"}).json()["fields"]
        assert current[0]["database"] == "new_db"
        assert current[0]["dataType"] == "BIGINT"

        created = client.post(
            "/api/fields",
            json={
                "kind": "legacy",
                "model": "CRM v1",
                "database": "old_db",
                "schema": "public",
                "table": "CLIENT",
                "column": "CLIENT_STATUS",
                "description": "Current status",
                "dataType": "VARCHAR",
            },
        )
        assert created.status_code == 201
        legacy_id = created.json()["fieldId"]
        mapping = client.post(
            "/api/mappings",
            json={"currentFieldId": current[0]["id"], "legacyFieldId": legacy_id},
        )
        assert mapping.status_code == 201
        refreshed = client.get("/api/current-fields", params={"model": "Customer API"}).json()["fields"][0]
        assert {field["column"] for field in refreshed["legacyFields"]} == {"CLIENT_ID", "CLIENT_STATUS"}
