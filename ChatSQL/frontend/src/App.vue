<script setup lang="ts">
import { computed, nextTick, onBeforeUnmount, onMounted, reactive, ref, watch } from "vue";
import Chart from "chart.js/auto";
import type { ChartConfiguration, ChartType } from "chart.js";
import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  Clipboard,
  Code2,
  Database,
  Download,
  FileSpreadsheet,
  LayoutDashboard,
  Link2,
  MessageSquarePlus,
  Pin,
  RefreshCcw,
  Save,
  Settings,
  Send,
  StopCircle,
  Trash2,
  Upload,
  X
} from "lucide-vue-next";
import {
  cancelConversation,
  clearAuthToken,
  connectMySQL,
  createConversation,
  createDashboard,
  createDashboardCard,
  createLLMConfig,
  deleteDashboard,
  deleteDashboardCard,
  deleteDataset,
  deleteLLMConfig,
  deleteRowPermissions,
  getDashboard,
  getDashboardDynamicValues,
  getPermissionCandidates,
  getPermissionValues,
  getCurrentUser,
  getConversation,
  getEntityCandidates,
  getSchema,
  listDashboards,
  listPermissionSubjects,
  listRowPermissions,
  previewDashboardManualQuery,
  refreshDashboard,
  refreshDashboardCard,
  listLLMConfigs,
  listConversations,
  listDatasets,
  login,
  preloadEmbedding,
  removeConversation,
  saveConversationState,
  saveRowPermissions,
  selectLLMConfig,
  sendMessage,
  setAuthToken,
  testLLMConfig,
  updateDashboard,
  updateDashboardCard,
  updateDashboardConfig,
  updateDataset,
  updateLLMConfig,
  uploadDatasetWithProgress,
  type AuthUser,
  type ConversationDetail,
  type ConversationSummary,
  type ChartRecommendation,
  type ChatMessage,
  type Dataset,
  type DashboardCard,
  type DashboardDetail,
  type DashboardSummary,
  type DebugRecord,
  type EntityCandidate,
  type LLMConfig,
  type PermissionSchemaTable,
  type PermissionSubjectGroup,
  type PermissionSubjectUser,
  type PermissionSubjectTarget,
  type RowPermissionItem,
  type SchemaSnapshot
} from "./api/client";

type BoardLayout = DashboardCard["layout"];
type ManualFilter = { column: string; operator: string; value: string; value_to?: string; time_strategy?: string; date_strategy?: string; globalLinked?: boolean; linkedToGlobal?: boolean; useGlobalCondition?: boolean };
type DashboardDynamicParameter = {
  id: string;
  name: string;
  dataset_id: string;
  table_name: string;
  column_name: string;
  column_type?: string;
  parameter_type?: "value" | "time";
  current_value: string | string[];
  time_strategy?: string;
  start_date?: string;
  end_date?: string;
  multi?: boolean;
};

const TIME_POLICY_OPTIONS = [
  { value: "latest_date", label: "最新有效日期" },
  { value: "last_3_days", label: "最近3天" },
  { value: "last_7_days", label: "最近7天" },
  { value: "last_30_days", label: "最近30天" },
  { value: "last_quarter", label: "最近一个季度" },
  { value: "custom_range", label: "自定义起止日期" }
];

const BOARD_GRID_COLUMNS = 64;
const LEGACY_BOARD_GRID_COLUMNS = 12;
const BOARD_ROW_HEIGHT = 52;
const BOARD_MIN_WIDTH = 4;
const BOARD_MAX_HEIGHT = 8;

const datasets = ref<Dataset[]>([]);
const conversations = ref<ConversationSummary[]>([]);
const referencedConversations = ref<ConversationSummary[]>([]);
const llmConfigs = ref<LLMConfig[]>([]);
const dashboards = ref<DashboardSummary[]>([]);
const currentDashboard = ref<DashboardDetail | null>(null);
const selectedDashboardCardId = ref("");
const dashboardBusy = ref(false);
const dashboardMode = ref<"edit" | "preview">("edit");
const boardPageRef = ref<HTMLElement | null>(null);
const dashboardCanvas = ref<HTMLElement | null>(null);
const dashboardCharts = new Map<string, Chart>();
const dashboardCanvases = new Map<string, HTMLCanvasElement>();
const dashboardChartContainers = new Map<Element, string>();
let dashboardChartResizeObserver: ResizeObserver | null = null;
const animatedChartKeys = new Set<string>();
const boardToolsOpen = ref(false);
const boardFilterOpen = ref(false);
const boardEditorVisible = ref(false);
const boardEditorPinned = ref(false);
const boardDynamicSettingsOpen = ref(false);
const boardEditorCardId = ref("");
const manualEditingCardId = ref("");
const manualBuilderHydrating = ref(false);
const boardEditorPosition = reactive({ x: 22, y: 72 });
const boardEditorDrag = ref<{ startX: number; startY: number; x: number; y: number } | null>(null);
const dashboardDynamicDraft = reactive({
  dataset_id: "",
  table_name: "",
  column_name: "",
  name: "",
  value: "",
  time_strategy: "latest_date",
  start_date: "",
  end_date: "",
  values: [] as string[],
  loadingValues: false
});
const dashboardDynamicValueCache = ref<Record<string, string[]>>({});
const addToDashboardOpen = ref(false);
const addToDashboardTargetId = ref("");
const addToDashboardTitle = ref("");
const addToDashboardSize = ref<"small" | "medium" | "large">("medium");
const addToDashboardMode = ref<"static" | "dynamic">("static");
const dashboardDrag = ref<{
  cardId: string;
  mode: "move" | "resize";
  startX: number;
  startY: number;
  layout: BoardLayout;
  pointerId: number;
  captureTarget: HTMLElement | null;
  grabX: number;
  grabY: number;
  fixedX: number;
  fixedY: number;
  width: number;
  height: number;
  lastClientX: number;
  lastClientY: number;
  pixelX: number;
  pixelY: number;
  targetLayout: BoardLayout;
  targetValid: boolean;
} | null>(null);
const dashboardAutoScrollFrame = ref<number | null>(null);
const manualBuilder = reactive({
  component: "chart",
  refreshMode: "static",
  chartType: "column_clustered",
  metricDecimals: "none",
  title: "手动组件",
  dataset_id: "",
  table_name: "",
  category_column: "",
  value_columns: [] as string[],
  selected_columns: [] as string[],
  aggregate: "sum",
  filters: [] as ManualFilter[],
  text: "看板说明文字",
  align: "left"
});
const authUser = ref<AuthUser | null>(null);
const authChecked = ref(false);
const loginBusy = ref(false);
const loginError = ref("");
const loginForm = reactive({ username: "", password: "" });
const currentConversation = ref<ConversationDetail | null>(null);
const schema = ref<SchemaSnapshot | null>(null);
const selectedDatasetId = ref("");
const activePage = ref<"chat" | "datasets" | "board">("chat");
const draft = ref("");
const exampleQuestionsOpen = ref(false);
const entityCandidatesOpen = ref(false);
const entityCandidates = ref<EntityCandidate[]>([]);
const entityCandidatesHasMore = ref(false);
const activeEntityCandidateIndex = ref(-1);
const entityCandidatesPanel = ref<HTMLElement | null>(null);
const composerInput = ref<HTMLTextAreaElement | null>(null);
const entityFragment = ref({ start: 0, end: 0, text: "" });
const DATASET_EXAMPLE_QUESTIONS: Record<string, string[]> = {
  "60d253f38e99d4fc7d0d43eef8276a73fb5c1212c8bf16f12d935a8496eb1a4f": [
    "帮忙查一下江苏省E市农商行2026年3月末的不良贷款率。",
    "江苏省B市农商行的对公存款余额从2024年末到2025-05-31，增幅是多少？",
    "请分析江苏省A市农商行的各项存款余额从2025年一季度末到2026年一季度末的逐季变化，各季度末数值是多少？哪个季度数值最高？",
    "2025年全年，江苏省G市农商行的成本收入比有多少天高于全省均值？",
    "列出江苏省F市农商行在2026-04-30的风险指标数据，含不良率、拨备覆盖率、逾期率和资本充足率。"
  ],
  "85ecb9fd66471d0891b2e7f59f1cad1fccc827320f24a0ab79d804a680e8854b": [
    "瀚海银行青岛分行2025年9月末的电子票据业务量是多少？",
    "瀚海银行深圳分行2025年6月末的供应链融资投放额是多少？",
    "瀚海银行北京分行2025年1月末的活跃公司客户数是多少？",
    "2025年全年国际结算量累计排名前三的分行是哪些？",
    "瀚海银行上海分行2025年3月末的公司金融税前贡献额是多少？请列出计算构成。"
  ],
  "67327c578b265c76f24a9b638769b072ddc71035caffddbf17e516b09a17c52a": [
    "信贷科技服务在2025年第1周的周活跃用户数是多少？",
    "保险科技服务在2025年第50周的风险技术服务收入是多少？",
    "2025年第20周，四个业务板块中营销获客数表现最好的是哪个？",
    "财富科技服务2025年第32周的平台技术服务收入较上一周变化多少？",
    "分析信贷科技服务2025年第1、13、26、39、52周的周活跃用户数变化，并指出最佳节点。"
  ]
};
const status = ref("准备就绪");
const error = ref("");
const toast = reactive({ visible: false, text: "", kind: "info" as "info" | "success" | "warning" | "error" });
const uploadBusy = ref(false);
const datasetBusy = ref(false);
const indexBusy = ref(false);
const queryBusy = ref(false);
const llmBusy = ref(false);
const thinkingModeEnabled = ref(false);
const fastMatchEnabled = ref(localStorage.getItem("chatsql.fast_match_enabled") === "1");
const contextModeEnabled = ref(false);
const contextModeSessionId = ref("");
const loading = computed(() => uploadBusy.value || datasetBusy.value || indexBusy.value || queryBusy.value || llmBusy.value);
const activeController = ref<AbortController | null>(null);
const chatArea = ref<HTMLElement | null>(null);
const lastImportResult = ref("");
const importProgress = reactive({
  visible: false,
  step: "",
  percent: 0,
  indeterminate: false
});
const pendingTurn = ref<PendingTurn | null>(null);
const workspaceOpen = ref(true);
const workspaceWidth = ref(404);
const workspaceResizing = ref(false);
const mobileNavigationOpen = ref(false);
const mobileWorkspaceOpen = ref(false);
const workspaceTab = ref<"chart" | "debug">("chart");
const debugModeEnabled = ref(false);
const canUseDebug = computed(() => authUser.value?.role === "admin");
const selectedChartTableId = ref("");
const selectedChartMessageId = ref("");
const chartCanvas = ref<HTMLCanvasElement | null>(null);
const activeChart = ref<Chart | null>(null);
const chartRendered = ref(false);
const chartError = ref("");
const chartNotice = ref("");
const chartModeNotice = ref("");
const chartExportData = ref<Record<string, any> | null>(null);
type ChartTypeKey =
  | "column_clustered"
  | "column_stacked"
  | "bar_horizontal"
  | "line"
  | "pie"
  | "scatter"
  | "area"
  | "stock"
  | "combo_column_line";
const chartOptions = reactive({
  type: "line" as ChartTypeKey,
  categoryColumn: "",
  numericColumns: [] as string[],
  lineColumns: [] as string[],
  seriesColumn: "",
  yZeroMode: "auto" as "auto" | "zero" | "data_range",
  labelDensity: "auto" as "auto" | "full" | "sparse",
  dataLabelMode: "auto" as "auto" | "show" | "hide",
  sortMode: "original" as "original" | "asc" | "desc",
  limitMode: "none" as "none" | "top" | "bottom",
  limitCount: 10,
  legendMode: "auto" as "auto" | "show" | "hide",
  legendPosition: "top" as "top" | "bottom" | "left" | "right",
  xAxisTitle: "",
  yAxisTitle: "",
  unitLabel: "",
  lineSmooth: true,
  areaFill: false,
  pieMode: "doughnut" as "pie" | "doughnut",
  colorScheme: "morandi" as "morandi" | "sage" | "slate" | "warm",
  barThickness: "auto" as "auto" | "slim" | "bold",
  fontScale: "compact" as "compact" | "normal",
  showTitle: true,
  titlePosition: "chart_inner" as "card_top" | "chart_inner",
  title: ""
});
const editForm = reactive({ name: "", short_code: "" });
const llmForm = reactive({
  id: "",
  name: "",
  provider_type: "online",
  base_url: "",
  api_key: "",
  model_name: "",
  timeout_seconds: 30,
  max_tokens: 4000,
  temperature: 0,
  structured_output_mode: "auto",
  is_enabled: true
});
const mysqlForm = reactive({
  host: "127.0.0.1",
  port: 3306,
  username: "",
  password: "",
  database: "",
  dataset_name: ""
});
const permissionBusy = ref(false);
const permissionMessage = ref("");
const permissionMode = ref<"user" | "group">("user");
const permissionTargetSearch = ref("");
const permissionDatasetSearch = ref("");
const permissionValueSearch = ref("");
const permissionSubjects = reactive({
  users: [] as PermissionSubjectUser[],
  groups: [] as PermissionSubjectGroup[]
});
const selectedPermissionTargets = ref<number[]>([]);
const selectedPermissionDatasetIds = ref<string[]>([]);
const permissionActiveDatasetId = ref("");
const permissionCandidates = ref<{ dataset_id: string; tables: PermissionSchemaTable[] } | null>(null);
const selectedPermissionTables = ref<string[]>([]);
const selectedPermissionColumns = ref<string[]>([]);
const permissionActiveColumnKey = ref("");
const permissionValues = ref<string[]>([]);
const permissionValuesHasMore = ref(false);
const permissionValuesOffset = ref(0);
const permissionValueSelections = ref<Record<string, string[]>>({});
const accountMenuOpen = ref(false);
const accountSettingsOpen = ref(false);

const selectedDataset = computed(() => datasets.value.find((item) => item.id === selectedDatasetId.value) || null);
const selectedExampleQuestions = computed(() => DATASET_EXAMPLE_QUESTIONS[selectedDataset.value?.content_fingerprint || ""] || []);
const supportsDatasetExampleQuestions = computed(() => selectedExampleQuestions.value.length > 0);
const selectedDashboardCard = computed(() => currentDashboard.value?.cards.find((item) => item.id === (boardEditorCardId.value || selectedDashboardCardId.value)) || null);
const dashboardTables = computed(() => schema.value?.tables || []);
const manualTable = computed(() => dashboardTables.value.find((item) => item.name === manualBuilder.table_name) || null);
const manualColumns = computed(() => manualTable.value?.columns || []);
const dashboardDynamicParameters = computed<DashboardDynamicParameter[]>(() => (currentDashboard.value?.config?.dynamic_parameters || []) as DashboardDynamicParameter[]);
const dashboardDynamicTable = computed(() => dashboardTables.value.find((item) => item.name === dashboardDynamicDraft.table_name) || null);
const dashboardDynamicColumns = computed(() => dashboardDynamicTable.value?.columns || []);
const dashboardDynamicDraftColumn = computed(() => dashboardDynamicColumns.value.find((item) => item.name === dashboardDynamicDraft.column_name) || null);
const dashboardDynamicDraftInvalid = computed(() => {
  if (!dashboardDynamicDraft.dataset_id || !dashboardDynamicDraft.table_name || !dashboardDynamicDraft.column_name) return true;
  return isDashboardDynamicDraftTime() && dashboardDynamicDraft.time_strategy === "custom_range" && (!dashboardDynamicDraft.start_date || !dashboardDynamicDraft.end_date);
});
const manualNumericColumns = computed(() => manualColumns.value.filter((column) => /INT|DOUBLE|DECIMAL|NUMERIC|FLOAT|REAL|BIGINT|SMALLINT|TINYINT/i.test(column.type)));
const manualComponentLabel = computed(() => ({
  metric: "指标卡",
  chart: "柱状图",
  line: "折线图",
  pie: "饼图",
  table: "表格",
  text: "文本说明"
}[manualBuilder.component] || "组件"));
const manualBuilderIssue = computed(() => {
  const component = manualBuilder.component;
  if (component === "text") return manualBuilder.title.trim() ? "" : "请填写标题。";
  if (!manualBuilder.dataset_id) return "请选择数据集。";
  if (!manualBuilder.table_name) return "请选择数据表。";
  if (component !== "metric" && component !== "table" && !manualBuilder.category_column && manualBuilder.aggregate !== "none") return "请选择分类字段。";
  if (component === "metric" && (!manualBuilder.value_columns.length || manualBuilder.aggregate === "none")) return "指标卡需要数值字段和聚合方式。";
  if (component !== "table" && !manualBuilder.value_columns.length) return "请选择至少一个数值字段。";
  if (component === "table" && manualBuilder.aggregate === "none" && !manualBuilder.selected_columns.length) return "请选择表格字段。";
  const invalidFilter = manualBuilder.filters.some((item) => {
    if (!item.column) return true;
    if (manualFilterUsesGlobal(item)) return false;
    if (isManualFilterDateColumn(item)) {
      const strategy = manualFilterTimeStrategy(item);
      return !strategy || (strategy === "custom_range" && (!String(item.value || "").trim() || !String(item.value_to || "").trim()));
    }
    if (!item.operator || !String(item.value || "").trim()) return true;
    return item.operator === "between" && !String(item.value_to || "").trim();
  });
  return invalidFilter ? "请补完整筛选条件，或删除空条件。" : "";
});
const canManagePermissions = computed(() => authUser.value?.role === "admin");
const permissionTargetOptions = computed(() => {
  const query = permissionTargetSearch.value.trim().toLowerCase();
  const source =
    permissionMode.value === "user"
      ? permissionSubjects.users.map((item) => ({ id: item.id, label: item.username, note: `${item.role}${item.enabled ? "" : " · disabled"}` }))
      : permissionSubjects.groups.map((item) => ({ id: item.id, label: item.name, note: `${item.description || "权限组"}${item.enabled ? "" : " · disabled"}` }));
  return query ? source.filter((item) => `${item.label} ${item.note}`.toLowerCase().includes(query)) : source;
});
const permissionDatasetOptions = computed(() => {
  const query = permissionDatasetSearch.value.trim().toLowerCase();
  const source = datasets.value.filter((item) => item.status === "ready");
  return query ? source.filter((item) => `${item.short_code} ${item.name}`.toLowerCase().includes(query)) : source;
});
const permissionTableOptions = computed(() => {
  const tables = permissionCandidates.value?.tables || [];
  return tables.map((item) => ({
    key: makePermissionTableKey(permissionActiveDatasetId.value, item.table_name),
    table: item
  }));
});
const permissionColumnOptions = computed(() => {
  const selectedTables = new Set(selectedPermissionTables.value);
  return (permissionCandidates.value?.tables || [])
    .filter((table) => selectedTables.has(makePermissionTableKey(permissionActiveDatasetId.value, table.table_name)))
    .flatMap((table) =>
      table.columns.map((column) => ({
        key: makePermissionColumnKey(permissionActiveDatasetId.value, table.table_name, column.column_name),
        table_name: table.table_name,
        column
      }))
    );
});
const permissionActiveColumn = computed(() => parsePermissionColumnKey(permissionActiveColumnKey.value));
const permissionSelectedValues = computed(() => permissionValueSelections.value[permissionActiveColumnKey.value] || []);
const permissionRulePreview = computed(() => {
  const rules: Array<{ dataset_id: string; table_name: string; column_name: string; operator: string; allowed_values: string[] }> = [];
  for (const [key, values] of Object.entries(permissionValueSelections.value)) {
    const parsed = parsePermissionColumnKey(key);
    const allowed_values = values.filter(Boolean);
    if (!parsed || !allowed_values.length) continue;
    rules.push({
      dataset_id: parsed.datasetId,
      table_name: parsed.tableName,
      column_name: parsed.columnName,
      operator: "=",
      allowed_values
    });
  }
  return rules;
});
const permissionSelectedTargetPayload = computed<PermissionSubjectTarget[]>(() =>
  selectedPermissionTargets.value.map((id) => ({ type: permissionMode.value, id }))
);
const latestReadyDataset = computed(() => {
  return [...datasets.value]
    .filter((item) => item.status === "ready")
    .sort((left, right) => {
      const leftTime = Date.parse(left.created_at || "");
      const rightTime = Date.parse(right.created_at || "");
      const timeDelta = (Number.isFinite(rightTime) ? rightTime : 0) - (Number.isFinite(leftTime) ? leftTime : 0);
      if (timeDelta !== 0) return timeDelta;
      return right.id.localeCompare(left.id);
    })[0] || null;
});
const stageKeys = ["input_processing", "embedding_retrieval", "sql_planning", "sql_execution", "answer_generation"];
const stageNames: Record<string, string> = {
  input_processing: "输入处理",
  embedding_retrieval: "Embedding 检索",
  sql_planning: "SQL 规划",
  sql_execution: "SQL 执行",
  answer_generation: "答案生成"
};
const latestDebugByStage = computed(() => {
  const items = new Map<string, DebugRecord>();
  for (const record of currentConversation.value?.debug_records || []) {
    items.set(record.stage, record);
  }
  return items;
});
const embeddingDebug = computed<Record<string, any> | null>(() => {
  const raw = latestDebugByStage.value.get("embedding_retrieval")?.output_summary;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Record<string, any>;
  } catch {
    return null;
  }
});
const sqlPlanningDebug = computed<Record<string, any> | null>(() => parseDebug("sql_planning"));
const sqlExecutionDebug = computed<Record<string, any> | null>(() => parseDebug("sql_execution"));
const answerDebug = computed<Record<string, any> | null>(() => parseDebug("answer_generation"));
const totalDebugMs = computed(() => {
  return stageKeys.reduce((sum, stage) => sum + (latestDebugByStage.value.get(stage)?.duration_ms || 0), 0);
});
const activeLLMConfig = computed(() => llmConfigs.value.find((item) => item.is_enabled) || null);
type ChartField = {
  name: string;
  index: number;
  type: "numeric" | "ordered" | "text";
  usable: number;
};
type PendingTurn = {
  turn_id: string;
  request_id: string;
  conversation_id: string;
  content: string;
  status: "thinking" | "cancelled" | "error";
  error: string;
};
type RenderedTurn = {
  turn_id: string;
  request_id: string;
  user_message: { id: string; content: string };
  loading_status: string;
  result_tables: Record<string, any>[];
  final_answer: string;
  error_status: string;
  assistant_message_id: string;
  chart_recommendations: ChartRecommendation[];
};

const sqlByTaskId = computed(() => {
  const items = new Map<string, { before: string; after: string }>();
  for (const item of sqlExecutionDebug.value?.sql_before_after || []) {
    items.set(String(item.task_id || ""), {
      before: String(item.before || ""),
      after: String(item.after || "")
    });
  }
  return items;
});
const renderedTurns = computed<RenderedTurn[]>(() => buildRenderedTurns());
const selectedChartTable = computed<Record<string, any> | null>(() => {
  if (!selectedChartTableId.value) return null;
  for (const turn of renderedTurns.value) {
    if (selectedChartMessageId.value && turn.assistant_message_id !== selectedChartMessageId.value) {
      continue;
    }
    for (const table of turn.result_tables || []) {
      if (String(table.task_id || "") === selectedChartTableId.value) {
        return table;
      }
    }
  }
  return null;
});
const selectedChartRecommendation = computed<ChartRecommendation | null>(() => {
  if (!selectedChartTableId.value) return null;
  const turn = renderedTurns.value.find((item) => item.assistant_message_id === selectedChartMessageId.value);
  return turn?.chart_recommendations.find((item) => String(item.table_id) === selectedChartTableId.value) || null;
});
const chartFields = computed(() => analyzeChartFields(selectedChartTable.value));
const categoryFields = computed(() => chartFields.value.filter((field) => field.type !== "numeric"));
const numericFields = computed(() => chartFields.value.filter((field) => field.type === "numeric"));
const groupFields = computed(() => chartFields.value.filter((field) => field.type !== "numeric" && field.name !== chartOptions.categoryColumn));
let toastTimer: number | undefined;
let entityCandidateTimer: number | undefined;
let entityCandidateController: AbortController | null = null;
const workspaceDefaultWidth = 404;
const narrowNavigationQuery = "(max-width: 820px)";
const mobilePortraitQuery = "(max-width: 640px) and (orientation: portrait)";

const appShellStyle = computed(() => ({
  "--workspace-width": `${workspaceWidth.value}px`
}));

function isMobilePortrait() {
  return window.matchMedia(mobilePortraitQuery).matches;
}

function usesNavigationDrawer() {
  return window.matchMedia(narrowNavigationQuery).matches;
}

function closeMobilePanels() {
  mobileNavigationOpen.value = false;
  mobileWorkspaceOpen.value = false;
}

function openMobileNavigation() {
  if (!usesNavigationDrawer()) return;
  mobileWorkspaceOpen.value = false;
  mobileNavigationOpen.value = true;
}

function openMobileWorkspace() {
  if (!isMobilePortrait()) return;
  mobileNavigationOpen.value = false;
  mobileWorkspaceOpen.value = true;
}

function syncMobilePanelsByViewport() {
  if (!usesNavigationDrawer()) mobileNavigationOpen.value = false;
  if (!isMobilePortrait()) mobileWorkspaceOpen.value = false;
}

function parseDebug(stage: string): Record<string, any> | null {
  const raw = latestDebugByStage.value.get(stage)?.output_summary;
  if (!raw) return null;
  try {
    return JSON.parse(raw) as Record<string, any>;
  } catch {
    return null;
  }
}

function parseAssistantPayload(content: string): Record<string, any> | null {
  try {
    const payload = JSON.parse(content) as Record<string, any>;
    return payload.kind === "bank_nl2sql_answer_v1" ? payload : null;
  } catch {
    return null;
  }
}

function messageTime(message: ChatMessage): number {
  const value = Date.parse(message.created_at || "");
  return Number.isFinite(value) ? value : 0;
}

function compareMessages(left: ChatMessage, right: ChatMessage): number {
  const timeDelta = messageTime(left) - messageTime(right);
  if (timeDelta !== 0) return timeDelta;
  const roleDelta = (left.role === "user" ? 0 : 1) - (right.role === "user" ? 0 : 1);
  if (roleDelta !== 0) return roleDelta;
  return left.id.localeCompare(right.id);
}

function answerTextFromPayload(payload: Record<string, any>): string {
  const status = String(payload.answer_status || "");
  if (status === "success" || status === "completed" || (!status && payload.answer)) {
    return cleanFinalAnswerDisplayText(String(payload.answer || ""));
  }
  return "";
}

