import {
  AlertCircle,
  ArrowRight,
  Check,
  ChevronLeft,
  ChevronRight,
  CircleDot,
  Database,
  Download,
  FileSpreadsheet,
  FolderInput,
  GitBranch,
  Layers3,
  Link2,
  LoaderCircle,
  LockKeyhole,
  Map,
  Plus,
  Pencil,
  Search,
  Server,
  SlidersHorizontal,
  Sparkles,
  Trash2,
  Unlink,
  Upload,
  X,
} from "lucide-react";
import { type ChangeEvent, type ReactNode, useEffect, useMemo, useRef, useState } from "react";
import {
  addMapping,
  clearCatalog,
  createField,
  emptyFilters,
  getCurrentFields,
  getFilters,
  getImports,
  getLegacyFields,
  getRelationship,
  getSummary,
  importCatalogFiles,
  removeMapping,
  searchMappings,
  type ActiveFilters,
} from "./api";
import type {
  CatalogSummary,
  CurrentField,
  FilterOptions,
  ImportKind,
  ImportRecord,
  ImportResponse,
  LegacyField,
  RelationshipDetail,
  RelationshipRow,
  SearchResponse,
  SearchScope,
} from "./types";

type View = "explore" | "mapping";

const blankSummary: CatalogSummary = {
  ready: false,
  legacyFieldCount: 0,
  currentFieldCount: 0,
  mappingCount: 0,
  matchedCount: 0,
  unmatchedCount: 0,
  matchedPercent: 0,
  unmatchedPercent: 0,
  currentMatchedCount: 0,
  currentUnmatchedCount: 0,
  currentUnmatchedPercent: 0,
  importCount: 0,
  lastImportedAt: null,
  legacyModels: [],
  currentModels: [],
};

function App() {
  const [view, setView] = useState<View>("explore");
  const [summary, setSummary] = useState<CatalogSummary>(blankSummary);
  const [sourcesOpen, setSourcesOpen] = useState(false);
  const [revision, setRevision] = useState(0);
  const [error, setError] = useState<string | null>(null);

  const refresh = () => setRevision((value) => value + 1);

  useEffect(() => {
    getSummary()
      .then(setSummary)
      .catch((reason) => setError(reason instanceof Error ? reason.message : "Could not open catalog."));
  }, [revision]);

  return (
    <div className="app-shell">
      <header className="topbar">
        <button className="brand" onClick={() => setView("explore")} aria-label="Open explorer">
          <span className="brand-mark"><Layers3 size={19} /></span>
          <span><strong>Entity Map</strong><small>Schema intelligence</small></span>
        </button>

        <nav className="primary-nav" aria-label="Primary navigation">
          <button className={view === "explore" ? "is-active" : ""} onClick={() => setView("explore")}>
            <Search size={15} /> Explore
          </button>
          <button className={view === "mapping" ? "is-active" : ""} onClick={() => setView("mapping")}>
            <GitBranch size={15} /> Map fields
          </button>
        </nav>

        <div className="topbar-actions">
          <span className="saved-badge"><span /> Saved locally</span>
          <button className="button button--secondary" onClick={() => setSourcesOpen(true)}>
            <Database size={15} /> Data sources
          </button>
        </div>
      </header>

      {error && (
        <div className="global-alert" role="alert">
          <AlertCircle size={17} /><span>{error}</span>
          <button onClick={() => setError(null)} aria-label="Dismiss"><X size={15} /></button>
        </div>
      )}

      <main className="main">
        {view === "explore" ? (
          <Explorer
            summary={summary}
            revision={revision}
            onOpenSources={() => setSourcesOpen(true)}
          />
        ) : (
          <MappingWorkspace
            summary={summary}
            revision={revision}
            onChanged={refresh}
            onOpenSources={() => setSourcesOpen(true)}
            onError={setError}
          />
        )}
      </main>

      {sourcesOpen && (
        <DataSources
          summary={summary}
          onClose={() => setSourcesOpen(false)}
          onChanged={refresh}
          onError={setError}
        />
      )}
    </div>
  );
}

interface ExplorerProps {
  summary: CatalogSummary;
  revision: number;
  onOpenSources: () => void;
}

