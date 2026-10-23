# Changelog

## 1.0.5 公开发布准备 - 2026-10-23

- 清理运行目录、内置 seed 与旧构建副本中的业务表格、Schema、历史对话、模型连接、API Key、实际服务地址、指标字典和看板快照。
- 保留本地演示登录账号；使用空库结构重新生成公开初始化内容，清除原令牌签名密钥。
- 增加公开 seed 导出脚本，Windows 构建只携带空业务库和登录账号，排除缓存表格。
- 重写仓库 README，补充安装包、环境、源码启动、服务器部署、登录与使用说明。
- 将旧 Git 历史和含数据构建产物移至上传目录外的私有备份。

## 1.0.5 - 2026-08-23

Changed:

- Added a phone-portrait-only responsive layout using the existing navigation,
  query, workspace, management, result, and dashboard components.
- Presented the existing left navigation and right chart/debug workspace as
  mutually exclusive overlay panels below 641px in portrait orientation.
- Kept desktop dashboard coordinates intact while displaying cards in one
  visual column on phone portrait screens.

## 1.0.4 - 2026-08-20

Fixed:

- Prevented numeric value columns from being treated as chart series, which
  produced disconnected one-point datasets in line charts.
- Bound dashboard chart canvases to card size changes with a shared resize
  observer and shrink-safe container sizing.
- Removed the “已加入看板” label from Dashboard-referenced conversations.

## 1.0.3 - 2026-08-19

Changed:

- Corrected institution pinyin initials for uncommon characters and banking
  pronunciations such as “瀚海银行” (`HHYH`).
- Increased entity candidates to ten while keeping a six-row scroll viewport.
- Added textarea-to-candidate keyboard navigation with Arrow Up/Down and Enter.

## 1.0.2 - 2026-08-17

Added:

- Added a default-off, per-user context mode for conservative multi-turn
  reference completion after fast-match misses.
- Added isolated in-memory context-template retrieval and rolling state scoped
  by user, conversation, dataset, and enable session.
- Preserved original questions for display/history while resolved questions
  feed the unchanged retrieval, QueryPlan, SQL, and answer pipeline.

## 1.0.1 - 2026-08-17

Added:

- Added read-only, dataset-scoped organization and metric autocomplete above
  the question composer, with Chinese prefix, pinyin initials, code, and
  existing metric-alias matching.
- Reused the selected dataset Schema, real DuckDB entity values, the existing
  metric dictionary, login authentication, and row-access-control rules.
- Kept suggestions to six items and made selection replace only the active
  input fragment without submitting the question.

## 1.0.0 - 2026-07-30

Changed:

- Prepared the first formal release without changing the accepted NL2SQL,
  fast-match, SQL validation, row-access-control, chart, history, Dashboard,
  dynamic-condition, or model-connection flows.
- Cleaned release UI symbols by removing visible version labels, simplifying
  refresh/delete icon buttons, and removing old empty-chat release-note copy.
- Added a Dashboard metric-card decimal display option for no decimals or two
  decimals; the setting affects display only and does not change SQL results.
- Standardized long select text to single-line ellipsis for dataset/model style
  controls.
- Backed up and cleaned runtime data for the release baseline while preserving
  D001, the `sqlbot` model configuration, and existing Dashboards.
- Added Windows EXE packaging support: FastAPI can serve the built frontend,
  the desktop launcher opens a local browser, EXE runtime data is initialized
  under `%LOCALAPPDATA%\ChatSQL\ChatSQLData`, and PyInstaller/Inno Setup scripts
  are provided with sanitized seed data.

## 0.12.7 - 2026-07-30

Changed:

- Reduced Board chart flicker during dynamic-condition refresh by updating
  existing Chart.js instances in place when the chart type is unchanged.
- Changed manual Board filter linking so links can only be enabled when a
  matching top dynamic condition exists; linked filters hide local
  operator/value controls and follow the global condition.
- Guarded doughnut center-label drawing while Chart.js layout is not ready to
  avoid `left` access errors.

## 0.12.6 - 2026-07-30

Changed:

- Hardened banking example Board template migration on dashboard detail reads,
  so stale SQL-only template cards are rebuilt into editable manual components.
- Added a frontend retry path for example-template card editing after dashboard
  reload, avoiding stale in-memory template cards from showing the SQL-only
  smart-query card warning.

## 0.12.5 - 2026-07-30

Changed:

- Converted banking example Board template cards to editable manual component
  queries instead of fixed SQL-only template sources.
- Added template-version replacement for previously seeded example Boards so
  older generated templates are refreshed to the editable form.
- Hardened Dashboard Chart.js cleanup by destroying any chart attached to a
  reused canvas before rendering a new chart.

## 0.12.4 - 2026-07-30

Backup tag: `v0.12.3-backup-before-v0.12.4`.

Changed:

- Added three editable banking analysis example Board templates: operating
  overview, asset-liability growth, and risk/return peer comparison.
- Seeded the templates through the existing Dashboard and DashboardCard storage
  model when a ready banking metric dataset is available.
- Reused existing card types, chart config, dynamic refresh, SQL validation,
  row-access-control, and Board editing behavior without changing frontend APIs
  or NL2SQL flows.

## 0.12.3 - 2026-07-30

Changed:

- Removed the duplicate Board date shortcut for recent month from the top
  dynamic-condition selector, keeping recent 30 days as the compact option.
- Added date shortcut strategies to manual Board card filters for date,
  datetime, and date-like VARCHAR fields.
- Kept v0.12.2 filter link semantics: linked date filters follow compatible top
  dynamic conditions, while unlinked filters resolve their own local shortcut or
  custom range.
- Standardized compact padding for Board component editing, filter, card edit,
  and dynamic-condition popovers.

## 0.12.2 - 2026-07-30

Changed:

- Added a per-filter Board link toggle so manual card filters can either follow
  matching top dynamic conditions or remain local card-specific exceptions.
- Kept old Board filter data compatible by treating missing link flags as
  enabled.
- Preserved dynamic refresh on the existing SQL validation, Schema validation,
  row-access-control, and DuckDB execution path.
- Normalized Board close, pin, dynamic-condition settings, and filter link
  controls to compact icon-only styling.

## 0.12.1 - 2026-07-30

Backup tag: `v0.12.0-backup-before-v0.12.1`.

Changed:

- Unified Board dynamic conditions so the top dynamic bar is the single source
  for ordinary value filters and date/time strategies.
- Added date/time strategy choices directly to date-like Board parameters,
  including latest available date, recent 3/7/30-day windows, recent
  month/quarter windows, and custom ranges.
- Removed the separate card-level dynamic data panel from the card editor;
  dynamic cards now automatically apply compatible top Board conditions during
  backend refresh.
- Reused the left Board component panel for editing manual cards and text
  cards, removing the duplicate component-settings form from the card editor.
- Kept dynamic refresh on the existing SQL validation, Schema validation,
  row-access-control, and DuckDB execution path.

## 0.12.0 - 2026-07-30

Backup tag: `v0.11.7-backup-before-v0.12.0`.

Changed:

- Added lightweight backend SQL mapping for Board cards, covering both manual
  Board components and charts added from smart Q&A results.
- Added Schema semantic metadata for date-like DuckDB columns during import,
  including VARCHAR date columns, without changing the physical table layout.
- Allowed Board dynamic time fields and manual range filters to use
  date-like VARCHAR columns via validated date expressions.
- Extended Board dynamic SQL refresh to rewrite conditions in safely parsed
  multi-table SQL blocks while preserving the existing SQL validation,
  Schema validation, row access control, and DuckDB execution path.
- Kept SQL mapping stored in Board backend metadata only; it is not shown in
  the frontend.

## 0.11.7 - 2026-07-30

Backup tag: `v0.11.6-backup-before-v0.11.7`.

Changed:

- Fixed Board drag target coordinate calculations to account for real grid
  padding and gaps, keeping the floating card and target preview aligned.
- Moved Board dynamic-condition setup out of the component creation panel into
  a compact top settings area and capped each Board at three parameters.
- Unified frontend card mode controls into static and dynamic choices for
  manual cards, chat-chart cards, duplicated cards, and card editing.
- Added a collapsible component-settings area for manual Board cards so fields,
  aggregation, and filters can be edited without creating duplicate cards.
- Tightened filter panel positioning and scrolling, and added the recent
  3-day dynamic time range.

## 0.11.6 - 2026-07-30

Backup tag: `v0.11.5-backup-before-v0.11.6`.

Changed:

- Added Board card refresh modes for fixed snapshot, fixed query, and dynamic
  query while keeping existing cards compatible.
- Added Schema-driven Board dynamic parameters and compact frontend controls
  for binding compatible cards to those parameters.
- Added dynamic time binding and refresh policies for latest available date,
  month/quarter endpoints, recent 7/30-day ranges, month/quarter windows, and
  custom date ranges.
- Kept dynamic refresh on the existing SQL validation, Schema validation,
  row-access-control, and DuckDB execution path; refresh does not call the
  model.
- Added minimal Board config storage and dynamic candidate/value APIs without
  changing existing business API payloads.

## 0.11.5 - 2026-07-29

Backup tag: `v0.11.4-backup-before-v0.11.5`.

Changed:

- Changed Board card movement to use pixel-level visual dragging with a target
  grid hint, committing the snapped layout only after release.
- Increased the Board virtual grid precision to 64 columns and added
  proportional compatibility for older saved layouts.
- Added backend layout overlap validation for Board card add/update operations.
- Tightened the manual filter editor by moving delete to a compact corner
  action.
- Added validated range filters for numeric and date-like manual Board
  component fields.
- Fixed Board card dragging while the Board scroll container moves by using
  pointer capture, a fixed drag layer, scroll-aware target calculation, and
  requestAnimationFrame edge auto-scroll.

## 0.11.4 - 2026-07-29

Backup tag: `v0.11.3-backup-before-v0.11.4`.

Changed:

- Replaced the Board's persistent left component handle with a full-width
  bottom add area that opens a temporary component panel.
- Changed manual component creation so selecting a type only configures the
  draft, and cards are created after clicking `确定添加`.