function cleanFinalAnswerDisplayText(content: string): string {
  let text = String(content || "").replace(/\r\n/g, "\n").replace(/\r/g, "\n").trim();
  const cutPatterns = [
    /^\s*(?:#{1,6}\s*)?(?:[一二三四五六七八九十]+[、.]\s*)?图表(?:推荐|建议)/im,
    /^\s*(?:#{1,6}\s*)?推荐图表/im,
    /^\s*<chart_recommendations\b/im,
    /^\s*```(?:json)?\s*\n\s*<chart_recommendations\b/im
  ];
  let cutAt = text.length;
  for (const pattern of cutPatterns) {
    const match = pattern.exec(text);
    if (match?.index !== undefined) cutAt = Math.min(cutAt, match.index);
  }
  text = text.slice(0, cutAt).trim();
  return text
    .split("\n")
    .map((line) => {
      let current = line.trim();
      if (current === "---") return "";
      current = current.replace(/^#{3,}\s*/, "");
      current = current.replace(/^(\s*(?:[-*]\s*)?(?:\d+[.、]\s*)?)\*\*/, "$1");
      current = current.replace(/\*\*\s*$/, "");
      current = current.replace(/\*\*/g, "");
      return current;
    })
    .filter((line, index, lines) => line || (index > 0 && lines[index - 1]))
    .join("\n")
    .trim();
}

function cleanAssistantDisplayText(content: string): string {
  let text = cleanFinalAnswerDisplayText(content);
  text = text.replace(/([：:])\s*T\d+\b/g, "");
  text = text.replace(/\bT\d+\./g, "");
  text = text.replace(/[ \t]+/g, " ").replace(/\n{3,}/g, "\n\n");
  if (text.includes("已反馈错误原因并重新请求第一次模型生成QueryPlan，仍未通过") && !text.includes("请修改描述后重试")) {
    text += "请修改描述后重试。";
  }
  return text;
}

function errorTextFromPayload(payload: Record<string, any>, hasTables: boolean): string {
  const status = String(payload.answer_status || "");
  const errorType = String(payload.error_type || "");
  if (status === "failed") {
    return hasTables ? `回答生成失败：${errorType || "-"}` : `查询失败：${errorType || "-"}`;
  }
  if (status === "cancelled") return "已停止生成";
  return "";
}

function turnFromUser(message: ChatMessage): RenderedTurn {
  return {
    turn_id: message.id,
    request_id: "",
    user_message: { id: message.id, content: message.content },
    loading_status: "",
    result_tables: [],
    final_answer: "",
    error_status: "",
    assistant_message_id: "",
    chart_recommendations: []
  };
}

function applyAssistantToTurn(turn: RenderedTurn, message: ChatMessage) {
  const payload = parseAssistantPayload(message.content);
  turn.assistant_message_id = message.id;
  if (!payload) {
    turn.final_answer = cleanAssistantDisplayText(message.content);
    turn.chart_recommendations = message.chart_recommendations || [];
    return;
  }
  const tables = Array.isArray(payload.tables) ? payload.tables : [];
  turn.result_tables = tables;
  const hasTables = tables.length > 0;
  const answer = answerTextFromPayload(payload);
  const error = errorTextFromPayload(payload, hasTables);
  turn.final_answer = answer;
  turn.error_status = error;
  turn.chart_recommendations = (Array.isArray(payload.chart_recommendations) ? payload.chart_recommendations : message.chart_recommendations || []) as ChartRecommendation[];
  turn.loading_status = String(payload.answer_status || "") === "running" ? (hasTables ? "正在生成回答" : "思考中") : "";
}

function hasBackendUserMessage(content: string): boolean {
  return (currentConversation.value?.messages || []).some((message) => message.role === "user" && message.content === content);
}

function buildRenderedTurns(): RenderedTurn[] {
  const messages = [...(currentConversation.value?.messages || [])].sort(compareMessages);
  const turns: RenderedTurn[] = [];
  let currentTurn: RenderedTurn | null = null;
  for (const message of messages) {
    if (message.role === "user") {
      currentTurn = turnFromUser(message);
      turns.push(currentTurn);
      continue;
    }
    if (!currentTurn) {
      currentTurn = {
        turn_id: message.id,
        request_id: "",
        user_message: { id: `${message.id}-user`, content: message.query_summary || "用户问题" },
        loading_status: "",
        result_tables: [],
        final_answer: "",
        error_status: "",
        assistant_message_id: "",
        chart_recommendations: []
      };
      turns.push(currentTurn);
    }
    applyAssistantToTurn(currentTurn, message);
  }
  if (pendingTurn.value && currentConversation.value?.id === pendingTurn.value.conversation_id && !hasBackendUserMessage(pendingTurn.value.content)) {
    turns.push({
      turn_id: pendingTurn.value.turn_id,
      request_id: pendingTurn.value.request_id,
      user_message: { id: `${pendingTurn.value.turn_id}-user`, content: pendingTurn.value.content },
      loading_status: pendingTurn.value.status === "thinking" ? "思考中" : "",
      result_tables: [],
      final_answer: "",
      error_status: pendingTurn.value.status === "cancelled" ? "已停止生成" : pendingTurn.value.error,
      assistant_message_id: pendingTurn.value.turn_id,
      chart_recommendations: []
    });
  }
  return turns;
}

function displayCell(cell: unknown): string {
  if (cell === null || cell === undefined) return "";
  return String(cell);
}

function formatMetricValue(card: DashboardCard | null | undefined): string {
  const value = tableFromCard(card as DashboardCard)?.rows?.[0]?.[0];
  const mode = String(card?.chart_config?.metricDecimals || "");
  if (!mode) return displayCell(value);
  const parsed = parseChartNumber(value);
  if (parsed === null) return displayCell(value);
  if (mode === "2") return new Intl.NumberFormat("zh-CN", { minimumFractionDigits: 2, maximumFractionDigits: 2 }).format(parsed);
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: 0 }).format(parsed);
}

function delay(ms: number) {
  return new Promise((resolve) => window.setTimeout(resolve, ms));
}

function toastKind(message: string, hasError: boolean): "info" | "success" | "warning" | "error" {
  if (hasError) return "error";
  if (/失败|错误|取消/.test(message)) return "warning";
  if (/完成|成功|通过|保存|恢复|已/.test(message)) return "success";
  return "info";
}

function showToast(message: string, hasError = false) {
  if (!message || message === "准备就绪") return;
  window.clearTimeout(toastTimer);
  toast.text = message;
  toast.kind = toastKind(message, hasError);
  toast.visible = true;
  toastTimer = window.setTimeout(() => {
    toast.visible = false;
  }, 8000);
}

function clearToastTimers() {
  window.clearTimeout(toastTimer);
}

function activateDebugMode() {
  if (!canUseDebug.value) {
    draft.value = "";
    status.value = "当前角色无权查看调试信息";
    showToast(status.value, true);
    return;
  }
  debugModeEnabled.value = true;
  workspaceOpen.value = true;
  workspaceTab.value = "debug";
  draft.value = "";
  status.value = "调试模式已开启";
}

function setImportProgress(step: string, percent: number, indeterminate = false) {
  importProgress.visible = true;
  importProgress.step = step;
  importProgress.percent = Math.max(0, Math.min(100, percent));
  importProgress.indeterminate = indeterminate;
}

const chartTypeOptions: Array<{ value: ChartTypeKey; label: string }> = [
  { value: "column_clustered", label: "簇状柱状图" },
  { value: "column_stacked", label: "堆叠柱状图" },
  { value: "bar_horizontal", label: "条形图" },
  { value: "line", label: "折线图" },
  { value: "pie", label: "饼图" },
  { value: "scatter", label: "散点图" },
  { value: "area", label: "面积图" },
  { value: "stock", label: "股价图" },
  { value: "combo_column_line", label: "组合图" }
];

type ChartOptionsSnapshot = ReturnType<typeof chartOptionsSnapshot>;

const chartPalettes: Record<string, string[]> = {
  morandi: ["#6f8fac", "#7fa58b", "#c99a71", "#9588aa", "#b97880", "#82909a", "#719f9a", "#b6a06d"],
  sage: ["#6f9a82", "#8ba58c", "#b5a879", "#7e9da6", "#a8848b", "#778897", "#98a67b", "#c29378"],
  slate: ["#6f8193", "#8097a7", "#6d9b9b", "#9a8faa", "#b1847d", "#8f9b80", "#7186ad", "#a99876"],
  warm: ["#b88f72", "#c4a574", "#9ba57a", "#8aa2a6", "#a58fa7", "#bd858d", "#8f9a8d", "#b3a184"]
};

function paletteFor(scheme = "morandi") {
  return chartPalettes[scheme] || chartPalettes.morandi;
}

function colorForKey(key: string, scheme = "morandi", fallbackIndex = 0) {
  const colors = paletteFor(scheme);
  let hash = 0;
  for (let index = 0; index < key.length; index += 1) hash = (hash * 31 + key.charCodeAt(index)) >>> 0;
  return colors[(key ? hash : fallbackIndex) % colors.length];
}

function alphaColor(hex: string, alpha: string) {
  return `${hex}${alpha}`;
}

function compactNumber(value: unknown) {
  const parsed = parseChartNumber(value);
  if (parsed === null) return displayCell(value);
  return new Intl.NumberFormat("zh-CN", { maximumFractionDigits: Math.abs(parsed) >= 100 ? 0 : 2 }).format(parsed);
}

function parseChartNumber(value: unknown): number | null {
  if (typeof value === "number" && Number.isFinite(value)) return value;
  if (typeof value !== "string") return null;
  const normalized = value.trim().replace(/,/g, "").replace(/%$/, "");
  if (!normalized) return null;
  const parsed = Number(normalized);
  return Number.isFinite(parsed) ? parsed : null;
}

function isOrderedValue(value: unknown): boolean {
  if (value === null || value === undefined) return false;
  const text = String(value).trim();
  return Boolean(/^\d{4}[-/]\d{1,2}([-/]\d{1,2})?$/.test(text) || /^\d{4}\s*Q[1-4]$/i.test(text) || /^\d{4}年?\d{1,2}月?$/.test(text) || /^Q[1-4]$/i.test(text) || /^\d+$/.test(text));
}

function analyzeChartFields(table: Record<string, any> | null): ChartField[] {
  const columns = (table?.columns || []) as string[];
  const rows = (table?.rows || []) as unknown[][];
  return columns.map((name, index) => {
    let numeric = 0;
    let ordered = 0;
    let usable = 0;
    for (const row of rows) {
      const value = row[index];
      if (value === null || value === undefined || String(value).trim?.() === "") continue;
      usable += 1;
      if (parseChartNumber(value) !== null) numeric += 1;
      if (isOrderedValue(value)) ordered += 1;
    }
    const threshold = Math.max(1, Math.ceil(usable * 0.6));
    const type = numeric >= threshold ? "numeric" : ordered >= threshold ? "ordered" : "text";
    return { name: String(name), index, type, usable };
  });
}

function destroyChart() {
  activeChart.value?.destroy();
  activeChart.value = null;
}

function resetChartRenderState() {
  destroyChart();
  chartRendered.value = false;
  chartError.value = "";
  chartNotice.value = "";
  chartExportData.value = null;
}

function markChartEdited() {
  resetChartRenderState();
  if (selectedChartRecommendation.value) chartModeNotice.value = "自定义修改，点击生成后应用。";
}

function tableRecommendationFor(messageId: string, table: Record<string, any>): ChartRecommendation | null {
  const turn = renderedTurns.value.find((item) => item.assistant_message_id === messageId);
  const tableId = String(table.task_id || "");
  return turn?.chart_recommendations.find((item) => String(item.table_id) === tableId) || null;
}

function applyChartRecommendation(recommendation: ChartRecommendation) {
  chartOptions.type = recommendation.type as ChartTypeKey;
  chartOptions.title = recommendation.title || "智能推荐图表";
  chartOptions.categoryColumn = recommendation.x || "";
  chartOptions.numericColumns = [...(recommendation.y || [])].slice(0, 4);
  chartOptions.lineColumns = [...(recommendation.y2 || [])].slice(0, 4);
  chartOptions.seriesColumn = recommendation.series || "";
  chartOptions.yZeroMode = recommendation.y_zero || "auto";
  chartOptions.labelDensity = "auto";
  chartOptions.dataLabelMode = "auto";
  chartOptions.sortMode = "original";
  chartOptions.limitMode = "none";
  chartOptions.limitCount = 10;
  chartOptions.legendMode = "auto";
  chartOptions.legendPosition = "top";
  chartOptions.xAxisTitle = recommendation.x || "";
  chartOptions.yAxisTitle = (recommendation.y || []).slice(0, 2).join(" / ");
  chartOptions.unitLabel = "";
  chartOptions.lineSmooth = true;
  chartOptions.areaFill = recommendation.type === "area";
  chartOptions.pieMode = "doughnut";
  chartOptions.colorScheme = "morandi";
  chartOptions.barThickness = "auto";
  chartOptions.fontScale = "compact";
  chartOptions.showTitle = true;
  chartOptions.titlePosition = "chart_inner";
}

async function restoreChartRecommendation() {
  const recommendation = selectedChartRecommendation.value;
  if (!recommendation) return;
  applyChartRecommendation(recommendation);
  chartModeNotice.value = "已按智能推荐生成，可手动调整。";
  await renderChart(false);
}

async function useChartTable(messageId: string, table: Record<string, any>) {
  selectedChartMessageId.value = messageId;
  selectedChartTableId.value = String(table.task_id || "");
  workspaceTab.value = "chart";
  workspaceOpen.value = true;
  openMobileWorkspace();
  const fields = analyzeChartFields(table);
  const recommendation = tableRecommendationFor(messageId, table);
  if (recommendation) {
    applyChartRecommendation(recommendation);
    chartModeNotice.value = "已按智能推荐生成，可手动调整。";
    await renderChart(false);
    return;
  }
  chartOptions.type = "line";
  chartOptions.title = String(table.purpose || table.task_id || "查询结果图表");
  chartOptions.categoryColumn = fields.find((field) => field.type === "ordered")?.name || fields.find((field) => field.type === "text")?.name || "";
  chartOptions.numericColumns = fields.filter((field) => field.type === "numeric").slice(0, 1).map((field) => field.name);
  chartOptions.lineColumns = [];
  chartOptions.seriesColumn = "";
  chartOptions.yZeroMode = "auto";
  chartOptions.labelDensity = "auto";
  chartOptions.dataLabelMode = "auto";
  chartOptions.sortMode = "original";
  chartOptions.limitMode = "none";
  chartOptions.limitCount = 10;
  chartOptions.legendMode = "auto";
  chartOptions.legendPosition = "top";
  chartOptions.xAxisTitle = chartOptions.categoryColumn;
  chartOptions.yAxisTitle = chartOptions.numericColumns.join(" / ");
  chartOptions.unitLabel = "";
  chartOptions.lineSmooth = true;
  chartOptions.areaFill = false;
  chartOptions.pieMode = "doughnut";
  chartOptions.colorScheme = "morandi";
  chartOptions.barThickness = "auto";
  chartOptions.fontScale = "compact";
  chartOptions.showTitle = true;
  chartOptions.titlePosition = "chart_inner";
  chartModeNotice.value = "手动模式：选择字段后点击生成。";
  resetChartRenderState();
}

function toggleNumericColumn(column: string, target: "main" | "line" = "main") {
  markChartEdited();
  const list = target === "line" ? chartOptions.lineColumns : chartOptions.numericColumns;
  if (chartOptions.type === "pie" && target === "main") {
    chartOptions.numericColumns = [column];
    return;
  }
  const index = list.indexOf(column);
  if (index >= 0) {
    list.splice(index, 1);
    return;
  }
  if (list.length >= 4) {
    chartNotice.value = "最多选择 4 个数值字段。";
    return;
  }
  list.push(column);
}

function onChartTypeChange() {
  markChartEdited();
  if (chartOptions.type === "pie" && chartOptions.numericColumns.length > 1) chartOptions.numericColumns = chartOptions.numericColumns.slice(0, 1);
  if (chartOptions.type !== "combo_column_line") chartOptions.lineColumns = [];
  if (chartOptions.type === "area") chartOptions.areaFill = true;
  if (chartOptions.type === "bar_horizontal" && chartOptions.limitMode === "none") chartOptions.limitMode = "top";
}

function columnIndex(columns: string[], name: string): number {
  return columns.indexOf(name);
}

function chartValidationError(columns: string[]): string {
  const xIndex = columnIndex(columns, chartOptions.categoryColumn);
  const y = chartOptions.numericColumns.filter((item) => columns.includes(item));
  const y2 = chartOptions.lineColumns.filter((item) => columns.includes(item));
  if (xIndex < 0) return "请选择分类字段或横轴字段。";
  if (["column_clustered", "column_stacked", "bar_horizontal", "line", "area"].includes(chartOptions.type) && (y.length < 1 || y.length > 4)) return "该图表需要 1 到 4 个数值字段。";
  if (chartOptions.type === "pie" && y.length !== 1) return "饼图需要 1 个非负数值字段。";
  if (chartOptions.type === "scatter" && y.length < 1) return "散点图需要数值型 X 字段和 1 个 Y 字段。";
  if (chartOptions.type === "stock" && y.length !== 4) return "股价图需要按开盘、最高、最低、收盘选择 4 个数值字段。";
  if (chartOptions.type === "combo_column_line" && (!y.length || !y2.length)) return "组合图需要至少 1 个柱状字段和 1 个折线字段。";
  return "";
}

function sortedRows(rows: unknown[][], columns: string[], numericColumns: string[]): unknown[][] {
  const firstNumeric = numericColumns[0];
  const index = firstNumeric ? columnIndex(columns, firstNumeric) : -1;
  if (index < 0) return rows;
  const sorted = chartOptions.sortMode === "original" && chartOptions.limitMode === "none" ? [...rows] : [...rows].sort((a, b) => {
    const left = parseChartNumber(a[index]) ?? 0;
    const right = parseChartNumber(b[index]) ?? 0;
    if (chartOptions.limitMode === "bottom") return left - right;
    return chartOptions.sortMode === "asc" ? left - right : right - left;
  });
  if (chartOptions.limitMode === "none") return sorted;
  return sorted.slice(0, Math.max(1, Math.min(100, Number(chartOptions.limitCount) || 10)));
}

function sortedRowsForConfig(rows: unknown[][], columns: string[], numericColumns: string[], config: ChartOptionsSnapshot): unknown[][] {
  const firstNumeric = numericColumns[0];
  const index = firstNumeric ? columnIndex(columns, firstNumeric) : -1;
  if (index < 0) return rows;
  const sorted = config.sortMode === "original" && config.limitMode === "none" ? [...rows] : [...rows].sort((a, b) => {
    const left = parseChartNumber(a[index]) ?? 0;
    const right = parseChartNumber(b[index]) ?? 0;
    if (config.limitMode === "bottom") return left - right;
    return config.sortMode === "asc" ? left - right : right - left;
  });
  if (config.limitMode === "none") return sorted;
  return sorted.slice(0, Math.max(1, Math.min(100, Number(config.limitCount) || 10)));
}

function sparseIndexes(length: number, maxPoints: number): Set<number> {
  if (length <= maxPoints) return new Set(Array.from({ length }, (_, index) => index));
  const keep = new Set<number>([0, length - 1]);
  const step = Math.ceil(length / Math.max(2, maxPoints));
  for (let index = 0; index < length; index += step) keep.add(index);
  return keep;
}

function maxTicksLimit(): number {
  const width = Math.max(260, workspaceWidth.value - 80);
  if (chartOptions.labelDensity === "full") return 50;
  if (chartOptions.labelDensity === "sparse") return Math.max(4, Math.floor(width / 110));
  return Math.max(5, Math.floor(width / 72));
}

function buildChartData() {
  const table = selectedChartTable.value;
  if (!table) throw new Error("请选择查询结果后生成图表。");
  const rows = (table.rows || []) as unknown[][];
  const columns = (table.columns || []) as string[];
  if (!rows.length) throw new Error("当前结果没有可用于绘图的数据行。");
  const validation = chartValidationError(columns);
  if (validation) throw new Error(validation);
  const xIndex = columnIndex(columns, chartOptions.categoryColumn);
  const yColumns = chartOptions.numericColumns.filter((item) => columns.includes(item));
  const y2Columns = chartOptions.lineColumns.filter((item) => columns.includes(item));
  const sourceRows = sortedRows(rows, columns, [...yColumns, ...y2Columns]);
  const renderLimit = chartOptions.type === "scatter" ? 1000 : ["line", "area"].includes(chartOptions.type) ? 900 : 3000;
  const keepIndexes = sparseIndexes(sourceRows.length, renderLimit);
  const labels: string[] = [];
  const rowMeta: unknown[][] = [];
  let skipped = 0;
  sourceRows.forEach((row, rowIndex) => {
    if (!keepIndexes.has(rowIndex)) return;
    const label = displayCell(row[xIndex]);
    if (!label) {
      skipped += 1;
      return;
    }
    labels.push(label);
    rowMeta.push(row);
  });
  if (!labels.length) throw new Error("全部数据为空或无法转换为图表数据。");
  const buildSeries = (cols: string[]) => cols.map((column) => {
    const index = columnIndex(columns, column);
    return { column, values: rowMeta.map((row) => parseChartNumber(row[index])) };
  });
  let series = buildSeries(yColumns);
  const lineSeries = buildSeries(y2Columns);
  if (series.some((item) => item.values.every((value) => value === null)) || lineSeries.some((item) => item.values.every((value) => value === null))) throw new Error("所选字段无法转换为数值。");
  const notices: string[] = [];
  if (keepIndexes.size < sourceRows.length) notices.push("为保持流畅，仅渲染 " + keepIndexes.size + "/" + sourceRows.length + " 个点，原始表格不变。");
  if (chartOptions.type === "pie") {
    const values = series[0].values.map((value) => value ?? 0);
    if (values.some((value) => value < 0)) throw new Error("饼图需要非负数值字段。");
    const total = values.reduce((sum, value) => sum + value, 0);
    if (total <= 0) throw new Error("饼图数值总和必须大于 0。");
    if (labels.length > 12) {
      if (chartOptions.labelDensity === "full") throw new Error("分类过多，完整模式下不生成不可读饼图。请选择自动或稀疏模式。");
      const pairs = labels.map((label, index) => ({ label, value: values[index] })).sort((a, b) => b.value - a.value);
      const top = pairs.slice(0, 10);
      const other = pairs.slice(10).reduce((sum, item) => sum + item.value, 0);
      labels.splice(0, labels.length, ...top.map((item) => item.label), "其他");
      series = [{ column: series[0].column, values: [...top.map((item) => item.value), other] }];
      notices.push("为便于展示，部分分类已合并为其他。");
    }
  }
  return { labels, series, lineSeries, rows: rowMeta, skipped, notices, columns };
}

function chartJsBaseType(): ChartType {
  if (["column_clustered", "column_stacked", "bar_horizontal"].includes(chartOptions.type)) return "bar";
  if (chartOptions.type === "pie" && chartOptions.pieMode === "doughnut") return "doughnut";
  if (["area", "stock", "combo_column_line"].includes(chartOptions.type)) return "line";
  if (chartOptions.type === "scatter") return "scatter";
  return chartOptions.type as ChartType;
}

function dashboardChartBaseType(type: ChartTypeKey, pieMode = "doughnut"): ChartType {
  if (type === "pie") return pieMode === "pie" ? "pie" : "doughnut";
  if (type === "line" || type === "area") return "line";
  return "bar";
}

const stockCandlestickPlugin = {
  id: "stockCandlestick",
  afterDatasetsDraw(chart: any) {
    const rows = chart.config.options?.plugins?.stockCandlestick?.rows || [];
    if (!rows.length) return;
    const xScale = chart.scales.x;
    const yScale = chart.scales.y;
    const ctx = chart.ctx;
    const candleWidth = Math.max(4, Math.min(12, chart.chartArea.width / Math.max(rows.length, 1) * 0.48));
    ctx.save();
    rows.forEach((row: any, index: number) => {
      const x = xScale.getPixelForValue(index);
      const open = yScale.getPixelForValue(row.open);
      const high = yScale.getPixelForValue(row.high);
      const low = yScale.getPixelForValue(row.low);
      const close = yScale.getPixelForValue(row.close);
      const up = row.close >= row.open;
      ctx.strokeStyle = up ? "#16865c" : "#c24136";
      ctx.fillStyle = up ? "#16865c" : "#c24136";
      ctx.beginPath();
      ctx.moveTo(x, high);
      ctx.lineTo(x, low);
      ctx.stroke();
      ctx.fillRect(x - candleWidth / 2, Math.min(open, close), candleWidth, Math.max(2, Math.abs(close - open)));
    });
    ctx.restore();
  }
};

const compactDataLabelsPlugin = {
  id: "compactDataLabels",
  afterDatasetsDraw(chart: any) {
    const mode = chart.config.options?.plugins?.compactDataLabels?.mode || "hide";
    if (mode === "hide") return;
    const unit = chart.config.options?.plugins?.compactDataLabels?.unit || "";
    const isHorizontal = chart.config.options?.indexAxis === "y";
    const ctx = chart.ctx;
    ctx.save();
    ctx.fillStyle = "#516070";
    ctx.font = "11px Inter, system-ui, sans-serif";
    ctx.textBaseline = "middle";
    chart.data.datasets.forEach((dataset: any, datasetIndex: number) => {
      const meta = chart.getDatasetMeta(datasetIndex);
      if (meta.hidden) return;
      const visibleLimit = mode === "auto" ? 24 : 80;
      if ((dataset.data || []).length > visibleLimit) return;
      meta.data.forEach((element: any, index: number) => {
        const raw = Array.isArray(dataset.data) ? dataset.data[index] : "";
        const value = typeof raw === "object" ? raw?.y : raw;
        const text = compactNumber(value) + (unit ? ` ${unit}` : "");
        const position = element.tooltipPosition();
        ctx.textAlign = isHorizontal ? "left" : "center";
        ctx.fillText(text, position.x + (isHorizontal ? 8 : 0), position.y - (isHorizontal ? 0 : 10));
      });
    });
    ctx.restore();
  }
};

const doughnutCenterPlugin = {
  id: "doughnutCenter",
  afterDraw(chart: any) {
    const text = chart.config.options?.plugins?.doughnutCenter?.text || "";
    if (!text || chart.config.type !== "doughnut") return;
    const area = chart.chartArea;
    if (!area) return;
    const ctx = chart.ctx;
    ctx.save();
    ctx.fillStyle = "#17212f";
    ctx.font = "600 13px Inter, system-ui, sans-serif";
    ctx.textAlign = "center";
    ctx.textBaseline = "middle";
    ctx.fillText(text, (area.left + area.right) / 2, (area.top + area.bottom) / 2);
    ctx.restore();
  }
};

function makeDatasets(data: ReturnType<typeof buildChartData>) {
  const lineTension = chartOptions.lineSmooth ? 0.32 : 0;
  const barThickness = chartOptions.barThickness === "slim" ? 14 : chartOptions.barThickness === "bold" ? 28 : undefined;
  if (chartOptions.type === "pie") return [{ label: data.series[0].column, data: data.series[0].values, backgroundColor: data.labels.map((label, index) => colorForKey(label, chartOptions.colorScheme, index)), borderColor: "#fff", borderWidth: 2 }];
  if (chartOptions.type === "scatter") {
    const xIndex = columnIndex(data.columns, chartOptions.categoryColumn);
    const yIndex = columnIndex(data.columns, chartOptions.numericColumns[0]);
    const color = colorForKey(chartOptions.numericColumns[0], chartOptions.colorScheme, 0);
    return [{ label: chartOptions.numericColumns[0], data: data.rows.map((row) => ({ x: parseChartNumber(row[xIndex]), y: parseChartNumber(row[yIndex]) })).filter((point) => point.x !== null && point.y !== null), backgroundColor: color, borderColor: color }];
  }
  if (chartOptions.type === "stock") {
    const indexes = chartOptions.numericColumns.map((column) => columnIndex(data.columns, column));
    const ohlc = data.rows.map((row) => ({ open: parseChartNumber(row[indexes[0]]) ?? 0, high: parseChartNumber(row[indexes[1]]) ?? 0, low: parseChartNumber(row[indexes[2]]) ?? 0, close: parseChartNumber(row[indexes[3]]) ?? 0 }));
    return [{ label: "收盘", data: ohlc.map((item) => item.close), borderColor: "transparent", pointRadius: 0, stockRows: ohlc }];
  }
  const bars = data.series.map((item, index) => {
    const color = colorForKey(item.column, chartOptions.colorScheme, index);
    return { type: "bar" as const, label: item.column, data: item.values, borderColor: color, backgroundColor: color, borderRadius: 5, maxBarThickness: barThickness };
  });
  if (chartOptions.type === "combo_column_line") return [...bars, ...data.lineSeries.map((item, index) => {
    const color = colorForKey(item.column, chartOptions.colorScheme, index + bars.length);
    return { type: "line" as const, label: item.column, data: item.values, yAxisID: "y1", borderColor: color, borderWidth: 2, backgroundColor: alphaColor(color, "2e"), showLine: true, tension: lineTension, pointRadius: data.labels.length > 120 ? 0 : 2 };
  })];
  if (["column_clustered", "column_stacked", "bar_horizontal"].includes(chartOptions.type)) return bars;
  return data.series.map((item, index) => {
    const color = colorForKey(item.column, chartOptions.colorScheme, index);
    return { label: item.column, data: item.values, borderColor: color, borderWidth: 2, backgroundColor: chartOptions.type === "area" || chartOptions.areaFill ? alphaColor(color, "2e") : alphaColor(color, "18"), fill: chartOptions.type === "area" || chartOptions.areaFill, showLine: true, tension: lineTension, pointRadius: data.labels.length > 120 ? 0 : 2, pointHoverRadius: 4 };
  });
}

function chartPluginsFor(type: ChartTypeKey) {
  return [compactDataLabelsPlugin as any, doughnutCenterPlugin as any, ...(type === "stock" ? [stockCandlestickPlugin as any] : [])];
}

function chartCommonOptions(config: ChartOptionsSnapshot, labels: string[], datasets: any[], stockRows: any[] = [], animate = true) {
  const legendDisplay = config.legendMode === "show" || (config.legendMode === "auto" && (datasets.length > 1 || config.type === "pie"));
  const yBeginAtZero = config.yZeroMode === "zero" || (config.yZeroMode === "auto" && ["column_clustered", "column_stacked", "bar_horizontal", "pie"].includes(config.type));
  const tickLimit = config.labelDensity === "full" ? 60 : config.labelDensity === "sparse" ? 6 : Math.max(6, Math.min(18, Math.floor(labels.length / 2) || 8));
  const fontSize = config.fontScale === "normal" ? 12 : 11;
  const firstDataset = datasets[0]?.data || [];
  const centerTotal = config.type === "pie"
    ? compactNumber((firstDataset as unknown[]).reduce<number>((sum, value) => sum + (parseChartNumber(value) || 0), 0))
    : "";
  return {
    responsive: true,
    maintainAspectRatio: false,
    animation: animate ? { duration: 520, easing: "easeOutQuart" } : false,
    transitions: animate ? undefined : { active: { animation: { duration: 0 } }, resize: { animation: { duration: 0 } } },
    resizeDelay: 80,
    indexAxis: config.type === "bar_horizontal" ? "y" : "x",
    layout: { padding: { top: 2, right: 8, bottom: 0, left: 2 } },
    plugins: {
      title: { display: Boolean(config.showTitle && config.titlePosition === "chart_inner" && config.title), text: config.title, align: "start", color: "#17212f", padding: { top: 2, bottom: 8 }, font: { size: fontSize + 2, weight: "600" } },
      legend: { display: config.type === "pie" ? config.legendMode !== "hide" : legendDisplay, position: config.legendPosition, labels: { boxWidth: 10, boxHeight: 10, usePointStyle: true, padding: 10, color: "#516070", font: { size: fontSize } } },
      tooltip: { backgroundColor: "rgba(23, 33, 47, 0.88)", padding: 9, cornerRadius: 8, displayColors: true },
      compactDataLabels: { mode: config.dataLabelMode, unit: config.unitLabel },
      doughnutCenter: { text: centerTotal },
      stockCandlestick: { rows: stockRows }
    },
    scales: config.type === "pie" ? undefined : {
      x: { stacked: config.type === "column_stacked", title: { display: Boolean(config.xAxisTitle), text: config.xAxisTitle, color: "#667386", font: { size: fontSize } }, grid: { color: "rgba(132, 145, 157, 0.12)", drawBorder: false }, ticks: { color: "#667386", autoSkip: config.labelDensity !== "full", maxTicksLimit: tickLimit, maxRotation: labels.length > 24 ? 20 : 0, font: { size: fontSize } } },
      y: { stacked: config.type === "column_stacked", beginAtZero: yBeginAtZero, title: { display: Boolean(config.yAxisTitle || config.unitLabel), text: [config.yAxisTitle, config.unitLabel].filter(Boolean).join(" · "), color: "#667386", font: { size: fontSize } }, grid: { color: "rgba(132, 145, 157, 0.14)", drawBorder: false }, ticks: { color: "#667386", font: { size: fontSize } } },
      ...(config.type === "combo_column_line" ? { y1: { position: "right", grid: { drawOnChartArea: false }, beginAtZero: false, ticks: { color: "#667386", font: { size: fontSize } } } } : {})
    }
  } as any;
}

function currentChartAnimationKey() {
  return `chat:${selectedChartMessageId.value}:${selectedChartTableId.value}`;
}

function shouldAnimateChart(key: string) {
  if (!key || animatedChartKeys.has(key)) return false;
  animatedChartKeys.add(key);
  return true;
}

async function renderChart(markCustom = true) {
  resetChartRenderState();
  await nextTick();
  if (!chartCanvas.value) {
    chartError.value = "图表组件尚未准备好。";
    return;
  }
  try {
    const data = buildChartData();
    const datasets: any[] = makeDatasets(data);
    const stockRows = datasets[0]?.stockRows || [];
    const config: ChartConfiguration = { type: chartJsBaseType(), data: { labels: data.labels, datasets }, plugins: chartPluginsFor(chartOptions.type), options: chartCommonOptions(chartOptionsSnapshot(), data.labels, datasets, stockRows, shouldAnimateChart(currentChartAnimationKey())) };
    activeChart.value = new Chart(chartCanvas.value, config);
    chartRendered.value = true;
    chartNotice.value = [data.skipped ? data.skipped + " 行为空或无法转换，未参与绘图。" : "", ...data.notices].filter(Boolean).join(" ");
    chartExportData.value = { type: chartOptions.type, title: chartOptions.title, options: { ...chartOptions }, labels: data.labels, datasets: datasets.map((item) => ({ label: item.label, data: item.data, yAxisID: item.yAxisID || "y" })), notice: chartNotice.value };
    if (markCustom && selectedChartRecommendation.value) chartModeNotice.value = "自定义修改已应用。";
  } catch (err) {
    chartError.value = err instanceof Error ? err.message : "图表渲染失败。";
    destroyChart();
  }
}

function downloadBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  link.click();
  URL.revokeObjectURL(url);
}

function safeChartFilename(ext: string): string {
  const stamp = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const title = (chartOptions.title || "chart").replace(/[<>:"/\\|?*\x00-\x1f]/g, "_").slice(0, 60);
  return title + "-" + stamp + "." + ext;
}

function exportChart(format: "png" | "jpeg" | "csv" | "json") {
  try {
    if (!chartRendered.value || !chartExportData.value) throw new Error("请先生成图表。");
    if (format === "json") {
      downloadBlob(new Blob([JSON.stringify(chartExportData.value, null, 2)], { type: "application/json;charset=utf-8" }), safeChartFilename("json"));
      return;
    }
    if (format === "csv") {
      const rows = [["series", "label", "value", "notice"]];
      for (const dataset of chartExportData.value.datasets || []) {
        const values = dataset.data || [];
        values.forEach((value: any, index: number) => rows.push([dataset.label, chartExportData.value?.labels?.[index] ?? "", typeof value === "object" ? JSON.stringify(value) : value, chartExportData.value?.notice || ""]));
      }
      const csv = rows.map((row) => row.map((cell) => "\"" + String(cell ?? "").replace(/"/g, '""') + "\"").join(",")).join("\n");
      downloadBlob(new Blob(["\uFEFF" + csv], { type: "text/csv;charset=utf-8" }), safeChartFilename("csv"));
      return;
    }
    const source = activeChart.value?.canvas;
    if (!source) throw new Error("图表画布不可用。");
    const scale = 2;
    const canvas = document.createElement("canvas");
    canvas.width = source.width * scale;
    canvas.height = source.height * scale;
    const ctx = canvas.getContext("2d");
    if (!ctx) throw new Error("无法创建导出画布。");
    ctx.fillStyle = "#ffffff";
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    ctx.drawImage(source, 0, 0, canvas.width, canvas.height);
    canvas.toBlob((blob) => {
      if (!blob) {
        chartError.value = "图表导出失败。";
        return;
      }
      downloadBlob(blob, safeChartFilename(format === "png" ? "png" : "jpg"));
    }, format === "png" ? "image/png" : "image/jpeg", 0.92);
  } catch (err) {
    chartError.value = err instanceof Error ? err.message : "图表导出失败。";
  }
}
function copyText(value: string) {
  if (!value) return;
  navigator.clipboard?.writeText(value).catch(() => undefined);
  status.value = "已复制";
}

function copyTable(table: Record<string, any>) {
  const columns = table.columns || [];
  const rows = table.rows || [];
  const text = [columns.join("\t"), ...rows.map((row: unknown[]) => row.map(displayCell).join("\t"))].join("\n");
  copyText(text);
}

function exportTable(table: Record<string, any>) {
  const columns = table.columns || [];
  const rows = table.rows || [];
  const csv = [columns, ...rows]
    .map((row: unknown[]) => row.map((cell) => `"${displayCell(cell).replace(/"/g, '""')}"`).join(","))
    .join("\n");
  const blob = new Blob([`\uFEFF${csv}`], { type: "text/csv;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = `${table.task_id || "result"}.csv`;
  link.click();
  URL.revokeObjectURL(url);
  status.value = "结果已导出";
}

function chartOptionsSnapshot() {
  return {
    type: chartOptions.type,
    title: chartOptions.title,
    categoryColumn: chartOptions.categoryColumn,
    numericColumns: [...chartOptions.numericColumns],
    lineColumns: [...chartOptions.lineColumns],
    seriesColumn: chartOptions.seriesColumn,
    yZeroMode: chartOptions.yZeroMode,
    labelDensity: chartOptions.labelDensity,
    dataLabelMode: chartOptions.dataLabelMode,
    sortMode: chartOptions.sortMode,
    limitMode: chartOptions.limitMode,
    limitCount: chartOptions.limitCount,
    legendMode: chartOptions.legendMode,
    legendPosition: chartOptions.legendPosition,
    xAxisTitle: chartOptions.xAxisTitle,
    yAxisTitle: chartOptions.yAxisTitle,
    unitLabel: chartOptions.unitLabel,
    lineSmooth: chartOptions.lineSmooth,
    areaFill: chartOptions.areaFill,
    pieMode: chartOptions.pieMode,
    colorScheme: chartOptions.colorScheme,
    barThickness: chartOptions.barThickness,
    fontScale: chartOptions.fontScale,
    showTitle: chartOptions.showTitle,
    titlePosition: chartOptions.titlePosition
  };
}

function normalizeDashboardChartConfig(raw: Record<string, any>): ChartOptionsSnapshot {
  return {
    type: (raw.type || "column_clustered") as ChartTypeKey,
    title: String(raw.title || "看板图表"),
    categoryColumn: String(raw.categoryColumn || raw.x || ""),
    numericColumns: Array.isArray(raw.numericColumns) ? raw.numericColumns.map(String) : Array.isArray(raw.y) ? raw.y.map(String) : [],
    lineColumns: Array.isArray(raw.lineColumns) ? raw.lineColumns.map(String) : Array.isArray(raw.y2) ? raw.y2.map(String) : [],
    seriesColumn: String(raw.seriesColumn || raw.series || ""),
    yZeroMode: (raw.yZeroMode || raw.y_zero || "auto") as ChartOptionsSnapshot["yZeroMode"],
    labelDensity: (raw.labelDensity || "auto") as ChartOptionsSnapshot["labelDensity"],
    dataLabelMode: (raw.dataLabelMode || "auto") as ChartOptionsSnapshot["dataLabelMode"],
    sortMode: (raw.sortMode || "original") as ChartOptionsSnapshot["sortMode"],
    limitMode: (raw.limitMode || "none") as ChartOptionsSnapshot["limitMode"],
    limitCount: Number(raw.limitCount) || 10,
    legendMode: (raw.legendMode || "auto") as ChartOptionsSnapshot["legendMode"],
    legendPosition: (raw.legendPosition || "top") as ChartOptionsSnapshot["legendPosition"],
    xAxisTitle: String(raw.xAxisTitle || raw.categoryColumn || raw.x || ""),
    yAxisTitle: String(raw.yAxisTitle || ""),
    unitLabel: String(raw.unitLabel || ""),
    lineSmooth: raw.lineSmooth !== false,
    areaFill: Boolean(raw.areaFill),
    pieMode: (raw.pieMode || "doughnut") as ChartOptionsSnapshot["pieMode"],
    colorScheme: (raw.colorScheme || "morandi") as ChartOptionsSnapshot["colorScheme"],
    barThickness: (raw.barThickness || "auto") as ChartOptionsSnapshot["barThickness"],
    fontScale: (raw.fontScale || "compact") as ChartOptionsSnapshot["fontScale"],
    showTitle: raw.showTitle !== false,
    titlePosition: (raw.titlePosition || "card_top") as ChartOptionsSnapshot["titlePosition"]
  };
}

function tableFromCard(card: DashboardCard): Record<string, any> | null {
  const snapshot = card.result_snapshot || {};
  return (snapshot.table || snapshot) as Record<string, any>;
}

function setDashboardCanvas(cardId: string, element: Element | null) {
  const previous = dashboardCanvases.get(cardId);
  if (previous?.parentElement) {
    dashboardChartResizeObserver?.unobserve(previous.parentElement);
    dashboardChartContainers.delete(previous.parentElement);
  }
  if (element instanceof HTMLCanvasElement) {
    dashboardCanvases.set(cardId, element);
    const container = element.parentElement;
    if (container) {
      dashboardChartContainers.set(container, cardId);
      if (!dashboardChartResizeObserver) {
        dashboardChartResizeObserver = new ResizeObserver((entries) => {
          for (const entry of entries) {
            const resizedCardId = dashboardChartContainers.get(entry.target);
            if (resizedCardId) dashboardCharts.get(resizedCardId)?.resize();
          }
        });
      }
      dashboardChartResizeObserver.observe(container);
    }
    requestAnimationFrame(() => renderDashboardCardChart(cardId));
    return;
  }
  destroyDashboardChart(cardId, dashboardCanvases.get(cardId));
  dashboardCanvases.delete(cardId);
}

function canUseDashboardSeries(rows: unknown[][], xIndex: number, seriesIndex: number, valueIndex: number) {
  if (seriesIndex < 0 || seriesIndex === xIndex || seriesIndex === valueIndex) return false;
  const values = rows.map((row) => displayCell(row[seriesIndex])).filter(Boolean);
  if (!values.length || values.every((value) => parseChartNumber(value) !== null)) return false;
  return new Set(values).size < values.length;
}

function renderDashboardCharts() {
  const visibleCardIds = new Set((currentDashboard.value?.cards || []).map((card) => card.id));
  for (const [cardId, chart] of dashboardCharts.entries()) {
    if (visibleCardIds.has(cardId)) continue;
    chart.destroy();
    dashboardCharts.delete(cardId);
  }
  for (const card of currentDashboard.value?.cards || []) renderDashboardCardChart(card.id);
}

function renderDashboardCardChart(cardId: string) {
  const card = currentDashboard.value?.cards.find((item) => item.id === cardId);
  const canvas = dashboardCanvases.get(cardId);
  if (!card || !canvas || card.card_type !== "chart") {
    destroyDashboardChart(cardId, canvas);
    return;
  }
  const table = tableFromCard(card);
  if (!table?.columns?.length || !table?.rows?.length) {
    destroyDashboardChart(cardId, canvas);
    return;
  }
  const options = normalizeDashboardChartConfig(card.chart_config || {});
  const columns = (table.columns || []) as string[];
  const rows = (table.rows || []) as unknown[][];
  const xIndex = Math.max(0, columns.indexOf(options.categoryColumn));
  const yColumns = options.numericColumns.filter((item) => columns.includes(item)).slice(0, 4);
  if (!yColumns.length) {
    destroyDashboardChart(cardId, canvas);
    return;
  }
  const sourceRows = sortedRowsForConfig(rows, columns, yColumns, options).slice(0, 400);
  const seriesIndex = columns.indexOf(options.seriesColumn);
  const valueIndex = columns.indexOf(yColumns[0] || "");
  const useSeries = options.type !== "pie" && yColumns.length === 1 && valueIndex >= 0 && canUseDashboardSeries(sourceRows, xIndex, seriesIndex, valueIndex);
  const labels = useSeries ? uniqueValues(sourceRows.map((row) => displayCell(row[xIndex])).filter(Boolean)) : sourceRows.map((row) => displayCell(row[xIndex]));
  const lineTension = options.lineSmooth ? 0.32 : 0;
  const barThickness = options.barThickness === "slim" ? 14 : options.barThickness === "bold" ? 28 : undefined;
  const datasets = useSeries
    ? buildDashboardSeriesDatasets(sourceRows, labels, xIndex, seriesIndex, valueIndex, options, lineTension, barThickness)
    : yColumns.map((column, index) => {
      const colIndex = columns.indexOf(column);
      const color = colorForKey(column, options.colorScheme, index);
      return {
        label: column,
        data: sourceRows.map((row) => parseChartNumber(row[colIndex]) ?? 0),
        borderColor: color,
        borderWidth: ["line", "area"].includes(options.type) ? 2 : undefined,
        backgroundColor: options.type === "line" && !options.areaFill ? alphaColor(color, "18") : color,
        borderRadius: 5,
        maxBarThickness: barThickness,
        tension: lineTension,
        fill: options.type === "area" || options.areaFill,
        showLine: ["line", "area"].includes(options.type),
        pointRadius: labels.length > 120 ? 0 : 2
      };
    });
  const baseType: ChartType = dashboardChartBaseType(options.type, options.pieMode);
  const chartDatasets = options.type === "pie"
    ? [{ label: yColumns[0], data: datasets[0].data, backgroundColor: labels.map((label, index) => colorForKey(label, options.colorScheme, index)), borderColor: "#fff", borderWidth: 2 }]
    : datasets;
  const config = {
    type: baseType,
    data: {
      labels,
      datasets: chartDatasets
    },
    plugins: chartPluginsFor(options.type),
    options: chartCommonOptions(options, labels, chartDatasets, [], shouldAnimateChart(`dashboard:${card.id}`))
  } as ChartConfiguration;
  const existing = dashboardCharts.get(cardId);
  if (existing && (existing.config as any).type === baseType) {
    existing.data.labels = labels;
    existing.data.datasets = chartDatasets as any;
    existing.options = config.options || {};
    existing.update("none");
    return;
  }
  destroyDashboardChart(cardId, canvas);
  dashboardCharts.set(cardId, new Chart(canvas, config));
}

function uniqueValues(values: string[]) {
  return Array.from(new Set(values));
}

function buildDashboardSeriesDatasets(rows: unknown[][], labels: string[], xIndex: number, seriesIndex: number, valueIndex: number, options: ChartOptionsSnapshot, lineTension: number, barThickness: number | undefined) {
  const seriesNames = uniqueValues(rows.map((row) => displayCell(row[seriesIndex])).filter(Boolean)).slice(0, 8);
  return seriesNames.map((seriesName, index) => {
    const color = colorForKey(seriesName, options.colorScheme, index);
    const points = new Map<string, number | null>();
    for (const row of rows) {
      if (displayCell(row[seriesIndex]) !== seriesName) continue;
      const label = displayCell(row[xIndex]);
      if (!label) continue;
      points.set(label, parseChartNumber(row[valueIndex]));
    }
    return {
      label: seriesName,
      data: labels.map((label) => points.get(label) ?? null),
      borderColor: color,
      borderWidth: ["line", "area"].includes(options.type) ? 2 : undefined,
      backgroundColor: options.type === "line" && !options.areaFill ? alphaColor(color, "18") : color,
      borderRadius: 5,
      maxBarThickness: barThickness,
      tension: lineTension,
      fill: options.type === "area" || options.areaFill,
      showLine: ["line", "area"].includes(options.type),
      pointRadius: labels.length > 120 ? 0 : 2
    };
  });
}

function destroyDashboardChart(cardId: string, canvas?: HTMLCanvasElement) {
  dashboardCharts.get(cardId)?.destroy();
  dashboardCharts.delete(cardId);
  if (canvas) {
    Chart.getChart(canvas)?.destroy();
  }
}

async function refreshDashboards(preferredId = "") {
  const response = await listDashboards();
  dashboards.value = response.items;
  const targetId = preferredId || currentDashboard.value?.id || dashboards.value[0]?.id || "";
  if (targetId) await openDashboard(targetId);
  else currentDashboard.value = null;
}

async function openDashboard(id: string) {
  const response = await getDashboard(id);
  currentDashboard.value = normalizeDashboardDetail(response.dashboard);
  selectedDashboardCardId.value = currentDashboard.value.cards[0]?.id || "";
  boardEditorCardId.value = "";
  boardEditorVisible.value = false;
  await nextTick();
  renderDashboardCharts();
}

async function createNewDashboard() {
  await guarded(async () => {
    const response = await createDashboard({ name: "我的看板" });
    dashboards.value = [{ id: response.dashboard.id, name: response.dashboard.name, card_count: response.dashboard.cards.length, created_at: response.dashboard.created_at, updated_at: response.dashboard.updated_at }, ...dashboards.value];
    currentDashboard.value = normalizeDashboardDetail(response.dashboard);
    selectedDashboardCardId.value = "";
  }, "看板已新建", dashboardBusy);
}

async function renameCurrentDashboard() {
  const dashboard = currentDashboard.value;
  if (!dashboard) return;
  const name = window.prompt("看板名称", dashboard.name)?.trim();
  if (!name) return;
  await guarded(async () => {
    const response = await updateDashboard(dashboard.id, { name });
    currentDashboard.value = normalizeDashboardDetail(response.dashboard);
    await refreshDashboards(response.dashboard.id);
  }, "看板已重命名", dashboardBusy);
}

async function removeCurrentDashboard() {
  const dashboard = currentDashboard.value;
  if (!dashboard || !window.confirm(`删除看板“${dashboard.name}”？`)) return;
  await guarded(async () => {
    await deleteDashboard(dashboard.id);
    currentDashboard.value = null;
    selectedDashboardCardId.value = "";
    await refreshDashboards();
    await refreshConversations(currentConversation.value?.id);
  }, "看板已删除", dashboardBusy);
}

async function refreshCurrentDashboard() {
  if (!currentDashboard.value) return;
  await guarded(async () => {
    const response = await refreshDashboard(currentDashboard.value!.id);
    currentDashboard.value = normalizeDashboardDetail(response.dashboard);
    await nextTick();
    renderDashboardCharts();
  }, "看板已刷新", dashboardBusy);
}

async function saveDashboardCard(card: DashboardCard, patch: Partial<DashboardCard>) {
  if (!currentDashboard.value) return;
  const response = await updateDashboardCard(currentDashboard.value.id, card.id, patch);
  currentDashboard.value.cards = currentDashboard.value.cards.map((item) => item.id === card.id ? { ...response.card, layout: normalizeSavedBoardLayout(response.card.layout) } : item);
  await nextTick();
  renderDashboardCardChart(card.id);
  return { ...response.card, layout: normalizeSavedBoardLayout(response.card.layout) };
}

async function saveDashboardChartOption(card: DashboardCard, key: string, value: unknown) {
  await saveDashboardCard(card, { chart_config: { ...card.chart_config, [key]: value } });
}

function refreshMode(card: DashboardCard) {
  return String(card.query?.refresh_mode || "fixed_query");
}

function cardUiMode(card: DashboardCard) {
  return refreshMode(card) === "dynamic_query" ? "dynamic" : "static";
}

function isDateLikeSchemaColumn(column: { name: string; type: string; semantic_type?: string }) {
  return /DATE|TIME|TIMESTAMP/i.test(column.type) || column.semantic_type === "date" || column.semantic_type === "date_candidate" || /(日期|时间|月份|年月|季度|date|time|month|period|quarter)/i.test(column.name);
}

async function saveDashboardRefreshMode(card: DashboardCard, mode: string) {
  const nextQuery = { ...card.query, refresh_mode: mode === "dynamic" ? "dynamic_query" : "fixed_query" };
  const saved = await saveDashboardCard(card, { query: nextQuery });
  if (saved && mode === "dynamic") await refreshOneCard(saved);
}

function isExampleTemplateCard(card: DashboardCard) {
  return card.source_type === "example_template" || Boolean(currentDashboard.value?.config?.template_key);
}

function isManualDashboardCard(card: DashboardCard) {
  return card.query?.mode === "manual_single_table" || card.source_type === "static_text";
}

function isParameterCompatible(card: DashboardCard, parameter: DashboardDynamicParameter) {
  return card.dataset_id === parameter.dataset_id && (!card.query?.table_name || card.query.table_name === parameter.table_name);
}


function dynamicParameterLabel(parameter: DashboardDynamicParameter) {
  return parameter.name === parameter.column_name ? parameter.name : `${parameter.name} / ${parameter.column_name}`;
}

function isTimeDynamicParameter(parameter: DashboardDynamicParameter) {
  if (parameter.parameter_type === "time") return true;
  const table = dashboardTables.value.find((item) => item.name === parameter.table_name);
  const column = table?.columns.find((item) => item.name === parameter.column_name);
  return Boolean(column && isDateLikeSchemaColumn(column));
}

function isDashboardDynamicDraftTime() {
  return Boolean(dashboardDynamicDraftColumn.value && isDateLikeSchemaColumn(dashboardDynamicDraftColumn.value));
}

function dashboardParameterControlValue(parameter: DashboardDynamicParameter) {
  return isTimeDynamicParameter(parameter) ? String(parameter.time_strategy || "") : dashboardParameterValue(parameter);
}

async function saveDashboardParameterControl(parameter: DashboardDynamicParameter, value: string) {
  if (isTimeDynamicParameter(parameter)) {
    await saveDashboardDynamicParameter(parameter, { time_strategy: value, current_value: "" }, true);
    return;
  }
  await saveDashboardDynamicParameter(parameter, { current_value: value }, true);
}

function dynamicParameterTypeLabel(parameter: DashboardDynamicParameter) {
  return isTimeDynamicParameter(parameter) ? "时间策略" : "字段筛选";
}

async function addDashboardDynamicParameter() {
  if (!currentDashboard.value || !dashboardDynamicDraft.dataset_id || !dashboardDynamicDraft.table_name || !dashboardDynamicDraft.column_name) return;
  if (dashboardDynamicParameters.value.length >= 3) {
    showToast("每个看板最多配置 3 个动态条件。", true);
    return;
  }
  const column = dashboardDynamicColumns.value.find((item) => item.name === dashboardDynamicDraft.column_name);
  const isTime = Boolean(column && isDateLikeSchemaColumn(column));
  const parameter: DashboardDynamicParameter = {
    id: `${dashboardDynamicDraft.dataset_id}:${dashboardDynamicDraft.table_name}:${dashboardDynamicDraft.column_name}`,
    name: dashboardDynamicDraft.name.trim() || dashboardDynamicDraft.column_name,
    dataset_id: dashboardDynamicDraft.dataset_id,
    table_name: dashboardDynamicDraft.table_name,
    column_name: dashboardDynamicDraft.column_name,
    column_type: column?.type || "",
    parameter_type: isTime ? "time" : "value",
    current_value: isTime ? "" : dashboardDynamicDraft.value || "",
    time_strategy: isTime ? dashboardDynamicDraft.time_strategy || "latest_date" : "",
    start_date: isTime ? dashboardDynamicDraft.start_date || "" : "",
    end_date: isTime ? dashboardDynamicDraft.end_date || "" : "",
    multi: false
  };
  const others = dashboardDynamicParameters.value.filter((item) => item.id !== parameter.id);
  const response = await updateDashboardConfig(currentDashboard.value.id, { config: { ...(currentDashboard.value.config || {}), dynamic_parameters: [...others, parameter] } });
  currentDashboard.value = normalizeDashboardDetail(response.dashboard);
  dashboardDynamicDraft.name = "";
  dashboardDynamicDraft.value = "";
  dashboardDynamicDraft.start_date = "";
  dashboardDynamicDraft.end_date = "";
  showToast("动态条件已添加");
}

async function saveDashboardDynamicParameter(parameter: DashboardDynamicParameter, patch: Partial<DashboardDynamicParameter>, refreshAfter = false) {
  if (!currentDashboard.value) return;
  const next = dashboardDynamicParameters.value.map((item) => item.id === parameter.id ? { ...item, ...patch } : item);
  const response = await updateDashboardConfig(currentDashboard.value.id, { config: { ...(currentDashboard.value.config || {}), dynamic_parameters: next } });
  currentDashboard.value = normalizeDashboardDetail(response.dashboard);
  if (refreshAfter) await refreshDashboardCardsBoundTo(parameter.id);
}

async function refreshDashboardCardsBoundTo(parameterId: string) {
  if (!currentDashboard.value) return;
  const parameter = dashboardDynamicParameters.value.find((item) => item.id === parameterId);
  if (!parameter) return;
  const cards = currentDashboard.value.cards.filter((card) => card.card_type !== "text" && cardUiMode(card) === "dynamic" && isParameterCompatible(card, parameter));
  for (const card of cards) {
    await refreshOneCard(card);
  }
}

async function removeDashboardDynamicParameter(parameter: DashboardDynamicParameter) {
  if (!currentDashboard.value) return;
  const next = dashboardDynamicParameters.value.filter((item) => item.id !== parameter.id);
  const response = await updateDashboardConfig(currentDashboard.value.id, { config: { ...(currentDashboard.value.config || {}), dynamic_parameters: next } });
  currentDashboard.value = normalizeDashboardDetail(response.dashboard);
}

async function loadDashboardDynamicValues() {
  if (!currentDashboard.value || !dashboardDynamicDraft.dataset_id || !dashboardDynamicDraft.table_name || !dashboardDynamicDraft.column_name) return;
  if (isDashboardDynamicDraftTime()) {
    dashboardDynamicDraft.values = [];
    return;
  }
  dashboardDynamicDraft.loadingValues = true;
  try {
    const response = await getDashboardDynamicValues(currentDashboard.value.id, dashboardDynamicDraft.dataset_id, dashboardDynamicDraft.table_name, dashboardDynamicDraft.column_name);
    dashboardDynamicDraft.values = response.values;
  } catch (err) {
    showToast(err instanceof Error ? err.message : "候选值读取失败", true);
  } finally {
    dashboardDynamicDraft.loadingValues = false;
  }
}

function dynamicValueCacheKey(parameter: DashboardDynamicParameter) {
  return `${parameter.dataset_id}:${parameter.table_name}:${parameter.column_name}`;
}

function dynamicValuesForParameter(parameter: DashboardDynamicParameter) {
  return dashboardDynamicValueCache.value[dynamicValueCacheKey(parameter)] || [];
}

function dashboardParameterValue(parameter: DashboardDynamicParameter) {
  return Array.isArray(parameter.current_value) ? String(parameter.current_value[0] || "") : String(parameter.current_value || "");
}

async function prepareDashboardParameterValues(parameter: DashboardDynamicParameter) {
  if (!currentDashboard.value) return;
  if (isTimeDynamicParameter(parameter)) return;
  const key = dynamicValueCacheKey(parameter);
  if (dashboardDynamicValueCache.value[key]?.length) return;
  try {
    const response = await getDashboardDynamicValues(currentDashboard.value.id, parameter.dataset_id, parameter.table_name, parameter.column_name);
    dashboardDynamicValueCache.value = { ...dashboardDynamicValueCache.value, [key]: response.values };
  } catch (err) {
    showToast(err instanceof Error ? err.message : "候选值读取失败", true);
  }
}

function dashboardCardFields(card: DashboardCard) {
  return analyzeChartFields(tableFromCard(card));
}

function dashboardCardCategoryFields(card: DashboardCard) {
  return dashboardCardFields(card).filter((field) => field.type !== "numeric");
}

function dashboardCardNumericFields(card: DashboardCard) {
  return dashboardCardFields(card).filter((field) => field.type === "numeric");
}

function shouldShowCardTopTitle(card: DashboardCard) {
  if (card.card_type !== "chart") return true;
  const config = normalizeDashboardChartConfig(card.chart_config || {});
  return config.showTitle && config.titlePosition === "card_top";
}

async function toggleDashboardNumericColumn(card: DashboardCard, column: string) {
  const config = normalizeDashboardChartConfig(card.chart_config || {});
  const exists = config.numericColumns.includes(column);
  const numericColumns = exists ? config.numericColumns.filter((item) => item !== column) : [...config.numericColumns, column].slice(0, 4);
  await saveDashboardCard(card, { chart_config: { ...card.chart_config, numericColumns } });
}

function selectDashboardCard(card: DashboardCard) {
  selectedDashboardCardId.value = card.id;
}

function openDashboardCardEditor(card: DashboardCard) {
  selectedDashboardCardId.value = card.id;
  if (dashboardMode.value !== "edit") return;
  if (!boardEditorPinned.value) {
    boardEditorCardId.value = card.id;
  }
  boardEditorVisible.value = true;
  placeBoardEditor();
}

function placeBoardEditor() {
  if (!dashboardCanvas.value || boardEditorPinned.value) return;
  const width = dashboardCanvas.value.clientWidth;
  boardEditorPosition.x = Math.max(12, width - 292);
  boardEditorPosition.y = 18;
}

function closeBoardEditor() {
  boardEditorVisible.value = false;
}

function toggleBoardEditorPin() {
  boardEditorPinned.value = !boardEditorPinned.value;
  if (boardEditorPinned.value && selectedDashboardCardId.value) {
    boardEditorCardId.value = selectedDashboardCardId.value;
  }
}

function startBoardEditorDrag(event: PointerEvent) {
  event.preventDefault();
  boardEditorDrag.value = { startX: event.clientX, startY: event.clientY, x: boardEditorPosition.x, y: boardEditorPosition.y };
  window.addEventListener("pointermove", onBoardEditorPointerMove);
  window.addEventListener("pointerup", stopBoardEditorDrag);
}

function onBoardEditorPointerMove(event: PointerEvent) {
  const drag = boardEditorDrag.value;
  const canvas = dashboardCanvas.value;
  if (!drag || !canvas) return;
  const maxX = Math.max(8, canvas.clientWidth - 280);
  const maxY = Math.max(8, canvas.clientHeight - 220);
  boardEditorPosition.x = Math.max(8, Math.min(maxX, drag.x + event.clientX - drag.startX));
  boardEditorPosition.y = Math.max(8, Math.min(maxY, drag.y + event.clientY - drag.startY));
}

function stopBoardEditorDrag() {
  boardEditorDrag.value = null;
  window.removeEventListener("pointermove", onBoardEditorPointerMove);
  window.removeEventListener("pointerup", stopBoardEditorDrag);
}

function nextCardLayout(size: "small" | "medium" | "large" = "medium") {
  const dims = size === "small" ? { w: 11, h: 2 } : size === "large" ? { w: 43, h: 5 } : { w: 27, h: 4 };
  let y = 0;
  while (true) {
    for (let x = 0; x <= BOARD_GRID_COLUMNS - dims.w; x += dims.w) {
      const layout = { x, y, ...dims, cols: BOARD_GRID_COLUMNS };
      if (!layoutOverlaps(layout, "")) return layout;
    }
    y += 1;
  }
}

function layoutOverlaps(layout: BoardLayout, cardId: string) {
  return Boolean(currentDashboard.value?.cards.some((card) => {
    if (card.id === cardId) return false;
    const other = normalizeSavedBoardLayout(card.layout);
    return layout.x < other.x + other.w && layout.x + layout.w > other.x && layout.y < other.y + other.h && layout.y + layout.h > other.y;
  }));
}

function normalizeBoardLayout(layout: BoardLayout) {
  const next = {
    x: Math.max(0, Math.min(BOARD_GRID_COLUMNS - 1, Math.round(layout.x || 0))),
    y: Math.max(0, Math.round(layout.y || 0)),
    w: Math.max(BOARD_MIN_WIDTH, Math.min(BOARD_GRID_COLUMNS, Math.round(layout.w || BOARD_MIN_WIDTH))),
    h: Math.max(2, Math.min(BOARD_MAX_HEIGHT, Math.round(layout.h || 3))),
    cols: BOARD_GRID_COLUMNS
  };
  if (next.x + next.w > BOARD_GRID_COLUMNS) next.x = BOARD_GRID_COLUMNS - next.w;
  return next;
}

function normalizeSavedBoardLayout(layout: BoardLayout): BoardLayout {
  const raw = layout || { x: 0, y: 0, w: 27, h: 4 };
  const rawCols = Number(raw.cols || 0);
  if (rawCols === BOARD_GRID_COLUMNS) return normalizeBoardLayout(raw);
  const inferredCols = rawCols || ((raw.x || 0) + (raw.w || 0) > LEGACY_BOARD_GRID_COLUMNS ? 24 : LEGACY_BOARD_GRID_COLUMNS);
  const scale = BOARD_GRID_COLUMNS / inferredCols;
  return normalizeBoardLayout({
    x: Math.round((raw.x || 0) * scale),
    y: raw.y || 0,
    w: Math.round((raw.w || 1) * scale),
    h: raw.h || 3,
    cols: BOARD_GRID_COLUMNS
  });
}

function normalizeDashboardDetail(dashboard: DashboardDetail): DashboardDetail {
  return {
    ...dashboard,
    config: { ...(dashboard.config || {}), dynamic_parameters: dashboard.config?.dynamic_parameters || [] },
    cards: dashboard.cards.map((card) => ({ ...card, layout: normalizeSavedBoardLayout(card.layout) }))
  };
}

function layoutGridStyle(layout: BoardLayout) {
  return {
    gridColumn: `${layout.x + 1} / span ${layout.w}`,
    gridRow: `${layout.y + 1} / span ${layout.h}`
  };
}

function dashboardCardStyle(card: DashboardCard) {
  const layout = normalizeSavedBoardLayout(card.layout);
  return layoutGridStyle(layout);
}

const dashboardDragCard = computed(() => currentDashboard.value?.cards.find((card) => card.id === dashboardDrag.value?.cardId) || null);

function dashboardDragLayerStyle() {
  const drag = dashboardDrag.value;
  if (!drag) return {};
  return {
    left: `${drag.fixedX}px`,
    top: `${drag.fixedY}px`,
    width: `${drag.width}px`,
    height: `${drag.height}px`
  };
}

function startDashboardPointer(event: PointerEvent, card: DashboardCard, mode: "move" | "resize") {
  if (dashboardMode.value !== "edit") return;
  event.preventDefault();
  event.stopPropagation();
  selectedDashboardCardId.value = card.id;
  const layout = normalizeSavedBoardLayout(card.layout);
  const target = event.currentTarget instanceof HTMLElement ? event.currentTarget : null;
  const cardElement = target?.closest(".board-card") as HTMLElement | null;
  const rect = cardElement?.getBoundingClientRect();
  target?.setPointerCapture?.(event.pointerId);
  dashboardDrag.value = {
    cardId: card.id,
    mode,
    startX: event.clientX,
    startY: event.clientY,
    layout,
    pointerId: event.pointerId,
    captureTarget: target,
    grabX: rect ? event.clientX - rect.left : 0,
    grabY: rect ? event.clientY - rect.top : 0,
    fixedX: rect ? rect.left : event.clientX,
    fixedY: rect ? rect.top : event.clientY,
    width: rect?.width || 240,
    height: rect?.height || 160,
    lastClientX: event.clientX,
    lastClientY: event.clientY,
    pixelX: 0,
    pixelY: 0,
    targetLayout: layout,
    targetValid: true
  };
  window.addEventListener("pointermove", onDashboardPointerMove);
  window.addEventListener("pointerup", stopDashboardPointer);
  window.addEventListener("pointercancel", cancelDashboardPointer);
  boardPageRef.value?.addEventListener("scroll", onDashboardDragScroll, { passive: true });
  updateDashboardDragFromPointer(event.clientX, event.clientY);
  startDashboardAutoScroll();
}

function onDashboardPointerMove(event: PointerEvent) {
  updateDashboardDragFromPointer(event.clientX, event.clientY);
}

function updateDashboardDragFromPointer(clientX: number, clientY: number) {
  const drag = dashboardDrag.value;
  const canvas = dashboardCanvas.value;
  if (!drag || !currentDashboard.value || !canvas) return;
  const card = currentDashboard.value.cards.find((item) => item.id === drag.cardId);
  if (!card) return;
  drag.lastClientX = clientX;
  drag.lastClientY = clientY;
  const metrics = boardGridMetrics();
  const canvasRect = canvas.getBoundingClientRect();
  const pointerCanvasX = clientX - canvasRect.left - metrics.paddingLeft;
  const pointerCanvasY = clientY - canvasRect.top - metrics.paddingTop;
  drag.fixedX = clientX - drag.grabX;
  drag.fixedY = clientY - drag.grabY;
  drag.pixelX = drag.fixedX - (drag.startX - drag.grabX);
  drag.pixelY = drag.fixedY - (drag.startY - drag.grabY);
  const raw = drag.mode === "move"
    ? { ...drag.layout, x: Math.round((pointerCanvasX - drag.grabX) / metrics.columnPitch), y: Math.round((pointerCanvasY - drag.grabY) / metrics.rowPitch) }
    : { ...drag.layout, w: drag.layout.w + Math.round((clientX - drag.startX) / metrics.columnPitch), h: drag.layout.h + Math.round((clientY - drag.startY) / metrics.rowPitch) };
  const next = normalizeBoardLayout(raw);
  drag.targetLayout = next;
  drag.targetValid = !layoutOverlaps(next, card.id);
  if (drag.mode === "resize" && drag.targetValid) card.layout = next;
}

function boardGridMetrics() {
  const canvas = dashboardCanvas.value;
  if (!canvas) return { paddingLeft: 0, paddingTop: 0, columnPitch: 1, rowPitch: BOARD_ROW_HEIGHT };
  const style = window.getComputedStyle(canvas);
  const paddingLeft = Number.parseFloat(style.paddingLeft || "0") || 0;
  const paddingRight = Number.parseFloat(style.paddingRight || "0") || 0;
  const paddingTop = Number.parseFloat(style.paddingTop || "0") || 0;
  const columnGap = Number.parseFloat(style.columnGap || style.gap || "0") || 0;
  const rowGap = Number.parseFloat(style.rowGap || style.gap || "0") || 0;
  const columnWidth = Math.max(1, (canvas.clientWidth - paddingLeft - paddingRight - columnGap * (BOARD_GRID_COLUMNS - 1)) / BOARD_GRID_COLUMNS);
  return { paddingLeft, paddingTop, columnPitch: columnWidth + columnGap, rowPitch: BOARD_ROW_HEIGHT + rowGap };
}

function onDashboardDragScroll() {
  const drag = dashboardDrag.value;
  if (!drag) return;
  updateDashboardDragFromPointer(drag.lastClientX, drag.lastClientY);
}

function startDashboardAutoScroll() {
  if (dashboardAutoScrollFrame.value !== null) return;
  const step = () => {
    const drag = dashboardDrag.value;
    const container = boardPageRef.value;
    if (!drag || !container || drag.mode !== "move") {
      dashboardAutoScrollFrame.value = null;
      return;
    }
    const rect = container.getBoundingClientRect();
    const edge = 72;
    const maxSpeed = 18;
    let speed = 0;
    if (drag.lastClientY < rect.top + edge) {
      speed = -maxSpeed * (1 - Math.max(0, drag.lastClientY - rect.top) / edge);
    } else if (drag.lastClientY > rect.bottom - edge) {
      speed = maxSpeed * (1 - Math.max(0, rect.bottom - drag.lastClientY) / edge);
    }
    if (speed) {
      const before = container.scrollTop;
      container.scrollTop = Math.max(0, Math.min(container.scrollHeight - container.clientHeight, before + speed));
      if (container.scrollTop !== before) updateDashboardDragFromPointer(drag.lastClientX, drag.lastClientY);
    }
    dashboardAutoScrollFrame.value = window.requestAnimationFrame(step);
  };
  dashboardAutoScrollFrame.value = window.requestAnimationFrame(step);
}

async function stopDashboardPointer() {
  const drag = dashboardDrag.value;
  cleanupDashboardDrag();
  if (!drag || !currentDashboard.value) return;
  const card = currentDashboard.value.cards.find((item) => item.id === drag.cardId);
  if (card && drag.targetValid) {
    card.layout = normalizeBoardLayout(drag.targetLayout);
    dashboardDrag.value = null;
    await saveDashboardCard(card, { layout: card.layout });
    return;
  }
  dashboardDrag.value = null;
}

function cancelDashboardPointer() {
  cleanupDashboardDrag();
  dashboardDrag.value = null;
}

function cleanupDashboardDrag() {
  const drag = dashboardDrag.value;
  window.removeEventListener("pointermove", onDashboardPointerMove);
  window.removeEventListener("pointerup", stopDashboardPointer);
  window.removeEventListener("pointercancel", cancelDashboardPointer);
  boardPageRef.value?.removeEventListener("scroll", onDashboardDragScroll);
  if (dashboardAutoScrollFrame.value !== null) {
    window.cancelAnimationFrame(dashboardAutoScrollFrame.value);
    dashboardAutoScrollFrame.value = null;
  }
  if (drag?.captureTarget?.hasPointerCapture?.(drag.pointerId)) {
    drag.captureTarget.releasePointerCapture(drag.pointerId);
  }
}

async function addTextCard() {
  selectManualComponent("text");
  openManualBuilder();
}

function openManualBuilder() {
  manualEditingCardId.value = "";
  boardToolsOpen.value = true;
  boardFilterOpen.value = false;
  if (!dashboardDynamicDraft.dataset_id) dashboardDynamicDraft.dataset_id = selectedDatasetId.value;
  if (!dashboardDynamicDraft.table_name) dashboardDynamicDraft.table_name = schema.value?.tables?.[0]?.name || "";
}

function closeManualBuilder() {
  boardToolsOpen.value = false;
  boardFilterOpen.value = false;
  manualEditingCardId.value = "";
}

async function openManualBuilderForCard(card: DashboardCard) {
  let targetCard = card;
  if (!isManualDashboardCard(targetCard) && isExampleTemplateCard(targetCard) && currentDashboard.value) {
    await openDashboard(currentDashboard.value.id);
    targetCard = currentDashboard.value?.cards.find((item) => item.id === card.id) || currentDashboard.value?.cards.find((item) => item.title === card.title && item.card_type === card.card_type) || targetCard;
  }
  if (!isManualDashboardCard(targetCard) && isExampleTemplateCard(targetCard)) {
    targetCard = {
      ...targetCard,
      source_type: "manual_single_table",
      query: {
        mode: "manual_single_table",
        refresh_mode: "dynamic_query",
        component: targetCard.card_type === "metric" ? "metric" : targetCard.card_type === "table" ? "table" : targetCard.card_type === "text" ? "text" : "chart",
        table_name: "",
        category_column: "",
        value_columns: [],
        selected_columns: [],
        aggregate: targetCard.card_type === "table" || targetCard.card_type === "text" ? "none" : "sum",
        filters: []
      }
    };
  }
  if (!isManualDashboardCard(targetCard)) {
    showToast("智能问数卡片保留原 SQL，不使用手动组件菜单编辑数据源。", true);
    return;
  }
  manualBuilderHydrating.value = true;
  try {
    if (targetCard.dataset_id && targetCard.dataset_id !== selectedDatasetId.value) {
      selectedDatasetId.value = targetCard.dataset_id;
      await refreshSchema().catch(() => undefined);
    }
    const query = targetCard.query || {};
    manualEditingCardId.value = targetCard.id;
    manualBuilder.component = String(query.component || (targetCard.card_type === "metric" ? "metric" : targetCard.card_type === "table" ? "table" : targetCard.card_type === "text" ? "text" : "chart"));
    manualBuilder.refreshMode = cardUiMode(targetCard);
    manualBuilder.chartType = String(targetCard.chart_config?.type || (manualBuilder.component === "line" ? "line" : manualBuilder.component === "pie" ? "pie" : "column_clustered"));
    manualBuilder.metricDecimals = String(targetCard.chart_config?.metricDecimals || "none");
    manualBuilder.title = targetCard.title || "手动组件";
    manualBuilder.dataset_id = targetCard.dataset_id || selectedDatasetId.value;
    manualBuilder.table_name = String(query.table_name || "");
    manualBuilder.category_column = String(query.category_column || "");
    manualBuilder.value_columns = Array.isArray(query.value_columns) ? [...query.value_columns] : [];
    manualBuilder.selected_columns = Array.isArray(query.selected_columns) ? [...query.selected_columns] : [];
    manualBuilder.aggregate = String(query.aggregate || "sum");
    manualBuilder.filters = Array.isArray(query.filters) ? query.filters.map((item: ManualFilter) => normalizeManualFilterForBuilder(item)) : [];
    manualBuilder.text = String(query.text || "看板说明文字");
    manualBuilder.align = String(query.align || "left");
    boardToolsOpen.value = true;
    boardFilterOpen.value = false;
  } finally {
    await nextTick();
    manualBuilderHydrating.value = false;
  }
}

function selectManualComponent(component: string) {
  manualBuilder.component = component;
  manualBuilder.chartType = component === "line" ? "line" : component === "pie" ? "pie" : "column_clustered";
  if (component === "metric" && !manualBuilder.metricDecimals) manualBuilder.metricDecimals = "none";
  manualBuilder.title = manualComponentLabel.value;
  if (component === "text" || component === "table") {
    manualBuilder.aggregate = "none";
  } else if (manualBuilder.aggregate === "none" && component !== "table") {
    manualBuilder.aggregate = "sum";
  }
}

function addManualFilter() {
  const firstColumn = manualColumns.value[0]?.name || "";
  const filter = normalizeManualFilterForBuilder({ column: firstColumn, operator: "=", value: "", globalLinked: true });
  manualBuilder.filters.push(filter);
  boardFilterOpen.value = true;
}

function removeManualFilter(index: number) {
  manualBuilder.filters.splice(index, 1);
}

function updateManualFilterColumn(index: number, column: string) {
  const filter = manualBuilder.filters[index];
  if (!filter) return;
  filter.column = column;
  filter.value = "";
  filter.value_to = "";
  if (isManualFilterDateColumn(filter)) {
    filter.operator = "between";
    filter.time_strategy = "latest_date";
  } else {
    filter.operator = filterOperatorOptions(column)[0]?.value || "=";
    filter.time_strategy = "";
  }
}

function updateManualFilterOperator(index: number, operator: string) {
  const filter = manualBuilder.filters[index];
  if (!filter) return;
  filter.operator = operator;
  if (operator !== "between") filter.value_to = "";
}

function normalizeManualFilterForBuilder(item: ManualFilter): ManualFilter {
  const filter: ManualFilter = { ...item, globalLinked: manualFilterLinked(item) };
  if (isManualFilterDateColumn(filter)) {
    const originalOperator = filter.operator;
    filter.operator = "between";
    filter.time_strategy = filter.time_strategy || filter.date_strategy || (originalOperator === "between" && filter.value && filter.value_to ? "custom_range" : "latest_date");
  }
  return filter;
}

function manualFilterLinked(filter: ManualFilter) {
  return filter.globalLinked !== false && filter.linkedToGlobal !== false && filter.useGlobalCondition !== false;
}

function manualFilterGlobalParameter(filter: ManualFilter) {
  if (!filter.column || !manualBuilder.dataset_id || !manualBuilder.table_name) return null;
  return dashboardDynamicParameters.value.find((parameter) =>
    parameter.dataset_id === manualBuilder.dataset_id
    && parameter.table_name === manualBuilder.table_name
    && parameter.column_name === filter.column
  ) || null;
}

function manualFilterUsesGlobal(filter: ManualFilter) {
  return manualFilterLinked(filter) && Boolean(manualFilterGlobalParameter(filter));
}

function toggleManualFilterGlobalLink(index: number) {
  const filter = manualBuilder.filters[index];
  if (!filter) return;
  if (manualFilterUsesGlobal(filter)) {
    filter.globalLinked = false;
    return;
  }
  const parameter = manualFilterGlobalParameter(filter);
  if (!parameter) {
    filter.globalLinked = false;
    showToast("顶部动态条件未启用该字段，无法链接。", true);
    return;
  }
  filter.globalLinked = true;
  filter.linkedToGlobal = true;
  filter.useGlobalCondition = true;
  filter.operator = isTimeDynamicParameter(parameter) ? "between" : (filter.operator || "=");
}

function manualFilterColumn(filter: ManualFilter) {
  return manualColumns.value.find((item) => item.name === filter.column) || null;
}

function isManualFilterDateColumn(filter: ManualFilter) {
  const column = manualFilterColumn(filter);
  return Boolean(column && isDateLikeSchemaColumn(column));
}

function manualFilterTimeStrategy(filter: ManualFilter) {
  return String(filter.time_strategy || filter.date_strategy || (isManualFilterDateColumn(filter) ? "latest_date" : ""));
}

function updateManualFilterTimeStrategy(index: number, strategy: string) {
  const filter = manualBuilder.filters[index];
  if (!filter) return;
  filter.time_strategy = strategy || "latest_date";
  filter.operator = "between";
  if (filter.time_strategy !== "custom_range") {
    filter.value = "";
    filter.value_to = "";
  }
}

function filterOperatorOptions(columnName: string) {
  const column = manualColumns.value.find((item) => item.name === columnName);
  const numeric = column ? isNumericColumnType(column.type) : false;
  const range = column ? numeric || isRangeColumn(column) : false;
  const base = [
    { value: "=", label: "等于" },
    { value: "!=", label: "不等于" },
    { value: "in", label: "IN 多值" }
  ];
  const rangeOption = range ? [{ value: "between", label: "在……到……之间" }] : [];
  return numeric
    ? [...base, { value: ">", label: "大于" }, { value: ">=", label: "大于等于" }, { value: "<", label: "小于" }, { value: "<=", label: "小于等于" }, ...rangeOption]
    : [...base, { value: "contains", label: "包含" }, ...rangeOption];
}

function isNumericColumnType(type: string) {
  return /INT|DOUBLE|DECIMAL|NUMERIC|FLOAT|REAL|BIGINT|SMALLINT|TINYINT/i.test(type);
}

function isRangeColumn(column: { name: string; type: string; semantic_type?: string }) {
  return isDateLikeSchemaColumn(column);
}

function filterValueInputType(columnName: string, operator = "") {
  if (operator === "in") return "text";
  const column = manualColumns.value.find((item) => item.name === columnName);
  const type = column?.type || "";
  if (isNumericColumnType(type)) return "number";
  if (/TIMESTAMP|DATETIME/i.test(type)) return "datetime-local";
  if ((column && isDateLikeSchemaColumn(column)) || /DATE/i.test(type)) return "date";
  return "text";
}

async function addManualCard(component: string) {
  if (manualBuilderIssue.value) return;
  if (!currentDashboard.value) await createNewDashboard();
  if (!currentDashboard.value) return;
  await guarded(async () => {
    const isText = component === "text";
    const editingCard = manualEditingCardId.value ? currentDashboard.value!.cards.find((card) => card.id === manualEditingCardId.value) : null;
    const payload: Partial<DashboardCard> = {
      card_type: component === "metric" ? "metric" : component === "table" ? "table" : isText ? "text" : "chart",
      title: manualBuilder.title || (isText ? "文本说明" : "手动组件"),
      layout: editingCard ? editingCard.layout : nextCardLayout(component === "metric" ? "small" : "medium"),
      dataset_id: isText ? "" : manualBuilder.dataset_id,
      source_type: isText ? "static_text" : "manual_single_table",
      query: isText ? { text: manualBuilder.text, align: manualBuilder.align } : manualQueryPayload(component),
      chart_config: isText ? {} : editingCard ? { ...editingCard.chart_config, ...manualChartConfig(component) } : manualChartConfig(component),
      result_snapshot: {}
    };
    if (!isText) {
      const preview = await previewDashboardManualQuery({ dataset_id: manualBuilder.dataset_id, title: manualBuilder.title, query: payload.query || {} });
      payload.result_snapshot = { table: preview.table };
    }
    if (editingCard) {
      const response = await updateDashboardCard(currentDashboard.value!.id, editingCard.id, payload);
      currentDashboard.value!.cards = currentDashboard.value!.cards.map((card) => card.id === editingCard.id ? { ...response.card, layout: normalizeSavedBoardLayout(response.card.layout) } : card);
      selectedDashboardCardId.value = response.card.id;
      await nextTick();
      renderDashboardCardChart(response.card.id);
    } else {
      const response = await createDashboardCard(currentDashboard.value!.id, payload);
      currentDashboard.value!.cards.push({ ...response.card, layout: normalizeSavedBoardLayout(response.card.layout) });
      selectedDashboardCardId.value = response.card.id;
      await nextTick();
      renderDashboardCardChart(response.card.id);
    }
    closeManualBuilder();
    await refreshDashboards(currentDashboard.value!.id);
  }, manualEditingCardId.value ? "组件已更新" : "组件已加入看板", dashboardBusy);
}

function manualQueryPayload(component: string) {
  return {
    mode: "manual_single_table",
    refresh_mode: manualBuilder.refreshMode === "dynamic" ? "dynamic_query" : "fixed_query",
    component,
    table_name: manualBuilder.table_name,
    category_column: manualBuilder.category_column,
    value_columns: manualBuilder.value_columns,
    selected_columns: manualBuilder.selected_columns,
    aggregate: manualBuilder.aggregate,
    filters: manualBuilder.filters
      .filter((item) => {
        if (!item.column) return false;
        if (manualFilterUsesGlobal(item)) return true;
        if (isManualFilterDateColumn(item)) {
          const strategy = manualFilterTimeStrategy(item);
          return Boolean(strategy && (strategy !== "custom_range" || (String(item.value || "").trim() && String(item.value_to || "").trim())));
        }
        return Boolean(item.operator && String(item.value || "").trim());
      })
      .map((item) => ({
        ...item,
        operator: isManualFilterDateColumn(item) ? "between" : item.operator,
        time_strategy: isManualFilterDateColumn(item) ? manualFilterTimeStrategy(item) : "",
        globalLinked: manualFilterUsesGlobal(item),
        linkedToGlobal: manualFilterUsesGlobal(item),
        useGlobalCondition: manualFilterUsesGlobal(item),
        value: manualFilterUsesGlobal(item) ? "" : item.value,
        value_to: manualFilterUsesGlobal(item) ? "" : item.value_to
      })),
    limit: 100
  };
}

function manualChartConfig(component: string) {
  return {
    ...chartOptionsSnapshot(),
    type: component === "line" ? "line" : component === "pie" ? "pie" : "column_clustered",
    metricDecimals: component === "metric" ? manualBuilder.metricDecimals : undefined,
    title: manualBuilder.title,
    categoryColumn: manualBuilder.category_column,
    numericColumns: manualBuilder.value_columns.slice(0, 4),
    showTitle: true,
    titlePosition: "card_top"
  };
}

function toggleManualValueColumn(column: string) {
  manualBuilder.value_columns = manualBuilder.value_columns.includes(column)
    ? manualBuilder.value_columns.filter((item) => item !== column)
    : [...manualBuilder.value_columns, column].slice(0, 4);
}

function toggleManualSelectedColumn(column: string) {
  manualBuilder.selected_columns = manualBuilder.selected_columns.includes(column)
    ? manualBuilder.selected_columns.filter((item) => item !== column)
    : [...manualBuilder.selected_columns, column].slice(0, 8);
}

function openAddToDashboard() {
  if (!selectedChartTable.value) {
    chartError.value = "请先选择查询结果。";
    return;
  }
  addToDashboardTitle.value = chartOptions.title || String(selectedChartTable.value.purpose || "查询图表");
  addToDashboardTargetId.value = currentDashboard.value?.id || dashboards.value[0]?.id || "";
  addToDashboardSize.value = "medium";
  addToDashboardMode.value = "static";
  addToDashboardOpen.value = true;
}

async function confirmAddToDashboard() {
  const table = selectedChartTable.value;
  if (!table) return;
  await guarded(async () => {
    let dashboardId = addToDashboardTargetId.value;
    if (!dashboardId) {
      const created = await createDashboard({ name: "我的看板" });
      dashboardId = created.dashboard.id;
      currentDashboard.value = normalizeDashboardDetail(created.dashboard);
    }
    const sql = sqlByTaskId.value.get(String(table.task_id || ""))?.after || "";
    const turn = renderedTurns.value.find((item) => item.assistant_message_id === selectedChartMessageId.value);
    await createDashboardCard(dashboardId, {
      card_type: "chart",
      title: addToDashboardTitle.value || chartOptions.title || "查询图表",
      layout: nextCardLayout(addToDashboardSize.value),
      dataset_id: selectedDatasetId.value,
      source_type: "nl2sql_result",
      query: { mode: "nl2sql_result", refresh_mode: addToDashboardMode.value === "dynamic" ? "dynamic_query" : "fixed_query", sql, question: turn?.user_message.content || "", task_id: table.task_id || "", conversation_id: currentConversation.value?.id || "", user_message_id: turn?.user_message.id || "", assistant_message_id: selectedChartMessageId.value },
      chart_config: { ...chartOptionsSnapshot(), title: addToDashboardTitle.value || chartOptions.title, showTitle: true, titlePosition: "card_top" },
      result_snapshot: { table }
    });
    addToDashboardOpen.value = false;
    await refreshDashboards(dashboardId);
    showToast("已加入看板");
  }, "已加入看板", dashboardBusy);
}

async function duplicateDashboardCard(card: DashboardCard) {
  if (!currentDashboard.value) return;
  const response = await createDashboardCard(currentDashboard.value.id, { ...card, id: undefined, title: `${card.title} 副本`, layout: nextCardLayout("medium") });
  currentDashboard.value.cards.push({ ...response.card, layout: normalizeSavedBoardLayout(response.card.layout) });
  selectedDashboardCardId.value = response.card.id;
  await nextTick();
  renderDashboardCharts();
}

async function removeDashboardCard(card: DashboardCard) {
  if (!currentDashboard.value) return;
  await deleteDashboardCard(currentDashboard.value.id, card.id);
  currentDashboard.value.cards = currentDashboard.value.cards.filter((item) => item.id !== card.id);
  if (selectedDashboardCardId.value === card.id) selectedDashboardCardId.value = currentDashboard.value.cards[0]?.id || "";
  await refreshConversations(currentConversation.value?.id);
}

async function refreshOneCard(card: DashboardCard) {
  if (!currentDashboard.value) return;
  const response = await refreshDashboardCard(currentDashboard.value.id, card.id);
  currentDashboard.value.cards = currentDashboard.value.cards.map((item) => item.id === card.id ? { ...response.card, layout: normalizeSavedBoardLayout(response.card.layout) } : item);
  await nextTick();
  renderDashboardCardChart(card.id);
}

function initializeWorkspaceByWidth() {
  workspaceOpen.value = window.innerWidth >= 1180;
  clampWorkspaceWidth();
}

function updateWorkspaceByWidth() {
  syncMobilePanelsByViewport();
  clampWorkspaceWidth();
  if (workspaceOpen.value && chartRendered.value) {
    nextTick(() => window.requestAnimationFrame(() => activeChart.value?.resize()));
  }
}

function clampWorkspaceWidth() {
  const maxWidth = Math.max(workspaceDefaultWidth, Math.floor(window.innerWidth * 0.5));
  workspaceWidth.value = Math.min(Math.max(workspaceWidth.value, workspaceDefaultWidth), maxWidth);
}

function resizeWorkspace(clientX: number) {
  const maxWidth = Math.max(workspaceDefaultWidth, Math.floor(window.innerWidth * 0.5));
  const nextWidth = window.innerWidth - clientX;
  workspaceWidth.value = Math.min(Math.max(nextWidth, workspaceDefaultWidth), maxWidth);
}

function stopWorkspaceResize() {
  workspaceResizing.value = false;
  window.removeEventListener("pointermove", onWorkspacePointerMove);
  window.removeEventListener("pointerup", stopWorkspaceResize);
}

function onWorkspacePointerMove(event: PointerEvent) {
  if (!workspaceResizing.value) return;
  resizeWorkspace(event.clientX);
}

function startWorkspaceResize(event: PointerEvent) {
  if (!workspaceOpen.value) return;
  event.preventDefault();
  workspaceResizing.value = true;
  resizeWorkspace(event.clientX);
  window.addEventListener("pointermove", onWorkspacePointerMove);
  window.addEventListener("pointerup", stopWorkspaceResize);
}

function setError(message: string) {
  error.value = message;
  status.value = "操作失败";
}

async function guarded(action: () => Promise<void>, success: string, busy = datasetBusy) {
  busy.value = true;
  error.value = "";
  try {
    await action();
    status.value = success;
  } catch (err) {
    setError(err instanceof Error ? err.message : "未知错误");
  } finally {
    busy.value = false;
  }
}

async function initializeAppData() {
  await refreshDatasets();
  await refreshConversations();
  await refreshLLMConfigs();
  await refreshDashboards();
  if (canManagePermissions.value) {
    await refreshPermissionSubjects();
  }
}

async function synchronizeServerState() {
  if (!authUser.value) return;
  await refreshDatasets(selectedDatasetId.value || undefined);
  await refreshLLMConfigs();
  await refreshConversations(currentConversation.value?.id);
}

async function checkAuthSession() {
  try {
    const response = await getCurrentUser();
    authUser.value = response.user;
    await initializeAppData();
    status.value = "页面已恢复";
  } catch {
    clearAuthToken();
    authUser.value = null;
  } finally {
    authChecked.value = true;
  }
}

async function submitLogin() {
  loginBusy.value = true;
  loginError.value = "";
  try {
    const response = await login({ username: loginForm.username.trim(), password: loginForm.password });
    setAuthToken(response.token);
    authUser.value = response.user;
    loginForm.password = "";
    await initializeAppData();
    status.value = "登录成功";
  } catch (err) {
    loginError.value = err instanceof Error ? err.message : "登录失败";
  } finally {
    loginBusy.value = false;
    authChecked.value = true;
  }
}

function logout() {
  closeMobilePanels();
  clearAuthToken();
  authUser.value = null;
  currentConversation.value = null;
  datasets.value = [];
  conversations.value = [];
  dashboards.value = [];
  currentDashboard.value = null;
  selectedDashboardCardId.value = "";
  llmConfigs.value = [];
  selectedDatasetId.value = "";
  debugModeEnabled.value = false;
  workspaceTab.value = "chart";
  accountMenuOpen.value = false;
  accountSettingsOpen.value = false;
  draft.value = "";
  status.value = "已退出登录";
}

async function refreshDatasets(nextId?: string) {
  const response = await listDatasets();
  datasets.value = response.items;
  if (nextId !== undefined) {
    selectedDatasetId.value = nextId;
  }
  if (selectedDatasetId.value && !datasets.value.some((item) => item.id === selectedDatasetId.value)) {
    selectedDatasetId.value = "";
  }
  syncEditForm();
  await refreshSchema();
}

async function refreshConversations(nextId?: string) {
  const response = await listConversations();
  conversations.value = response.items;
  referencedConversations.value = response.referenced_items || [];
  const currentId = currentConversation.value?.id || "";
  const allConversationItems = [...conversations.value, ...referencedConversations.value];
  const nextExists = nextId ? allConversationItems.some((item) => item.id === nextId) : false;
  const targetId =
    (nextExists ? nextId : "") ||
    (allConversationItems.some((item) => item.id === currentId) ? currentId : "") ||
    findReusableEmptyConversationId() ||
    conversations.value[0]?.id ||
    referencedConversations.value[0]?.id ||
    "";
  if (targetId) {
    await openConversation(targetId);
  } else {
    currentConversation.value = null;
    pendingTurn.value = null;
  }
}

function isEmptyConversation(item: ConversationSummary | ConversationDetail | null | undefined): boolean {
  if (!item) return false;
  if (Array.isArray((item as ConversationDetail).messages)) {
    return (item as ConversationDetail).messages.length === 0;
  }
  return !item.last_user_message_at;
}

function findReusableEmptyConversationId(): string {
  if (isEmptyConversation(currentConversation.value)) return currentConversation.value?.id || "";
  return conversations.value.find((item) => isEmptyConversation(item))?.id || "";
}

async function openConversation(conversationId: string) {
  closeMobilePanels();
  await saveCurrentScroll();
  try {
    const response = await getConversation(conversationId);
    currentConversation.value = response.conversation;
    selectedDatasetId.value = response.conversation.selected_dataset_id || "";
    syncEditForm();
    await refreshSchema();
    await restoreScroll();
  } catch (err) {
    if (err instanceof Error && err.message.includes("404")) {
      currentConversation.value = null;
      await refreshConversations();
      return;
    }
    throw err;
  }
}

async function startConversation() {
  closeMobilePanels();
  activePage.value = "chat";
  accountMenuOpen.value = false;
  await saveCurrentScroll();
  debugModeEnabled.value = false;
  workspaceTab.value = "chart";
  const reusableId = findReusableEmptyConversationId();
  if (reusableId) {
    draft.value = "";
    await openConversation(reusableId);
    await initializeEmptyConversationDataset();
    return;
  }
  const response = await createConversation();
  currentConversation.value = response.conversation;
  selectedDatasetId.value = response.conversation.selected_dataset_id || "";
  draft.value = "";
  await refreshSchema();
  await reloadConversationList(response.conversation.id);
  await restoreScroll();
}

async function initializeEmptyConversationDataset() {
  if (!isEmptyConversation(currentConversation.value)) return;
  const dataset = latestReadyDataset.value;
  const nextDatasetId = dataset?.id || "";
  if (selectedDatasetId.value === nextDatasetId && currentConversation.value?.selected_dataset_id === nextDatasetId) {
    await refreshSchema();
    return;
  }
  selectedDatasetId.value = nextDatasetId;
  if (currentConversation.value) {
    const response = await saveConversationState(currentConversation.value.id, {
      selected_dataset_id: nextDatasetId
    });
    currentConversation.value = response.conversation;
  }
  await refreshSchema();
}

async function reloadConversationList(preferredId?: string) {
  const response = await listConversations();
  conversations.value = response.items;
  referencedConversations.value = response.referenced_items || [];
  if (preferredId && currentConversation.value?.id !== preferredId) {
    await openConversation(preferredId);
  }
}

async function submitQuestion() {
  exampleQuestionsOpen.value = false;
  const content = draft.value;
  const command = content.trim();
  if (!command) return;
  if (command === "/debug") {
    activateDebugMode();
    return;
  }
  await guarded(async () => {
    let target = currentConversation.value;
    if (!target) {
      const reusableId = findReusableEmptyConversationId();
      if (reusableId) {
        await openConversation(reusableId);
        await initializeEmptyConversationDataset();
        target = currentConversation.value;
      }
      if (!target) {
        const created = await createConversation();
        target = created.conversation;
        currentConversation.value = target;
        selectedDatasetId.value = target.selected_dataset_id || "";
        await refreshSchema();
      }
    }
    const datasetSnapshot = selectedDatasetId.value || target.selected_dataset_id || "";
    if (!datasetSnapshot) {
      throw new Error("请先选择数据集后再提问。");
    }
    const controller = new AbortController();
    const requestId = crypto.randomUUID();
    draft.value = "";
    pendingTurn.value = {
      turn_id: requestId,
      request_id: requestId,
      conversation_id: target.id,
      content,
      status: "thinking",
      error: ""
    };
    await nextTick();
    scrollToBottom();
    activeController.value = controller;
    let response;
    try {
      response = await sendMessage(
        target.id,
        {
          content,
          selected_dataset_id: datasetSnapshot,
          request_id: requestId,
          thinking_enabled: thinkingModeEnabled.value,
          fast_match_enabled: fastMatchEnabled.value,
          context_mode_enabled: contextModeEnabled.value,
          context_mode_session_id: contextModeSessionId.value
        },
        controller.signal
      );
    } catch (err) {
      if (pendingTurn.value?.request_id === requestId) {
        pendingTurn.value.status = err instanceof DOMException && err.name === "AbortError" ? "cancelled" : "error";
        pendingTurn.value.error = err instanceof Error ? err.message : "查询失败";
      }
      throw err;
    } finally {
      activeController.value = null;
    }
    currentConversation.value = response.conversation;
    selectedDatasetId.value = response.conversation.selected_dataset_id || "";
    if (pendingTurn.value?.request_id === requestId) {
      pendingTurn.value = null;
    }
    await reloadConversationList(response.conversation.id);
    const shouldFollow = isNearBottom();
    await nextTick();
    if (shouldFollow) scrollToBottom();
    if (response.conversation.status === "running") {
      await pollConversationUntilIdle(response.conversation.id);
    }
  }, "问题已记录", queryBusy);
}

function openExampleQuestions() {
  closeEntityCandidates();
  exampleQuestionsOpen.value = Boolean(supportsDatasetExampleQuestions.value && selectedDataset.value?.status === "ready" && !draft.value);
}

function closeExampleQuestions() {
  exampleQuestionsOpen.value = false;
}

function selectExampleQuestion(question: string) {
  draft.value = question;
  closeExampleQuestions();
}

function closeEntityCandidates() {
  window.clearTimeout(entityCandidateTimer);
  entityCandidateController?.abort();
  entityCandidateController = null;
  entityCandidatesOpen.value = false;
  entityCandidates.value = [];
  entityCandidatesHasMore.value = false;
  activeEntityCandidateIndex.value = -1;
}

function closeComposerPopovers() {
  closeExampleQuestions();
  closeEntityCandidates();
}

function currentEntityFragment() {
  const input = composerInput.value;
  const end = input?.selectionStart ?? draft.value.length;
  const match = draft.value.slice(0, end).match(/[A-Za-z0-9\u4e00-\u9fff]+$/);
  const text = (match?.[0] || "").slice(-10);
  return { start: end - text.length, end, text };
}

function scheduleEntityCandidates() {
  closeExampleQuestions();
  window.clearTimeout(entityCandidateTimer);
  entityCandidateController?.abort();
  entityCandidateController = null;
  entityCandidatesOpen.value = false;
  entityCandidates.value = [];
  const datasetId = selectedDatasetId.value;
  const fragment = currentEntityFragment();
  entityFragment.value = fragment;
  if (!datasetId || !fragment.text) return;
  entityCandidateTimer = window.setTimeout(async () => {
    const controller = new AbortController();
    entityCandidateController = controller;
    try {
      const response = await getEntityCandidates(datasetId, fragment.text, controller.signal);
      const current = currentEntityFragment();
      if (selectedDatasetId.value !== datasetId || current.start !== fragment.start || current.end !== fragment.end || current.text !== fragment.text) return;
      const matchedText = response.matched_text || "";
      entityFragment.value = { start: fragment.end - matchedText.length, end: fragment.end, text: matchedText };
      entityCandidates.value = response.items.slice(0, 10);
      entityCandidatesHasMore.value = Boolean(response.has_more);
      activeEntityCandidateIndex.value = -1;
      entityCandidatesOpen.value = entityCandidates.value.length > 0;
    } catch (err) {
      if (!(err instanceof DOMException && err.name === "AbortError")) closeEntityCandidates();
    } finally {
      if (entityCandidateController === controller) entityCandidateController = null;
    }
  }, 180);
}

function selectEntityCandidate(candidate: EntityCandidate) {
  const fragment = entityFragment.value;
  draft.value = `${draft.value.slice(0, fragment.start)}${candidate.name}${draft.value.slice(fragment.end)}`;
  closeEntityCandidates();
  const caret = fragment.start + candidate.name.length;
  nextTick(() => {
    composerInput.value?.focus();
    composerInput.value?.setSelectionRange(caret, caret);
  });
}

function composerCaretIsOnFirstVisualRow() {
  const input = composerInput.value;
  if (!input) return false;
  const beforeCaret = draft.value.slice(0, input.selectionStart ?? 0);
  const currentLine = beforeCaret.slice(beforeCaret.lastIndexOf("\n") + 1);
  if (beforeCaret.includes("\n")) return false;
  const style = window.getComputedStyle(input);
  const canvas = document.createElement("canvas");
  const context = canvas.getContext("2d");
  if (!context) return true;
  context.font = style.font;
  const available = input.clientWidth - parseFloat(style.paddingLeft) - parseFloat(style.paddingRight);
  return context.measureText(currentLine).width <= available;
}

function focusEntityCandidate(index: number) {
  if (!entityCandidates.value.length) return;
  activeEntityCandidateIndex.value = Math.max(0, Math.min(entityCandidates.value.length - 1, index));
  nextTick(() => {
    const buttons = entityCandidatesPanel.value?.querySelectorAll<HTMLButtonElement>("button[data-entity-option]");
    buttons?.[activeEntityCandidateIndex.value]?.scrollIntoView({ block: "nearest" });
  });
}

function handleComposerClick() {
  if (!draft.value) openExampleQuestions();
  else scheduleEntityCandidates();
}

function handleComposerKeydown(event: KeyboardEvent) {
  if (entityCandidatesOpen.value && event.key === "ArrowUp" && (activeEntityCandidateIndex.value >= 0 || composerCaretIsOnFirstVisualRow())) {
    event.preventDefault();
    focusEntityCandidate(activeEntityCandidateIndex.value < 0 ? 0 : activeEntityCandidateIndex.value - 1);
    return;
  }
  if (entityCandidatesOpen.value && event.key === "ArrowDown" && activeEntityCandidateIndex.value >= 0) {
    event.preventDefault();
    focusEntityCandidate(activeEntityCandidateIndex.value + 1);
    return;
  }
  if (entityCandidatesOpen.value && event.key === "Enter" && activeEntityCandidateIndex.value >= 0) {
    event.preventDefault();
    selectEntityCandidate(entityCandidates.value[activeEntityCandidateIndex.value]);
    return;
  }
  if (entityCandidatesOpen.value && event.key === "Escape") {
    event.preventDefault();
    closeEntityCandidates();
    return;
  }
  if (event.key !== "Enter" || event.isComposing || event.shiftKey || event.ctrlKey) return;
  event.preventDefault();
  void submitQuestion();
}

async function pollConversationUntilIdle(conversationId: string) {
  for (let index = 0; index < 120 && queryBusy.value; index += 1) {
    await delay(1000);
    const response = await getConversation(conversationId);
    if (currentConversation.value?.id === conversationId) {
      const shouldFollow = isNearBottom();
      currentConversation.value = response.conversation;
      await nextTick();
      if (shouldFollow) scrollToBottom();
    }
    if (response.conversation.status !== "running") {
      await reloadConversationList(response.conversation.id);
      return;
    }
  }
}

async function refreshLLMConfigs() {
  const response = await listLLMConfigs();
  llmConfigs.value = response.items;
}

async function stopQuestion() {
  activeController.value?.abort();
  activeController.value = null;
  if (pendingTurn.value) {
    pendingTurn.value.status = "cancelled";
    pendingTurn.value.error = "";
  }
  if (currentConversation.value) {
    await cancelConversation(currentConversation.value.id).catch(() => undefined);
  }
  queryBusy.value = false;
  status.value = "查询已取消";
}

async function onDatasetChange() {
  datasetBusy.value = true;
  error.value = "";
  try {
    if (currentConversation.value) {
      const response = await saveConversationState(currentConversation.value.id, {
        selected_dataset_id: selectedDatasetId.value
      });
      currentConversation.value = response.conversation;
    }
    syncEditForm();
    await refreshSchema();
    datasetBusy.value = false;
    if (selectedDatasetId.value) {
      indexBusy.value = true;
      await preloadEmbedding(selectedDatasetId.value);
      indexBusy.value = false;
    }
    status.value = "数据集选择已保存";
  } catch (err) {
    setError(err instanceof Error ? err.message : "鏈煡閿欒");
  } finally {
    datasetBusy.value = false;
    indexBusy.value = false;
  }
}

async function saveCurrentScroll() {
  if (!currentConversation.value || !chatArea.value) return;
  await saveConversationState(currentConversation.value.id, {
    scroll_position: Math.round(chatArea.value.scrollTop)
  }).catch(() => undefined);
}

async function restoreScroll() {
  await nextTick();
  if (!chatArea.value || !currentConversation.value) return;
  chatArea.value.scrollTop = currentConversation.value.scroll_position || 0;
}

function scrollToBottom() {
  if (!chatArea.value) return;
  chatArea.value.scrollTop = chatArea.value.scrollHeight;
}

function isNearBottom() {
  if (!chatArea.value) return true;
  const distance = chatArea.value.scrollHeight - chatArea.value.scrollTop - chatArea.value.clientHeight;
  return distance < 120;
}

async function refreshSchema() {
  schema.value = null;
  if (!selectedDatasetId.value) return;
  try {
    schema.value = await getSchema(selectedDatasetId.value);
  } catch (err) {
    if (err instanceof Error && err.message.includes("404")) {
      selectedDatasetId.value = "";
      if (currentConversation.value) {
        await saveConversationState(currentConversation.value.id, { selected_dataset_id: "" }).catch(() => undefined);
      }
      return;
    }
    throw err;
  }
}

function makePermissionTableKey(datasetId: string, tableName: string) {
  return `${datasetId}\u001f${tableName}`;
}

function makePermissionColumnKey(datasetId: string, tableName: string, columnName: string) {
  return `${datasetId}\u001f${tableName}\u001f${columnName}`;
}

function parsePermissionColumnKey(key: string): { datasetId: string; tableName: string; columnName: string } | null {
  const parts = key.split("\u001f");
  if (parts.length !== 3) return null;
  return { datasetId: parts[0], tableName: parts[1], columnName: parts[2] };
}

function selectionState(total: number, selected: number) {
  if (!total || !selected) return "未选";
  return selected >= total ? "全部" : "部分";
}

function targetSelectionState() {
  return selectionState(permissionTargetOptions.value.length, selectedPermissionTargets.value.filter((id) => permissionTargetOptions.value.some((item) => item.id === id)).length);
}

function datasetSelectionState() {
  return selectionState(permissionDatasetOptions.value.length, selectedPermissionDatasetIds.value.filter((id) => permissionDatasetOptions.value.some((item) => item.id === id)).length);
}

function tableSelectionState() {
  return selectionState(permissionTableOptions.value.length, selectedPermissionTables.value.filter((key) => permissionTableOptions.value.some((item) => item.key === key)).length);
}

function columnSelectionState() {
  return selectionState(permissionColumnOptions.value.length, selectedPermissionColumns.value.filter((key) => permissionColumnOptions.value.some((item) => item.key === key)).length);
}

function valueSelectionState() {
  return selectionState(permissionValues.value.length, permissionSelectedValues.value.filter((value) => permissionValues.value.includes(value)).length);
}

function toggleNumberSelection(target: typeof selectedPermissionTargets, value: number) {
  target.value = target.value.includes(value) ? target.value.filter((item) => item !== value) : [...target.value, value];
}

function toggleStringSelection(target: typeof selectedPermissionDatasetIds, value: string) {
  target.value = target.value.includes(value) ? target.value.filter((item) => item !== value) : [...target.value, value];
}

async function refreshPermissionSubjects() {
  if (!canManagePermissions.value) return;
  try {
    const response = await listPermissionSubjects();
    permissionSubjects.users = response.users;
    permissionSubjects.groups = response.groups;
  } catch (err) {
    permissionMessage.value = err instanceof Error ? err.message : "权限对象读取失败";
  }
}

async function togglePermissionTarget(id: number) {
  toggleNumberSelection(selectedPermissionTargets, id);
  await loadSelectedTargetPermissions();
}

async function selectAllPermissionTargets() {
  selectedPermissionTargets.value = permissionTargetOptions.value.map((item) => item.id);
  await loadSelectedTargetPermissions();
}

async function clearPermissionTargets() {
  selectedPermissionTargets.value = [];
  await loadSelectedTargetPermissions();
}

async function togglePermissionDataset(id: string) {
  toggleStringSelection(selectedPermissionDatasetIds, id);
  cleanPermissionSelections();
  permissionActiveDatasetId.value = selectedPermissionDatasetIds.value.includes(id) ? id : selectedPermissionDatasetIds.value[0] || "";
  await loadPermissionCandidates();
}

async function selectAllPermissionDatasets() {
  selectedPermissionDatasetIds.value = permissionDatasetOptions.value.map((item) => item.id);
  permissionActiveDatasetId.value = selectedPermissionDatasetIds.value[0] || "";
  cleanPermissionSelections();
  await loadPermissionCandidates();
}

async function clearPermissionDatasets() {
  selectedPermissionDatasetIds.value = [];
  permissionActiveDatasetId.value = "";
  cleanPermissionSelections();
  permissionCandidates.value = null;
  permissionValues.value = [];
}

async function setPermissionActiveDataset(datasetId: string) {
  permissionActiveDatasetId.value = datasetId;
  await loadPermissionCandidates();
}

async function loadPermissionCandidates() {
  permissionCandidates.value = null;
  if (!permissionActiveDatasetId.value) return;
  permissionBusy.value = true;
  try {
    permissionCandidates.value = await getPermissionCandidates(permissionActiveDatasetId.value);
    cleanPermissionSelections();
  } catch (err) {
    permissionMessage.value = err instanceof Error ? err.message : "权限 Schema 读取失败";
  } finally {
    permissionBusy.value = false;
  }
}

function togglePermissionTable(key: string) {
  toggleStringSelection(selectedPermissionTables, key);
  cleanPermissionSelections();
}

function selectAllPermissionTables() {
  selectedPermissionTables.value = Array.from(new Set([...selectedPermissionTables.value, ...permissionTableOptions.value.map((item) => item.key)]));
  cleanPermissionSelections();
}

function clearPermissionTables() {
  const activeKeys = new Set(permissionTableOptions.value.map((item) => item.key));
  selectedPermissionTables.value = selectedPermissionTables.value.filter((key) => !activeKeys.has(key));
  cleanPermissionSelections();
}

async function togglePermissionColumn(key: string) {
  toggleStringSelection(selectedPermissionColumns, key);
  cleanPermissionSelections();
  if (selectedPermissionColumns.value.includes(key)) {
    permissionActiveColumnKey.value = key;
    await loadPermissionValues(true);
  }
}

async function activatePermissionColumn(key: string) {
  if (!selectedPermissionColumns.value.includes(key)) {
    selectedPermissionColumns.value = [...selectedPermissionColumns.value, key];
    cleanPermissionSelections();
  }
  permissionActiveColumnKey.value = key;
  await loadPermissionValues(true);
}

async function selectAllPermissionColumns() {
  selectedPermissionColumns.value = Array.from(new Set([...selectedPermissionColumns.value, ...permissionColumnOptions.value.map((item) => item.key)]));
  permissionActiveColumnKey.value = permissionColumnOptions.value[0]?.key || permissionActiveColumnKey.value;
  await loadPermissionValues(true);
}

function clearPermissionColumns() {
  const activeKeys = new Set(permissionColumnOptions.value.map((item) => item.key));
  selectedPermissionColumns.value = selectedPermissionColumns.value.filter((key) => !activeKeys.has(key));
  cleanPermissionSelections();
}

async function loadPermissionValues(reset = false) {
  const active = permissionActiveColumn.value;
  if (!active) return;
  if (reset) {
    permissionValues.value = [];
    permissionValuesOffset.value = 0;
  }
  permissionBusy.value = true;
  try {
    const response = await getPermissionValues(active.datasetId, active.tableName, active.columnName, {
      q: permissionValueSearch.value,
      limit: 100,
      offset: permissionValuesOffset.value
    });
    permissionValues.value = reset ? response.values : Array.from(new Set([...permissionValues.value, ...response.values]));
    permissionValuesOffset.value = response.offset + response.values.length;
    permissionValuesHasMore.value = response.has_more;
  } catch (err) {
    permissionMessage.value = err instanceof Error ? err.message : "授权值读取失败";
  } finally {
    permissionBusy.value = false;
  }
}

function togglePermissionValue(value: string) {
  if (!permissionActiveColumnKey.value) return;
  const current = permissionValueSelections.value[permissionActiveColumnKey.value] || [];
  permissionValueSelections.value = {
    ...permissionValueSelections.value,
    [permissionActiveColumnKey.value]: current.includes(value) ? current.filter((item) => item !== value) : [...current, value]
  };
}

function selectAllPermissionValues() {
  if (!permissionActiveColumnKey.value) return;
  permissionValueSelections.value = {
    ...permissionValueSelections.value,
    [permissionActiveColumnKey.value]: Array.from(new Set([...(permissionValueSelections.value[permissionActiveColumnKey.value] || []), ...permissionValues.value]))
  };
}

function clearPermissionValues() {
  if (!permissionActiveColumnKey.value) return;
  permissionValueSelections.value = {
    ...permissionValueSelections.value,
    [permissionActiveColumnKey.value]: []
  };
}

async function loadSelectedTargetPermissions() {
  if (selectedPermissionTargets.value.length !== 1) {
    permissionMessage.value = selectedPermissionTargets.value.length ? "批量授权模式：保存后会覆盖所选对象的行级权限。" : "";
    return;
  }
  permissionBusy.value = true;
  try {
    const response = await listRowPermissions(permissionMode.value, selectedPermissionTargets.value[0]);
    applyPermissionItems(response.items);
    permissionMessage.value = response.items.length ? "已载入当前对象的权限。" : "当前对象暂无行级权限。";
  } catch (err) {
    permissionMessage.value = err instanceof Error ? err.message : "已有权限读取失败";
  } finally {
    permissionBusy.value = false;
  }
}

async function applyPermissionItems(items: RowPermissionItem[]) {
  const datasetIds = Array.from(new Set(items.map((item) => item.dataset_id).filter((id) => datasets.value.some((dataset) => dataset.id === id))));
  selectedPermissionDatasetIds.value = datasetIds;
  permissionActiveDatasetId.value = datasetIds[0] || "";
  selectedPermissionTables.value = Array.from(new Set(items.map((item) => makePermissionTableKey(item.dataset_id, item.table_name))));
  selectedPermissionColumns.value = Array.from(new Set(items.map((item) => makePermissionColumnKey(item.dataset_id, item.table_name, item.column_name))));
  const selections: Record<string, string[]> = {};
  for (const item of items) {
    const key = makePermissionColumnKey(item.dataset_id, item.table_name, item.column_name);
    selections[key] = Array.from(new Set([...(selections[key] || []), item.allowed_value]));
  }
  permissionValueSelections.value = selections;
  permissionActiveColumnKey.value = selectedPermissionColumns.value[0] || "";
  await loadPermissionCandidates();
  if (permissionActiveColumnKey.value) await loadPermissionValues(true);
}

function cleanPermissionSelections() {
  const datasetSet = new Set(selectedPermissionDatasetIds.value);
  selectedPermissionTables.value = selectedPermissionTables.value.filter((key) => datasetSet.has(key.split("\u001f")[0]));
  const tableSet = new Set(selectedPermissionTables.value);
  selectedPermissionColumns.value = selectedPermissionColumns.value.filter((key) => {
    const parsed = parsePermissionColumnKey(key);
    return parsed ? tableSet.has(makePermissionTableKey(parsed.datasetId, parsed.tableName)) : false;
  });
  const columnSet = new Set(selectedPermissionColumns.value);
  permissionValueSelections.value = Object.fromEntries(Object.entries(permissionValueSelections.value).filter(([key]) => columnSet.has(key)));
  if (!columnSet.has(permissionActiveColumnKey.value)) {
    permissionActiveColumnKey.value = selectedPermissionColumns.value[0] || "";
    permissionValues.value = [];
  }
}

async function savePermissionRules() {
  if (!permissionSelectedTargetPayload.value.length) {
    permissionMessage.value = "请先选择用户或权限组。";
    return;
  }
  if (!permissionRulePreview.value.length) {
    permissionMessage.value = "请至少选择一个授权值。";
    return;
  }
  permissionBusy.value = true;
  try {
    await saveRowPermissions({ targets: permissionSelectedTargetPayload.value, rules: permissionRulePreview.value });
    permissionMessage.value = "权限已保存。";
    showToast("权限已保存");
  } catch (err) {
    permissionMessage.value = err instanceof Error ? err.message : "权限保存失败";
  } finally {
    permissionBusy.value = false;
  }
}

async function deleteSelectedPermissions() {
  if (!permissionSelectedTargetPayload.value.length) {
    permissionMessage.value = "请先选择用户或权限组。";
    return;
  }
  permissionBusy.value = true;
  try {
    await deleteRowPermissions({ targets: permissionSelectedTargetPayload.value });
    selectedPermissionDatasetIds.value = [];
    permissionActiveDatasetId.value = "";
    selectedPermissionTables.value = [];
    selectedPermissionColumns.value = [];
    permissionValueSelections.value = {};
    permissionValues.value = [];
    permissionMessage.value = "所选对象权限已删除。";
    showToast("权限已删除");
  } catch (err) {
    permissionMessage.value = err instanceof Error ? err.message : "权限删除失败";
  } finally {
    permissionBusy.value = false;
  }
}

async function cancelPermissionEdits() {
  await loadSelectedTargetPermissions();
}

function syncEditForm() {
  if (!selectedDataset.value) {
    editForm.name = "";
    editForm.short_code = "";
    return;
  }
  editForm.name = selectedDataset.value.name;
  editForm.short_code = selectedDataset.value.short_code;
}

async function handleFileUpload(kind: "csv" | "excel", event: Event) {
  const input = event.target as HTMLInputElement;
  const file = input.files?.[0];
  input.value = "";
  if (!file) return;
  await guarded(async () => {
    lastImportResult.value = "";
    setImportProgress("文件上传", 0);
    const response = await uploadDatasetWithProgress(kind, file, (progress) => {
      setImportProgress(`文件上传 ${progress.percent}%`, progress.percent);
      if (progress.percent >= 100) {
        setImportProgress("数据解析、Schema 读取、数据集保存", 100, true);
      }
    });
    setImportProgress("处理完成", 100);
    selectedDatasetId.value = response.dataset.id;
    await refreshDatasets(response.dataset.id);
    await onDatasetChange();
    activePage.value = "datasets";
    lastImportResult.value = response.removed.length
      ? `导入完成：${response.dataset.name}；已清理：${response.removed.join("、")}`
      : `导入完成：${response.dataset.name}`;
    status.value = lastImportResult.value;
  }, "导入完成", uploadBusy);
}

async function saveDataset() {
  const dataset = selectedDataset.value;
  if (!dataset) return;
  await guarded(async () => {
    const response = await updateDataset(dataset.id, editForm);
    await refreshDatasets(response.dataset.id);
  }, "数据集信息已保存");
}

async function removeSelectedDataset() {
  if (!selectedDataset.value) return;
  const id = selectedDataset.value.id;
  await guarded(async () => {
    await deleteDataset(id);
    selectedDatasetId.value = "";
    await refreshDatasets("");
    await onDatasetChange();
  }, "数据集已删除");
}

async function submitMySQL() {
  await guarded(async () => {
    const response = await connectMySQL({
      ...mysqlForm,
      port: Number(mysqlForm.port),
      dataset_name: mysqlForm.dataset_name || undefined
    });
    mysqlForm.password = "";
    selectedDatasetId.value = response.dataset.id;
    await refreshDatasets(response.dataset.id);
    await onDatasetChange();
    activePage.value = "datasets";
    lastImportResult.value = response.removed.length
      ? `MySQL Schema 已读取：${response.dataset.name}；已清理：${response.removed.join("、")}`
      : `MySQL Schema 已读取：${response.dataset.name}`;
    status.value = lastImportResult.value;
  }, "MySQL Schema 已读取");
}

function editLLMConfig(config: LLMConfig) {
  llmForm.id = config.id;
  llmForm.name = config.name;
  llmForm.provider_type = config.provider_type;
  llmForm.base_url = config.base_url;
  llmForm.api_key = "";
  llmForm.model_name = config.model_name;
  llmForm.timeout_seconds = config.timeout_seconds;
  llmForm.max_tokens = config.max_tokens;
  llmForm.temperature = config.temperature;
  llmForm.structured_output_mode = config.structured_output_mode;
  llmForm.is_enabled = config.is_enabled;
}

function resetLLMForm() {
  llmForm.id = "";
  llmForm.name = "";
  llmForm.provider_type = "online";
  llmForm.base_url = "";
  llmForm.api_key = "";
  llmForm.model_name = "";
  llmForm.timeout_seconds = 30;
  llmForm.max_tokens = 4000;
  llmForm.temperature = 0;
  llmForm.structured_output_mode = "auto";
  llmForm.is_enabled = true;
}

function llmPayload() {
  return {
    name: llmForm.name,
    provider_type: llmForm.provider_type,
    base_url: llmForm.base_url,
    api_key: llmForm.api_key,
    model_name: llmForm.model_name,
    timeout_seconds: Number(llmForm.timeout_seconds),
    max_tokens: Number(llmForm.max_tokens),
    temperature: Number(llmForm.temperature),
    structured_output_mode: llmForm.structured_output_mode,
    is_enabled: llmForm.is_enabled
  };
}

async function saveLLMConfig() {
  await guarded(async () => {
    if (llmForm.id) {
      await updateLLMConfig(llmForm.id, llmPayload());
    } else {
      await createLLMConfig(llmPayload());
    }
    llmForm.api_key = "";
    await refreshLLMConfigs();
  }, "模型配置已保存", llmBusy);
}

async function removeLLMConfig(configId: string) {
  await guarded(async () => {
    await deleteLLMConfig(configId);
    if (llmForm.id === configId) resetLLMForm();
    await refreshLLMConfigs();
  }, "模型配置已删除", llmBusy);
}

async function chooseLLMConfig(configId: string) {
  await guarded(async () => {
    await selectLLMConfig(configId);
    await refreshLLMConfigs();
  }, "当前模型已选择", llmBusy);
}

async function pingLLMConfig(configId: string) {
  await guarded(async () => {
    await testLLMConfig(configId);
  }, "模型连接测试通过", llmBusy);
}

async function deleteCurrentConversation() {
  if (!currentConversation.value) return;
  const id = currentConversation.value.id;
  await guarded(async () => {
    await removeConversation(id);
    currentConversation.value = null;
    selectedDatasetId.value = "";
    await refreshConversations();
  }, "对话已删除");
}

onMounted(() => {
  initializeWorkspaceByWidth();
  window.addEventListener("resize", updateWorkspaceByWidth);
  window.addEventListener("focus", synchronizeServerState);
  checkAuthSession();
});

watch(
  () => [status.value, error.value],
  ([nextStatus, nextError]) => {
    if (!nextError && nextStatus === "操作失败") return;
    showToast(nextError || nextStatus, Boolean(nextError));
  }
);

watch(fastMatchEnabled, (value) => {
  localStorage.setItem("chatsql.fast_match_enabled", value ? "1" : "0");
});

watch(contextModeEnabled, (value) => {
  const username = authUser.value?.username;
  if (!username) return;
  localStorage.setItem(`chatsql.context_mode_enabled:${username}`, value ? "1" : "0");
  contextModeSessionId.value = value ? crypto.randomUUID() : "";
});

watch(draft, (value) => {
  if (value) closeExampleQuestions();
});

watch(selectedDatasetId, closeExampleQuestions);
watch(selectedDatasetId, closeEntityCandidates);

watch(workspaceWidth, () => {
  if (chartRendered.value) {
    nextTick(() => activeChart.value?.resize());
  }
});

watch(workspaceOpen, (open) => {
  if (!open) return;
  nextTick(() => window.requestAnimationFrame(() => activeChart.value?.resize()));
});

watch(authUser, (user) => {
  if (user) {
    contextModeEnabled.value = localStorage.getItem(`chatsql.context_mode_enabled:${user.username}`) === "1";
    contextModeSessionId.value = contextModeEnabled.value ? crypto.randomUUID() : "";
    void synchronizeServerState();
  } else {
    contextModeEnabled.value = false;
    contextModeSessionId.value = "";
  }
}, { immediate: true });

watch(activePage, (page) => {
  closeMobilePanels();
  if (page === "datasets") void synchronizeServerState();
  if (page === "board") nextTick(renderDashboardCharts);
}, { immediate: true });

watch(
  () => manualBuilder.dataset_id,
  async (datasetId) => {
    if (!datasetId) return;
    if (manualBuilderHydrating.value) return;
    selectedDatasetId.value = datasetId;
    await refreshSchema().catch(() => undefined);
    manualBuilder.table_name = schema.value?.tables?.[0]?.name || "";
    manualBuilder.category_column = schema.value?.tables?.[0]?.columns?.[0]?.name || "";
    manualBuilder.value_columns = [];
    manualBuilder.selected_columns = [];
    manualBuilder.filters = [];
    boardFilterOpen.value = false;
  }
);

watch(
  () => dashboardDynamicDraft.dataset_id,
  (datasetId) => {
    dashboardDynamicDraft.table_name = "";
    dashboardDynamicDraft.column_name = "";
    dashboardDynamicDraft.value = "";
    dashboardDynamicDraft.time_strategy = "latest_date";
    dashboardDynamicDraft.start_date = "";
    dashboardDynamicDraft.end_date = "";
    dashboardDynamicDraft.values = [];
    if (datasetId && datasetId !== selectedDatasetId.value) return;
    dashboardDynamicDraft.table_name = schema.value?.tables?.[0]?.name || "";
  }
);

watch(
  () => dashboardDynamicDraft.table_name,
  () => {
    dashboardDynamicDraft.column_name = dashboardDynamicColumns.value[0]?.name || "";
    dashboardDynamicDraft.value = "";
    dashboardDynamicDraft.time_strategy = "latest_date";
    dashboardDynamicDraft.start_date = "";
    dashboardDynamicDraft.end_date = "";
    dashboardDynamicDraft.values = [];
  }
);

watch(
  () => dashboardDynamicDraft.column_name,
  () => {
    dashboardDynamicDraft.values = [];
    dashboardDynamicDraft.value = "";
    dashboardDynamicDraft.time_strategy = "latest_date";
    dashboardDynamicDraft.start_date = "";
    dashboardDynamicDraft.end_date = "";
    void loadDashboardDynamicValues();
  }
);

watch(
  () => manualBuilder.table_name,
  () => {
    if (manualBuilderHydrating.value) return;
    manualBuilder.category_column = manualColumns.value[0]?.name || "";
    manualBuilder.value_columns = [];
    manualBuilder.selected_columns = [];
    manualBuilder.filters = [];
    boardFilterOpen.value = false;
  }
);

onBeforeUnmount(() => {
  closeEntityCandidates();
  window.removeEventListener("resize", updateWorkspaceByWidth);
  window.removeEventListener("focus", synchronizeServerState);
  stopWorkspaceResize();
  cancelDashboardPointer();
  stopBoardEditorDrag();
  clearToastTimers();
  destroyChart();
  dashboardChartResizeObserver?.disconnect();
  dashboardChartResizeObserver = null;
  dashboardChartContainers.clear();
  dashboardCharts.forEach((chart) => chart.destroy());
});
</script>

<template>
  <main v-if="!authChecked" class="login-shell">
    <section class="login-card">
      <div class="login-brand">
        <h1>ChatSQL</h1>
      </div>
      <p>正在检查登录状态...</p>
    </section>
  </main>
  <main v-else-if="!authUser" class="login-shell">
    <form class="login-card" @submit.prevent="submitLogin">
      <div class="login-brand">
        <h1>ChatSQL</h1>
      </div>
      <label>
        <span>用户名</span>
        <input v-model="loginForm.username" autocomplete="username" autofocus />
      </label>
      <label>
        <span>密码</span>
        <input v-model="loginForm.password" type="password" autocomplete="current-password" />
      </label>
      <p v-if="loginError" class="login-error">{{ loginError }}</p>
      <button type="submit" :disabled="loginBusy || !loginForm.username.trim() || !loginForm.password">
        {{ loginBusy ? "登录中" : "登录" }}
      </button>
    </form>
  </main>
  <main v-else class="app-shell" :class="{ 'dataset-mode': activePage !== 'chat', 'workspace-collapsed': !workspaceOpen, 'workspace-resizing': workspaceResizing }" :style="appShellStyle">
    <Transition name="toast-slide">
      <div v-if="toast.visible" class="toast" :class="toast.kind" role="status" aria-live="polite">
        {{ toast.text }}
      </div>
    </Transition>
    <button
      v-if="mobileNavigationOpen || mobileWorkspaceOpen"
      type="button"
      class="mobile-panel-backdrop"
      aria-label="关闭移动面板"
      @click="closeMobilePanels"
    ></button>
    <button v-if="!mobileNavigationOpen" type="button" class="mobile-panel-trigger mobile-navigation-trigger" aria-label="展开左侧导航" @click="openMobileNavigation">
      <ChevronRight :size="18" />
    </button>
    <button v-if="activePage === 'chat' && !mobileWorkspaceOpen" type="button" class="mobile-panel-trigger mobile-workspace-trigger" aria-label="展开图表与调试面板" @click="openMobileWorkspace">
      <ChevronLeft :size="18" />
    </button>
    <aside class="conversation-rail" :class="{ 'mobile-open': mobileNavigationOpen }">
      <button type="button" class="mobile-panel-close mobile-navigation-close" aria-label="收回左侧导航" @click="closeMobilePanels">
        <ChevronLeft :size="18" />
      </button>
      <div class="brand">
        <h1>ChatSQL</h1>
      </div>
      <button type="button" class="nav-row primary" :disabled="queryBusy" @click="startConversation">
        <MessageSquarePlus :size="17" />
        新建对话
      </button>
      <button type="button" class="nav-row" :class="{ active: activePage === 'board' }" @click="activePage = 'board'; accountMenuOpen = false">
        <LayoutDashboard :size="17" />
        看板
      </button>
      <button type="button" class="nav-row" :class="{ active: activePage === 'datasets' }" @click="activePage = 'datasets'">
        <FileSpreadsheet :size="17" />
        控制与管理
      </button>
      <section class="recent-list">
        <h2>最近对话</h2>
        <div class="recent-scroll">
          <button
            v-for="item in conversations"
            :key="item.id"
            type="button"
            class="conversation-row"
            :class="{ active: activePage === 'chat' && item.id === currentConversation?.id }"
            @click="activePage = 'chat'; accountMenuOpen = false; openConversation(item.id)"
          >
            <span>{{ item.title || "空白对话" }}</span>
          </button>
          <div class="recent-limit-note">最多保存25轮历史对话</div>
          <template v-if="referencedConversations.length">
            <div class="referenced-divider">看板引用对话</div>
            <button
              v-for="item in referencedConversations"
              :key="item.id"
              type="button"
              class="conversation-row referenced"
              :class="{ active: activePage === 'chat' && item.id === currentConversation?.id }"
              @click="activePage = 'chat'; accountMenuOpen = false; openConversation(item.id)"
            >
              <span>{{ item.title || "空白对话" }}</span>
            </button>
          </template>
        </div>
      </section>
      <section class="account-entry">
        <button type="button" class="account-trigger" :class="{ active: accountMenuOpen }" @click="accountMenuOpen = !accountMenuOpen">
          <span class="account-avatar">{{ authUser.username.slice(0, 1).toUpperCase() }}</span>
          <span class="account-meta">
            <strong>{{ authUser.username }}</strong>
            <small>{{ authUser.role }}</small>
          </span>
        </button>
        <div v-if="accountMenuOpen" class="account-menu">
          <button type="button" class="account-menu-row" @click="accountSettingsOpen = !accountSettingsOpen">
            <Settings :size="16" />
            设置
          </button>
          <div v-if="accountSettingsOpen" class="account-settings">
            <label class="inline-check">
              <input v-model="fastMatchEnabled" type="checkbox" />
              快速匹配
            </label>
            <p>优先匹配已验证问题模板，未命中时自动使用原查询流程。</p>
            <label class="inline-check">
              <input v-model="contextModeEnabled" type="checkbox" />
              上下文模式
            </label>
            <p>开启后对明确的多轮追问进行本地补全，未命中时仍执行原查询流程。</p>
          </div>
          <button type="button" class="account-menu-row" @click="logout">
            退出登录
          </button>
        </div>
      </section>
    </aside>

    <section v-if="activePage === 'chat'" class="main-pane">
      <header class="topbar">
        <div class="topbar-controls">
          <label class="dataset-picker">
            <span>当前数据集</span>
            <select v-model="selectedDatasetId" @change="onDatasetChange">
              <option value="">未选择</option>
              <option v-for="item in datasets" :key="item.id" :value="item.id">
                {{ item.short_code }} · {{ item.name }}
              </option>
            </select>
          </label>
          <div class="model-chip">
            <span>当前模型：</span>
            <strong :title="activeLLMConfig ? `${activeLLMConfig.name} / ${activeLLMConfig.model_name}` : '未配置'">{{ activeLLMConfig ? `${activeLLMConfig.name} / ${activeLLMConfig.model_name}` : "未配置" }}</strong>
          </div>
        </div>
        <div class="top-actions">
          <button type="button" class="icon-button" title="刷新" aria-label="刷新对话" :disabled="queryBusy" @click="guarded(() => refreshConversations(), '对话已刷新')">
            <RefreshCcw :size="17" />
          </button>
          <button type="button" class="icon-button danger-icon" title="删除当前对话" aria-label="删除当前对话" :disabled="!currentConversation || queryBusy" @click="deleteCurrentConversation">
            <Trash2 :size="17" />
          </button>
        </div>
      </header>

      <div ref="chatArea" class="chat-scroll">
        <div v-if="!renderedTurns.length" class="empty-chat">
          <strong>空白对话</strong>
          <span>请选择数据集后输入问题</span>
        </div>
        <article
          v-for="turn in renderedTurns"
          :key="turn.turn_id"
          class="turn-block"
        >
          <div class="message user">
            <div class="bubble">{{ turn.user_message.content }}</div>
          </div>
          <div v-if="turn.loading_status && !turn.result_tables.length" class="turn-status">
            <span class="loading-dot"></span>
            {{ turn.loading_status }}
          </div>
          <section v-if="turn.result_tables.length" class="result-tables in-message">
            <article v-for="table in turn.result_tables" :key="table.task_id" class="result-table">
              <header>
                <strong>{{ table.purpose || table.task_id }}</strong>
                <span>{{ table.row_count }} 行</span>
              </header>
              <div class="result-actions">
                <details class="sql-fold result-action-sql">
                  <summary>
                    <Code2 :size="14" />
                    查看SQL
                  </summary>
                  <pre>{{ sqlByTaskId.get(table.task_id)?.after || sqlByTaskId.get(table.task_id)?.before || "暂无 SQL" }}</pre>
                  <button type="button" class="small-tool-button" @click="copyText(sqlByTaskId.get(table.task_id)?.after || sqlByTaskId.get(table.task_id)?.before || '')">
                    <Clipboard :size="14" />
                    复制SQL
                  </button>
                </details>
                <button type="button" class="small-tool-button result-action-chart" @click="useChartTable(turn.assistant_message_id, table)">
                  <BarChart3 :size="14" />
                  生成图表
                </button>
                <button type="button" class="small-tool-button result-action-export" @click="exportTable(table)">
                  <Download :size="14" />
                  导出结果
                </button>
                <button type="button" class="small-tool-button result-action-copy" @click="copyTable(table)">
                  <Clipboard :size="14" />
                  复制数据
                </button>
              </div>
              <div class="table-scroll">
                <table>
                  <thead>
                    <tr>
                      <th v-for="column in table.columns" :key="column">{{ column }}</th>
                    </tr>
                  </thead>
                  <tbody>
                    <tr v-for="(row, rowIndex) in table.rows" :key="rowIndex">
                      <td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ displayCell(cell) }}</td>
                    </tr>
                  </tbody>
                </table>
              </div>
            </article>
          </section>
          <div v-if="turn.loading_status && turn.result_tables.length" class="turn-status after-tables">
            <span class="loading-dot"></span>
            {{ turn.loading_status }}
          </div>
          <div v-if="turn.final_answer" class="message assistant">
            <div class="answer-block">
              <div class="bubble">{{ turn.final_answer }}</div>
            </div>
          </div>
          <div v-if="turn.error_status" class="turn-error">{{ turn.error_status }}</div>
        </article>
      </div>

      <form class="composer" @submit.prevent="submitQuestion">
        <div class="composer-input">
          <div v-if="entityCandidatesOpen" ref="entityCandidatesPanel" class="entity-candidates" role="listbox" aria-label="业务实体候选">
            <button
              v-for="(candidate, index) in entityCandidates"
              :key="`${candidate.type}:${candidate.code}`"
              type="button"
              role="option"
              data-entity-option
              :class="{ active: activeEntityCandidateIndex === index }"
              :aria-selected="activeEntityCandidateIndex === index"
              @mouseenter="activeEntityCandidateIndex = index"
              @mousedown.prevent="selectEntityCandidate(candidate)"
            >
              <span class="entity-candidate-type">{{ candidate.type === "organization" ? "机构" : "指标" }}</span>
              <span class="entity-candidate-name">{{ candidate.name }}</span>
              <span class="entity-candidate-code">{{ candidate.code }}</span>
            </button>
            <div v-if="entityCandidatesHasMore" class="entity-candidate-limit-note">最多显示10项待选</div>
          </div>
          <div v-else-if="exampleQuestionsOpen && supportsDatasetExampleQuestions" class="example-questions" role="listbox" aria-label="示例问题">
            <button
              v-for="(question, index) in selectedExampleQuestions"
              :key="question"
              type="button"
              role="option"
              @mousedown.prevent="selectExampleQuestion(question)"
            >
              <span class="example-question-index">{{ index + 1 }}</span>
              <span class="example-question-text">{{ question }}</span>
            </button>
          </div>
          <textarea
            ref="composerInput"
            v-model="draft"
            rows="2"
            placeholder="输入问题"
            @click="handleComposerClick"
            @focus="openExampleQuestions"
            @input="scheduleEntityCandidates"
            @blur="closeComposerPopovers"
            @keyup.left="scheduleEntityCandidates"
            @keyup.right="scheduleEntityCandidates"
            @keydown="handleComposerKeydown"
          ></textarea>
        </div>
        <div class="composer-actions">
          <label class="thinking-switch" title="关闭时后端发送 thinking disabled；开启时不发送 thinking 字段">
            <input v-model="thinkingModeEnabled" type="checkbox" :disabled="queryBusy" />
            <span></span>
            思考模式
          </label>
          <button v-if="!queryBusy" type="submit" :disabled="!draft.trim()">
            <Send :size="17" />
            发送
          </button>
          <button v-else type="button" class="danger-button" @click="stopQuestion">
            <StopCircle :size="17" />
            停止
          </button>
        </div>
      </form>
    </section>

    <section v-else-if="activePage === 'board'" ref="boardPageRef" class="dataset-page board-page">
      <header class="board-toolbar">
        <div class="board-title">
          <h2>{{ currentDashboard?.name || "看板" }}</h2>
          <span>{{ dashboardMode === "edit" ? "编辑模式" : "预览模式" }}</span>
        </div>
        <select :value="currentDashboard?.id || ''" @change="openDashboard(($event.target as HTMLSelectElement).value)">
          <option value="">选择看板</option>
          <option v-for="item in dashboards" :key="item.id" :value="item.id">{{ item.name }} · {{ item.card_count }}</option>
        </select>
        <button type="button" @click="createNewDashboard">新建看板</button>
        <button type="button" :disabled="!currentDashboard" @click="renameCurrentDashboard">重命名</button>
        <button type="button" :disabled="!currentDashboard" @click="dashboardMode = dashboardMode === 'edit' ? 'preview' : 'edit'">{{ dashboardMode === "edit" ? "预览" : "编辑" }}</button>
        <button type="button" :disabled="!currentDashboard" @click="showToast('看板已保存')">
          <Save :size="15" />
          保存
        </button>
        <button type="button" :disabled="!currentDashboard || dashboardBusy" @click="refreshCurrentDashboard">
          <RefreshCcw :size="15" />
          刷新全部
        </button>
        <button type="button" class="danger-button" :disabled="!currentDashboard" @click="removeCurrentDashboard">删除</button>
      </header>

      <section v-if="currentDashboard" class="board-dynamic-strip panel">
        <strong>动态条件</strong>
        <span v-if="!dashboardDynamicParameters.length" class="dynamic-empty">未配置</span>
        <label v-for="parameter in dashboardDynamicParameters.slice(0, 3)" :key="parameter.id">
          <span>{{ dynamicParameterLabel(parameter) }}</span>
          <select
            :value="dashboardParameterControlValue(parameter)"
            @focus="prepareDashboardParameterValues(parameter)"
            @change="saveDashboardParameterControl(parameter, ($event.target as HTMLSelectElement).value)"
          >
            <option value="">不筛选</option>
            <template v-if="isTimeDynamicParameter(parameter)">
              <option v-for="option in TIME_POLICY_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
            </template>
            <template v-else>
              <option v-for="value in dynamicValuesForParameter(parameter)" :key="value" :value="value">{{ value }}</option>
              <option v-if="dashboardParameterValue(parameter) && !dynamicValuesForParameter(parameter).includes(dashboardParameterValue(parameter))" :value="dashboardParameterValue(parameter)">{{ dashboardParameterValue(parameter) }}</option>
            </template>
          </select>
        </label>
        <button type="button" class="icon-button compact board-settings-button" title="动态条件设置" :class="{ active: boardDynamicSettingsOpen }" @click="boardDynamicSettingsOpen = !boardDynamicSettingsOpen">
          <Settings :size="15" />
        </button>
        <section v-if="boardDynamicSettingsOpen" class="board-dynamic-settings panel">
          <label>
            <span>数据集</span>
            <select v-model="dashboardDynamicDraft.dataset_id">
              <option value="">选择数据集</option>
              <option v-for="item in datasets.filter((dataset) => dataset.status === 'ready')" :key="item.id" :value="item.id">{{ item.short_code }} · {{ item.name }}</option>
            </select>
          </label>
          <label>
            <span>数据表</span>
            <select v-model="dashboardDynamicDraft.table_name">
              <option value="">选择表</option>
              <option v-for="table in dashboardTables" :key="table.name" :value="table.name">{{ table.name }}</option>
            </select>
          </label>
          <label>
            <span>字段</span>
            <select v-model="dashboardDynamicDraft.column_name">
              <option value="">选择字段</option>
              <option v-for="column in dashboardDynamicColumns" :key="column.name" :value="column.name">{{ column.name }}</option>
            </select>
          </label>
          <label>
            <span>显示名</span>
            <input v-model="dashboardDynamicDraft.name" placeholder="默认使用字段名" />
          </label>
          <label>
            <span>{{ isDashboardDynamicDraftTime() ? '默认时间策略' : '默认值' }}</span>
            <select v-if="isDashboardDynamicDraftTime()" v-model="dashboardDynamicDraft.time_strategy">
              <option value="">不筛选</option>
              <option v-for="option in TIME_POLICY_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
            </select>
            <select v-else :disabled="dashboardDynamicDraft.loadingValues || !dashboardDynamicDraft.column_name" v-model="dashboardDynamicDraft.value" @focus="loadDashboardDynamicValues">
              <option value="">不筛选</option>
              <option v-for="value in dashboardDynamicDraft.values" :key="value" :value="value">{{ value }}</option>
            </select>
          </label>
          <label v-if="isDashboardDynamicDraftTime() && dashboardDynamicDraft.time_strategy === 'custom_range'">
            <span>起始日期</span>
            <input type="date" v-model="dashboardDynamicDraft.start_date" />
          </label>
          <label v-if="isDashboardDynamicDraftTime() && dashboardDynamicDraft.time_strategy === 'custom_range'">
            <span>结束日期</span>
            <input type="date" v-model="dashboardDynamicDraft.end_date" />
          </label>
          <button type="button" class="secondary-tool" :disabled="dashboardDynamicParameters.length >= 3 || dashboardDynamicDraftInvalid" @click="addDashboardDynamicParameter">添加</button>
          <button type="button" class="ghost-icon" title="关闭" @click="boardDynamicSettingsOpen = false"><X :size="14" /></button>
          <small v-if="dashboardDynamicParameters.length >= 3">每个看板最多 3 个动态条件。</small>
          <div v-if="dashboardDynamicParameters.length" class="dynamic-existing">
            <button v-for="parameter in dashboardDynamicParameters" :key="parameter.id" type="button" :title="`${dynamicParameterTypeLabel(parameter)} · 删除动态条件`" @click="removeDashboardDynamicParameter(parameter)">
              <X :size="12" />
              <span>{{ dynamicParameterLabel(parameter) }}</span>
            </button>
          </div>
          <div v-if="dashboardDynamicParameters.some((parameter) => isTimeDynamicParameter(parameter))" class="dynamic-parameter-settings">
            <div v-for="parameter in dashboardDynamicParameters.filter((item) => isTimeDynamicParameter(item))" :key="`time-${parameter.id}`" class="dynamic-parameter-row">
              <strong>{{ dynamicParameterLabel(parameter) }}</strong>
              <label>
                <span>时间策略</span>
                <select :value="parameter.time_strategy || ''" @change="saveDashboardParameterControl(parameter, ($event.target as HTMLSelectElement).value)">
                  <option value="">不筛选</option>
                  <option v-for="option in TIME_POLICY_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
                </select>
              </label>
              <label v-if="parameter.time_strategy === 'custom_range'">
                <span>起始日期</span>
                <input type="date" :value="parameter.start_date || ''" @change="saveDashboardDynamicParameter(parameter, { start_date: ($event.target as HTMLInputElement).value }, true)" />
              </label>
              <label v-if="parameter.time_strategy === 'custom_range'">
                <span>结束日期</span>
                <input type="date" :value="parameter.end_date || ''" @change="saveDashboardDynamicParameter(parameter, { end_date: ($event.target as HTMLInputElement).value }, true)" />
              </label>
            </div>
          </div>
        </section>
      </section>

      <div class="board-layout" :class="{ 'tools-open': boardToolsOpen, 'preview-mode': dashboardMode === 'preview' }">
        <aside v-if="dashboardMode === 'edit'" class="board-tools panel" :class="{ open: boardToolsOpen }">
          <div class="board-tools-head">
            <h3>{{ manualEditingCardId ? '编辑组件' : '添加组件' }}</h3>
            <button type="button" class="ghost-icon" title="关闭" @click="closeManualBuilder"><X :size="15" /></button>
          </div>
          <div class="board-tool-buttons">
            <button type="button" :class="{ active: manualBuilder.component === 'metric' }" @click="selectManualComponent('metric')">指标卡</button>
            <button type="button" :class="{ active: manualBuilder.component === 'chart' }" @click="selectManualComponent('chart')">柱状图</button>
            <button type="button" :class="{ active: manualBuilder.component === 'line' }" @click="selectManualComponent('line')">折线图</button>
            <button type="button" :class="{ active: manualBuilder.component === 'pie' }" @click="selectManualComponent('pie')">饼图</button>
            <button type="button" :class="{ active: manualBuilder.component === 'table' }" @click="selectManualComponent('table')">表格</button>
            <button type="button" :class="{ active: manualBuilder.component === 'text' }" @click="selectManualComponent('text')">文本说明</button>
          </div>
          <div class="manual-builder">
            <label>
              <span>标题</span>
              <input v-model="manualBuilder.title" />
            </label>
            <label v-if="manualBuilder.component !== 'text'">
              <span>模式</span>
              <select v-model="manualBuilder.refreshMode">
                <option value="static">静态</option>
                <option value="dynamic">动态</option>
              </select>
            </label>
            <label v-if="manualBuilder.component === 'metric'">
              <span>小数位</span>
              <select v-model="manualBuilder.metricDecimals">
                <option value="none">不保留小数</option>
                <option value="2">保留 2 位小数</option>
              </select>
            </label>
            <label v-if="manualBuilder.component !== 'text'">
              <span>数据集</span>
              <select v-model="manualBuilder.dataset_id">
                <option value="">请选择</option>
                <option v-for="item in datasets.filter((dataset) => dataset.status === 'ready')" :key="item.id" :value="item.id">{{ item.short_code }} · {{ item.name }}</option>
              </select>
            </label>
            <label v-if="manualBuilder.component !== 'text'">
              <span>数据表</span>
              <select v-model="manualBuilder.table_name">
                <option value="">请选择</option>
                <option v-for="table in dashboardTables" :key="table.name" :value="table.name">{{ table.name }}</option>
              </select>
            </label>
            <label v-if="!['text', 'metric', 'table'].includes(manualBuilder.component)">
              <span>分类字段</span>
              <select v-model="manualBuilder.category_column">
                <option value="">无</option>
                <option v-for="column in manualColumns" :key="column.name" :value="column.name">{{ column.name }}</option>
              </select>
            </label>
            <label v-if="manualBuilder.component !== 'text'">
              <span>聚合方式</span>
              <select v-model="manualBuilder.aggregate">
                <option value="sum">SUM</option>
                <option value="avg">AVG</option>
                <option value="max">MAX</option>
                <option value="min">MIN</option>
                <option value="count">COUNT</option>
                <option value="count_distinct">COUNT DISTINCT</option>
                <option value="none">不聚合</option>
              </select>
            </label>
            <div v-if="manualBuilder.component !== 'text' && manualBuilder.component !== 'table'" class="chart-fieldset">
              <span>数值字段</span>
              <label v-for="column in manualNumericColumns.length ? manualNumericColumns : manualColumns" :key="column.name" class="chart-check">
                <input type="checkbox" :checked="manualBuilder.value_columns.includes(column.name)" @change="toggleManualValueColumn(column.name)" />
                <span>{{ column.name }}</span>
              </label>
            </div>
            <div v-if="manualBuilder.component === 'table'" class="chart-fieldset">
              <span>表格字段</span>
              <label v-for="column in manualColumns" :key="column.name" class="chart-check">
                <input type="checkbox" :checked="manualBuilder.selected_columns.includes(column.name)" @change="toggleManualSelectedColumn(column.name)" />
                <span>{{ column.name }}</span>
              </label>
            </div>
            <button v-if="manualBuilder.component !== 'text'" type="button" class="secondary-tool filter-config-button" @click="boardFilterOpen = true">
              筛选条件 · {{ manualBuilder.filters.length }}
            </button>
            <label v-if="manualBuilder.component === 'text'">
              <span>文本说明</span>
              <textarea v-model="manualBuilder.text" rows="3"></textarea>
            </label>
            <p v-if="manualBuilderIssue" class="manual-builder-issue">{{ manualBuilderIssue }}</p>
            <button type="button" class="primary-tool manual-submit" :disabled="Boolean(manualBuilderIssue) || dashboardBusy" @click="addManualCard(manualBuilder.component)">
              {{ manualEditingCardId ? '保存修改' : '确定添加' }}
            </button>
          </div>
        </aside>
        <aside v-if="dashboardMode === 'edit' && boardToolsOpen && boardFilterOpen" class="board-filter-panel panel">
          <div class="board-tools-head">
            <h3>筛选条件</h3>
            <button type="button" class="ghost-icon" title="关闭筛选" @click="boardFilterOpen = false"><X :size="15" /></button>
          </div>
          <div class="filter-list">
            <div v-for="(filter, index) in manualBuilder.filters" :key="index" class="filter-row" :class="{ linked: manualFilterUsesGlobal(filter), unlinked: !manualFilterUsesGlobal(filter) }">
              <button type="button" class="filter-remove" title="删除筛选条件" @click="removeManualFilter(index)"><X :size="12" /></button>
              <select :value="filter.column" @change="updateManualFilterColumn(index, ($event.target as HTMLSelectElement).value)">
                <option value="">字段</option>
                <option v-for="column in manualColumns" :key="column.name" :value="column.name">{{ column.name }}</option>
              </select>
              <p v-if="manualFilterUsesGlobal(filter)" class="filter-policy-note">跟随顶部动态条件</p>
              <select v-else-if="isManualFilterDateColumn(filter)" :value="manualFilterTimeStrategy(filter)" @change="updateManualFilterTimeStrategy(index, ($event.target as HTMLSelectElement).value)">
                <option v-for="option in TIME_POLICY_OPTIONS" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
              <select v-else :value="filter.operator" @change="updateManualFilterOperator(index, ($event.target as HTMLSelectElement).value)">
                <option v-for="option in filterOperatorOptions(filter.column)" :key="option.value" :value="option.value">{{ option.label }}</option>
              </select>
              <template v-if="!manualFilterUsesGlobal(filter) && isManualFilterDateColumn(filter) && manualFilterTimeStrategy(filter) === 'custom_range'">
                <input v-model="filter.value" :type="filterValueInputType(filter.column, 'between')" placeholder="起始日期" />
                <input v-model="filter.value_to" :type="filterValueInputType(filter.column, 'between')" placeholder="结束日期" />
              </template>
              <p v-else-if="!manualFilterUsesGlobal(filter) && isManualFilterDateColumn(filter)" class="filter-policy-note">按快捷日期刷新</p>
              <template v-else-if="!manualFilterUsesGlobal(filter) && filter.operator === 'between'">
                <input v-model="filter.value" :type="filterValueInputType(filter.column, filter.operator)" placeholder="起始值" />
                <input v-model="filter.value_to" :type="filterValueInputType(filter.column, filter.operator)" placeholder="结束值" />
              </template>
              <input v-else-if="!manualFilterUsesGlobal(filter)" v-model="filter.value" :type="filterValueInputType(filter.column, filter.operator)" placeholder="值，IN 用逗号分隔" />
              <button
                type="button"
                class="filter-global-link"
                :class="{ active: manualFilterUsesGlobal(filter) }"
                :title="manualFilterUsesGlobal(filter) ? '跟随顶部动态条件' : '链接顶部动态条件'"
                :aria-pressed="manualFilterUsesGlobal(filter)"
                @click="toggleManualFilterGlobalLink(index)"
              >
                <Link2 :size="13" />
              </button>
            </div>
            <p v-if="!manualBuilder.filters.length" class="empty-small">暂无筛选条件，多条条件默认使用 AND。</p>
            <button type="button" class="secondary-tool" @click="addManualFilter">新增条件</button>
          </div>
        </aside>

        <main class="board-main">
          <div v-if="!currentDashboard" class="board-empty">
            <LayoutDashboard :size="34" />
            <strong>还没有看板</strong>
            <span>点击“新建看板”，或从智能问数图表加入看板。</span>
          </div>
          <div v-else-if="!currentDashboard.cards.length" class="board-empty">
            <LayoutDashboard :size="34" />
            <strong>空白看板</strong>
            <span>从智能问数加入图表，或点击下方添加基础组件。</span>
          </div>
          <div v-else ref="dashboardCanvas" class="board-canvas" :class="{ preview: dashboardMode === 'preview' }">
            <div
              v-if="dashboardDrag?.mode === 'move'"
              class="board-drop-hint"
              :class="{ invalid: !dashboardDrag.targetValid }"
              :style="layoutGridStyle(dashboardDrag.targetLayout)"
            ></div>
            <article
              v-for="card in currentDashboard.cards"
              :key="card.id"
              class="board-card"
              :class="{ selected: selectedDashboardCardId === card.id, 'dragging-placeholder': dashboardDrag?.cardId === card.id && dashboardDrag.mode === 'move', 'drag-invalid': dashboardDrag?.cardId === card.id && !dashboardDrag.targetValid }"
              :style="dashboardCardStyle(card)"
              @click="selectDashboardCard(card)"
            >
              <header :class="{ titleless: !shouldShowCardTopTitle(card) }" @pointerdown="startDashboardPointer($event, card, 'move')">
                <strong v-if="shouldShowCardTopTitle(card)">{{ card.title }}</strong>
                <span v-if="card.error_message">{{ card.error_message }}</span>
              </header>
              <div class="board-card-body" @dblclick.stop="openDashboardCardEditor(card)">
                <p v-if="card.card_type === 'text'" :style="{ textAlign: card.query.align || 'left' }">{{ card.query.text || card.title }}</p>
                <div v-else-if="card.card_type === 'metric'" class="metric-value">{{ formatMetricValue(card) }}</div>
                <div v-else-if="card.card_type === 'table'" class="mini-table">
                  <table>
                    <thead><tr><th v-for="column in tableFromCard(card)?.columns || []" :key="column">{{ column }}</th></tr></thead>
                    <tbody><tr v-for="(row, index) in (tableFromCard(card)?.rows || []).slice(0, 20)" :key="index"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ displayCell(cell) }}</td></tr></tbody>
                  </table>
                </div>
                <canvas v-else :ref="(el) => setDashboardCanvas(card.id, el as Element | null)"></canvas>
              </div>
              <button v-if="dashboardMode === 'edit'" type="button" class="resize-handle" @dblclick.stop @pointerdown.stop="startDashboardPointer($event, card, 'resize')"></button>
            </article>
          </div>
          <article
            v-if="dashboardDrag?.mode === 'move' && dashboardDragCard"
            class="board-card board-drag-layer"
            :class="{ 'drag-invalid': !dashboardDrag.targetValid }"
            :style="dashboardDragLayerStyle()"
          >
            <header :class="{ titleless: !shouldShowCardTopTitle(dashboardDragCard) }">
              <strong v-if="shouldShowCardTopTitle(dashboardDragCard)">{{ dashboardDragCard.title }}</strong>
              <span v-if="dashboardDragCard.error_message">{{ dashboardDragCard.error_message }}</span>
            </header>
            <div class="board-card-body">
              <p v-if="dashboardDragCard.card_type === 'text'" :style="{ textAlign: dashboardDragCard.query.align || 'left' }">{{ dashboardDragCard.query.text || dashboardDragCard.title }}</p>
              <div v-else-if="dashboardDragCard.card_type === 'metric'" class="metric-value">{{ formatMetricValue(dashboardDragCard) }}</div>
              <div v-else-if="dashboardDragCard.card_type === 'table'" class="mini-table">
                <table>
                  <thead><tr><th v-for="column in tableFromCard(dashboardDragCard)?.columns || []" :key="column">{{ column }}</th></tr></thead>
                  <tbody><tr v-for="(row, index) in (tableFromCard(dashboardDragCard)?.rows || []).slice(0, 8)" :key="index"><td v-for="(cell, cellIndex) in row" :key="cellIndex">{{ displayCell(cell) }}</td></tr></tbody>
                </table>
              </div>
              <div v-else class="board-drag-chart-placeholder">图表卡片</div>
            </div>
          </article>
          <button v-if="dashboardMode === 'edit'" type="button" class="board-add-zone" @click="openManualBuilder">
            <span>＋</span>
            <strong>添加组件</strong>
          </button>
        </main>

        <aside
          v-if="dashboardMode === 'edit' && boardEditorVisible"
          class="board-editor panel"
          :style="{ left: `${boardEditorPosition.x}px`, top: `${boardEditorPosition.y}px` }"
        >
          <header class="board-editor-head" @pointerdown="startBoardEditorDrag">
            <h3>编辑卡片</h3>
            <button type="button" class="board-icon-action" :class="{ active: boardEditorPinned }" :title="boardEditorPinned ? '取消钉选' : '钉选'" @pointerdown.stop @click.stop="toggleBoardEditorPin">
              <Pin :size="14" />
            </button>
            <button type="button" class="board-icon-action" title="关闭" @pointerdown.stop @click.stop="closeBoardEditor">
              <X :size="15" />
            </button>
          </header>
          <div v-if="!selectedDashboardCard" class="empty-small">请选择一个卡片。</div>
          <template v-else>
            <label>
              <span>标题</span>
              <input :value="selectedDashboardCard.title" @change="saveDashboardCard(selectedDashboardCard, { title: ($event.target as HTMLInputElement).value })" />
            </label>
            <label v-if="selectedDashboardCard.card_type !== 'text'">
              <span>模式</span>
              <select :value="cardUiMode(selectedDashboardCard)" @change="saveDashboardRefreshMode(selectedDashboardCard, ($event.target as HTMLSelectElement).value)">
                <option value="static">静态</option>
                <option value="dynamic">动态</option>
              </select>
            </label>
            <label v-if="selectedDashboardCard.card_type === 'metric'">
              <span>小数位</span>
              <select :value="selectedDashboardCard.chart_config.metricDecimals || 'none'" @change="saveDashboardChartOption(selectedDashboardCard, 'metricDecimals', ($event.target as HTMLSelectElement).value)">
                <option value="none">不保留小数</option>
                <option value="2">保留 2 位小数</option>
              </select>
            </label>
            <div class="board-editor-actions compact">
              <button type="button" @click="openManualBuilderForCard(selectedDashboardCard)">组件设置</button>
            </div>
            <label v-if="selectedDashboardCard.card_type === 'chart'">
              <span>图表类型</span>
              <select :value="selectedDashboardCard.chart_config.type || 'column_clustered'" @change="saveDashboardCard(selectedDashboardCard, { chart_config: { ...selectedDashboardCard.chart_config, type: ($event.target as HTMLSelectElement).value } })">
                <option v-for="item in chartTypeOptions.filter((option) => ['column_clustered','column_stacked','bar_horizontal','line','pie','area'].includes(option.value))" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <div v-if="selectedDashboardCard.card_type === 'chart'" class="board-editor-grid">
              <label class="chart-inline-check">
                <input type="checkbox" :checked="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).showTitle" @change="saveDashboardChartOption(selectedDashboardCard, 'showTitle', ($event.target as HTMLInputElement).checked)" />
                <span>显示标题</span>
              </label>
              <label>
                <span>标题位置</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).titlePosition" @change="saveDashboardChartOption(selectedDashboardCard, 'titlePosition', ($event.target as HTMLSelectElement).value)">
                  <option value="card_top">卡片顶部</option>
                  <option value="chart_inner">图表内部顶部</option>
                </select>
              </label>
              <label>
                <span>分类字段</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).categoryColumn" @change="saveDashboardChartOption(selectedDashboardCard, 'categoryColumn', ($event.target as HTMLSelectElement).value)">
                  <option value="">请选择</option>
                  <option v-for="field in dashboardCardCategoryFields(selectedDashboardCard)" :key="field.name" :value="field.name">{{ field.name }}</option>
                </select>
              </label>
              <label>
                <span>图例</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).legendMode" @change="saveDashboardChartOption(selectedDashboardCard, 'legendMode', ($event.target as HTMLSelectElement).value)">
                  <option value="auto">智能</option>
                  <option value="show">显示</option>
                  <option value="hide">隐藏</option>
                </select>
              </label>
              <label>
                <span>位置</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).legendPosition" @change="saveDashboardChartOption(selectedDashboardCard, 'legendPosition', ($event.target as HTMLSelectElement).value)">
                  <option value="top">顶部</option>
                  <option value="bottom">底部</option>
                  <option value="left">左侧</option>
                  <option value="right">右侧</option>
                </select>
              </label>
              <label>
                <span>标签</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).dataLabelMode" @change="saveDashboardChartOption(selectedDashboardCard, 'dataLabelMode', ($event.target as HTMLSelectElement).value)">
                  <option value="auto">智能</option>
                  <option value="show">显示</option>
                  <option value="hide">隐藏</option>
                </select>
              </label>
              <label>
                <span>排序</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).sortMode" @change="saveDashboardChartOption(selectedDashboardCard, 'sortMode', ($event.target as HTMLSelectElement).value)">
                  <option value="original">原顺序</option>
                  <option value="asc">升序</option>
                  <option value="desc">降序</option>
                </select>
              </label>
              <label>
                <span>筛选</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).limitMode" @change="saveDashboardChartOption(selectedDashboardCard, 'limitMode', ($event.target as HTMLSelectElement).value)">
                  <option value="none">不限制</option>
                  <option value="top">Top N</option>
                  <option value="bottom">Bottom N</option>
                </select>
              </label>
              <label v-if="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).limitMode !== 'none'">
                <span>N</span>
                <input :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).limitCount" type="number" min="1" max="100" @change="saveDashboardChartOption(selectedDashboardCard, 'limitCount', Number(($event.target as HTMLInputElement).value) || 10)" />
              </label>
              <label>
                <span>单位</span>
                <input :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).unitLabel" @change="saveDashboardChartOption(selectedDashboardCard, 'unitLabel', ($event.target as HTMLInputElement).value)" />
              </label>
              <label>
                <span>配色</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).colorScheme" @change="saveDashboardChartOption(selectedDashboardCard, 'colorScheme', ($event.target as HTMLSelectElement).value)">
                  <option value="morandi">灰蓝</option>
                  <option value="sage">灰绿</option>
                  <option value="slate">雾蓝</option>
                  <option value="warm">灰橙</option>
                </select>
              </label>
              <label v-if="['line','area'].includes(normalizeDashboardChartConfig(selectedDashboardCard.chart_config).type)" class="chart-inline-check">
                <input type="checkbox" :checked="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).lineSmooth" @change="saveDashboardChartOption(selectedDashboardCard, 'lineSmooth', ($event.target as HTMLInputElement).checked)" />
                <span>平滑</span>
              </label>
              <label v-if="['line','area'].includes(normalizeDashboardChartConfig(selectedDashboardCard.chart_config).type)" class="chart-inline-check">
                <input type="checkbox" :checked="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).areaFill" @change="saveDashboardChartOption(selectedDashboardCard, 'areaFill', ($event.target as HTMLInputElement).checked)" />
                <span>面积</span>
              </label>
              <label v-if="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).type === 'pie'">
                <span>样式</span>
                <select :value="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).pieMode" @change="saveDashboardChartOption(selectedDashboardCard, 'pieMode', ($event.target as HTMLSelectElement).value)">
                  <option value="doughnut">环形</option>
                  <option value="pie">饼图</option>
                </select>
              </label>
            </div>
            <div v-if="selectedDashboardCard.card_type === 'chart'" class="chart-fieldset board-chart-fields">
              <span>数值字段</span>
              <label v-for="field in dashboardCardNumericFields(selectedDashboardCard)" :key="field.name" class="chart-check">
                <input type="checkbox" :checked="normalizeDashboardChartConfig(selectedDashboardCard.chart_config).numericColumns.includes(field.name)" @change="toggleDashboardNumericColumn(selectedDashboardCard, field.name)" />
                <span>{{ field.name }}</span>
              </label>
              <small v-if="!dashboardCardNumericFields(selectedDashboardCard).length">当前快照没有可用数值列。</small>
            </div>
            <div class="board-editor-actions">
              <button type="button" @click="refreshOneCard(selectedDashboardCard)">刷新</button>
              <button type="button" @click="duplicateDashboardCard(selectedDashboardCard)">复制</button>
              <button type="button" class="danger-button" @click="removeDashboardCard(selectedDashboardCard)">删除</button>
            </div>
          </template>
        </aside>
      </div>
    </section>

    <section v-else class="dataset-page">
      <header class="page-header">
        <div>
          <h2>控制与管理</h2>
          <p>导入结果、数据集管理、大模型选择和Schema预览</p>
        </div>
        <button type="button" class="icon-button" title="刷新" aria-label="刷新数据集" :disabled="datasetBusy" @click="guarded(() => refreshDatasets(selectedDatasetId), '数据集已刷新')">
          <RefreshCcw :size="17" />
        </button>
      </header>

      <div class="dataset-workspace">
        <div class="dashboard-left">
          <section class="panel data-panel">
            <div class="panel-title">
              <FileSpreadsheet :size="18" />
              <h2>导入与管理</h2>
            </div>
            <div v-if="lastImportResult" class="import-result">{{ lastImportResult }}</div>
            <div v-if="importProgress.visible" class="import-progress" :class="{ indeterminate: importProgress.indeterminate }">
              <div class="import-progress-head">
                <span>{{ importProgress.step }}</span>
                <span v-if="!importProgress.indeterminate">{{ importProgress.percent }}%</span>
              </div>
              <div class="import-progress-track">
                <div class="import-progress-bar" :style="{ width: `${importProgress.percent}%` }"></div>
              </div>
            </div>
            <label class="dataset-picker wide-picker">
              <span>当前数据集</span>
              <select v-model="selectedDatasetId" @change="onDatasetChange">
                <option value="">未选择</option>
                <option v-for="item in datasets" :key="item.id" :value="item.id">
                  {{ item.short_code }} · {{ item.name }}
                </option>
              </select>
            </label>
            <div class="upload-grid">
              <label class="upload-button">
                <Upload :size="16" />
                Excel
                <input type="file" accept=".xlsx,.xls" @change="handleFileUpload('excel', $event)" />
              </label>
              <label class="upload-button">
                <Upload :size="16" />
                CSV
                <input type="file" accept=".csv,text/csv" @change="handleFileUpload('csv', $event)" />
              </label>
            </div>
            <div class="dataset-edit">
              <input v-model="editForm.name" :disabled="!selectedDataset" placeholder="数据集名称" />
              <input v-model="editForm.short_code" :disabled="!selectedDataset" placeholder="短编号" maxlength="4" />
              <button type="button" :disabled="!selectedDataset || datasetBusy" @click="saveDataset">
                <Save :size="15" />
                保存
              </button>
              <button type="button" class="danger-button" :disabled="!selectedDataset || datasetBusy" @click="removeSelectedDataset">
                <Trash2 :size="15" />
                删除
              </button>
            </div>
            <details class="mysql-box">
              <summary>MySQL Schema 读取</summary>
              <div class="mysql-grid">
                <input v-model="mysqlForm.host" placeholder="主机" />
                <input v-model.number="mysqlForm.port" type="number" min="1" max="65535" placeholder="端口" />
                <input v-model="mysqlForm.username" placeholder="用户名" />
                <input v-model="mysqlForm.password" type="password" placeholder="密码" />
                <input v-model="mysqlForm.database" placeholder="数据库 / Schema" />
                <input v-model="mysqlForm.dataset_name" placeholder="数据集名称（可选）" />
              </div>
              <button type="button" :disabled="datasetBusy" @click="submitMySQL">
                <Database :size="15" />
                读取 Schema
              </button>
            </details>
          </section>
          <section class="panel llm-box">
            <div class="panel-title compact-title">
              <Database :size="16" />
              <h3>LLM 模型配置</h3>
            </div>
            <p class="llm-current">当前模型：{{ activeLLMConfig ? `${activeLLMConfig.name} / ${activeLLMConfig.model_name}` : "未配置" }}</p>
            <div class="llm-list">
              <article v-for="config in llmConfigs" :key="config.id" class="llm-row" :class="{ active: config.is_enabled }">
                <button type="button" @click="editLLMConfig(config)">
                  <strong>{{ config.name }}</strong>
                  <span>{{ config.provider_type }} / {{ config.model_name }}</span>
                  <small>{{ config.base_url }} / {{ config.structured_output_mode }} / Key {{ config.has_api_key ? "已保存" : "未保存" }}</small>
                </button>
                <div class="llm-actions">
                  <button type="button" :disabled="llmBusy" @click="chooseLLMConfig(config.id)">选择</button>
                  <button type="button" :disabled="llmBusy" @click="pingLLMConfig(config.id)">测试</button>
                  <button type="button" class="danger-button" :disabled="llmBusy" @click="removeLLMConfig(config.id)">删除</button>
                </div>
              </article>
            </div>
            <div class="llm-form">
              <label class="form-field field-name">
                <span>配置名称</span>
                <input v-model="llmForm.name" placeholder="配置名称" />
              </label>
              <label class="form-field field-provider">
                <span>接入类型</span>
                <select v-model="llmForm.provider_type">
                  <option value="online">online</option>
                  <option value="local">local</option>
                  <option value="cloud">cloud</option>
                </select>
              </label>
              <label class="form-field field-url">
                <span>Base URL</span>
                <input v-model="llmForm.base_url" placeholder="请输入模型服务的 Base URL" />
              </label>
              <label class="form-field">
                <span>API Key</span>
                <input v-model="llmForm.api_key" type="password" autocomplete="off" placeholder="留空则保留已保存密钥" />
              </label>
              <label class="form-field field-model">
                <span>模型名称</span>
                <input v-model="llmForm.model_name" placeholder="模型名称" />
              </label>
              <label class="form-field field-output">
                <span>输出模式</span>
                <select v-model="llmForm.structured_output_mode">
                  <option value="auto">auto</option>
                  <option value="json_schema">json_schema</option>
                  <option value="json_object">json_object</option>
                  <option value="prompt_json">prompt_json</option>
                </select>
              </label>
              <label class="form-field field-timeout">
                <span>请求超时（秒）</span>
                <input v-model.number="llmForm.timeout_seconds" type="number" min="1" max="300" placeholder="30" />
              </label>
              <label class="form-field field-tokens">
                <span>最大输出 Token</span>
                <input v-model.number="llmForm.max_tokens" type="number" min="128" max="8192" placeholder="4000" />
              </label>
              <label class="form-field field-temperature">
                <span>Temperature</span>
                <input v-model.number="llmForm.temperature" type="number" min="0" max="2" step="0.1" placeholder="0" />
              </label>
              <div class="llm-form-actions">
                <label class="inline-check">
                <input v-model="llmForm.is_enabled" type="checkbox" />
                  启用此模型配置
                </label>
                <button type="button" :disabled="llmBusy" @click="saveLLMConfig">
                  <Save :size="15" />
                  保存模型
                </button>
                <button type="button" :disabled="llmBusy" @click="resetLLMForm">重置</button>
              </div>
            </div>
          </section>
          <section v-if="canManagePermissions" class="panel permission-panel">
            <div class="permission-head">
              <div>
                <h3>权限管理</h3>
                <p>基于当前导入生成的真实 Schema 配置行级权限。</p>
              </div>
              <span v-if="permissionBusy" class="permission-badge">处理中</span>
            </div>

            <div class="permission-mode">
              <button type="button" :class="{ active: permissionMode === 'user' }" @click="permissionMode = 'user'; selectedPermissionTargets = []; loadSelectedTargetPermissions()">用户</button>
              <button type="button" :class="{ active: permissionMode === 'group' }" @click="permissionMode = 'group'; selectedPermissionTargets = []; loadSelectedTargetPermissions()">权限组</button>
            </div>

            <div class="permission-grid">
              <section class="permission-column">
                <header>
                  <strong>{{ permissionMode === "user" ? "用户" : "权限组" }}</strong>
                  <span>{{ targetSelectionState() }} · {{ selectedPermissionTargets.length }} 已选</span>
                </header>
                <input v-model="permissionTargetSearch" placeholder="搜索对象" />
                <div class="permission-actions">
                  <button type="button" @click="selectAllPermissionTargets">全选</button>
                  <button type="button" @click="clearPermissionTargets">取消全选</button>
                </div>
                <div class="permission-list">
                  <label v-for="item in permissionTargetOptions" :key="item.id">
                    <input type="checkbox" :checked="selectedPermissionTargets.includes(item.id)" @change="togglePermissionTarget(item.id)" />
                    <span>{{ item.label }}</span>
                    <small>{{ item.note }}</small>
                  </label>
                  <p v-if="!permissionTargetOptions.length" class="empty-small">暂无对象</p>
                </div>
              </section>

              <section class="permission-column">
                <header>
                  <strong>数据集</strong>
                  <span>{{ datasetSelectionState() }} · {{ selectedPermissionDatasetIds.length }} 已选</span>
                </header>
                <input v-model="permissionDatasetSearch" placeholder="搜索数据集" />
                <div class="permission-actions">
                  <button type="button" @click="selectAllPermissionDatasets">全选</button>
                  <button type="button" @click="clearPermissionDatasets">取消全选</button>
                </div>
                <div class="permission-list">
                  <label v-for="item in permissionDatasetOptions" :key="item.id">
                    <input type="checkbox" :checked="selectedPermissionDatasetIds.includes(item.id)" @change="togglePermissionDataset(item.id)" />
                    <button type="button" class="permission-link" :class="{ active: permissionActiveDatasetId === item.id }" @click.prevent="setPermissionActiveDataset(item.id)">
                      {{ item.short_code }} · {{ item.name }}
                    </button>
                  </label>
                  <p v-if="!permissionDatasetOptions.length" class="empty-small">暂无可用数据集</p>
                </div>
              </section>

              <section class="permission-column">
                <header>
                  <strong>数据表</strong>
                  <span>{{ tableSelectionState() }} · {{ selectedPermissionTables.length }} 已选</span>
                </header>
                <div class="permission-actions">
                  <button type="button" @click="selectAllPermissionTables">全选</button>
                  <button type="button" @click="clearPermissionTables">取消全选</button>
                </div>
                <div class="permission-list">
                  <label v-for="item in permissionTableOptions" :key="item.key">
                    <input type="checkbox" :checked="selectedPermissionTables.includes(item.key)" @change="togglePermissionTable(item.key)" />
                    <span>{{ item.table.table_name }}</span>
                    <small>{{ item.table.columns.length }} 列</small>
                  </label>
                  <p v-if="!permissionTableOptions.length" class="empty-small">请先选择数据集</p>
                </div>
              </section>

              <section class="permission-column">
                <header>
                  <strong>权限列</strong>
                  <span>{{ columnSelectionState() }} · {{ selectedPermissionColumns.length }} 已选</span>
                </header>
                <div class="permission-actions">
                  <button type="button" @click="selectAllPermissionColumns">全选</button>
                  <button type="button" @click="clearPermissionColumns">取消全选</button>
                </div>
                <div class="permission-list">
                  <label v-for="item in permissionColumnOptions" :key="item.key">
                    <input type="checkbox" :checked="selectedPermissionColumns.includes(item.key)" @change="togglePermissionColumn(item.key)" />
                    <button type="button" class="permission-link" :class="{ active: permissionActiveColumnKey === item.key }" @click.prevent="activatePermissionColumn(item.key)">
                      {{ item.table_name }} · {{ item.column.column_name }}
                    </button>
                    <small>{{ item.column.type }}</small>
                  </label>
                  <p v-if="!permissionColumnOptions.length" class="empty-small">请先选择数据表</p>
                </div>
              </section>

              <section class="permission-column permission-values">
                <header>
                  <strong>允许值</strong>
                  <span>{{ valueSelectionState() }} · {{ permissionSelectedValues.length }} 已选</span>
                </header>
                <input v-model="permissionValueSearch" placeholder="搜索列值" @keyup.enter="loadPermissionValues(true)" />
                <div class="permission-actions">
                  <button type="button" @click="loadPermissionValues(true)">搜索</button>
                  <button type="button" @click="selectAllPermissionValues">全选本页</button>
                  <button type="button" @click="clearPermissionValues">取消全选</button>
                </div>
                <div class="permission-list">
                  <label v-for="value in permissionValues" :key="value">
                    <input type="checkbox" :checked="permissionSelectedValues.includes(value)" @change="togglePermissionValue(value)" />
                    <span>{{ value }}</span>
                  </label>
                  <button v-if="permissionValuesHasMore" type="button" class="permission-more" @click="loadPermissionValues(false)">加载更多</button>
                  <p v-if="!permissionValues.length" class="empty-small">请选择权限列后加载值</p>
                </div>
              </section>
            </div>

            <div class="permission-preview">
              <strong>预览</strong>
              <p v-if="!permissionRulePreview.length">尚未形成可保存的权限规则。</p>
              <ul v-else>
                <li v-for="rule in permissionRulePreview" :key="`${rule.dataset_id}-${rule.table_name}-${rule.column_name}`">
                  {{ datasets.find((item) => item.id === rule.dataset_id)?.short_code || rule.dataset_id }} · {{ rule.table_name }} · {{ rule.column_name }}：{{ rule.allowed_values.length }} 个值
                </li>
              </ul>
            </div>

            <div class="permission-footer">
              <p>{{ permissionMessage || "保存前后端会再次校验数据集、表、列和值。" }}</p>
              <button type="button" :disabled="permissionBusy" @click="cancelPermissionEdits">取消未保存修改</button>
              <button type="button" :disabled="permissionBusy" @click="deleteSelectedPermissions">删除所选对象权限</button>
              <button type="button" class="primary-tool" :disabled="permissionBusy" @click="savePermissionRules">保存权限</button>
            </div>
          </section>
        </div>

        <section class="panel schema-panel mobile-schema-preview">
          <div class="panel-title">
            <Database :size="18" />
            <h2>Schema</h2>
          </div>
          <div v-if="!schema" class="empty-small">未选择数据集</div>
          <article v-for="table in (schema ? schema.tables : [])" :key="table.name" class="table-block">
            <header>{{ table.short_code }} · {{ table.name }}</header>
            <p>{{ table.columns.map((column) => column.name).join("、") }}</p>
          </article>
        </section>
      </div>
    </section>

    <aside v-if="activePage === 'chat'" class="workspace-rail" :class="{ collapsed: !workspaceOpen, 'mobile-open': mobileWorkspaceOpen }">
      <button type="button" class="mobile-panel-close mobile-workspace-close" aria-label="收回图表与调试面板" @click="closeMobilePanels">
        <ChevronRight :size="18" />
      </button>
      <div
        v-if="workspaceOpen"
        class="workspace-resizer"
        role="separator"
        aria-orientation="vertical"
        title="拖拽调整右侧工作区宽度"
        @pointerdown="startWorkspaceResize"
      ></div>
      <button type="button" class="workspace-toggle" :title="workspaceOpen ? '收起右侧工作区' : '展开右侧工作区'" :aria-label="workspaceOpen ? '收起右侧工作区' : '展开右侧工作区'" @click="workspaceOpen = !workspaceOpen">
        <ChevronRight v-if="workspaceOpen" :size="18" />
        <ChevronLeft v-else :size="18" />
      </button>
      <div v-if="workspaceOpen || mobileWorkspaceOpen" class="workspace-content">
        <div v-if="debugModeEnabled && canUseDebug" class="workspace-tabs">
          <button type="button" class="chart-tab" :class="{ active: workspaceTab === 'chart' }" @click="workspaceTab = 'chart'">
            <BarChart3 :size="18" />
            图表
          </button>
          <button type="button" class="debug-tab" :class="{ active: workspaceTab === 'debug' }" @click="workspaceTab = 'debug'">
            <Database :size="13" />
            调试
          </button>
        </div>

        <section v-show="!debugModeEnabled || !canUseDebug || workspaceTab === 'chart'" class="panel chart-panel active">
          <div class="panel-title">
            <BarChart3 :size="18" />
            <h2>图表</h2>
          </div>
          <div v-if="!selectedChartTable" class="chart-empty">
            <strong>{{ selectedChartTableId ? "图表待生成" : "选择查询结果后生成图表" }}</strong>
            <span v-if="selectedChartTableId">当前结果不可用，请重新选择表格。</span>
          </div>
          <div v-else class="chart-builder">
            <div v-if="chartModeNotice || selectedChartRecommendation" class="chart-recommend-row">
              <p v-if="chartModeNotice" class="chart-notice">{{ chartModeNotice }}</p>
              <button v-if="selectedChartRecommendation" type="button" class="small-tool-button" @click="restoreChartRecommendation">恢复智能推荐</button>
            </div>
            <label>
              <span>图表标题</span>
              <input v-model="chartOptions.title" @input="markChartEdited" />
            </label>
            <div class="chart-preview-actions">
              <button type="button" class="small-tool-button primary-tool" @click="() => renderChart()">
                <BarChart3 :size="14" />
                {{ chartRendered ? "应用修改" : "生成" }}
              </button>
              <button type="button" class="small-tool-button" :disabled="!selectedChartTable" @click="openAddToDashboard">
                <LayoutDashboard :size="14" />
                加入看板
              </button>
              <span>{{ selectedChartTable.task_id }} · {{ selectedChartTable.row_count }} 行</span>
            </div>
            <p v-if="chartError" class="chart-error">{{ chartError }}</p>
            <p v-if="chartNotice" class="chart-notice">{{ chartNotice }}</p>
            <div class="chart-canvas-wrap" :class="{ empty: !chartRendered }">
              <canvas ref="chartCanvas" aria-label="查询结果图表"></canvas>
              <span v-if="!chartRendered">选择字段后点击生成</span>
            </div>
            <label>
              <span>图表类型</span>
              <select v-model="chartOptions.type" @change="onChartTypeChange">
                <option v-for="item in chartTypeOptions" :key="item.value" :value="item.value">{{ item.label }}</option>
              </select>
            </label>
            <label>
              <span>{{ chartOptions.type === "scatter" ? "X 数值字段" : "分类/横轴字段" }}</span>
              <select v-model="chartOptions.categoryColumn" @change="markChartEdited">
                <option value="">请选择</option>
                <option v-for="field in chartOptions.type === 'scatter' ? numericFields : categoryFields" :key="field.name" :value="field.name">
                  {{ field.name }} · {{ field.type === "numeric" ? "数值" : field.type === "ordered" ? "有序" : "文本" }}
                </option>
              </select>
            </label>
            <label>
              <span>系列/分组字段</span>
              <select v-model="chartOptions.seriesColumn" @change="markChartEdited">
                <option value="">不分组</option>
                <option v-for="field in groupFields" :key="field.name" :value="field.name">{{ field.name }}</option>
              </select>
            </label>
            <label>
              <span>Y 轴起点</span>
              <select v-model="chartOptions.yZeroMode" @change="markChartEdited">
                <option value="auto">智能选择</option>
                <option value="zero">强制从 0 开始</option>
                <option value="data_range">按数据实际范围</option>
              </select>
            </label>
            <label>
              <span>横轴标签密度</span>
              <select v-model="chartOptions.labelDensity" @change="markChartEdited">
                <option value="auto">智能</option>
                <option value="full">完整显示</option>
                <option value="sparse">稀疏显示</option>
              </select>
            </label>
            <label>
              <span>数据顺序</span>
              <select v-model="chartOptions.sortMode" @change="markChartEdited">
                <option value="original">保持原顺序</option>
                <option value="asc">升序</option>
                <option value="desc">降序</option>
              </select>
            </label>
            <label>
              <span>图例</span>
              <select v-model="chartOptions.legendMode" @change="markChartEdited">
                <option value="auto">智能</option>
                <option value="show">显示</option>
                <option value="hide">隐藏</option>
              </select>
            </label>
            <div class="chart-config-grid">
              <label>
                <span>图例位置</span>
                <select v-model="chartOptions.legendPosition" @change="markChartEdited">
                  <option value="top">顶部</option>
                  <option value="bottom">底部</option>
                  <option value="left">左侧</option>
                  <option value="right">右侧</option>
                </select>
              </label>
              <label>
                <span>数据标签</span>
                <select v-model="chartOptions.dataLabelMode" @change="markChartEdited">
                  <option value="auto">智能</option>
                  <option value="show">显示</option>
                  <option value="hide">隐藏</option>
                </select>
              </label>
              <label v-if="chartOptions.type !== 'pie'">
                <span>数据筛选</span>
                <select v-model="chartOptions.limitMode" @change="markChartEdited">
                  <option value="none">不限制</option>
                  <option value="top">Top N</option>
                  <option value="bottom">Bottom N</option>
                </select>
              </label>
              <label v-if="chartOptions.type !== 'pie' && chartOptions.limitMode !== 'none'">
                <span>N 值</span>
                <input v-model.number="chartOptions.limitCount" type="number" min="1" max="100" @input="markChartEdited" />
              </label>
              <label v-if="chartOptions.type !== 'pie'">
                <span>X 轴标题</span>
                <input v-model="chartOptions.xAxisTitle" @input="markChartEdited" />
              </label>
              <label v-if="chartOptions.type !== 'pie'">
                <span>Y 轴标题</span>
                <input v-model="chartOptions.yAxisTitle" @input="markChartEdited" />
              </label>
              <label>
                <span>单位</span>
                <input v-model="chartOptions.unitLabel" placeholder="可留空" @input="markChartEdited" />
              </label>
              <label>
                <span>配色</span>
                <select v-model="chartOptions.colorScheme" @change="markChartEdited">
                  <option value="morandi">灰蓝</option>
                  <option value="sage">灰绿</option>
                  <option value="slate">雾蓝</option>
                  <option value="warm">灰橙</option>
                </select>
              </label>
              <label v-if="['line','area','combo_column_line'].includes(chartOptions.type)" class="chart-inline-check">
                <input v-model="chartOptions.lineSmooth" type="checkbox" @change="markChartEdited" />
                <span>平滑线</span>
              </label>
              <label v-if="['line','area'].includes(chartOptions.type)" class="chart-inline-check">
                <input v-model="chartOptions.areaFill" type="checkbox" @change="markChartEdited" />
                <span>面积填充</span>
              </label>
              <label v-if="chartOptions.type === 'pie'">
                <span>饼图样式</span>
                <select v-model="chartOptions.pieMode" @change="markChartEdited">
                  <option value="doughnut">环形</option>
                  <option value="pie">饼图</option>
                </select>
              </label>
              <label v-if="['column_clustered','column_stacked','bar_horizontal'].includes(chartOptions.type)">
                <span>条宽</span>
                <select v-model="chartOptions.barThickness" @change="markChartEdited">
                  <option value="auto">自动</option>
                  <option value="slim">细</option>
                  <option value="bold">粗</option>
                </select>
              </label>
              <label>
                <span>字号密度</span>
                <select v-model="chartOptions.fontScale" @change="markChartEdited">
                  <option value="compact">紧凑</option>
                  <option value="normal">标准</option>
                </select>
              </label>
            </div>
            <div class="chart-fieldset">
              <span>{{ chartOptions.type === "combo_column_line" ? "柱状字段" : chartOptions.type === "stock" ? "OHLC 字段" : "数值字段" }}</span>
              <label v-for="field in numericFields" :key="field.name" class="chart-check">
                <input type="checkbox" :checked="chartOptions.numericColumns.includes(field.name)" @change="toggleNumericColumn(field.name)" />
                <span>{{ field.name }}</span>
              </label>
              <small v-if="!numericFields.length">当前结果没有可用数值列。</small>
            </div>
            <div v-if="chartOptions.type === 'combo_column_line'" class="chart-fieldset">
              <span>折线字段</span>
              <label v-for="field in numericFields" :key="`line-${field.name}`" class="chart-check">
                <input type="checkbox" :checked="chartOptions.lineColumns.includes(field.name)" @change="toggleNumericColumn(field.name, 'line')" />
                <span>{{ field.name }}</span>
              </label>
            </div>
            <div v-if="chartRendered" class="chart-actions chart-export-actions">
              <span>导出图表</span>
              <button v-if="chartRendered" type="button" class="small-tool-button" @click="exportChart('png')">PNG</button>
              <button v-if="chartRendered" type="button" class="small-tool-button" @click="exportChart('jpeg')">JPEG</button>
              <button v-if="chartRendered" type="button" class="small-tool-button" @click="exportChart('csv')">CSV</button>
              <button v-if="chartRendered" type="button" class="small-tool-button" @click="exportChart('json')">JSON</button>
            </div>
          </div>        </section>

      <section v-if="debugModeEnabled && canUseDebug" v-show="workspaceTab === 'debug'" class="panel debug-panel active">
        <div class="panel-title">
          <Database :size="18" />
          <h2>调试窗口</h2>
          <span class="debug-total">Total {{ totalDebugMs }}ms</span>
        </div>
        <div class="stage-list debug-scroll">
          <article v-for="stage in stageKeys" :key="stage" class="stage-row">
            <header>
              <strong>{{ stageNames[stage] }}</strong>
              <span>{{ latestDebugByStage.get(stage)?.status || "占位" }}</span>
            </header>
            <div v-if="stage === 'sql_planning' && sqlPlanningDebug" class="embedding-debug">
              <p>Provider {{ sqlPlanningDebug.provider_type || "-" }}；配置 {{ sqlPlanningDebug.config_name || "-" }}；模型 {{ sqlPlanningDebug.model_name || "-" }}</p>
              <p>Base URL {{ sqlPlanningDebug.base_url || "-" }}；模式 {{ sqlPlanningDebug.effective_structured_output_mode || sqlPlanningDebug.structured_output_mode || "-" }}；request {{ sqlPlanningDebug.request_id || "-" }}</p>
              <p>HTTP {{ sqlPlanningDebug.http_status || "-" }}；finish {{ sqlPlanningDebug.finish_reason || "-" }}；content {{ sqlPlanningDebug.content_length ?? "-" }} 字；reasoning {{ sqlPlanningDebug.reasoning_content_exists ? "有" : "无" }}</p>
              <p>Prompt {{ sqlPlanningDebug.prompt_chars }} 字；模型 {{ sqlPlanningDebug.model_ms }}ms；网络重试 {{ sqlPlanningDebug.network_retried ? "是" : "否" }}；格式重试 {{ sqlPlanningDebug.format_retried ? "是" : "否" }}；M-Schema {{ sqlPlanningDebug.mschema_dedupe?.prompt_mschema_occurrences }} 次</p>
              <p v-if="sqlPlanningDebug.metric_knowledge_lookup">指标知识库：{{ sqlPlanningDebug.metric_knowledge_lookup.status || "-" }}；指标 {{ sqlPlanningDebug.metric_knowledge_lookup.metric_hits ?? 0 }}；术语 {{ sqlPlanningDebug.metric_knowledge_lookup.term_hits ?? 0 }}；规则 {{ sqlPlanningDebug.metric_knowledge_lookup.rule_hits ?? 0 }}；注入 {{ sqlPlanningDebug.metric_knowledge_lookup.injected_count ?? 0 }}；新增 {{ sqlPlanningDebug.metric_knowledge_lookup.prompt_chars_added ?? 0 }} 字；耗时 {{ sqlPlanningDebug.metric_knowledge_lookup.duration_ms ?? 0 }}ms；降级 {{ sqlPlanningDebug.metric_knowledge_lookup.fallback ? "是" : "否" }}</p>
              <p v-if="sqlPlanningDebug.fast_match_enabled !== undefined">快速匹配：{{ sqlPlanningDebug.fast_match_status || "disabled" }}；模板 {{ sqlPlanningDebug.matched_template_id || "-" }}；耗时 {{ sqlPlanningDebug.match_duration_ms ?? 0 }}ms；跳过第一轮模型 {{ sqlPlanningDebug.first_llm_skipped ? "是" : "否" }}</p>
              <p>Prompt Hash {{ sqlPlanningDebug.prompt_hash || "-" }}；主请求 {{ sqlPlanningDebug.main_request_count ?? "-" }}；格式修复 {{ sqlPlanningDebug.format_repair_count ?? "-" }}</p>
              <p>模型参数 {{ JSON.stringify(sqlPlanningDebug.model_params || {}) }}</p>
              <p v-if="sqlPlanningDebug.error_type">错误：{{ sqlPlanningDebug.error_type }} · {{ sqlPlanningDebug.message }}</p>
              <p v-if="sqlPlanningDebug.corrective_retry">纠错重询：{{ sqlPlanningDebug.corrective_retry.original_message || sqlPlanningDebug.corrective_retry.original_error_type }}；正在反馈错误原因并重新请求第一次模型生成 QueryPlan；状态 {{ sqlPlanningDebug.corrective_retry.status }}</p>
              <details>
                <summary>请求尝试</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.attempts, null, 2) }}</pre>
              </details>
              <details v-if="sqlPlanningDebug.metric_knowledge_candidates?.length">
                <summary>指标知识库候选</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.metric_knowledge_candidates, null, 2) }}</pre>
              </details>
              <details v-if="sqlPlanningDebug.fast_match_enabled !== undefined">
                <summary>快速匹配</summary>
                <pre>{{ JSON.stringify({
                  fast_match_enabled: sqlPlanningDebug.fast_match_enabled,
                  fast_match_status: sqlPlanningDebug.fast_match_status,
                  matched_template_id: sqlPlanningDebug.matched_template_id,
                  match_method: sqlPlanningDebug.match_method,
                  match_duration_ms: sqlPlanningDebug.match_duration_ms,
                  extracted_parameters: sqlPlanningDebug.extracted_parameters,
                  fallback_reason: sqlPlanningDebug.fallback_reason,
                  first_llm_skipped: sqlPlanningDebug.first_llm_skipped
                }, null, 2) }}</pre>
              </details>
              <details v-if="sqlPlanningDebug.corrective_retry">
                <summary>纠错重询</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.corrective_retry, null, 2) }}</pre>
              </details>
              <details v-if="sqlPlanningDebug.retry_prompt">
                <summary>纠错 Prompt</summary>
                <pre>{{ sqlPlanningDebug.retry_prompt }}</pre>
              </details>
              <details>
                <summary>System Prompt</summary>
                <pre>{{ sqlPlanningDebug.system_prompt }}</pre>
              </details>
              <details>
                <summary>User Prompt</summary>
                <pre>{{ sqlPlanningDebug.user_prompt }}</pre>
              </details>
              <details>
                <summary>返回格式与约束</summary>
                <pre>{{ sqlPlanningDebug.format_prompt }}</pre>
              </details>
              <details>
                <summary>模型原始返回</summary>
                <pre>{{ sqlPlanningDebug.raw_model_return }}</pre>
              </details>
              <details>
                <summary>JSON 解析</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.json_parse, null, 2) }}</pre>
              </details>
              <details>
                <summary>类型校验</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.type_validation, null, 2) }}</pre>
              </details>
              <details>
                <summary>标准化 QueryPlan</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.normalized_query_plan, null, 2) }}</pre>
              </details>
              <details>
                <summary>后端派生字段</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.derived_fields, null, 2) }}</pre>
              </details>
              <details>
                <summary>QueryPlan 校验</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.query_plan_schema, null, 2) }}</pre>
              </details>
              <details>
                <summary>QueryPlan 契约</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.query_plan_contract, null, 2) }}</pre>
              </details>
              <details>
                <summary>QueryPlan</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.query_plan, null, 2) }}</pre>
              </details>
              <details>
                <summary>覆盖检查</summary>
                <pre>{{ JSON.stringify(sqlPlanningDebug.coverage_check, null, 2) }}</pre>
              </details>
            </div>
            <div v-else-if="stage === 'sql_execution' && sqlExecutionDebug" class="embedding-debug">
              <p>{{ sqlExecutionDebug.database?.type }} {{ sqlExecutionDebug.database?.version }}；执行 {{ sqlExecutionDebug.execution_ms }}ms；表格 {{ sqlExecutionDebug.tables?.length || 0 }} 个</p>
              <p v-if="sqlExecutionDebug.corrective_retry">纠错重询：{{ sqlExecutionDebug.corrective_retry.original_message || sqlExecutionDebug.corrective_retry.original_error_type }}；正在反馈错误原因并重新请求第一次模型生成 QueryPlan；状态 {{ sqlExecutionDebug.corrective_retry.status }}</p>
              <details v-if="sqlExecutionDebug.corrective_retry">
                <summary>纠错重询</summary>
                <pre>{{ JSON.stringify(sqlExecutionDebug.corrective_retry, null, 2) }}</pre>
              </details>
              <details>
                <summary>SQL 校验</summary>
                <pre>{{ JSON.stringify(sqlExecutionDebug.ast_validation, null, 2) }}</pre>
              </details>
              <details>
                <summary>结果列检查</summary>
                <pre>{{ JSON.stringify(sqlExecutionDebug.result_column_check, null, 2) }}</pre>
              </details>
              <details>
                <summary>机构范围与结果粒度</summary>
                <pre>{{ JSON.stringify(sqlExecutionDebug.result_scope_check, null, 2) }}</pre>
              </details>
              <details>
                <summary>数据库错误摘要</summary>
                <pre>{{ JSON.stringify({ error_type: sqlExecutionDebug.database_error_type, error: sqlExecutionDebug.database_error, actual_sql: sqlExecutionDebug.actual_sql }, null, 2) }}</pre>
              </details>
              <details>
                <summary>SQL 修复前后</summary>
                <pre>{{ JSON.stringify(sqlExecutionDebug.sql_before_after, null, 2) }}</pre>
              </details>
              <details>
                <summary>返回表格</summary>
                <pre>{{ JSON.stringify(sqlExecutionDebug.tables, null, 2) }}</pre>
              </details>
            </div>
            <div v-else-if="stage === 'answer_generation' && answerDebug" class="embedding-debug">
              <p>Prompt {{ answerDebug.second_prompt_chars ?? "-" }} 字；附加提示 {{ answerDebug.second_extra_prompt_chars ?? "-" }} 字；阶段 {{ answerDebug.stage_ms ?? latestDebugByStage.get(stage)?.duration_ms }}ms</p>
              <p v-if="answerDebug.error_type">错误：{{ answerDebug.error_type }} · {{ answerDebug.message }}</p>
              <details>
                <summary>请求尝试</summary>
                <pre>{{ JSON.stringify(answerDebug.attempts || [], null, 2) }}</pre>
              </details>
              <details open>
                <summary>第二次实际输入</summary>
                <pre>{{ answerDebug.second_input }}</pre>
              </details>
              <details>
                <summary>模型返回</summary>
                <pre>{{ answerDebug.model_return || answerDebug.raw_model_return }}</pre>
              </details>
              <details open>
                <summary>最终回答</summary>
                <pre>{{ answerDebug.final_answer }}</pre>
              </details>
              <details>
                <summary>质量统计</summary>
                <pre>{{ JSON.stringify(answerDebug.quality || {}, null, 2) }}</pre>
              </details>
            </div>
            <p v-else-if="stage !== 'embedding_retrieval'">{{ latestDebugByStage.get(stage)?.output_summary || "暂无运行数据" }}</p>
            <div v-else-if="embeddingDebug" class="embedding-debug">
              <p>上下文：{{ embeddingDebug.has_context ? "携带" : "不携带" }}；批量编码文本：{{ embeddingDebug.batch_encoded_texts }}</p>
              <p>模型加载：{{ embeddingDebug.model?.already_loaded ? "已复用" : "首次加载" }} / {{ embeddingDebug.model?.load_ms }}ms</p>
              <p>索引：磁盘 {{ embeddingDebug.disk_index_hit ? "命中" : "未命中" }}，内存 {{ embeddingDebug.memory_index_hit ? "命中" : "未命中" }}，构建 {{ embeddingDebug.index_build_ms }}ms</p>
              <p>编码 {{ embeddingDebug.question_encoding_ms }}ms；检索 {{ embeddingDebug.total_embedding_ms }}ms；M-Schema {{ embeddingDebug.mschema_ms }}ms</p>
              <details>
                <summary>原始候选</summary>
                <pre>{{ JSON.stringify(embeddingDebug.raw_candidates, null, 2) }}</pre>
              </details>
              <details>
                <summary>过滤原因</summary>
                <pre>{{ JSON.stringify(embeddingDebug.filter_reasons, null, 2) }}</pre>
              </details>
              <details>
                <summary>最终候选</summary>
                <pre>{{ JSON.stringify(embeddingDebug.final_candidates, null, 2) }}</pre>
              </details>
              <details open>
                <summary>M-Schema</summary>
                <pre>{{ embeddingDebug.mschema }}</pre>
              </details>
            </div>
            <p v-else>暂无运行数据</p>
          </article>
          <article class="stage-row context-row">
            <header>
              <strong>上下文状态</strong>
              <span>{{ latestDebugByStage.get("context_lifecycle")?.status || "等待输入" }}</span>
            </header>
            <p>{{ latestDebugByStage.get("context_lifecycle")?.output_summary || "暂无上下文段" }}</p>
          </article>
        </div>
      </section>
      </div>

    </aside>
    <div v-if="addToDashboardOpen" class="modal-backdrop" @click.self="addToDashboardOpen = false">
      <section class="modal-card add-dashboard-modal">
        <h3>加入看板</h3>
        <label>
          <span>目标看板</span>
          <select v-model="addToDashboardTargetId">
            <option value="">快速新建看板</option>
            <option v-for="item in dashboards" :key="item.id" :value="item.id">{{ item.name }}</option>
          </select>
        </label>
        <label>
          <span>卡片标题</span>
          <input v-model="addToDashboardTitle" />
        </label>
        <label>
          <span>初始尺寸</span>
          <select v-model="addToDashboardSize">
            <option value="small">小</option>
            <option value="medium">中</option>
            <option value="large">大</option>
          </select>
        </label>
        <label>
          <span>模式</span>
          <select v-model="addToDashboardMode">
            <option value="static">静态</option>
            <option value="dynamic">动态</option>
          </select>
        </label>
        <div class="modal-actions">
          <button type="button" @click="addToDashboardOpen = false">取消</button>
          <button type="button" class="primary-tool" :disabled="dashboardBusy" @click="confirmAddToDashboard">确认加入</button>
        </div>
      </section>
    </div>
  </main>
</template>
