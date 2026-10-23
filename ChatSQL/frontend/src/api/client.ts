export interface Dataset {
  id: string;
  name: string;
  short_code: string;
  source_type: string;
  dialect: string;
  db_version: string;
  schema_version: number;
  table_count: number;
  status: string;
  error_message: string;
  created_at: string;
  updated_at: string;
  content_fingerprint: string;
}

export interface SchemaColumn {
  name: string;
  type: string;
  comment: string;
  nullable: boolean;
  semantic_type?: string;
  semantic_confidence?: number;
  parse_format?: string;
  role?: string;
}

export interface SchemaTable {
  name: string;
  short_code: string;
  comment: string;
  columns: SchemaColumn[];
  primary_key: string[];
  foreign_keys: Array<Record<string, unknown>>;
}

export interface SchemaSnapshot {
  schema_version: number;
  dataset_id: string;
  dataset_name: string;
  db_type: string;
  db_version: string;
  tables: SchemaTable[];
}

export interface EntityCandidate {
  type: "organization" | "metric";
  code: string;
  name: string;
  matched_by: "code_exact" | "name_exact" | "alias_exact" | "pinyin_exact" | "business_abbreviation_exact" | "name_prefix" | "pinyin_prefix" | "business_abbreviation_prefix";
}

export interface PermissionSubjectUser {
  id: number;
  username: string;
  role: string;
  enabled: number;
  created_at: string;
  updated_at: string;
}

export interface PermissionSubjectGroup {
  id: number;
  name: string;
  description: string;
  enabled: number;
  created_at: string;
  updated_at: string;
}

export interface PermissionSubjectTarget {
  type: "user" | "group";
  id: number;
}

export interface PermissionSchemaColumn {
  column_name: string;
  type: string;
  nullable: boolean;
  semantic_type?: string;
  semantic_confidence?: number;
  parse_format?: string;
  role?: string;
}

export interface PermissionSchemaTable {
  dataset_id: string;
  table_name: string;
  columns: PermissionSchemaColumn[];
}

export interface RowPermissionItem {
  id: number;
  dataset_id: string;
  table_name: string;
  column_name: string;
  operator: string;
  allowed_value: string;
  permission_group_id: number;
  permission_group_name: string;
  enabled: number;
  created_at: string;
  updated_at: string;
}

export interface ApiError {
  error?: {
    type: string;
    message: string;
  };
}

export interface ConversationSummary {
  id: string;
  title: string;
  status: string;
  selected_dataset_id: string;
  scroll_position: number;
  created_at: string;
  last_activity_at: string;
  last_user_message_at: string | null;
  dashboard_referenced?: boolean;
}

export interface ContextSegment {
  id: string;
  conversation_id: string;
  position: number;
  query_summary: string;
  created_at: string;
  last_activity_at: string;
}

export interface ChatMessage {
  id: string;
  conversation_id: string;
  context_segment_id: string;
  role: "user" | "assistant";
  content: string;
  query_summary: string;
  created_at: string;
  chart_recommendations?: ChartRecommendation[];
}

export interface ChartRecommendation {
  table_id: string;
  type: string;
  title: string;
  x: string;
  y: string[];
  y2: string[];
  series: string;
  y_zero: "auto" | "zero" | "data_range";
}

export interface DebugRecord {
  id: string;
  conversation_id: string;
  context_segment_id: string;
  message_id: string;
  stage: string;
  status: string;
  started_at: string;
  ended_at: string;
  duration_ms: number;
  input_summary: string;
  output_summary: string;
  error_type: string;
}

export interface LLMConfig {
  id: string;
  name: string;
  provider_type: "online" | "local" | "cloud";
  base_url: string;
  model_name: string;
  timeout_seconds: number;
  max_tokens: number;
  temperature: number;
  structured_output_mode: "json_schema" | "json_object" | "prompt_json" | "auto";
  is_enabled: boolean;
  has_api_key: boolean;
  created_at: string;
  updated_at: string;
}

export interface ConversationDetail extends ConversationSummary {
  contexts: ContextSegment[];
  messages: ChatMessage[];
  debug_records: DebugRecord[];
  future_context: Array<{ role: string; question_summary: string }>;
}