- Added a temporary auxiliary filter panel for manual Board components with
  multiple AND conditions.
- Extended backend manual-query filter validation to support field, operator,
  and value checks against the existing dataset Schema before the current SQL
  validation, execution, and row-access-control chain runs.

## 0.11.3 - 2026-07-29

Backup tag: `v0.11.2-backup-before-v0.11.3`.

Changed:

- Protected conversations referenced by Board cards from the ordinary
  25-conversation cleanup, with a separate referenced-conversation section in
  the left history list.
- Added backend validation so referenced conversations cannot be deleted by
  cleanup or direct delete calls while a Board card still points to them.
- Made chat and Board chart animations play only once per chart instance to
  avoid repeated redraw jitter during selection, editing, moving, and resizing.
- Added Board chart title display controls so a card uses either the card-top
  title or the chart-internal title, avoiding duplicate titles by default.
- Changed Board card editing to open from double-clicking card content while
  single-click, drag, and resize only select or move cards.
- Cleaned the Board canvas background to white and tightened card spacing.

## 0.11.2 - 2026-07-29

Backup tag: `v0.11.1-backup-before-v0.11.2`.

Changed:

- Unified chat charts and Board chart cards around a compact light dashboard
  Chart.js theme with Morandi-style palettes, softer grid lines, tighter
  legends, rounded bars, subtler card treatment, and responsive spacing.
- Added chart editing options for legend position, data labels, Top/Bottom N,
  axis titles, unit labels, line smoothing, area fill, doughnut versus pie,
  palette scheme, bar density, and font density.
- Extended Board chart card editing to adjust chart type, category field,
  numeric fields, labels, legend, sorting, limits, units, palette, smoothing,
  area fill, and pie/doughnut style without changing stored data or refresh
  behavior.
- Preserved existing chart recommendation, apply modification, restore
  recommendation, add to Board, dashboard refresh, query, permission, and API
  flows.

## 0.11.1 - 2026-07-29

Backup tag: `v0.11.0-backup-before-v0.11.1`.

Changed:

- Renamed Data & Control Center to `控制与管理` in the left navigation and page
  title.
- Reduced the Control & Management and Board top-bar height and control spacing.
- Changed the Board component tools into a collapsible left handle panel that
  frees canvas space when closed.
- Replaced the always-visible right card editor with a draggable floating editor
  that opens on card selection and supports close and pin controls.
- Made refresh, copy, and delete card actions a compact single-row action group.
- Increased Board layout density by using smaller row units and tighter card
  spacing while preserving existing saved layout compatibility.

## 0.11.0 - 2026-07-29

Backup tag: `v0.10.3-backup-before-v0.11.0`.

Added:

- Added the first lightweight personal Board builder with create, switch,
  rename, delete, edit/preview, save, reopen, drag, resize, copy, delete, single
  card refresh, and refresh-all.
- Added one-click `加入看板` from the existing chat chart panel, saving the current
  chart config, validated SQL when available, result columns, and latest result
  snapshot without another model call.
- Added manual single-table text, metric, chart, line, pie, and table cards
  generated from real dataset Schema fields without free-form SQL.
- Added board storage in the existing local metadata SQLite database through
  `dashboards` and `dashboard_cards` tables.

Security:

- Board APIs require bearer-token authentication and use the verified token
  username for ownership; users cannot access another user's boards by changing
  request payloads.
- Board refresh reuses the existing SQL AST/Schema validation, DuckDB execution,
  and backend row-level access-control layer before updating snapshots.

## 0.10.3 - 2026-07-29

Backup tag: `v0.10.2-backup-before-v0.10.3`.

Changed:

- Renamed the left navigation dashboard entry and page title to Data & Control
  Center while keeping the original dataset, import, model, and Schema features.
- Added a blank Board page with the existing muted visual style.
- Replaced the left-bottom bordered account card with a lightweight avatar menu
  containing Settings and logout.
- Moved the fast-match setting into the account menu Settings area and removed
  the old Advanced Settings entry.
- Moved admin permission management out of the Schema card into its own card
  below LLM model configuration, with no internal fixed-height scroller.

## 0.10.2 - 2026-07-28

Backup tag: `v0.10.1-backup-before-v0.10.2`.

Added:

- Added an admin-only visual permission manager inside Dashboard → Schema.
- Reused the existing imported dataset Schema as the source for real table and
  column candidates; no parallel Schema model or import flow changes were added.
- Added admin APIs to list users/groups, read row permissions, fetch searchable
  paged column values, save batch permissions, and delete selected target rules.

Changed:

- Row-permission saves now validate dataset, table, column, and DuckDB column
  values on the backend before writing to `ChatSQLData\auth\auth.sqlite3`.
- Normal users continue to receive 403 from permission-management APIs and do
  not see the Schema permission-management entry.

## 0.10.1 - 2026-07-28

Backup tag: `v0.10.0-backup-before-v0.10.1`.

Changed:

- Moved local account, permission-group, user-group binding, and row-permission
  storage from `users.json` to `ChatSQLData\auth\auth.sqlite3`.
- Added `backend\auth_admin.py` for local auth database initialization and
  maintenance without adding a web account-management UI.
- Kept the v0.10.0 login page, bearer token flow, admin/user behavior, and SQL
  row-level enforcement unchanged.

Added:

- Added admin-only Schema permission candidate APIs for future dashboard
  permission editing: table/column candidates come from real dataset Schema,
  and distinct column values can be fetched for local DuckDB datasets.

## 0.10.0 - 2026-07-28

Backup tag: `v0.9.11-backup-before-v0.10.0`.

Added:

- Added a standalone login screen backed by local `ChatSQLData\auth\users.json`
  accounts and bearer-token authentication for protected API calls.
- Added role handling: admins retain all features including `/debug`; normal
  users keep business workflows but cannot open or receive debug records.
- Added backend row-level access control before DuckDB SQL execution, shared by
  deterministic fast match and normal model-generated SQL paths.

Changed:

- Limited local Excel/CSV datasets to five total ready datasets. The sixth
  local file upload is rejected by the backend instead of deleting older data.
- Documented local plaintext password limitations, row permission examples, and
  the future auth-provider extension point.

## 0.9.11 - 2026-07-28

Backup tag: `v0.9.10-backup-before-v0.9.11`.

Changed:

- Unified scrollbar visuals with thin rounded Morandi-gray thumbs, transparent
  tracks, and hidden WebKit arrow buttons.
- Made the chart builder, recent conversation list, and result table scrollers
  reveal their scrollbar thumbs only on hover while preserving scroll behavior
  and layout stability.
- Kept the main chat scroll area styled and visible when content overflows.

## 0.9.10 - 2026-07-28

Backup tag: `v0.9.9-backup-before-v0.9.10`.

Changed:

- Added a compact Morandi-gray import progress display to the dashboard import
  area. Browser upload progress is shown during file transfer, followed by the
  existing backend processing phase for data parsing, Schema reading, and
  dataset saving.
- Increased the retained recent conversation limit from 10 to 25 using the
  existing conversation cleanup mechanism.
- Made the left recent conversation list an independent vertical scroll area,
  keeping the brand, new conversation button, and dashboard entry fixed.
- Added the bottom reminder `最多保存25轮历史对话` inside the history scroll area.

## 0.9.9 - 2026-07-28

Backup tag: `v0.9.8-backup-before-v0.9.9`.

Changed:

- Hid the debug workspace entry by default. The existing debug panel is now
  shown only after entering `/debug` as a standalone frontend command.
- Kept `/debug` out of the NL2SQL flow: it is not sent to the backend, not
  stored as a chat message, and does not trigger model calls or SQL execution.
- Removed the one-hour idle auto-new-conversation behavior; the current
  conversation remains active until the user explicitly creates a new one.
- Changed model context selection from the previous 5-minute follow-up window
  to a rolling 20-minute window within the same conversation, including related
  user/assistant turns.
- New conversations now automatically bind the latest `ready` dataset by
  dataset creation time. Existing conversations keep their saved dataset.

## 0.9.8 - 2026-07-28

Small compatibility fix on `v0.9.7`.

Fixed:

- Restored the `_is_quarter_series_question` compatibility alias in
  `query_service.py` by importing `is_quarter_series_question` from
  `fast_match_service.py`.
- Fixed a `NameError` during metric-knowledge prompt construction for ordinary
  unmatched questions after the old local fast-match helper functions were
  removed from `query_service.py`.

Verification:

- Reproduced the failing `NameError` from saved debug records.
- Verified the two failed questions now complete query planning and SQL
  execution.
- Verified backend and frontend proxy health.

Post-baseline micro-adjustment:

- Added backup tag `v0.9.8-backup-before-org-relax`.
- Relaxed only the organization text assumptions in strict deterministic fast
  match: province is no longer limited to Jiangsu, and organization type is no
  longer limited to rural commercial banks when a real runtime organization
  candidate is available.
- Runtime fast match now passes real organization candidates from
  `机构信息表.机构名称` into `fast_match_service.py`; candidate-based matching is
  exact and overlap-deduped, while unmatched values still fall back to the
  normal model path.

- Isolated the dashboard fast-match switch: deterministic QueryPlan assembly now
  runs only through `run_fast_match_plan_and_sql` when `fast_match_enabled=true`.
  When the switch is off, matched-looking questions use the normal Embedding +
  first-model NL2SQL path.

## 0.9.7 - 2026-07-28

Strict deterministic fast-match rebuild on `v0.9.6`.

Changed:

- Replaced the canonical `backend/app/services/fast_match_service.py` with the
  expanded deterministic fast-match implementation from the candidate
  `fast_match_service(1).py`.
- Added strict deterministic planners for high-confidence banking metric
  questions, while preserving the existing QueryPlan structure.
- Updated `run_fast_match_plan_and_sql` so the optional dashboard fast-match
  switch calls the deterministic service directly instead of loading the
  obsolete runtime `fast_match_dictionary.sqlite3`.
- Matched fast plans still pass through the existing QueryPlan contract check,
  SQL AST/schema validation, DuckDB execution, table-first response, metric unit
  append, debug records, and second natural-language answer generation.