function Explorer({ summary, revision, onOpenSources }: ExplorerProps) {
  const [scope, setScope] = useState<SearchScope>("legacy");
  const [query, setQuery] = useState("");
  const [filters, setFilters] = useState<ActiveFilters>(emptyFilters);
  const [filterOptions, setFilterOptions] = useState<FilterOptions | null>(null);
  const [results, setResults] = useState<SearchResponse | null>(null);
  const [selected, setSelected] = useState<number | null>(null);
  const [detail, setDetail] = useState<RelationshipDetail | null>(null);
  const [loading, setLoading] = useState(false);
  const [offset, setOffset] = useState(0);
  const [legacyModel, setLegacyModel] = useState("");
  const [currentModel, setCurrentModel] = useState("");
  const [displaySummary, setDisplaySummary] = useState(summary);

  useEffect(() => setDisplaySummary(summary), [summary]);
  useEffect(() => {
    getSummary(legacyModel, currentModel).then(setDisplaySummary).catch(() => undefined);
  }, [currentModel, legacyModel, revision]);

  useEffect(() => {
    getFilters().then(setFilterOptions).catch(() => setFilterOptions(null));
  }, [revision]);

  useEffect(() => {
    const timer = window.setTimeout(() => {
      setLoading(true);
      searchMappings(query, scope, {
        ...filters,
        legacyModel: legacyModel ? [legacyModel] : [],
        currentModel: currentModel ? [currentModel] : [],
      }, offset)
        .then((response) => {
          setResults(response);
          if (selected !== null && !response.rows.some((row) => row.relationship_id === selected)) {
            setSelected(null);
            setDetail(null);
          }
        })
        .finally(() => setLoading(false));
    }, 130);
    return () => window.clearTimeout(timer);
  }, [currentModel, filters, legacyModel, offset, query, revision, scope, selected]);

  useEffect(() => {
    if (selected === null) return;
    getRelationship(selected).then(setDetail).catch(() => setDetail(null));
  }, [selected, revision]);

  const changeScope = (next: SearchScope) => {
    setScope(next);
    setOffset(0);
    setSelected(null);
    setDetail(null);
  };

  const filterCount = Object.values(filters).reduce((total, values) => total + values.length, 0);

  return (
    <section className="explorer page-enter">
      <div className="page-heading">
        <div>
          <span className="eyebrow"><Sparkles size={13} /> Mapping catalog</span>
          <h1>Find where your data lives now.</h1>
          <p>Search from either side of the migration. The scope controls which schema is queried.</p>
        </div>
        <div className="summary-strip" aria-label="Catalog summary">
          <SummaryMetric value={displaySummary.legacyFieldCount} label="All legacy" />
          <SummaryMetric value={displaySummary.matchedCount} label="Matched" />
          <SummaryMetric value={displaySummary.matchedPercent} label="Coverage %" />
          <SummaryMetric value={displaySummary.unmatchedCount} label="Unmapped" />
          <SummaryMetric value={displaySummary.currentUnmatchedCount} label="Current gaps" />
        </div>
      </div>

      <div className="search-shell">
        <div className="scope-switch" aria-label="Search scope">
          <button className={scope === "legacy" ? "is-active" : ""} onClick={() => changeScope("legacy")}>
            Legacy
          </button>
          <button className={scope === "current" ? "is-active" : ""} onClick={() => changeScope("current")}>
            Current
          </button>
        </div>
        <Search size={20} />
        <input
          value={query}
          onChange={(event) => { setQuery(event.target.value); setOffset(0); }}
          placeholder={
            scope === "legacy"
              ? "Search legacy field — e.g. CLIENT.CLINETN_ID"
              : "Search current field — e.g. CUSTOMER.ID"
          }
          aria-label={`Search ${scope} fields`}
          autoFocus
        />
        {query && <button className="clear-search" onClick={() => setQuery("")} aria-label="Clear search"><X size={17} /></button>}
        <div className="scope-context"><CircleDot size={12} /> Searching {scope}</div>
      </div>

      <div className="model-pair-bar surface">
        <div><span>Legacy model</span><select value={legacyModel} onChange={(event) => { setLegacyModel(event.target.value); setOffset(0); }}><option value="">All legacy models</option>{summary.legacyModels.map((model) => <option key={model} value={model}>{model}</option>)}</select></div>
        <ArrowRight size={15} />
        <div><span>Current model</span><select value={currentModel} onChange={(event) => { setCurrentModel(event.target.value); setOffset(0); }}><option value="">All current models</option>{summary.currentModels.map((model) => <option key={model} value={model}>{model}</option>)}</select></div>
        <span className="model-pair-note">Choose a pair to inspect its saved relationships</span>
      </div>

      {!summary.ready ? (
        <EmptyCatalog onOpenSources={onOpenSources} />
      ) : (
        <div className="explorer-grid">
          <FilterPanel
            options={filterOptions}
            filters={filters}
            count={filterCount}
            onChange={(next) => { setFilters(next); setOffset(0); }}
          />
          <ResultsPanel
            results={results}
            loading={loading}
            scope={scope}
            selected={selected}
            offset={offset}
            onSelect={setSelected}
            onOffset={setOffset}
          />
          <DetailPanel detail={detail} />
        </div>
      )}
    </section>
  );
}