export interface DashboardCard {
  id: string;
  dashboard_id: string;
  card_type: "chart" | "table" | "metric" | "text" | string;
  title: string;
  layout: { x: number; y: number; w: number; h: number; cols?: number };
  dataset_id: string;
  source_type: string;
  query: Record<string, any>;
  chart_config: Record<string, any>;
  result_snapshot: Record<string, any>;
  error_message: string;
  created_at: string;
  updated_at: string;
}

export interface DashboardSummary {
  id: string;
  name: string;
  card_count: number;
  created_at: string;
  updated_at: string;
}

export interface DashboardDetail {
  id: string;
  name: string;
  config?: Record<string, any>;
  cards: DashboardCard[];
  created_at: string;
  updated_at: string;
}

const API_BASE = "";
const TOKEN_STORAGE_KEY = "chatsql.auth_token";

let authToken = localStorage.getItem(TOKEN_STORAGE_KEY) || "";

export interface AuthUser {
  username: string;
  role: "admin" | "user" | string;
  expires_at: number;
}

export function setAuthToken(token: string) {
  authToken = token;
  localStorage.setItem(TOKEN_STORAGE_KEY, token);
}

export function clearAuthToken() {
  authToken = "";
  localStorage.removeItem(TOKEN_STORAGE_KEY);
}

function withAuthHeaders(options?: RequestInit): RequestInit {
  const headers = new Headers(options?.headers || {});
  if (authToken && !headers.has("Authorization")) {
    headers.set("Authorization", `Bearer ${authToken}`);
  }
  return { ...(options || {}), headers };
}

async function request<T>(url: string, options?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE}${url}`, withAuthHeaders(options));
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as ApiError;
    throw new Error(body.error?.message || `请求失败：${response.status}`);
  }
  return (await response.json()) as T;
}

export async function login(payload: { username: string; password: string }): Promise<{ token: string; user: AuthUser }> {
  return request("/api/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function getCurrentUser(): Promise<{ user: AuthUser }> {
  return request("/api/auth/me");
}

export async function listDatasets(): Promise<{ items: Dataset[]; limit: number }> {
  return request("/api/datasets");
}

export async function getEntityCandidates(datasetId: string, query: string, signal?: AbortSignal): Promise<{ dataset_id: string; query: string; matched_text: string; items: EntityCandidate[]; has_more?: boolean }> {
  return request(`/api/entity-candidates/${datasetId}?q=${encodeURIComponent(query)}`, { signal });
}

export async function listConversations(): Promise<{ items: ConversationSummary[]; referenced_items?: ConversationSummary[]; limit: number }> {
  return request("/api/conversations");
}

export async function createConversation(): Promise<{ conversation: ConversationDetail }> {
  return request("/api/conversations", { method: "POST" });
}

export async function getConversation(conversationId: string): Promise<{ conversation: ConversationDetail }> {
  return request(`/api/conversations/${conversationId}`);
}

export async function saveConversationState(
  conversationId: string,
  payload: { selected_dataset_id?: string; scroll_position?: number }
): Promise<{ conversation: ConversationDetail }> {
  return request(`/api/conversations/${conversationId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function sendMessage(
  conversationId: string,
  payload: { content: string; selected_dataset_id?: string; request_id?: string; thinking_enabled?: boolean; fast_match_enabled?: boolean; context_mode_enabled?: boolean; context_mode_session_id?: string },
  signal?: AbortSignal
): Promise<{
  conversation: ConversationDetail;
  messages: ChatMessage[];
  debug_records: DebugRecord[];
  auto_created: boolean;
}> {
  return request(`/api/conversations/${conversationId}/messages`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal
  });
}

export async function removeConversation(conversationId: string): Promise<{ deleted: { id: string; title: string } }> {
  return request(`/api/conversations/${conversationId}`, { method: "DELETE" });
}

export async function cancelConversation(conversationId: string): Promise<{ conversation: ConversationDetail }> {
  return request(`/api/conversations/${conversationId}/cancel`, { method: "POST" });
}

export async function listDashboards(): Promise<{ items: DashboardSummary[] }> {
  return request("/api/dashboards");
}