- Unmatched, ambiguous, or schema-incompatible questions still fall back to the
  normal Embedding + M-Schema + first-model NL2SQL path.

Compatibility:

- No backend API field, request shape, response shape, dataset import,
  Embedding, M-Schema, SQL execution, chart generation, history format, or
  second-answer API was intentionally changed.
- The source tree keeps normal Python import semantics by using
  `fast_match_service.py` as the importable module name; the candidate
  `fast_match_service(1).py` was not imported directly because parentheses are
  not a valid Python module path.

Minimum tests:

- Passed backend `compileall`.
- Passed frontend `npm run build`.
- Verified backend and frontend proxy health report `0.9.7`.
- Verified direct fast-match service smoke test generates a deterministic
  quarter trend QueryPlan and executes one DuckDB result table with 4 rows.
- Verified HTTP conversation flow with `fast_match_enabled=true` skips
  Embedding, completes SQL planning/execution, returns the quarter table first,
  and completes the second natural-language answer asynchronously.

## 0.9.6 - 2026-07-28

Small fast-match preparation release on `v0.9.5`.
Backup tag: `v0.9.5-backup-before-v0.9.6`.

Changed:

- Added `backend/app/services/fast_match_service.py` as the dedicated module
  for deterministic fast-match QueryPlan assembly.
- Moved the existing deterministic quarter-end trend plan, performance plan,
  quarter parsing, business time-policy helper, SQL text escaping, and single
  task QueryPlan assembly out of `query_service.py`.
- `query_service.py` now imports those helpers through compatibility aliases,
  so existing call sites, QueryPlan shape, SQL strings, validation path, model
  path, table-first return, answer generation, chart behavior, and debug data
  remain unchanged.
- Marked the old runtime SQLite fast-match dictionary as obsolete and removed
  `<data_root>\fast_match\fast_match_dictionary.sqlite3` from the local runtime
  data directory. The runtime dictionary was not tracked by Git.

Compatibility:

- No backend API, request field, response structure, dataset import, Embedding,
  M-Schema, LLM prompt contract, SQL validation/execution, chart logic, or
  frontend interaction was intentionally changed.
- This version is only the first split step before rebuilding fast match around
  the deterministic assembly structure.

## 0.9.5 - 2026-07-28

Small backend stability update on the accepted `v0.9.4` baseline.
Backup tag: `v0.9.4-backup-before-v0.9.5`.

Changed:

- Saved the current `0.9.4` baseline as a release commit and backup tag before
  making `0.9.5` changes.
- Extended the first-stage corrective retry so QueryPlan structure/coverage
  failures, SQL validation failures, SQL execution failures, and result
  contract failures can all feed a brief error reason back into one retry of
  the first NL2SQL model stage.
- The retry prompt keeps the original return-format contract, caps the added
  correction hint to 500 characters, and trims the original prompt body when
  needed so the total prompt length does not grow.
- Added compact business guidance for two common banking error classes:
  risk-style "last/bottom N" ranking uses higher values as worse for metrics
  such as overdue and non-performing loan ratios, and "non-performing +
  overdue as loan ratio" prefers adding the two ratio metrics when available.
- Added a small DuckDB compatibility repair for model-generated `SAFE_DIVIDE`
  expressions by relying on sqlglot to emit a DuckDB `CASE WHEN` expression
  before execution.

Compatibility:

- No frontend behavior, layout, API shape, dataset import, Embedding flow,
  metric dictionary lookup, SQL safety checks, second answer prompt, chart
  generation, or history format was changed.
- Corrective retry is still limited to one extra first-stage request and does
  not bypass SQL AST validation or result checks.

Minimum tests:

- Verified the retry prompt keeps the original length budget and preserves the
  return-format section.
- Verified `SAFE_DIVIDE` is converted to DuckDB-compatible SQL.
- Verified the ranking and `不良+逾期` business hints are generated for matching
  natural-language questions.
- Verified the current dataset contains the expected reference answers:
  overdue-loan-rate bottom three by business meaning are D/H/I at
  `1.36%/1.25%/1.23%`, and M city's 2025-12-31 non-performing plus overdue
  ratio is `1.21% + 1.04% = 2.25%`.

## 0.9.4 - 2026-07-27

Optional strict fast-match channel rebuilt on the accepted `v0.9.3` baseline.
Backup tag: `v0.9.3-backup-before-v0.9.4`.

Changed:

- Added a default-off dashboard `快速匹配` switch stored in localStorage and sent
  as the optional compatible request field `fast_match_enabled`.
- Added a runtime fast-match dictionary under
  `<data_root>\fast_match\fast_match_dictionary.sqlite3`; the generated runtime
  database is not tracked by Git.
- Added five strict templates from verified examples: single ratio,
  multi-organization best value, month-over-month delta, quarter-end trend, and
  metrics-versus-province-average.
- Fast match is isolated before the normal query chain. When the switch is off,
  no fast-match logic runs. When enabled but not matched, ambiguous, invalid, or
  unavailable, it immediately falls back to the existing metric dictionary,
  Embedding, M-Schema, first-model QueryPlan, SQL validation, execution, second
  answer, and chart flow.
- Matched fast plans still use the existing QueryPlan structure and pass through
  the existing SQL AST/schema/result-column/result-scope checks and SQL
  execution path.
- Added compact debug fields for fast-match status, template, method, duration,
  extracted parameters, fallback reason, and whether the first model was
  skipped.

Compatibility:

- Default behavior remains the original 0.9.3 model path.
- No existing QueryPlan schema, SQL validator, SQL executor, second answer,
  chart logic, dataset import, history format, or metric dictionary integration
  was replaced.
- Old frontends or requests without `fast_match_enabled` behave as `false`.

Minimum tests:

- Passed backend compile.
- Passed frontend `npm run build`.
- Verified switch-off status does not skip the first model.
- Verified five dictionary examples match and return SQL result tables.
- Verified a Q1/quarter trend query preserves the existing quarter-end logic.
- Verified non-match P50/P95 local overhead was about `0.67ms / 0.84ms`.
- Verified dictionary-missing state reports `dictionary_unavailable` and falls
  back without raising a user-facing error.

## 0.9.3 - 2026-07-27

Small answer-display cleanup on fixed `v0.9.2`.
Backup tags: `v0.9.2`, `v0.9.2-backup-before-v0.9.3`.

Changed:

- Tightened the second-model answer instruction so the visible answer should not
  use `---`, `###`, or Markdown bold markers, and chart recommendations must
  stay only in the hidden `<chart_recommendations>` block.
- Added backend cleanup before storing the final answer: removes paragraph
  separator lines, leading `###`, leading/trailing `**`, `**` after list
  numbers, and truncates any visible "图表推荐/图表建议" section.
- Added the same lightweight cleanup in the frontend display path so older
  stored answers with leaked chart-recommendation text are hidden from the
  normal answer area.

Compatibility:

- No dataset, Embedding, SQL planning, SQL execution, chart recommendation
  validation, API shape, or debug data source was changed.

Minimum tests:

- Backend answer-cleaning smoke check for Markdown markers and leaked chart
  recommendation text.
- Backend compile and frontend build.

## 0.9.2 - 2026-07-27

Runtime metric-knowledge dictionary integration on accepted `v0.9.1`.
Backup tag: `v0.9.1-backup-before-v0.9.2`.

Changed:

- Copied `metric_dictionary.sqlite3` and `build_report.json` into the runtime
  data directory under `metric_knowledge`; source dictionary files remain
  unchanged and runtime copies are not tracked by Git.
- Added startup dictionary status checking from `build_report.json`.
- Added a lightweight SQLite alias lookup before the first model call. It
  retrieves compact banking metric, terminology, and calculation-rule evidence
  such as Chinese/English names, abbreviations, aliases, units, formulas,
  dependencies, Q1/quarter, YoY, and MoM.
- The dictionary evidence is appended to the existing first-model prompt as a
  small supplement only. It does not replace Embedding candidates, M-Schema,
  QueryPlan validation, SQL validation, SQL execution, answer generation, chart
  logic, or history/debug data.
- Prompt growth is capped by `METRIC_KNOWLEDGE_MAX_PROMPT_CHARS = 500`; the
  injected content keeps only names, matched aliases, units, formulas,
  dependencies, time semantics, and key calculation expressions.
- Dictionary missing, damaged, or incompatible states fall back to the previous
  flow without failing startup or query execution.
- SQL planning debug now records dictionary status, metric/term/rule hit
  counts, injected candidate count, lookup duration, prompt added characters,
  and fallback state.

Compatibility:

- No endpoint path, request parameter, response structure, dataset import,
  Embedding request, model-call count, SQL execution flow, chart generation, or
  data structure was changed.
- No dependency was added.
- `build_report.json` is never added to model prompts and is only used for
  startup status checking.

Minimum tests:

- Passed backend `python -m compileall backend/app`.
- Passed frontend `npm run build`.
- Verified `不良贷款率`, `不良率`, `NPL ratio`, and `NPL率` resolve to the
  same core ratio candidate.
- Verified `Q1`/`一季度`, `同比`/`YoY`, and `环比`/`MoM` hit terminology or
  calculation-rule evidence.
- Verified derived metrics such as `存贷比` include formula and dependencies.
- Verified dictionary-missing fallback returns no prompt injection and does not
  raise an application error.

## 0.9.1 - 2026-07-26

Small compatibility update on accepted `0.9.0`. Backup tag:
`v0.9.0-backup-before-v0.9.1`.

Changed:

- Updated frontend package/display version and backend health/API version to
  `0.9.1`.
- Added lightweight metric-unit lookup after Embedding candidate selection.
  The backend performs one local batch DuckDB dictionary query against tables
  containing metric name/code/unit columns, then appends compact unit candidates
  to the first-model prompt.
- The unit lookup reuses existing metric candidates, does not add Embedding
  requests, and does not add model calls. Missing unit tables or unmatched units
  fall back to the existing flow without errors or guessed units.
- Added `metric_unit_lookup` planning debug metadata with status, matched count,
  and local lookup duration.