function SummaryMetric({ value, label }: { value: number; label: string }) {
  return <div><strong>{value.toLocaleString()}</strong><span>{label}</span></div>;
}

function EmptyCatalog({ onOpenSources }: { onOpenSources: () => void }) {
  return (
    <div className="empty-catalog surface">
      <span className="empty-catalog-icon"><FolderInput size={25} /></span>
      <h2>Your catalog is ready for its first source</h2>
      <p>Import your current schema as the benchmark, then add legacy fields or existing mappings. Future visits open here—no repeat wizard.</p>
      <button className="button button--primary" onClick={onOpenSources}><Plus size={16} /> Add data sources</button>
    </div>
  );
}

interface FilterPanelProps {
  options: FilterOptions | null;
  filters: ActiveFilters;
  count: number;
  onChange: (filters: ActiveFilters) => void;
}

function FilterPanel({ options, filters, count, onChange }: FilterPanelProps) {
  const toggle = (key: keyof ActiveFilters, value: string) => {
    const current = filters[key];
    onChange({
      ...filters,
      [key]: current.includes(value) ? current.filter((item) => item !== value) : [...current, value],
    });
  };
  return (
    <aside className="filter-panel surface">
      <header><SlidersHorizontal size={14} /><strong>Filters</strong>{count > 0 && <span>{count}</span>}
        <button disabled={!count} onClick={() => onChange(emptyFilters)}>Clear</button>
      </header>
      <FilterGroup title="Mapping state" values={options?.mappingStates ?? []} selected={filters.mappingState} onToggle={(value) => toggle("mappingState", value)} />
      <FilterGroup title="Legacy model" values={options?.legacyModels ?? []} selected={filters.legacyModel} onToggle={(value) => toggle("legacyModel", value)} />
      <FilterGroup title="Legacy table" values={options?.legacyTables ?? []} selected={filters.legacyTable} onToggle={(value) => toggle("legacyTable", value)} />
      <FilterGroup title="Current model" values={options?.currentModels ?? []} selected={filters.currentModel} onToggle={(value) => toggle("currentModel", value)} />
      <FilterGroup title="Current table" values={options?.currentTables ?? []} selected={filters.currentTable} onToggle={(value) => toggle("currentTable", value)} />
      <FilterGroup title="Source file" values={options?.sourceFiles ?? []} selected={filters.sourceFile} onToggle={(value) => toggle("sourceFile", value)} />
    </aside>
  );
}

function FilterGroup({ title, values, selected, onToggle }: { title: string; values: string[]; selected: string[]; onToggle: (value: string) => void }) {
  if (!values.length) return null;
  return (
    <div className="filter-group">
      <h3>{title}</h3>
      <div>{values.map((value) => (
        <label key={value}>
          <input type="checkbox" checked={selected.includes(value)} onChange={() => onToggle(value)} />
          <span>{selected.includes(value) && <Check size={11} />}</span><em>{value}</em>
        </label>
      ))}</div>
    </div>
  );
}

interface ResultsPanelProps {
  results: SearchResponse | null;
  loading: boolean;
  scope: SearchScope;
  selected: number | null;
  offset: number;
  onSelect: (id: number) => void;
  onOffset: (offset: number) => void;
}

