import type {
  CatalogSummary,
  CurrentField,
  FilterOptions,
  ImportKind,
  ImportRecord,
  ImportResponse,
  LegacyField,
  RelationshipDetail,
  SearchResponse,
  SearchScope,
} from "./types";

async function request<T>(url: string, init?: RequestInit): Promise<T> {
  const response = await fetch(url, init);
  if (!response.ok) {
    let message = `Request failed (${response.status})`;
    try {
      const payload = await response.json();
      if (typeof payload.detail === "string") message = payload.detail;
      else if (payload.detail) message = JSON.stringify(payload.detail);
    } catch {
      // Keep the status-based message when a response has no JSON body.
    }
    throw new Error(message);
  }
  if (response.status === 204) return undefined as T;
  return response.json() as Promise<T>;
}

export interface ActiveFilters {
  legacyTable: string[];
  currentTable: string[];
  mappingState: string[];
  sourceFile: string[];
  legacyModel: string[];
  currentModel: string[];
}

export const emptyFilters: ActiveFilters = {
  legacyTable: [],
  currentTable: [],
  mappingState: [],
  sourceFile: [],
  legacyModel: [],
  currentModel: [],
};

export function getSummary(legacyModel = "", currentModel = ""): Promise<CatalogSummary> {
  const params = new URLSearchParams({ legacy_model: legacyModel, current_model: currentModel });
  return request<CatalogSummary>(`/api/catalog/summary?${params}`);
}

export function getImports(): Promise<{ imports: ImportRecord[] }> {
  return request<{ imports: ImportRecord[] }>("/api/catalog/imports");
}

export function importCatalogFiles(
  kind: ImportKind,
  files: File[],
  options: { model?: string; legacyModel?: string; currentModel?: string } = {},
): Promise<ImportResponse> {
  const body = new FormData();
  files.forEach((file) => body.append("files", file));
  if (options.model) body.append("model", options.model);
  if (options.legacyModel) body.append("legacy_model", options.legacyModel);
  if (options.currentModel) body.append("current_model", options.currentModel);
  return request<ImportResponse>(`/api/import/${kind}`, { method: "POST", body });
}

export function getFilters(): Promise<FilterOptions> {
  return request<FilterOptions>("/api/catalog/filters");
}

export function searchMappings(
  query: string,
  scope: SearchScope,
  filters: ActiveFilters,
  offset = 0,
): Promise<SearchResponse> {
  const params = new URLSearchParams({ q: query, scope, offset: String(offset), limit: "200" });
  filters.legacyTable.forEach((value) => params.append("legacy_table", value));
  filters.currentTable.forEach((value) => params.append("current_table", value));
  filters.mappingState.forEach((value) => params.append("mapping_state", value));
  filters.sourceFile.forEach((value) => params.append("source_file", value));
  filters.legacyModel.forEach((value) => params.append("legacy_model", value));
  filters.currentModel.forEach((value) => params.append("current_model", value));
  return request<SearchResponse>(`/api/catalog/search?${params}`);
}

export function getRelationship(relationshipId: number): Promise<RelationshipDetail> {
  return request<RelationshipDetail>(`/api/catalog/relationships/${relationshipId}`);
}

export function getCurrentFields(query = "", model = ""): Promise<{ fields: CurrentField[]; count: number }> {
  return request<{ fields: CurrentField[]; count: number }>(
    `/api/current-fields?q=${encodeURIComponent(query)}&model=${encodeURIComponent(model)}&limit=200`,
  );
}

export function getLegacyFields(query = "", model = ""): Promise<{ fields: LegacyField[]; count: number }> {
  return request<{ fields: LegacyField[]; count: number }>(
    `/api/legacy-fields?q=${encodeURIComponent(query)}&model=${encodeURIComponent(model)}&limit=80`,
  );
}

export function addMapping(currentFieldId: number, legacyFieldId: number): Promise<{ mappingId: number }> {
  return request<{ mappingId: number }>("/api/mappings", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ currentFieldId, legacyFieldId }),
  });
}

export function removeMapping(mappingId: number): Promise<void> {
  return request<void>(`/api/mappings/${mappingId}`, { method: "DELETE" });
}

export function createField(payload: {
  kind: "legacy" | "current";
  model: string;
  database?: string;
  schema?: string;
  table: string;
  column: string;
  description?: string;
  dataType?: string;
}): Promise<{ fieldId: number }> {
  return request<{ fieldId: number }>("/api/fields", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
}

export function clearCatalog(): Promise<void> {
  return request<void>("/api/catalog", { method: "DELETE" });
}