- Added a lightweight result-table unit fill: when exactly one selected metric
  has a matched unit and the returned table has metric values but no unit
  column, the backend appends `指标单位` locally. This does not mark the QueryPlan
  invalid and does not trigger an extra model request.
- Added narrow deterministic handling for accepted banking QA patterns:
  quarter trend questions now use each quarter's last available date instead of
  quarterly averages, and single-organization performance questions use core
  risk/profitability metrics with province-wide rank direction before labeling
  weak indicators.
- Reordered the right chart panel: smart-recommendation notice and restore
  button share one row, title stays at the top, chart preview and the
  generate/apply button are closer together, while type/field/Y-axis/export
  controls move below the preview.

Compatibility:

- No public API structure, NL2SQL main flow, chart generation logic, chart
  export logic, dataset import, model configuration, runtime data, API key, or
  history format was changed.
- No new dependency was added.
- Old datasets without a metric-unit table and old messages without chart
  recommendation fields remain compatible.

Minimum tests:

- Passed backend `python -m compileall backend/app`.
- Passed frontend `npm run build`.
- Checked unit lookup with a real metric dictionary table and a schema without
  unit columns; both use local logic only and keep model request counts
  unchanged.

## 0.9.0 - 2026-07-26

Full-stack chart enhancement on accepted `v0.8.8`. Backup tag:
`v0.8.8-backup-before-v0.9.0`.

Changed:

- Updated frontend package/display version and backend health/API version to
  `0.9.0`.
- Expanded local Chart.js charting to nine types: clustered column, stacked
  column, horizontal bar, line, pie, scatter, area, stock/OHLC, and combo
  column-line.
- Added simple business-user chart controls for title, type, axis/category,
  numeric fields, optional grouping, Y-axis start, label density, sort order,
  and legend visibility.
- Added smart chart recommendations to the existing second answer-generation
  model call using a hidden `<chart_recommendations>` block. No third model
  call was added.
- Backend strips the hidden machine block from the visible answer, validates
  chart type, real table IDs, real columns, and numeric fields, then stores
  valid items in the optional `chart_recommendations` assistant-message field.
- Invalid, malformed, or missing recommendations are ignored without failing the
  natural-language answer or hiding SQL tables. Old messages without
  `chart_recommendations` remain compatible.
- Result-table `生成图表` now auto-applies and renders a valid recommendation;
  otherwise it keeps the manual chart flow.
- Added local chart export to PNG, JPEG, CSV, and JSON. No backend export
  endpoint was added.
- Added light chart crowding controls: auto label skipping, deterministic
  render sampling for dense charts, and pie-category `其他` merging in automatic
  mode.

Compatibility:

- No SQL, Embedding, first-model QueryPlan, dataset import, model config, API
  key, runtime data, or result-table mutation path was changed.
- Charts still use only result tables already returned to the browser.
- Chart.js was retained; no ECharts, Plotly, new dependency, microservice,
  queue, cache service, vector database, or workflow framework was introduced.
- Table-first display behavior and second-answer failure recovery remain
  unchanged: SQL tables stay visible even when final answer or recommendation
  generation fails.

Minimum tests:

- Passed backend `python -m compileall backend/app`.
- Passed frontend `npm run build`.
- Added inline backend checks for recommendation extraction, hidden-block
  removal, invalid field/table dropping, invalid JSON fallback, no-block
  compatibility, and optional old-message behavior.
- Checked working diff excludes runtime data, uploads, logs, cache, DuckDB,
  Embedding indexes, API keys, `ChatSQLData`, `node_modules`, and dependency
  additions.

## 0.8.8 - 2026-07-26

Frontend-only layout polish on accepted `v0.8.7`. Backup tag:
`v0.8.7-backup-before-v0.8.8`.

Changed:

- Updated the visible frontend release version to `0.8.8`.
- Unified select controls with regular input borders, radius, and height.
- Adjusted the LLM configuration form proportions so the model name field is
  wider, the output mode select is shorter, and timeout/max-token/temperature
  fields share one equal-width row.
- Increased the default expanded right chart/debug workspace width by 24px.
- Added a native pointer-event drag divider between the main content area and
  right workspace. Drag width is clamped from the new default width to 50% of
  the page width and is not persisted.

Compatibility:

- No backend file, endpoint, request parameter, response field, database schema,
  dataset logic, model configuration logic, query flow, chart logic, or debug
  data source was changed.
- No dependency and no file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Checked the working diff contains no backend files and no dependency changes
  beyond the existing frontend package version.

## 0.8.7 - 2026-07-25

Frontend-only dashboard layout adjustment on accepted `v0.8.6`. Backup tag:
`v0.8.6-backup-before-v0.8.7`.

Changed:

- Updated the visible frontend release version to `0.8.7`.
- Split the dashboard left column into two independent white panels:
  `导入与管理` and `LLM 模型配置`.
- Kept dataset name, dataset code, save, and delete on one compact aligned row.
  Save/delete icons and text now stay horizontal instead of wrapping vertically.
- Adjusted the LLM form proportions so `接入类型` is narrower and `Base URL`
  receives the wider field.
- Added fixed visible labels for `请求超时（秒）`, `最大输出 Token`, and
  `Temperature`; the values `30`, `4000`, and `0` are no longer shown without
  context.
- Kept the enable checkbox and `启用此模型配置` text on one action row with
  save/reset.
- Tightened model-card text wrapping so model names, URLs, and action buttons do
  not split into single-character vertical text.
- Centered the left navigation `仪表盘` icon/text group to match `新建对话`.

Compatibility:

- No backend file, endpoint, request parameter, response field, database schema,
  dataset logic, model configuration logic, query flow, chart logic, or debug
  data source was changed.
- No dependency and no file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Verified backend and Vite proxy health are reachable and remain backend
  version `0.8.6`.
- Verified the working diff contains no backend files and no dependency changes
  beyond the existing frontend package version.

## 0.8.6 - 2026-07-24

Backend-only stability fix on accepted `v0.8.5`. Backup tag:
`v0.8.5-backup-before-v0.8.6`.

Confirmed causes:

- The same natural-language question could produce different results because
  the first model sometimes generated semantically weaker SQL while still
  passing table/column AST validation. Examples observed in stored debug records
  included `机构名称='G市农商行'` instead of the stored full value
  `江苏省G市农商行`, model-created `机构编号 LIKE '32%'`, and treating a derived
  ratio such as `存贷比` as a stored metric name.
- These SQL variants were syntactically valid and used existing columns, so the
  backend previously executed them and returned empty tables instead of forcing
  a corrected QueryPlan/SQL.

Changed:

- `backend/app/services/query_service.py` now builds a lightweight real-value
  index for institution/metric names and codes from the selected DuckDB dataset.
- SQL validation checks equality, `IN`, and `LIKE` filters on those dictionary
  columns before execution.
- Unique shortened values are normalized to the stored value, for example a
  unique city-bank short name can be expanded to the full stored institution
  name.
- Nonexistent direct metrics, impossible code filters, and unmatched dictionary
  names are rejected as `SQL_VALIDATION_ERROR`, allowing the existing first-model
  corrective retry to regenerate SQL with real values or real component metrics.
- The first-model system prompt adds the same compact generic rule: filters must
  use real candidate values, and ratios without a stored metric must be computed
  from component metrics.
- Updated backend version reporting to `0.8.6`.

Interface compatibility:

- No frontend file, endpoint path, request parameter, response field, database
  schema, import flow, Embedding flow, LLM provider API, chart logic, or debug
  data source was changed.
- No file or dependency was added.

Minimum tests:

- Passed Python `compileall` for `backend/app`.
- Verified real dataset value index includes institution and metric dictionary
  values.
- Verified a unique short institution name is normalized before execution.
- Verified impossible institution-code `LIKE` filters fail before execution.
- Verified nonexistent direct metric filters such as a derived ratio fail before
  execution and are eligible for corrective retry.

## 0.8.5 - 2026-07-24

Backend stability fix on accepted `v0.8.4` plus hotfix commits. Backup tag:
`v0.8.4-hotfix-backup-before-v0.8.5`.

Confirmed causes:

- Repeated “SQL引用了未授权表” failures were caused by the first model using
  QueryPlan task IDs such as `T1` and `T2` as intermediate SQL sources. Those
  IDs are not physical database tables, and the backend previously did not
  materialize declared `depends_on` tasks for later SQL tasks.
- Single-institution ranking answers such as every rank being `1` were caused
  by SQL that filtered the target institution in the same SELECT where
  `RANK`/`DENSE_RANK`/`ROW_NUMBER` was computed. That ranks only the filtered
  one-row scope instead of the full institution scope.

Changed:

- `backend/app/services/query_service.py` now compiles declared task
  dependencies into CTEs before SQL validation and execution. Later tasks can
  reference prior task IDs only through their explicit `depends_on` contract.
- SQL AST validation now rejects same-SELECT organization filtering before
  window ranking. Correct SQL must rank all institutions first and filter the
  requested institution in an outer SELECT/CTE.
- The first-model system prompt adds the same compact constraints: task IDs are
  not physical tables, and ranking must be computed before target filtering.
- Updated version reporting to `0.8.5`.

Interface compatibility:

- No endpoint path, request parameter, response field, database schema, data
  import flow, Embedding flow, LLM provider API, chart logic, or debug data
  source was changed.
- Frontend behavior and layout were not changed; only existing version text was
  updated to keep the release version visible.
- No file or dependency was added.

Minimum tests:

- Passed Python `compileall` for `backend/app`.
- Verified QueryPlan task dependency SQL is compiled into CTEs and executes in
  DuckDB.
- Verified raw `FROM T1` without dependency CTE still fails as an unauthorized
  table.
- Verified valid “rank all institutions first, filter later” SQL passes.
- Verified invalid “filter target institution first, then rank” SQL fails before
  execution and is eligible for first-model corrective retry.
- Passed frontend `npm run build`.

## 0.8.4 - 2026-07-24

Model-request speed optimization on accepted `v0.8.3` plus the chat-order
hotfix commits. Backup tag: `v0.8.3-hotfix-backup-before-v0.8.4`.