function ResultsPanel({ results, loading, scope, selected, offset, onSelect, onOffset }: ResultsPanelProps) {
  const rows = results?.rows ?? [];
  return (
    <div className="results-panel surface">
      <header>
        <div><strong>Relationships</strong><span>{results?.total.toLocaleString() ?? "—"}</span></div>
        <small>{loading ? <><LoaderCircle className="spin" size={12} /> Searching</> : `Ranked by ${scope} match`}</small>
      </header>
      <div className="results-scroll">
        {rows.length ? (
          <table>
            <thead><tr><th>Legacy field</th><th /><th>Current field</th><th>Status</th><th>Sources</th></tr></thead>
            <tbody>{rows.map((row) => (
              <tr className={`${row.relationship_id === selected ? "is-selected" : ""} ${row.mapping_state === "Unmapped" ? "is-unmapped-row" : ""}`} key={row.relationship_id} onClick={() => onSelect(row.relationship_id)}>
                <td>{row.legacy_table && row.legacy_column ? <><strong>{row.legacy_model || "Legacy"} · {row.legacy_table}</strong><code>{row.legacy_column}</code><small>{row.legacy_description || "No description"}</small><small className="metadata-line">{row.legacy_database || "—"} · {row.legacy_schema || "—"} · {row.legacy_data_type || "type unknown"}</small></> : <span className="unmapped-copy">No legacy source · review needed</span>}</td>
                <td className="arrow-cell"><ArrowRight size={14} /></td>
                <td>{row.current_table && row.current_column ? <><strong>{row.current_model || "Current"} · {row.current_table}</strong><code>{row.current_column}</code><small>{row.current_description || "No description"}</small><small className="metadata-line">{row.current_database || "—"} · {row.current_schema || "—"} · {row.current_data_type || "type unknown"}</small></> : <span className="unmapped-copy">No current target · review needed</span>}</td>
                <td><span className={`mapping-pill is-${row.mapping_state.toLowerCase()}`}><span />{row.mapping_state}</span></td>
                <td><span className="source-count">{row.provenance_count}</span></td>
              </tr>
            ))}</tbody>
          </table>
        ) : (
          <div className="empty-results"><Search size={23} /><h3>No relationships found</h3><p>Try a shorter query or clear a filter.</p></div>
        )}
      </div>
      <footer className="pagination">
        <span>{results ? `${Math.min(offset + 1, results.total)}–${Math.min(offset + 200, results.total)} of ${results.total}` : "Loading…"}</span>
        <div>
          <button disabled={offset === 0} onClick={() => onOffset(Math.max(0, offset - 200))} aria-label="Previous page"><ChevronLeft size={15} /></button>
          <button disabled={!results || offset + 200 >= results.total} onClick={() => onOffset(offset + 200)} aria-label="Next page"><ChevronRight size={15} /></button>
        </div>
      </footer>
    </div>
  );
}

function DetailPanel({ detail }: { detail: RelationshipDetail | null }) {
  if (!detail) {
    return <aside className="detail-panel"><div className="detail-empty"><GitBranch size={27} /><h3>Select a relationship</h3><p>Lineage and exact workbook references will appear here.</p></div></aside>;
  }
  return (
    <aside className="detail-panel">
      <div className="detail-top">
        <span className="detail-label">Selected {detail.sourceSide} field</span>
        <span className="detail-icon"><GitBranch size={18} /></span>
        <h2>{detail.source.table}<b>.</b>{detail.source.column}</h2>
        <p>{detail.source.description || "No field description supplied."}</p>
        <div className="metadata-grid metadata-grid--dark">
          <span><small>Model</small><strong>{detail.source.model || "Legacy"}</strong></span>
          <span><small>Database</small><strong>{detail.source.database || "—"}</strong></span>
          <span><small>Schema</small><strong>{detail.source.schema || "—"}</strong></span>
          <span><small>Type</small><strong>{detail.source.dataType || "—"}</strong></span>
        </div>
      </div>
      <div className="detail-body">
        <h3>{detail.sourceSide === "current" ? "Legacy sources" : "Current destinations"} <span>{detail.targets.length}</span></h3>
        <div className="lineage">
          <div className="lineage-source"><small>{detail.sourceSide === "current" ? "Current" : "Legacy"}</small><strong>{detail.source.column}</strong></div>
          <div className="lineage-connector"><span /><ArrowRight size={13} /></div>
          <div className="lineage-targets">
            {detail.targets.map((target) => (
              <div className={`lineage-target ${target.state === "Unmapped" ? "is-unmapped" : ""}`} key={target.relationshipId}>
                <small>{target.model || target.table || (detail.sourceSide === "current" ? "No legacy source" : "Unmapped")}</small><strong>{target.column || (detail.sourceSide === "current" ? "No source" : "No target")}</strong>
                {target.description && <p>{target.description}</p>}
                {target.state === "Mapped" && <em>{target.database || "—"} · {target.schema || "—"} · {target.dataType || "type unknown"}</em>}
              </div>
            ))}
          </div>
        </div>
        <h3 className="provenance-title">Evidence <span>{detail.provenance.length}</span></h3>
        <div className="provenance-list">
          {detail.provenance.map((source, index) => (
            <div key={`${source.source_file}-${source.source_sheet}-${source.source_row}-${index}`}>
              <FileSpreadsheet size={14} /><span><strong>{source.source_file}</strong><small>{source.source_sheet} · row {source.source_row || "manual"}</small></span>
            </div>
          ))}
        </div>
      </div>
    </aside>
  );
}

