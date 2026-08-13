export type SearchScope = "legacy" | "current";
export type ImportKind = "current" | "legacy" | "mappings";

export interface CatalogSummary {
  ready: boolean;
  legacyFieldCount: number;
  currentFieldCount: number;
  mappingCount: number;
  matchedCount: number;
  unmatchedCount: number;
  matchedPercent: number;
  unmatchedPercent: number;
  currentMatchedCount: number;
  currentUnmatchedCount: number;
  currentUnmatchedPercent: number;
  importCount: number;
  lastImportedAt: string | null;
  legacyModels: string[];
  currentModels: string[];
}

export interface ImportRecord {
  id: number;
  kind: ImportKind;
  filename: string;
  importedAt: string;
  validCount: number;
  invalidCount: number;
  legacyModel?: string;
  currentModel?: string;
}

export interface ImportResponse {
  validCount: number;
  invalidCount: number;
  invalidRows: Array<Record<string, string | number>>;
  invalidRowsTruncated: boolean;
  files: Array<{ filename: string; validCount: number; invalidCount: number }>;
  summary: CatalogSummary;
}

export interface FilterOptions {
  legacyTables: string[];
  currentTables: string[];
  mappingStates: string[];
  sourceFiles: string[];
  legacyModels: string[];
  currentModels: string[];
}

export interface RelationshipRow {
  relationship_id: number;
  legacy_model: string;
  legacy_database: string;
  legacy_schema: string;
  legacy_table: string;
  legacy_column: string;
  legacy_description: string;
  legacy_data_type: string;
  current_model: string;
  current_database: string;
  current_schema: string;
  current_table: string;
  current_column: string;
  current_description: string;
  current_data_type: string;
  mapping_state: "Mapped" | "Unmapped";
  unmapped_side: "legacy" | "current" | "";
  provenance_count: number;
  source_files: string;
}

export interface SearchResponse {
  total: number;
  offset: number;
  limit: number;
  rows: RelationshipRow[];
  legacyFieldCount: number;
  currentFieldCount: number;
}

export interface RelationshipDetail {
  sourceSide: "legacy" | "current";
  source: {
    model: string;
    database: string;
    schema: string;
    table: string;
    column: string;
    description: string;
    dataType: string;
  };
  targets: Array<{
    relationshipId: number;
    model: string;
    database: string;
    schema: string;
    table: string;
    column: string;
    description: string;
    dataType: string;
    state: "Mapped" | "Unmapped";
    sourceCount: number;
  }>;
  provenance: Array<{ source_file: string; source_sheet: string; source_row: number }>;
}

export interface LegacyField {
  id: number;
  model: string;
  database: string;
  schema: string;
  table: string;
  column: string;
  description: string;
  dataType: string;
  mappingCount: number;
}

export interface CurrentField {
  id: number;
  model: string;
  database: string;
  schema: string;
  table: string;
  column: string;
  description: string;
  dataType: string;
  mappingCount: number;
  legacyFields: Array<{
    mappingId: number;
    id: number;
    model: string;
    database: string;
    schema: string;
    table: string;
    column: string;
    description: string;
    dataType: string;
  }>;
}