Changed:

- Unified backend and frontend version reporting to `0.8.4`.
- For DeepSeek-compatible endpoints or model names, the first QueryPlan model
  request and the second natural-language answer request now explicitly send
  `thinking: {"type":"disabled"}` by default.
- Added a small front-end `思考模式` switch above the send button. When enabled
  for the current request, the backend omits the `thinking` field so the model
  can use thinking mode.
- Cleaned legacy plain-text assistant failure messages at display time so saved
  historical errors no longer expose task IDs such as `T1` and show
  `请修改描述后重试。` after corrective retry failure.
- Kept the first call's existing structured QueryPlan behavior.
- Kept the second-answer prompt content unchanged, but ensured the second call
  remains plain text (`prompt_text`) and sends no JSON Output /
  `response_format`.
- Added model-parameter debug fields so the request behavior can be verified:
  `thinking_disabled_sent`, `thinking`, and `response_format_sent`.

Interface compatibility:

- No API endpoint path, response field, database schema, SQL execution logic,
  Embedding logic, chart logic, or prompt content changed. The existing message
  request accepts a compatible optional `thinking_enabled` flag.
- No dependency and no file was added.

Minimum tests:

- Passed Python `compileall` for `backend/app`.
- Passed FastAPI `create_app()` version check for `0.8.4`.
- Passed frontend `npm run build`.
- Verified generated DeepSeek QueryPlan request body includes
  `thinking: {"type":"disabled"}`.
- Verified generated DeepSeek final-answer request body includes
  `thinking: {"type":"disabled"}` and does not include `response_format`.
- Verified enabling `思考模式` omits `thinking` from both model request bodies.

## 0.8.3 - 2026-07-24

Frontend chat-order hotfix on accepted `v0.8.2`. Backup tag:
`v0.8.2-backup-before-v0.8.3`.

Changed:

- Replaced raw message-order rendering with a derived fixed turn layout in the
  existing chat component. Each turn renders these slots in order:
  `user_message`, `loading_status`, `result_tables`, `final_answer`, and
  `error_status`.
- Added optimistic front-end display for the current request: after send, the
  user question appears immediately on the right and a lightweight `思考中`
  indicator appears below it on the left.
- Kept returned tables ahead of the final natural-language answer. Multi-task
  tables use the backend table order and render together before the answer.
- If tables return while the second answer is still running, the loading text
  changes to answer generation state without delaying table display.
- If answer generation fails after tables exist, the tables remain visible and
  `回答生成失败` is shown below them.
- Adjusted chat auto-scroll so send still jumps to the new turn, while poll
  updates only follow if the user is already near the bottom.
- Removed ordinary result-table execution milliseconds from the chat table
  header. Headers now show row counts only, while debug timing remains intact.

Interface compatibility:

- No backend directory was modified.
- No API endpoint, request payload, response field, database, data structure,
  query flow, SQL, LLM, Embedding, chart detection/rendering logic, or debug
  data source changed.
- No dependency and no file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Verified backend and Vite proxy health remain reachable.
- Verified Vite serves the current frontend source with version `0.8.3`.
- Verified no `backend` or `frontend/src/api` diff exists.

## 0.8.2 - 2026-07-24

Frontend page adjustment release on accepted `v0.8.1`. Backup tag:
`v0.8.1-backup-before-v0.8.2`.

Changed:

- Renamed the left navigation `数据集` entry and the former dataset page title to
  `仪表盘`. The route and all dataset/model/Schema functions remain unchanged.
- Updated the dashboard description to
  `导入结果、数据集管理、大模型选择和Schema预览`.
- Adjusted the dashboard desktop layout to a wider import/management/model area
  and a narrower Schema preview area, roughly 65/35, with the existing
  single-column fallback on narrow widths.
- Kept MySQL Schema reading folded, but removed the outer LLM configuration fold
  so the current model card and full model form are visible when entering the
  dashboard.
- Tightened dashboard controls, upload buttons, dataset save/delete controls,
  model cards, and Schema rows with compact spacing and weak dividers.
- Aligned the chat topbar so current dataset, current model, refresh, and delete
  controls stay on one vertically centered row with stable 40-44px control
  height.
- Changed the collapsed right workspace to show only one white arrow button,
  without a gray vertical rail.
- Preserved the mutually exclusive `图表` / `调试` tabs, emphasized the chart tab,
  subdued the debug tab, and made debug selection show the full debug panel
  directly without a second `展开` button.
- Moved the global palette further toward black/white/gray and low-saturation
  accents using the existing CSS variables.

Interface compatibility:

- No backend directory was modified.
- No API endpoint, request payload, response field, database, data structure,
  SQL, LLM, Embedding, dataset/import flow, query flow, chart detection/rendering
  logic, or debug data source changed.
- No dependency and no file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Verified backend and Vite proxy health remain reachable.
- Verified Vite serves the current frontend source with version `0.8.2`.
- Verified changed files are limited to existing frontend files and docs.
- Verified no `backend` or `frontend/src/api` diff exists.

## 0.8.1 - 2026-07-23

Frontend interface repair release on accepted `v0.8.0`. Backup tag:
`v0.8.0-backup-before-v0.8.1`.

Changed:

- Removed the visible `idle` second line from recent conversations. Each row is
  now a compact single-line item with the existing status dot, title, and
  ellipsis.
- Added a frontend-only empty-conversation reuse guard. Repeated `新建对话`
  clicks reuse the current/listed empty conversation until the first user
  question is sent.
- Replaced the full-width status strip with one top-centered floating Toast.
  Existing status/error triggers are preserved; new messages replace the
  previous Toast and hide after about eight seconds.
- Removed the duplicate right-workspace toggle from the top toolbar. The only
  toggle now lives on the right workspace boundary; refresh and delete remain in
  the top toolbar.
- Changed the right workspace to one active panel at a time: `图表` or `调试`.
  Switching tabs preserves local state and does not call the backend or model.
- Made the current-model display a single-line chip:
  `当前模型：配置名称 / 模型名称`, with ellipsis and full-name hover title.
- Tightened the centered Q&A layout so the conversation body, result tables, and
  input composer share the same max-width axis and wider page margins.

Interface compatibility:

- No backend directory was modified.
- No API endpoint, request payload, response field, database, data structure,
  SQL, LLM, Embedding, dataset/import flow, conversation backend logic, or chart
  detection/rendering logic changed.
- No dependency and no file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Verified changed files are limited to existing frontend files and docs.
- Verified backend and Vite proxy health remain reachable.
- Verified no `backend` or `frontend/src/api` diff exists.
- Verified the Vite-served frontend source exposes version `0.8.1`.

## 0.8.0 - 2026-07-23

Frontend visual polish and freeze release on accepted `v0.7.0`. Backup tag:
`v0.7.0b-backup-before-v0.8.0`.

Changed:

- Unified frontend visual variables for backgrounds, text, borders, brand,
  success, and error colors.
- Switched the frontend font stack to system fonts and normalized base text to
  14px with 1.6 line-height.
- Reduced visual weight across the shell: weak 1px borders, 8-12px component
  radius, 16-18px input radius, no heavy card shadows, and short 140ms focus and
  hover transitions.
- Restyled the left navigation as a flatter list. Recent conversations no
  longer read as separate heavy cards, and current/idle states are quieter.
- Restyled chat messages so user messages use a muted gray surface instead of a
  saturated blue block, while assistant answers read as normal content.
- Harmonized result tables, SQL folds, chart panel, and debug panel with the
  same weak-border, white-surface, compact-control style.
- Kept MySQL and LLM configuration in existing collapsible sections on the
  dataset page, and improved dataset/schema layout spacing.
- Added focus-visible treatment and aria labels for existing icon buttons.
- Added responsive style rules around 1280px, 1024px, and narrow widths so the
  right workspace collapses first and the dataset page can fall back to one
  column.

Frontend freeze:

- The current frontend structure is marked as stable. Later versions should only
  fix explicit bugs unless a new accepted version explicitly unfreezes frontend
  structure.

Interface compatibility:

- No backend directory was modified.
- No API endpoint, request payload, response field, SQL, LLM, Embedding,
  M-Schema, dataset, upload, conversation, query flow, or chart generation logic
  changed.
- No dependency and no file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Verified backend and Vite proxy health remain reachable.
- Verified changed files are limited to existing frontend files and docs.
- Verified Vite serves the 0.8.0 frontend source.

## 0.7.0 - 2026-07-23

Frontend-only local chart generation on accepted `v0.6.9`. Backup tag:
`v0.6.9-backup-before-v0.7.0`.

Changed:

- Added local chart generation in the existing right workspace chart panel.
- Result-table `生成图表` now only selects the returned table and opens the chart
  builder. No chart instance is created until the user clicks `生成` inside the
  chart panel.
- Added chart type selection for line, bar, and pie charts.
- Added frontend field recognition from existing `columns` and `rows`:
  text/category fields, ordered date/month/quarter/year fields, and numeric
  fields. Numeric strings are converted only for drawing and the original table
  remains unchanged.
- Line and bar charts can use up to 3 numeric series. Pie charts require one
  category field and one non-negative numeric field, and reject time-series,
  negative, too-many-category, or non-positive-total data with a local chart
  error.
- Chart errors are isolated to the chart panel and do not change query status,
  SQL tables, natural-language answers, debug records, uploads, datasets, or
  conversations.

Dependency:

- Added one frontend dependency: `chart.js`.

Interface compatibility:

- No backend directory was modified.
- No API endpoint, request payload, response field, SQL, LLM, Embedding,
  M-Schema, dataset, upload, conversation, or query flow changed.
- No new frontend file was added.

Minimum tests:

- Passed frontend `npm run build`.
- Verified the backend and Vite proxy still report health.
- Verified chart code is local to `App.vue` and does not call backend or model
  APIs.
- Verified chart creation is tied to the chart-panel `生成` action, not the
  result-table `生成图表` action.

## 0.6.9 - 2026-07-23

Corrective-prompt size hotfix on `v0.6.8`. Backup tag:
`v0.6.8-backup-before-v0.6.9`.

Confirmed cause:

- The reported failure happened during the corrective first-model retry, not in
  SQL execution or second-answer generation.
- Recent debug records showed corrective prompts of about 4.8K characters and
  request bodies of 7.8K-8.9K bytes because the retry prompt appended a full JSON
  diagnostic object plus the previous QueryPlan.
- The retry request then failed before any HTTP status was returned with
  `MODEL_REQUEST_ERROR / llm_connection_failed` and low-level detail
  `[Errno 2] No such file or directory`.

Changed:

- Corrective prompts now append only a short natural-language error reason to
  the original first Prompt.
- Removed detailed JSON diagnostics such as `result_column_check`,
  `result_scope_check`, `database_error`, and `ast_validation` from corrective
  prompts.
- Removed previous full QueryPlan/raw model output from corrective prompts.
- Added a 500-character cap for the corrective suffix beyond the original first
  Prompt.
- Replaced urllib-based model POST calls with a direct `http.client` POST path to
  avoid intermittent opener/proxy-layer connection failures without changing
  model request content.
- Final-answer generation now retries transient network failures up to three
  times after the first attempt, still serially and still reusing the already
  returned SQL table instead of re-running SQL.
- After SQL has returned a real table, result scope or grain checks no longer
  fail the whole query. Those findings are kept in debug output and passed to
  the second-answer model as a short result hint so the table can still be shown
  and the answer can explain missing scope or grain mismatch from the real data.
- Quarter wording hotfix: Q1/Q2/Q3/Q4 and Chinese quarter wording now add an
  explicit first-prompt time policy. The policy tells the model not to compare
  date columns with literal values such as `2025Q1`, and quarter trend queries
  must return one row per quarter using `YYYYQn`, based on quarter aggregation
  or the last available quarter-end date according to metric grain.
- Result-scope debug now warns when a quarter question returns daily/monthly
  detail rows instead of quarter-grain rows.

Interface compatibility:

- No public API endpoint, request payload shape, response field, frontend layout,
  upload flow, dataset logic, Embedding, M-Schema, SQL execution, or chart
  placeholder changed. The second-answer prompt may include a short result-scope
  hint only when SQL returned a table but scope/grain checks found issues.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Verified SQL corrective prompt keeps the original Prompt and adds under 500
  characters.
- Verified JSON/type corrective prompt keeps the original Prompt and adds under
  500 characters.
- Verified direct HTTP POST smoke test.
- Verified final-answer generation can recover when two transient connection
  failures are followed by a successful third request.
- Verified quarter questions include the dynamic time policy and daily detail
  rows are marked with a `time_grain` warning.

## 0.6.8 - 2026-07-23

Model output-limit hotfix on `v0.6.7`. Backup tag:
`v0.6.7-backup-before-v0.6.8`.

Changed:

- Removed `max_tokens` from both first-model and second-model request bodies, so
  the application no longer imposes an output token limit on model responses.
- Kept the existing LLM config `max_tokens` field for API/UI compatibility, but
  debug now marks it as `configured_max_tokens` with `max_tokens_sent=false`.
- Kept truncated-output detection. If a provider still returns
  `finish_reason=length` because of its own service-side limit, the backend still
  rejects the incomplete response instead of parsing half JSON.

Interface compatibility:

- No public API endpoint, request payload shape, response field, frontend layout,
  upload flow, dataset logic, Embedding, M-Schema, QueryPlan validation, SQL
  execution, chart placeholder, or second-answer prompt changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Verified generated model request bodies no longer contain `max_tokens`.
- Verified debug model params report `max_tokens_sent=false`.

## 0.6.7 - 2026-07-23

Corrective-retry wording hotfix on `v0.6.6`. Backup tag:
`v0.6.6-backup-before-v0.6.7`.

Confirmed cause:

- The `0.6.6` corrective retry did not rerun Embedding or start a new full
  query. It fed the original first Prompt and validation error back to the first
  model so the model could generate QueryPlan again.
- The frontend/debug wording said `正在重新查询`, which was technically
  inaccurate and could make the user think the whole retrieval/query chain was
  being restarted.

Changed:

- Replaced the misleading `正在重新查询` wording with
  `正在反馈错误原因并重新请求第一次模型生成 QueryPlan` in frontend debug text.
- Updated backend retry reason/debug strings and failure suffix to match the
  actual behavior.
- Updated version display and docs to `0.6.7`.

Interface compatibility:

- No public API endpoint, request payload, response field, frontend layout, CSS,
  upload flow, dataset logic, Embedding, M-Schema, QueryPlan validation, SQL
  execution, chart placeholder, or second-answer prompt changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Verified backend and Vite proxy health report `0.6.7`.

## 0.6.6 - 2026-07-23

First-model corrective retry hotfix on `v0.6.5`. Backup tag:
`v0.6.5-backup-before-v0.6.6`.

Confirmed cause:

- A local self-check of repeated F-city risk-indicator questions showed the same
  dataset, same context, same Embedding candidates, and same first-prompt hash
  could still produce different first-model outputs.
- Observed drift included nonexistent English columns such as `t.data_date`,
  malformed QueryPlan fields such as object-array `selected_metrics`, and
  occasional valid QueryPlans for the same user question.
- The application was usually rejecting these bad outputs correctly, but it had
  no targeted way to send the validation reason back to the first model before
  failing the user-visible query.

Changed:

- Increased the effective minimum QueryPlan wait window from 90 seconds to 120
  seconds. Final-answer minimum timeout remains 120 seconds.
- QueryPlan structural repair now includes the original first Prompt and the
  concrete JSON/type/schema validation reason.
- If a first QueryPlan passes structure but later fails SQL AST validation,
  result-column validation, QueryPlan coverage/reference validation, or another
  first-model output contract check, the backend sends the original first Prompt,
  failed QueryPlan/SQL, and sanitized error reason back to the first model once.
- The corrective retry is serial and uses a derived retry request id; it does not
  create a duplicate user message or a parallel query.
- When corrective retry metadata exists, the frontend debug panel shows the
  original reason and `正在重新查询` state. If the retry still fails, the normal
  answer area keeps the failure reason and notes that the app already retried.
- The second-answer input, output, short instruction, and table-first answer flow
  were not changed.

Interface compatibility:

- No public API endpoint, request payload, response field, frontend layout, CSS,
  chart placeholder, upload flow, dataset logic, Embedding, M-Schema, second
  answer prompt, or SQL execution interface changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Verified first-model JSON/type repair prompt includes the original Prompt and
  concrete error reason.
- Verified QueryPlan effective timeout is 120 seconds and final-answer effective
  timeout remains 120 seconds.
- Verified SQL-validation corrective retry prompt includes the failed SQL reason
  and `正在重新查询` notice.
- Verified a mocked corrective retry calls the first model once, re-executes once,
  and returns the existing `answer_status=running` assistant payload.

## 0.6.5 - 2026-07-23

Interrupted final-answer recovery hotfix on `v0.6.4`.

Confirmed cause:

- Some conversations showed `SQL 表格已返回，正在生成答案` but never received a
  final answer.
- The corresponding `answer_generation` debug records were still
  `status=running` with only `{"status":"running","table_count":...}`.
- Backend logs showed repeated Uvicorn reloads while the answer background
  thread was running. Because the second answer stage was held only in a
  process-local daemon thread, reload or process restart could kill the thread
  after SQL tables had already been saved.

Changed:

- Added a recovery path for interrupted final-answer jobs. The app can rebuild a
  second-answer job from persisted messages, SQL result tables, request id, and
  debug records.
- On backend startup, the newest stale `answer_generation=running` record is
  recovered automatically.
- Conversation list/detail access also triggers recovery for stale running
  answer jobs, with an in-process lock to avoid duplicate recovery.
- If a running answer record cannot be reconstructed, it is marked with
  `ANSWER_JOB_RECOVERY_ERROR` and a non-empty debug payload instead of staying
  `running` forever.
- Recovery is limited to one job per trigger to avoid accidental batch model
  calls.

Interface compatibility:

- No public API endpoint, request shape, response field, frontend layout, chart
  placeholder, upload flow, dataset logic, Embedding, QueryPlan, or SQL
  execution interface changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Added and ran a local recovery smoke test with a temporary conversation:
  a persisted `answer_generation=running` record was reconstructed and the
  assistant payload was updated to `answer_status=completed` without calling a
  real model.

## 0.6.4 - 2026-07-23

Final-answer model request hotfix on `v0.6.3`.

Confirmed cause:

- The SQL execution path had succeeded and returned the real result table.
- The failed `answer_generation` record showed the second LLM input was present:
  original question, one SQL result table, and the short answer instruction.
- The failure happened before any model content was returned. The recorded
  attempt had no HTTP status, no finish reason, no content, and
  `error_detail_type=llm_connection_failed`.
- The final-answer failure path also hid a later failed retry attempt when the
  retry itself failed, which made the debug panel look blank or incomplete.

Changed:

- Final-answer requests no longer send an empty `system` message. QueryPlan
  requests still send the existing non-empty system prompt.
- Final-answer generation now uses an effective minimum timeout of 120 seconds.
  QueryPlan generation remains at a 90-second minimum.
- Final-answer `max_tokens` is capped at 1024 because the second call only needs
  a short natural-language answer from returned tables.
- The second prompt's short instruction now explicitly says to answer only the
  user question, use the returned table, treat NULL as missing, and not guess
  missing units.
- URL-layer errors are classified more accurately as timeout, connection reset,
  incomplete read, or connection failure when possible.
- Failed final-answer attempts are now appended to debug even when a retry also
  fails, so the `answer_generation` panel shows every request attempt instead of
  blank model-return/final-answer sections only.
- The frontend answer-generation debug panel now includes a `请求尝试` section.

Interface compatibility:

- No public API endpoint, request payload, response field, dataset/import flow,
  Embedding, M-Schema, QueryPlan, SQL execution contract, chart placeholder, or
  0.6.0 layout changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Verified the final-answer request body omits empty system messages.
- Verified the final-answer effective timeout is 120 seconds when model config
  timeout is 30 seconds.