interface MappingWorkspaceProps {
  summary: CatalogSummary;
  revision: number;
  onChanged: () => void;
  onOpenSources: () => void;
  onError: (message: string) => void;
}

function MappingWorkspace({ summary, revision, onChanged, onOpenSources, onError }: MappingWorkspaceProps) {
  const [query, setQuery] = useState("");
  const [fields, setFields] = useState<CurrentField[]>([]);
  const [picker, setPicker] = useState<number | null>(null);
  const [legacyQuery, setLegacyQuery] = useState("");
  const [legacyFields, setLegacyFields] = useState<LegacyField[]>([]);
  const [busy, setBusy] = useState(false);
  const [currentModel, setCurrentModel] = useState(summary.currentModels[0] ?? "");
  const [legacyModel, setLegacyModel] = useState(summary.legacyModels[0] ?? "");
  const [manualOpen, setManualOpen] = useState<number | null>(null);
  const [manual, setManual] = useState({ database: "", schema: "", table: "", column: "", description: "", dataType: "" });

  useEffect(() => {
    if (!currentModel && summary.currentModels[0]) setCurrentModel(summary.currentModels[0]);
    if (!legacyModel && summary.legacyModels[0]) setLegacyModel(summary.legacyModels[0]);
  }, [legacyModel, currentModel, summary.currentModels, summary.legacyModels]);

  const loadCurrent = () => getCurrentFields(query, currentModel).then((response) => setFields(response.fields));
  useEffect(() => {
    const timer = window.setTimeout(() => void loadCurrent(), 130);
    return () => window.clearTimeout(timer);
  }, [currentModel, query, revision]);

  useEffect(() => {
    if (picker === null) return;
    const timer = window.setTimeout(() => {
      getLegacyFields(legacyQuery, legacyModel).then((response) => setLegacyFields(response.fields));
    }, 110);
    return () => window.clearTimeout(timer);
  }, [legacyModel, legacyQuery, picker, revision]);

  const connect = async (currentId: number, legacyId: number) => {
    setBusy(true);
    try {
      await addMapping(currentId, legacyId);
      setPicker(null);
      setLegacyQuery("");
      await loadCurrent();
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not save mapping.");
    } finally {
      setBusy(false);
    }
  };

  const disconnect = async (mappingId: number) => {
    setBusy(true);
    try {
      await removeMapping(mappingId);
      await loadCurrent();
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not remove mapping.");
    } finally {
      setBusy(false);
    }
  };

  const createManual = async (currentId: number) => {
    setBusy(true);
    try {
      await createField({ kind: "legacy", model: legacyModel || "Legacy", ...manual });
      const response = await getLegacyFields(`${manual.table}.${manual.column}`, legacyModel);
      const created = response.fields[0];
      if (!created) throw new Error("The new legacy field could not be found after saving.");
      await addMapping(currentId, created.id);
      setManualOpen(null);
      setManual({ database: "", schema: "", table: "", column: "", description: "", dataType: "" });
      setPicker(null);
      await loadCurrent();
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not save manual field.");
    } finally {
      setBusy(false);
    }
  };

  return (
    <section className="mapping-workspace page-enter">
      <div className="page-heading mapping-heading">
        <div>
          <span className="eyebrow"><Map size={13} /> Current-first assignment</span>
          <h1>Map legacy fields to your current model.</h1>
          <p>The current schema is the benchmark. Choose a current field, then attach every legacy field that feeds it.</p>
        </div>
        <div className="benchmark-pill"><Server size={16} /><span><strong>{summary.currentFieldCount}</strong> benchmark fields</span></div>
      </div>

      {!summary.currentFieldCount ? (
        <div className="empty-catalog surface">
          <span className="empty-catalog-icon"><Server size={25} /></span>
          <h2>Import your current schema first</h2>
          <p>The mapping workspace is intentionally anchored to your current system.</p>
          <button className="button button--primary" onClick={onOpenSources}><Upload size={16} /> Import current schema</button>
        </div>
      ) : (
        <>
          <div className="mapping-toolbar surface">
            <Search size={18} /><input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Find a current table or field…" />
            <select value={currentModel} onChange={(event) => setCurrentModel(event.target.value)} aria-label="Current model">{summary.currentModels.map((model) => <option key={model} value={model}>{model}</option>)}</select>
            <select value={legacyModel} onChange={(event) => setLegacyModel(event.target.value)} aria-label="Legacy model">{summary.legacyModels.map((model) => <option key={model} value={model}>{model}</option>)}</select>
            <span>{fields.length} current fields</span>
          </div>
          <div className="benchmark-label"><span>Current system · benchmark</span><span>Available legacy fields</span></div>
          <div className="current-field-list">
            {fields.map((field) => {
              const mappedIds = new Set(field.legacyFields.map((legacy) => legacy.id));
              return (
                <article className={`current-card surface ${picker === field.id ? "is-open" : ""}`} key={field.id}>
                  <div className="current-anchor">
                    <span className="system-tag">{field.model || "Current"}</span>
                    <h2><span>{field.table}.</span>{field.column}</h2>
                    <p>{field.description || "No field description supplied."}</p>
                    <small className="field-meta">{field.database || "—"} · {field.schema || "—"} · {field.dataType || "type unknown"}</small>
                  </div>
                  <div className="mapping-rail"><span>{field.legacyFields.length}</span><ArrowRight size={15} /></div>
                  <div className="legacy-assignments">
                    <div className="assignment-head"><strong>Legacy inputs</strong><span>{field.legacyFields.length} mapped</span></div>
                    {field.legacyFields.map((legacy) => (
                      <div className="legacy-chip" key={legacy.mappingId}>
                        <span><strong>{legacy.model} · {legacy.table}.{legacy.column}</strong><small>{legacy.description || "Legacy field"} · {legacy.database || "—"} · {legacy.dataType || "type unknown"}</small></span>
                        <button disabled={busy} onClick={() => void disconnect(legacy.mappingId)} aria-label={`Remove ${legacy.table}.${legacy.column}`}><Unlink size={14} /></button>
                      </div>
                    ))}
                    <button className="add-legacy" onClick={() => { setPicker(picker === field.id ? null : field.id); setLegacyQuery(""); }}>
                      <Plus size={15} /> Find legacy field
                    </button>
                    {picker === field.id && (
                      <div className="legacy-picker">
                        <div><Search size={15} /><input value={legacyQuery} onChange={(event) => setLegacyQuery(event.target.value)} placeholder="Search legacy table or column…" autoFocus /><button onClick={() => setPicker(null)}><X size={14} /></button></div>
                        <div className="legacy-options">
                          {legacyFields.filter((legacy) => !mappedIds.has(legacy.id)).map((legacy) => (
                            <button disabled={busy} key={legacy.id} onClick={() => void connect(field.id, legacy.id)}>
                              <span><strong>{legacy.table}.{legacy.column}</strong><small>{legacy.description || "No description"}</small></span>
                              <span className="map-action">Map <ArrowRight size={12} /></span>
                            </button>
                          ))}
                          {!legacyFields.length && !manualOpen && <><p>No legacy fields match this search.</p><button className="manual-entry-button" onClick={() => setManualOpen(field.id)}><Pencil size={13} /> Create and save legacy field</button></>}
                          {manualOpen === field.id && <div className="manual-field-form">
                            <strong>New legacy field · {legacyModel || "Legacy"}</strong>
                            <input placeholder="Database" value={manual.database} onChange={(event) => setManual({ ...manual, database: event.target.value })} />
                            <input placeholder="Schema" value={manual.schema} onChange={(event) => setManual({ ...manual, schema: event.target.value })} />
                            <input placeholder="Table name *" value={manual.table} onChange={(event) => setManual({ ...manual, table: event.target.value })} />
                            <input placeholder="Column name *" value={manual.column} onChange={(event) => setManual({ ...manual, column: event.target.value })} />
                            <input placeholder="Description" value={manual.description} onChange={(event) => setManual({ ...manual, description: event.target.value })} />
                            <input placeholder="Data type" value={manual.dataType} onChange={(event) => setManual({ ...manual, dataType: event.target.value })} />
                            <button className="button button--primary" disabled={busy || !manual.table || !manual.column} onClick={() => void createManual(field.id)}><Check size={13} /> Save and map</button>
                          </div>}
                        </div>
                      </div>
                    )}
                  </div>
                </article>
              );
            })}
          </div>
        </>
      )}
    </section>
  );
}

