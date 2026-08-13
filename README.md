# Entity Map

Entity Map is a lightweight local catalog for legacy-to-current database mappings. It opens directly into a searchable explorer, keeps imported data between server restarts, and provides a current-first workspace for assigning legacy fields to the model used today. Multiple legacy and current models can coexist under user-defined aliases.

The interface is React and TypeScript; a small FastAPI service parses CSV/XLSX files and stores the catalog in SQLite. The server binds to `127.0.0.1` by default.

For a complete explanation of the architecture, data model, workflows, local operation, API, and troubleshooting, see the [Project Guide](docs/PROJECT_GUIDE.md).

## Install and launch with uv

Python 3.11+ is supported; Python 3.12 is recommended.

```bash
uv venv --python 3.12
source .venv/bin/activate
uv pip install -e ".[dev]"
entity-map serve
```

Open [http://127.0.0.1:8501](http://127.0.0.1:8501). To change the port or suppress automatic browser launch:

```bash
entity-map serve --port 8600 --no-browser
```

The source-checkout launcher also works:

```bash
python app.py
```

## Day-to-day workflow

There is no upload wizard. Entity Map opens directly into two work areas:

- **Explore** searches the saved catalog. Set the scope to **Legacy** or **Current**, choose a legacy/current model pair, then enter `COLUMN_NAME` or `TABLE_NAME.COLUMN_NAME`. Exact matches rank before substring matches. Filters narrow by model, table, mapping state, or source file. Unmapped fields on either side remain in the relationship table and are highlighted amber: a legacy row with no current target, or a current row with no legacy source.
- **Map fields** treats the current schema as the benchmark. Choose the current and legacy model aliases, find a current field, search the available legacy inventory inside its card, and add or remove legacy inputs. If a field is missing, create it manually with database, schema, table, column, description, and data type metadata. One current field can accept many legacy inputs, and one legacy field can feed multiple current fields.
- The explorer summary shows all legacy fields, matched fields, coverage percentage, legacy unmapped fields, and current-side gaps for the selected model pair.

Use **Data sources** when a schema or mapping actually changes. Imports merge with the existing catalog; they do not replace it.

## Data source formats

Current and legacy inventories use the same shape. `Table Name`, `Column Name`, and `Description` are the minimum useful headers; database, schema, and data type metadata are optional:

```csv
Table Name,Column Name,Description
CUSTOMER,ID,Primary key of the customer
CUSTOMER,FULL_NAME,Customer full name
```

```csv
Database,Schema,Table Name,Column Name,Description,Data Type
new_db,core,CUSTOMER,ID,Primary key of the customer,BIGINT
```

Existing paired mappings use the paired legacy/current headers below. Database, schema, and data type headers can be added with the corresponding `Legacy ...` and `Current ...` prefixes:

```csv
Legacy Table,Legacy Column,Legacy Description,Current Table,Current Column,Current Description
CLIENT,CLINETN_ID,Unique client identifier,CUSTOMER,ID,Primary key of the customer
CLIENT,CLIENT_NAME,Full name of the client,CUSTOMER,FULL_NAME,Customer full name
```

Both `.csv` and `.xlsx` files are accepted. Headers are detected automatically, including when they are not on the first row. All Excel sheets are imported. Invalid rows are skipped and reported; the remaining valid rows are merged.

Each import has an alias. Inventory imports use one alias (for example `CRM v1` or `Customer API`). Paired mapping imports use one alias for each side. A field is identified by `(model alias, table, column)`, so identical names from different systems do not overwrite each other.

For paired mappings, legacy table and column are required. Current table and column must either both be present or both be blank. A blank pair creates an **Unmapped** legacy field. Current inventory imports also create **Unmapped** current fields until a legacy source is assigned.

## Persistence and privacy

- The catalog is stored in `~/.entity-map/catalog.db` by default.
- Set `ENTITY_MAP_DB_PATH=/path/to/catalog.db` to use another database location.
- Imported workbook bytes are not retained. Normalized fields, relationships, import history, and provenance are stored in SQLite.
- **Clear** in Data sources removes the local catalog. Export the normalized catalog CSV first if you need a backup.
- No mapping data is sent to a remote service, and no authentication is included for this single-user local version.

## Development

Run the backend suite:

```bash
uv run --no-sync pytest
```

Build the frontend after changing `frontend/`:

```bash
cd frontend
npm install
npm run build
```

The production bundle is written to `src/entity_map/static` and included in the Python package. For hot reload, run `npm run dev` while `entity-map serve --no-browser` is listening on port 8501.

## Troubleshooting

- **The catalog is empty:** open Data sources and import the current schema, legacy inventory, or an existing paired mapping file.
- **A field is not found:** confirm the correct Legacy/Current search scope, then try the unqualified column name.
- **A file is rejected:** use `.csv` or `.xlsx` and include recognizable table/column headers.
- **An older Excel file fails:** `.xls` is not supported; save it as `.xlsx` first.
- **The default port is occupied:** run `entity-map serve --port 8600`.
- **The frontend build is missing:** run `npm install && npm run build` in `frontend/`.

## License

MIT