- Verified final-answer `max_tokens` is capped at 1024 while preserving the
  configured value in debug.
- Verified multiple failed final-answer attempts are retained in debug.
- Verified the H-city four-metric result table can be sent directly to the
  second answer generator and returns the expected directions without guessing
  missing units.

## 0.6.3 - 2026-07-23

Model request timeout hotfix on `v0.6.2`.

Confirmed cause:

- Recent failed `sql_planning` debug records showed prompts were built and sent
  to the configured DeepSeek-compatible endpoint. Each failed attempt waited
  roughly 33-39 seconds with no HTTP status or content, then raised
  `llm_timeout`. The active model configuration had `timeout_seconds=30`, so
  the app was cutting off slow model responses rather than failing before send.

Changed:

- QueryPlan generation now uses an effective minimum timeout of 90 seconds.
- Final-answer generation now uses an effective minimum timeout of 60 seconds.
- The existing user-facing `timeout_seconds` config is still respected when it
  is higher than the minimum, and all effective timeouts remain capped at 300
  seconds.
- Model debug now records configured timeout, effective timeout, request bytes,
  elapsed request time, and timeout detail for both successful and failed
  attempts.
- Timeout error text now says the request was sent but waiting for the model
  response timed out, instead of implying the request was never sent.
- Added a small metric-candidate intent boost for broad user words such as
  `存款`, `贷款`, `不良率`, and `净利润`, so the prompt includes the real metric
  dictionary records `各项存款余额`, `各项贷款余额`, `不良贷款率`, and `净利润`
  instead of forcing the model to guess metric names.
- Fixed SQL identifier auto-quoting boundaries so a real column name is not
  quoted inside a longer CTE or alias name. For example `贷款指标编号` no longer
  becomes invalid SQL such as `贷款"指标编号"`.

Interface compatibility:

- No public API endpoint, request payload, response field, frontend layout,
  chart placeholder, dataset/import flow, Embedding, M-Schema, QueryPlan, or SQL
  execution contract changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed frontend `npm run build`.
- Verified timeout policy helper reports 90 seconds for QueryPlan and 60
  seconds for final answer when the stored model config is 30 seconds.
- Verified the H-city change-direction question receives the four intended
  metric candidates before prompt generation.
- Verified a complex Chinese `WITH` query using CTEs such as `贷款指标编号` and
  `指标编号集` parses after safe auto-quoting.

## 0.6.2 - 2026-07-22

Emergency stability hotfix on `v0.6.1`.

Changed:

- Relaxed the new `0.6.1` result-scope gate so valid SQL tables are not blocked
  before final answer generation.
- Fixed organization extraction so phrases such as `帮忙查一下江苏省E市农商行`
  and `贷款余额比江苏省K市农商行` do not become fake organization names.
- Single-organization scalar results, such as one bank's non-performing loan
  rate, no longer require an organization-name output column.
- Two-organization scalar comparison results, such as balance differences, no
  longer require a returned organization column when the SQL returns one
  verified scalar table.
- Winner/extreme questions such as `三家谁存款最多` may return either the full
  comparison rows or only the winning institution; reduced-grain cases are kept
  as debug warnings instead of hard failures.
- Actual out-of-range organizations, empty tables, and all-NULL tables still
  fail before final answer generation.

Interface compatibility:

- No public API endpoint, request shape, response field, frontend layout, chart
  placeholder, upload flow, dataset logic, Embedding, QueryPlan, or SQL
  execution interface changed.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed focused result-scope tests for the three reported query shapes:
  single-bank scalar, two-bank scalar difference, and three-bank winner.
- Confirmed out-of-range organization rows still fail.

## 0.6.1 - 2026-07-22

Stability repair release built on accepted `v0.6.0`. Backup tag:
`v0.6.0-backup-before-v0.6.1`.

Changed:

- Updated backend and frontend version to `0.6.1`.
- Kept the `0.6.0` page layout, right workspace, chart placeholder, dataset
  page, upload/import UI, and existing API shapes.
- Strengthened SQL AST validation in `backend/app/services/query_service.py`:
  physical tables, CTEs, subqueries, table aliases, and column aliases now have
  separate scopes. Invalid references such as `a.机构编号` fail unless alias
  `a` actually exposes that column.
- Added final SELECT output-column extraction from sqlglot AST before SQL
  execution. `expected_columns` are checked against output aliases before
  execution and against real result columns after execution.
- Added one safe alias repair for unaliased SELECT expressions when SELECT item
  count exactly matches `expected_columns`.
- Added result-scope validation before second-answer generation: empty result,
  all-NULL result, explicit multi-organization coverage, out-of-scope
  organizations, row grain, and top/bottom ranking row count are classified.
- Captured DuckDB BinderException and other execution failures as
  `SQL_EXECUTION_ERROR` with sanitized database error summary and actual SQL in
  debug.
- Froze request snapshot in `backend/app/services/conversation_service.py`:
  request ID, original question, selected dataset, Schema version, context
  segment, and context state are recorded at input time.
- Backend now rejects no-dataset sends before writing user/assistant messages.
  Existing conversation-bound dataset is used as the send snapshot when the
  frontend selected value is temporarily empty.
- Added in-process duplicate `request_id` protection so the same request cannot
  create duplicate user messages while a request is active.
- Improved metric debug summaries to include code and unit, with missing units
  shown as `未提供`.
- Improved `backend/app/services/llm_service.py` network handling:
  ConnectionResetError, RemoteDisconnected, IncompleteRead, timeout, and 5xx
  connection failures are normalized to `MODEL_REQUEST_ERROR` and retried at
  most once, serially. Authentication, bad request, and model-not-found errors
  are not retried.
- Added one retry path and full debug fields for second-answer model calls.
- Ensured second-answer failures preserve returned SQL tables and write
  non-empty debug: second actual input, attempts, model return preview, finish
  reason, elapsed time, final answer, and error category.
- Frontend send logic freezes dataset ID before request and blocks empty-dataset
  sends before clearing the input box. The existing debug panel now displays
  result-scope and database-error details.

Confirmed causes and fixes:

- Missing/invalid SQL columns came from global alias lookup that did not model
  CTE/subquery output. Fixed with scoped AST source maps in `query_service.py`.
- `expected_columns` mismatches came from direct string comparison and delayed
  detection after execution. Fixed with AST output extraction plus safe
  normalization and post-execution recheck.
- BinderException reached the UI as a generic failure. Fixed by catching DuckDB
  errors in `_execute_one` and recording sanitized SQL/error details.
- `data_date` was generated by the model despite only `数据日期` existing.
  Scoped validation now rejects it before execution; Prompt still explicitly
  forbids it.
- Same question returning NULL, 0 rows, 9 rows, or a merged 1 row was caused by
  weak result grain validation and variable model SQL. Fixed by validating
  explicit organization coverage, outside organizations, row grain, empty
  result, and all-NULL result before answer generation.
- Missing metric unit could be guessed by the second model. Prompt evidence and
  debug now expose unit or `未提供`, and the second prompt says missing units
  must be stated.
- Model timeout/connection reset/incomplete read were not consistently
  normalized or retried. Fixed in `llm_service.py`.
- Second model failure debug was blank because failure branches did not attach
  second input/attempt/debug payload. Fixed in `generate_final_answer` and the
  answer thread failure handler.
- Historical conversations could send an empty dataset snapshot. Fixed by
  backend fallback to the conversation-bound dataset and frontend send-time
  snapshot.
- Duplicate sends could race before database debug records existed. Fixed with
  active request ID protection and the existing persisted debug-record check.

Interface compatibility:

- No public endpoint added or removed.
- Existing dataset, import, Schema, Embedding, LLM config, conversation, cancel,
  and delete endpoints remain compatible.
- Existing assistant message envelope remains compatible.
- No chart generation or 0.7.0 functionality added.

Deleted:

- No source files deleted.
- No runtime data, uploads, user databases, logs, indexes, caches, or model
  files touched.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed FastAPI health after restart: backend and Vite proxy report `0.6.1`.
- Passed frontend `npm run build`.
- Passed SQL validator smoke tests for valid alias, invalid alias column, CTE
  output column, invalid CTE column, expected-column mismatch, safe alias
  repair, and missing `data_date`.
- Passed Chinese identifier validation with `数据日期` present and `data_date`
  rejected.
- Passed result-scope smoke tests: three specified institutions return exactly
  three rows; 9-row duplicate grain and 1-row merge fail.
- Passed no-dataset send smoke test: no user message is written before error.
- Passed DuckDB BinderException smoke test: `SQL_EXECUTION_ERROR` with sanitized
  database error summary.
- Passed retry classification smoke test: connection reset, incomplete read,
  and timeout retry; auth and bad request do not retry.
- Passed second-answer failure debug smoke test: failed debug contains
  second_input, attempts, retry flag, and stage duration.

Manual test steps:

- See `README.md`.
- Real-model SQL correctness, repeated query stability, yearly average
  semantics, multi-metric banking questions, ranking interpretation, colloquial
  wording, and total answer quality still require human acceptance.

Known issues:

- SQL repair is intentionally limited to safe output alias repair. It does not
  ask the model for a second SQL rewrite in this release.
- Result-scope validation is conservative for explicit multi-organization
  questions and may reject ambiguous one-row winner-only SQL that lacks the
  compared organizations.
- MySQL SQL execution remains unavailable because passwords and connection
  strings are not persisted by design.
- Formal chart generation remains intentionally unimplemented.

## 0.6.0 - 2026-07-22

Frontend-only workspace layout adjustment built on accepted `v0.5.0`.
Backup tag: `v0.5.0-backup-before-v0.6.0`.

Changed:

- Reorganized the question page into left navigation, centered Q&A, and a
  collapsible right workspace.
- Kept the left navigation width in the 240-280px range with product/version,
  new conversation, dataset entry, and recent conversations preserved.
- Added the current model display beside the current dataset selector in the
  Q&A top bar.
- Centered chat content with a constrained maximum width instead of stretching
  messages across the full browser width.
- Moved the existing five-stage debug view into the right workspace. The debug
  panel is folded by default and independently scrollable when expanded.
