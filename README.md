# ChatSQL

面向银行经营分析场景的轻量自然语言问数系统。用户通过中文提问，系统结合数据集结构生成 SQL，经过校验和权限控制后执行查询，再基于真实结果生成回答与图表。支持 Windows 安装包和源码运行。

当前版本：**1.0.5**。

## 功能

- 智能问数：自然语言转 SQL、上下文问答、指标知识检索、确定性快速匹配。
- 数据接入：CSV、Excel 导入，以及 MySQL 只读连接；查看 Schema 与 M-Schema。
- 查询安全：SQL AST、字段与表结构校验、后端行级权限控制。
- 结果展示：表格、自然语言回答、指标卡、折线图、柱状图、饼图等。
- 可编辑看板：组件配置、保存、刷新、全局动态条件及卡片局部筛选。
- 本地登录、角色与权限管理、大模型连接管理、历史对话。

## 公开版本的数据范围

本仓库已清理原项目的业务表格、DuckDB 数据、数据集 Schema、索引、缓存、历史对话、看板数据和模型连接配置，包括 API Key 与实际 AI 服务地址。Windows 安装包也使用相同的空数据初始化内容重新构建。

**首次启动没有预置数据集和有数据的看板。** 登录后需要自行导入允许使用的数据、配置模型连接，再开始问数或创建看板。数据接入、模型管理和看板功能的代码均保留；原业务数据及专用指标知识库不随仓库发布。

## 登录账号

| 角色 | 账号 | 密码 |
| --- | --- | --- |
| 管理员 | `admin` | `admin123` |
| 普通用户 | `user01` | `user123` |

首次配置数据与模型请使用管理员账号。普通用户的数据访问范围需要管理员按导入后的实际字段配置。

以上是按项目要求保留的公开演示账号。当前本地认证以明文保存密码，适合本机演示；部署到公网前应修改默认密码并配置 HTTPS。可通过源码目录中的 `backend/auth_admin.py --help` 查看账号管理命令。

## Windows 一键安装

1. 下载根目录中的 [ChatSQL-Setup-1.0.5.exe](./ChatSQL-Setup-1.0.5.exe)。GitHub 文件页面提供下载按钮，也可以在仓库 Releases 中分发安装包。
2. 双击安装，按向导完成安装，可选择创建桌面快捷方式。
3. 启动 ChatSQL，程序自动启动本机服务并打开默认浏览器。无需另外安装 Python 或 Node.js。
4. 使用上面的管理员账号登录，在“控制与管理”中导入自己的数据并配置大模型。

安装版运行数据保存在 `%LOCALAPPDATA%\ChatSQL\ChatSQLData`。后续启动会继续使用本机已有数据，不会自动清除或覆盖旧安装产生的内容。

## 源码运行

### 环境

- Windows 10/11，或支持 Python、Node.js 的 Linux 环境。
- Python **3.11**。
- Node.js **22.12 及以上**，附带 npm；前端使用 Vite 7。
- 使用自然语言问数时，需要能够访问自己配置的 OpenAI-compatible 模型服务。

项目自带依赖清单，不携带 `.venv`、`node_modules` 等本机环境目录。文件导入模式使用 DuckDB，无需单独安装 MySQL 服务。

### Windows 开发启动

在仓库根目录打开 PowerShell：

```powershell
cd .\ChatSQL
py -3.11 -m venv backend\.venv
.\start-dev.ps1
```

脚本会安装后端与前端依赖并启动两个服务。PowerShell 如果限制脚本执行，可先在当前窗口运行 `Set-ExecutionPolicy -Scope Process Bypass`。

- 前端：`http://127.0.0.1:5173`
- 后端健康检查：`http://127.0.0.1:8000/api/health`

```powershell
.\status-dev.ps1
.\stop-dev.ps1
```

启动脚本将运行数据放在源码目录旁的 `ChatSQLData`，即仓库根目录下的同名文件夹。

### 手动启动与构建

以下命令从仓库根目录执行；两个服务分别在两个终端运行。

后端（Windows）：