export async function createDashboard(payload: { name?: string }): Promise<{ dashboard: DashboardDetail }> {
  return request("/api/dashboards", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function getDashboard(dashboardId: string): Promise<{ dashboard: DashboardDetail }> {
  return request(`/api/dashboards/${dashboardId}`);
}

export async function updateDashboard(dashboardId: string, payload: { name: string }): Promise<{ dashboard: DashboardDetail }> {
  return request(`/api/dashboards/${dashboardId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function updateDashboardConfig(dashboardId: string, payload: { config: Record<string, any> }): Promise<{ dashboard: DashboardDetail }> {
  return request(`/api/dashboards/${dashboardId}/config`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteDashboard(dashboardId: string): Promise<{ deleted: { id: string; name: string } }> {
  return request(`/api/dashboards/${dashboardId}`, { method: "DELETE" });
}

export async function createDashboardCard(dashboardId: string, payload: Partial<DashboardCard>): Promise<{ card: DashboardCard }> {
  return request(`/api/dashboards/${dashboardId}/cards`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function updateDashboardCard(dashboardId: string, cardId: string, payload: Partial<DashboardCard>): Promise<{ card: DashboardCard }> {
  return request(`/api/dashboards/${dashboardId}/cards/${cardId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteDashboardCard(dashboardId: string, cardId: string): Promise<{ deleted: { id: string; title: string } }> {
  return request(`/api/dashboards/${dashboardId}/cards/${cardId}`, { method: "DELETE" });
}

export async function refreshDashboardCard(dashboardId: string, cardId: string): Promise<{ card: DashboardCard }> {
  return request(`/api/dashboards/${dashboardId}/cards/${cardId}/refresh`, { method: "POST" });
}

export async function refreshDashboard(dashboardId: string): Promise<{ dashboard: DashboardDetail }> {
  return request(`/api/dashboards/${dashboardId}/refresh`, { method: "POST" });
}

export async function previewDashboardManualQuery(payload: { dataset_id: string; title?: string; query: Record<string, any> }): Promise<{ table: Record<string, any> }> {
  return request("/api/dashboards/manual-preview", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function getDashboardDynamicSchema(dashboardId: string, datasetId: string): Promise<{
  dataset_id: string;
  schema_version: number;
  updated_at: string;
  tables: Array<{ table_name: string; columns: Array<{ column_name: string; type: string; nullable: boolean }> }>;
}> {
  return request(`/api/dashboards/${dashboardId}/dynamic-schema/${datasetId}`);
}

export async function getDashboardDynamicValues(
  dashboardId: string,
  datasetId: string,
  tableName: string,
  columnName: string,
  q = ""
): Promise<{ dataset_id: string; table_name: string; column_name: string; values: string[]; has_more: boolean }> {
  const params = new URLSearchParams({ table_name: tableName, column_name: columnName, q, limit: "200" });
  return request(`/api/dashboards/${dashboardId}/dynamic-values/${datasetId}?${params.toString()}`);
}

export async function getSchema(datasetId: string): Promise<SchemaSnapshot> {
  return request(`/api/schema/${datasetId}`);
}

export async function listPermissionSubjects(): Promise<{ users: PermissionSubjectUser[]; groups: PermissionSubjectGroup[] }> {
  return request("/api/auth/admin/permission-subjects");
}

export async function getPermissionCandidates(datasetId: string): Promise<{ dataset_id: string; tables: PermissionSchemaTable[] }> {
  return request(`/api/auth/admin/schema-permissions/${datasetId}/candidates`);
}

export async function getPermissionValues(
  datasetId: string,
  tableName: string,
  columnName: string,
  params: { q?: string; limit?: number; offset?: number } = {}
): Promise<{ dataset_id: string; table_name: string; column_name: string; values: string[]; limit: number; offset: number; has_more: boolean }> {
  const query = new URLSearchParams({
    table_name: tableName,
    column_name: columnName,
    q: params.q || "",
    limit: String(params.limit || 100),
    offset: String(params.offset || 0)
  });
  return request(`/api/auth/admin/schema-permissions/${datasetId}/values?${query.toString()}`);
}

export async function listRowPermissions(subjectType: "user" | "group", subjectId: number): Promise<{ items: RowPermissionItem[] }> {
  const query = new URLSearchParams({ subject_type: subjectType, subject_id: String(subjectId) });
  return request(`/api/auth/admin/row-permissions?${query.toString()}`);
}

export async function saveRowPermissions(payload: {
  targets: PermissionSubjectTarget[];
  rules: Array<{ dataset_id: string; table_name: string; column_name: string; operator: string; allowed_values: string[] }>;
}): Promise<{ status: string; updated_group_count: number; rule_count: number }> {
  return request("/api/auth/admin/row-permissions", {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteRowPermissions(payload: { targets: PermissionSubjectTarget[] }): Promise<{ status: string; updated_group_count: number; rule_count: number }> {
  return request("/api/auth/admin/row-permissions", {
    method: "DELETE",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ ...payload, rules: [] })
  });
}

export async function preloadEmbedding(datasetId: string): Promise<Record<string, unknown>> {
  return request(`/api/embedding/preload/${datasetId}`, { method: "POST" });
}

export async function uploadDataset(kind: "csv" | "excel", file: File): Promise<{ dataset: Dataset; removed: string[] }> {
  return uploadDatasetWithProgress(kind, file);
}

export async function uploadDatasetWithProgress(
  kind: "csv" | "excel",
  file: File,
  onProgress?: (progress: { loaded: number; total: number; percent: number }) => void
): Promise<{ dataset: Dataset; removed: string[] }> {
  const form = new FormData();
  form.append("file", file);
  return new Promise((resolve, reject) => {
    const xhr = new XMLHttpRequest();
    xhr.open("POST", `${API_BASE}/api/imports/${kind}`);
    if (authToken) {
      xhr.setRequestHeader("Authorization", `Bearer ${authToken}`);
    }
    xhr.upload.onprogress = (event) => {
      if (!event.lengthComputable) return;
      onProgress?.({
        loaded: event.loaded,
        total: event.total,
        percent: Math.max(0, Math.min(100, Math.round((event.loaded / event.total) * 100)))
      });
    };
    xhr.upload.onload = () => {
      onProgress?.({ loaded: file.size, total: file.size, percent: 100 });
    };
    xhr.onload = () => {
      const body = xhr.responseText ? JSON.parse(xhr.responseText) : {};
      if (xhr.status >= 200 && xhr.status < 300) {
        resolve(body as { dataset: Dataset; removed: string[] });
        return;
      }
      const errorBody = body as ApiError;
      reject(new Error(errorBody.error?.message || `请求失败：${xhr.status}`));
    };
    xhr.onerror = () => reject(new Error("网络请求失败"));
    xhr.onabort = () => reject(new Error("上传已取消"));
    xhr.send(form);
  });
}

export async function updateDataset(datasetId: string, payload: { name: string; short_code: string }): Promise<{ dataset: Dataset }> {
  return request(`/api/datasets/${datasetId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteDataset(datasetId: string): Promise<{ deleted: { id: string; name: string } }> {
  return request(`/api/datasets/${datasetId}`, { method: "DELETE" });
}

export async function connectMySQL(payload: {
  host: string;
  port: number;
  username: string;
  password: string;
  database: string;
  dataset_name?: string;
}): Promise<{ dataset: Dataset; removed: string[] }> {
  return request("/api/mysql/schema", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function listLLMConfigs(): Promise<{ items: LLMConfig[] }> {
  return request("/api/llm/configs");
}

export async function createLLMConfig(payload: {
  name: string;
  provider_type: string;
  base_url: string;
  api_key?: string;
  model_name: string;
  timeout_seconds: number;
  max_tokens: number;
  temperature: number;
  structured_output_mode: string;
  is_enabled: boolean;
}): Promise<{ config: LLMConfig }> {
  return request("/api/llm/configs", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function updateLLMConfig(
  configId: string,
  payload: {
    name: string;
    provider_type: string;
    base_url: string;
    api_key?: string;
    model_name: string;
    timeout_seconds: number;
    max_tokens: number;
    temperature: number;
    structured_output_mode: string;
    is_enabled: boolean;
  }
): Promise<{ config: LLMConfig }> {
  return request(`/api/llm/configs/${configId}`, {
    method: "PUT",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload)
  });
}

export async function deleteLLMConfig(configId: string): Promise<{ deleted: { id: string; name: string } }> {
  return request(`/api/llm/configs/${configId}`, { method: "DELETE" });
}

export async function selectLLMConfig(configId: string): Promise<{ config: LLMConfig }> {
  return request(`/api/llm/configs/${configId}/select`, { method: "POST" });
}

export async function testLLMConfig(configId: string): Promise<Record<string, unknown>> {
  return request(`/api/llm/configs/${configId}/test`, { method: "POST" });
}