interface DataSourcesProps {
  summary: CatalogSummary;
  onClose: () => void;
  onChanged: () => void;
  onError: (message: string) => void;
}

function DataSources({ summary, onClose, onChanged, onError }: DataSourcesProps) {
  const [imports, setImports] = useState<ImportRecord[]>([]);
  const [busy, setBusy] = useState<ImportKind | null>(null);
  const [result, setResult] = useState<ImportResponse | null>(null);
  const [confirmClear, setConfirmClear] = useState(false);
  const [currentModel, setCurrentModel] = useState("Current");
  const [legacyModel, setLegacyModel] = useState("Legacy");
  const [mappingLegacyModel, setMappingLegacyModel] = useState("Legacy");
  const [mappingCurrentModel, setMappingCurrentModel] = useState("Current");
  const inputs = {
    current: useRef<HTMLInputElement>(null),
    legacy: useRef<HTMLInputElement>(null),
    mappings: useRef<HTMLInputElement>(null),
  };

  const loadHistory = () => getImports().then((response) => setImports(response.imports));
  useEffect(() => { void loadHistory(); }, []);

  const upload = async (kind: ImportKind, event: ChangeEvent<HTMLInputElement>) => {
    const files = [...(event.target.files ?? [])];
    event.target.value = "";
    if (!files.length) return;
    setBusy(kind);
    setResult(null);
    try {
      const response = await importCatalogFiles(kind, files, kind === "mappings"
        ? { legacyModel: mappingLegacyModel, currentModel: mappingCurrentModel }
        : { model: kind === "current" ? currentModel : legacyModel });
      setResult(response);
      await loadHistory();
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Import failed.");
    } finally {
      setBusy(null);
    }
  };

  const clear = async () => {
    if (!confirmClear) { setConfirmClear(true); return; }
    try {
      await clearCatalog();
      setImports([]);
      setResult(null);
      setConfirmClear(false);
      onChanged();
    } catch (reason) {
      onError(reason instanceof Error ? reason.message : "Could not clear catalog.");
    }
  };

  return (
    <div className="drawer-layer" role="dialog" aria-modal="true" aria-label="Data sources">
      <button className="drawer-scrim" onClick={onClose} aria-label="Close" />
      <aside className="drawer">
        <header>
          <div><span className="eyebrow"><Database size={13} /> Persistent catalog</span><h2>Data sources</h2><p>Imports merge into the saved local catalog.</p></div>
          <button className="icon-button" onClick={onClose} aria-label="Close"><X size={19} /></button>
        </header>

        <div className="source-stats">
          <SummaryMetric value={summary.currentFieldCount} label="Current" />
          <SummaryMetric value={summary.legacyFieldCount} label="Legacy" />
          <SummaryMetric value={summary.mappingCount} label="Mappings" />
        </div>

        <div className="source-cards">
          <SourceCardWrap label="Current model alias" value={currentModel} onChange={setCurrentModel}><SourceCard kind="current" title="Current system" badge="Benchmark" description="The tables and fields your organization uses now." busy={busy} onChoose={() => inputs.current.current?.click()} /></SourceCardWrap>
          <SourceCardWrap label="Legacy model alias" value={legacyModel} onChange={setLegacyModel}><SourceCard kind="legacy" title="Legacy systems" badge="Available fields" description="Candidate source fields that can be assigned to the benchmark." busy={busy} onChoose={() => inputs.legacy.current?.click()} /></SourceCardWrap>
          <SourceCardWrap label="Mapping pair aliases" value={`${mappingLegacyModel} → ${mappingCurrentModel}`} onChange={(value) => { const [legacy, current] = value.split("→").map((part) => part.trim()); setMappingLegacyModel(legacy || "Legacy"); setMappingCurrentModel(current || "Current"); }} placeholder="Legacy → Current"><SourceCard kind="mappings" title="Existing mappings" badge="Paired rows" description="Merge existing legacy-to-current relationships into the catalog." busy={busy} onChoose={() => inputs.mappings.current?.click()} /></SourceCardWrap>
          {(Object.keys(inputs) as ImportKind[]).map((kind) => <input key={kind} ref={inputs[kind]} hidden type="file" multiple accept=".csv,.xlsx" onChange={(event) => void upload(kind, event)} />)}
        </div>

        {result && (
          <div className="import-result"><Check size={15} /><span><strong>{result.validCount} rows imported.</strong>{result.invalidCount ? ` ${result.invalidCount} invalid rows skipped.` : " Catalog is up to date."}</span></div>
        )}

        <div className="format-note"><FileSpreadsheet size={17} /><div><strong>Simple formats, automatic detection</strong><p>Inventories use Table Name, Column Name, Description. Existing mappings use paired legacy/current headers. CSV and XLSX are supported.</p></div></div>

        <section className="import-history">
          <header><strong>Recent imports</strong>{summary.ready && <a href="/api/catalog/download"><Download size={13} /> Export catalog</a>}</header>
          {imports.length ? imports.slice(0, 8).map((item) => (
            <div className="history-row" key={item.id}>
              <span className={`history-icon history-icon--${item.kind}`}><FileSpreadsheet size={14} /></span>
              <span><strong>{item.filename}</strong><small>{item.kind} · {item.legacyModel || item.currentModel ? `${item.legacyModel || ""}${item.legacyModel && item.currentModel ? " → " : ""}${item.currentModel || ""} · ` : ""}{new Date(item.importedAt).toLocaleString()}</small></span>
              <b>{item.validCount}</b>
            </div>
          )) : <p className="history-empty">No files imported yet.</p>}
        </section>

        {summary.ready && (
          <div className="danger-zone">
            <div><strong>Reset local catalog</strong><p>Removes fields, mappings, and import history from this machine.</p></div>
            <button className={confirmClear ? "is-confirming" : ""} onClick={() => void clear()} onBlur={() => setConfirmClear(false)}><Trash2 size={14} />{confirmClear ? "Click again" : "Clear"}</button>
          </div>
        )}
        <footer><LockKeyhole size={13} /> Stored only in your local Entity Map database</footer>
      </aside>
    </div>
  );
}

function SourceCard({ kind, title, badge, description, busy, onChoose }: { kind: ImportKind; title: string; badge: string; description: string; busy: ImportKind | null; onChoose: () => void }) {
  const icons = { current: Server, legacy: Layers3, mappings: Link2 };
  const Icon = icons[kind];
  return (
    <button className={`source-card source-card--${kind}`} disabled={busy !== null} onClick={onChoose}>
      <span className="source-icon">{busy === kind ? <LoaderCircle className="spin" size={20} /> : <Icon size={20} />}</span>
      <span><span className="source-title"><strong>{title}</strong><em>{badge}</em></span><small>{description}</small></span>
      <Upload size={16} />
    </button>
  );
}

function SourceCardWrap({ label, value, onChange, placeholder, children }: { label: string; value: string; onChange: (value: string) => void; placeholder?: string; children: ReactNode }) {
  return <div className="source-card-wrap"><label>{label}<input value={value} placeholder={placeholder} onChange={(event) => onChange(event.target.value)} /></label>{children}</div>;
}

export default App;