```powershell
cd .\ChatSQL\backend
py -3.11 -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
$env:BANKNL2SQL_LITE_DATA_ROOT = (Resolve-Path ..\..\ChatSQLData).Path
.\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

前端：

```powershell
cd .\ChatSQL\frontend
npm ci
npm run dev
```

生产前端构建与后端语法检查：

```powershell
cd .\ChatSQL\frontend
npm run build
cd ..
py -3.11 -m compileall backend/app
```

### Linux 服务器

准备 Python 3.11、Node.js 与 Nginx 后，从仓库根目录执行：

```bash
cd ChatSQL/backend
python3.11 -m venv .venv
.venv/bin/python -m pip install -r requirements.txt
export BANKNL2SQL_LITE_DATA_ROOT="$(cd ../../ChatSQLData && pwd)"
.venv/bin/python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

另一个终端进入 `ChatSQL/frontend`，运行 `npm ci && npm run build`。使用 Nginx 提供该目录下 `dist` 的静态文件，将 `/api/` 反向代理到本机 8000 端口：

```nginx
server {
    listen 80;
    server_name _;
    root /opt/chatsql/ChatSQL/frontend/dist;
    index index.html;
    client_max_body_size 100m;

    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_read_timeout 300s;
    }
    location / {
        try_files $uri $uri/ /index.html;
    }
}
```

将 `root` 改成实际部署路径，使用 systemd 等进程管理工具保持后端运行。正式访问请配置域名与 HTTPS，手机访问也应使用 HTTPS。

## 使用方法

1. **导入数据**：管理员进入“控制与管理”，上传自己的 CSV / Excel 文件或添加 MySQL 只读连接。
2. **检查结构**：查看 Schema，确认字段类型、业务含义与数据集名称。
3. **配置模型**：新增模型连接，填写名称、Base URL、API Key、模型名称并启用；测试连接是否可用。仓库不提供可直接使用的模型密钥或服务地址。
4. **开始问数**：回到智能问数，选择数据集并输入与实际字段有关的问题。结果会显示为自然语言回答和表格，可继续生成图表。
5. **配置看板**：在看板界面创建组件或加入查询图表，配置机构、日期等动态条件，保存后可刷新查看。
6. **配置权限**：管理员为普通用户设置实际数据集的行级权限后，再使用普通账号验证访问范围。

业务数据和模型配置会保存在当前运行数据目录中。再次公开源码前，请重新执行脱敏检查，不要上传个人数据目录。

## 技术栈与流程

| 部分 | 技术与职责 |
| --- | --- |
| 前端 | Vue 3、TypeScript、Vite：问答、数据管理、模型管理和看板交互 |
| 图表 | Chart.js、Lucide：图表绘制与界面图标 |
| 后端 | Python、FastAPI、Uvicorn：接口、查询编排、认证与权限 |
| 查询 | sqlglot：SQL AST 和结构校验；DuckDB：文件数据分析执行 |
| 存储 | SQLite、SQLAlchemy：元数据、账号、历史对话及看板 |
| 数据接入 | pandas、openpyxl、PyMySQL：文件解析与数据库连接 |
| Windows 分发 | PyInstaller、Inno Setup：程序打包与安装向导 |

主要流程：中文问题 → Schema / 检索 / 指标上下文 → 第一次模型生成 QueryPlan 与 SQL → SQL 与权限校验 → 数据库执行 → 真实表格 → 第二次模型生成回答 → 前端图表和看板。

## 目录

```text
ChatSQL/                         源码目录
  backend/app/                   API、服务、数据模型与初始化内容
  frontend/src/                  Vue 页面、接口调用与样式
  packaging/                     Windows 打包脚本与公开 seed 导出
  start-dev.ps1                  开发启动
  status-dev.ps1                 服务检查
  stop-dev.ps1                   开发停止
  VERSION / CHANGELOG.md         版本与变更记录
ChatSQLData/                     脱敏后的空运行数据库及登录账号
ChatSQL-Setup-1.0.5.exe           脱敏重建的 Windows 安装包
README.md                       本说明
```

## 重新打包

进入 `ChatSQL` 目录运行 `packaging/build-exe.ps1`，再使用 Inno Setup 6 编译 `packaging/ChatSQL.iss`。脚本只生成空业务数据库和本地账号，不打包源运行目录中的表格、模型连接、历史对话或看板快照。详细说明见 [Windows 打包说明](./ChatSQL/packaging/README_EXE.md)。

## 版本记录

当前公开源码版本为 **1.0.5**，包含智能问数、权限、可编辑看板和 Windows 打包支持。本次公开准备清理业务数据与个人连接信息，保留演示登录账号。历史功能变更见 [CHANGELOG](./ChatSQL/CHANGELOG.md)。