- Added a chart workspace container and empty/pending state only. No chart data
  is generated and no fake chart is rendered.
- Grouped result-table actions as `查看SQL`, `生成图表`, `导出结果`, and
  `复制数据`. `生成图表` only opens/selects the chart container.
- Preserved SQL content and kept SQL folded by default.

Interface compatibility:

- No backend files were changed for this release.
- No public API endpoint, request parameter, response field, conversation
  payload structure, dataset logic, Embedding retrieval, M-Schema, QueryPlan,
  SQL validation/execution, or LLM call order changed.
- Backend health remains the accepted `0.5.0` capability
  `query_plan_sql_execution_answer_generation`; the frontend package and page
  version are `0.6.0`.

Deleted:

- No source files deleted.
- No user data, runtime data, logs, uploads, indexes, caches, models, or
  database files touched.

Minimum tests:

- Passed frontend `npm run build`.
- Checked backend and Vite proxy health remained available and reported
  `0.5.0`.
- Checked ports only used the current backend/Vite development services.
- Confirmed the `v0.5.0-backup-before-v0.6.0` backup tag exists.

Manual test steps:

- Confirm the browser left version text is `0.6.0`.
- Confirm new conversation, recent conversation switching, dataset selection,
  selected model display, sending, stopping, errors, answers, result tables,
  SQL folding/copying, export, and data copy still work.
- Confirm the right workspace expands/collapses and defaults closed on narrow
  browser widths.
- Confirm the chart area only shows `选择查询结果后生成图表` or selected-result
  pending state and never renders fabricated chart data.
- Expand the debug panel and confirm all five stages, total duration, second
  actual input, model return, final answer, and quality details remain visible
  without secrets.
- Open the dataset page and confirm Excel/CSV import, MySQL Schema read, Schema
  preview, LLM test/save/edit/delete, dataset update/delete, and refresh remain
  present.

Known issues:

- Formal chart generation is intentionally not implemented in `0.6.0`.
- Mobile-specific redesign is not implemented; narrow browsers collapse the
  right workspace.
- The second answer call remains asynchronous through existing conversation
  detail polling, unchanged from `0.5.0`.

## 0.5.0 - 2026-07-22

Second LLM answer generation, complete first-product interaction, five-stage
debugging, and lightweight quality statistics built on accepted `v0.4.4`.
Backup tag: `v0.4.4-backup-before-v0.5.0`.

Changed:

- Added second OpenAI-compatible LLM call for final natural-language answers.
- Second call input is limited to original question, real SQL result tables, and
  one short answer instruction. It does not include Schema, M-Schema, Embedding
  candidates, QueryPlan, SQL generation rules, history, first raw model output,
  or debug records.
- SQL tables are persisted into the assistant message first. The second answer
  is written back into the same assistant message after completion.
- If second answer generation fails, times out, or is cancelled, returned SQL
  tables remain visible.
- Added assistant message envelope `bank_nl2sql_answer_v1` while preserving
  legacy plain text message display.
- Added `answer_generation` debug details: second actual input, extra prompt
  character count, prompt size, model return, final answer, validation, quality
  stats, and stage duration.
- Added total debug duration display in the right rail.
- Added lightweight quality stats for recall counts, requirement coverage, SQL
  success, answer coverage, numeric anomaly flag, prompt sizes, Embedding
  timings, first-table time, and final-answer time.
- Cleaned result value formatting so NULL stays NULL and count/integer-like
  values can display as integers instead of `184.000000`.
- Updated health capability to
  `query_plan_sql_execution_answer_generation`.
- Updated frontend version and restored malformed UI text that blocked build.

Interface compatibility:

- No new public endpoints.
- Existing dataset, import, Schema, Embedding, LLM config, conversation, cancel,
  and delete endpoints remain compatible.
- `POST /api/conversations/{conversation_id}/messages` still returns the same
  top-level shape. Assistant `content` can now be legacy text or a structured
  JSON envelope for table-first/final-answer rendering.

Stable paths preserved:

- `backend/app/services/import_service.py` was not modified.
- `backend/app/services/schema_registry.py` was not modified.
- Existing data import, dataset limits, conversation limits, Embedding
  retrieval, M-Schema Builder, strict QueryPlan validation, SQL AST validation,
  SQL execution, and table payloads were kept as the base chain.

Deleted:

- No source files deleted.
- No user data, runtime data, logs, uploads, indexes, caches, or models touched.

Minimum tests:

- Passed Python compileall for `backend/app`.
- Passed FastAPI `create_app()` version check: `0.5.0`.
- Passed frontend `npm run build`.
- Passed backend and Vite proxy health checks reporting `0.5.0`.
- Passed smoke checks for table-first assistant envelope.
- Passed smoke check that second prompt excludes M-Schema/QueryPlan and keeps
  extra instruction characters under 50.
- Passed smoke check that count-like `184.000000` formats as `184`.
- Passed smoke check that NULL remains NULL and empty result tables are not
  converted to zero answers.
- Passed smoke check that a failed second answer payload keeps SQL tables.
- Passed smoke check for user-cancel error category.
- Passed smoke check that answer-generation quality stats include required
  recall, coverage, prompt-size, timing, and anomaly fields.

Manual test steps:

- See `README.md`.
- Complex banking SQL correctness, answer quality, oral expressions,
  abbreviations, ranking,同比/环比, and overall accuracy require manual
  acceptance with real data and real model output.

Known issues:

- The second answer call is asynchronous through the existing conversation
  detail polling path, not SSE streaming.
- Second model quality depends on the configured provider and the real SQL
  tables. The backend performs only light structure/coverage/numeric anomaly
  checks and does not replace the model with a calculation engine.
- MySQL SQL execution remains unavailable because passwords and connection
  strings are not persisted by design.

## 0.4.4 - 2026-07-21

Typed QueryPlan cleanup and retrieval hardening on accepted
`v0.4.3-strict`. Backup tag:
`v0.4.3-strict-backup-before-v0.4.4`.

- `requirements` must be an object array:
  `[{"requirement_id":"R1","description":"..."}]`; mapping form is rejected as
  `QUERY_PLAN_TYPE_ERROR`.
- Tasks must include `task_id`, `purpose`, `sql`, `covers`, `depends_on`, and
  `expected_columns`.
- Top-level `depends_on` is backend-derived from task dependencies.
- Validation order is strict: JSON parse, type validation, QueryPlan contract,
  coverage, SQL validation, execution, result-column validation.
- Type errors no longer become empty arrays, empty strings, or defaults.
- Added/clarified `QUERY_PLAN_REFERENCE_ERROR` and `RESULT_COLUMN_ERROR`.
- SQL execution checks real returned columns against task `expected_columns`.
- Context cleanup deduplicates repeated questions and filters unrelated history.
- Embedding candidates are separated by table, column, metric, organization, and
  policy; training/case tables are filtered from ordinary queries.
- Metric candidates can include real dictionary name/code/unit records.
- M-Schema only writes confirmed or deterministic selected-table relationships.
- Debug output separates model return, parse/type/schema checks, normalized
  QueryPlan, derived fields, SQL validation, and result-column checks.

Limits: no second LLM answer call in 0.4.4, no MySQL SQL execution, complex
business SQL still needs manual acceptance.

## 0.4.3 - 2026-07-20

Strict QueryPlan and SQL validation repair on accepted `v0.4.2`. Backup tag:
`v0.4.2-baseline-before-v0.4.3-strict`.

- Fixed context pollution and limited carried context to same-segment follow-ups
  within 5 minutes.
- Added prompt budgets, prompt hash/debug details, complete QueryPlan contract,
  strict `covers`, one format-repair request, and no Mock fallback.
- Strengthened SQL validation for Schema identifiers, aliases, CTEs, nested
  SELECT, UNION, and write/multi-statement rejection.

## 0.4.2 - 2026-07-20

Real-LLM parsing and request-safety update on accepted `v0.4.1`. Backup tag:
`v0.4.1-final`.

- Default LLM config values became `max_tokens=4000` and `temperature=0`.
- Structured output `auto` chooses provider-compatible JSON Schema,
  `json_object`, or explicit `prompt_json`.
- Model output validation covers HTTP/content/finish reason, JSON parsing,
  QueryPlan schema, coverage, SQL validation, and one repair request.

## 0.4.1 - 2026-07-20

OpenAI-compatible real LLM Provider on accepted `v0.4.0-retry`. Backup tag:
`v0.4.0-backup-before-v0.4.1`.

- Added online/local/cloud model config storage, APIs, frontend panel,
  structured output modes, real first QueryPlan/SQL call, debug fields, and
  cancellation protection.
- API keys are stored only in external runtime SQLite and are never returned,
  logged, placed in debug records, or stored in localStorage.

## 0.4.0 - 2026-07-20

SQL planning and table-return version on original `v0.3.0` baseline. Backup tag:
`v0.3.0-baseline-before-v0.4.0-retry`. Corrected tag: `v0.4.0-retry`.

- Added QueryPlan/SQL planning, prompt assembly, sqlglot read-only validation,
  DuckDB SQL execution, result tables, duplicate request-id rejection, cancel
  endpoint, and split frontend busy states.

## 0.3.0 - 2026-07-19

Embedding retrieval and M-Schema on accepted `v0.2.0-final`.

- Added local Embedding provider, five collections, cache keys, preload/rebuild
  APIs, retrieval debug output, and compact M-Schema.

## 0.2.0 - 2026-07-19

Conversation and page-frame version on accepted `v0.1.0`. Backup tag:
`v0.1.0-final`.

- Added conversation/message/context/debug storage, recent conversations capped
  at 10, new conversation flow, time-based context lifecycle, scroll
  persistence, fixed query page, dataset page navigation, and stale-state
  handling.

## 0.1.0 - 2026-07-19

Initial clean-room version.

- Added FastAPI backend, Vue 3 frontend, SQLAlchemy metadata DB, Alembic,
  external runtime data, Excel/CSV import into DuckDB, MySQL read-only Schema,
  Schema Registry snapshots, dataset editing/UI, retention limit, and reserved
  provider interfaces.
