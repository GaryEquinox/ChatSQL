# Windows 安装包

公开版 1.0.5 安装后在本机启动 FastAPI 并打开浏览器，无需另行安装 Python、Node.js。

## 初次使用

使用 `admin / admin123` 登录。普通账号为 `user01 / user123`。
在“控制与管理”中自行导入数据、填写自己的模型 Base URL / API Key / 模型名称并启用，再开始问数。
公开版没有预置业务表格、模型连接、查询历史和带数据的看板，也不包含原专用指标知识库。

运行数据位于 `%LOCALAPPDATA%\ChatSQL\ChatSQLData`。程序保留已有安装的数据；重新安装不等于清空本机数据。

## 构建

准备 Python 3.11、Node.js 22.12 及以上、Inno Setup 6。在源码目录运行：

```powershell
.\packaging\build-exe.ps1
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" .\packaging\ChatSQL.iss
```

`create_seed.py` 调用 `create_public_seed.py`，只保留数据库结构与本地账号；不会复制任何数据集、模型配置、看板、历史、索引或指标字典。
源数据默认取源码旁的 `ChatSQLData`，可通过 `CHATSQL_SOURCE_DATA_ROOT` 指定。构建目标必须为 `backend/app/seed/ChatSQLData`。

EXE 输出到 `dist/ChatSQL/ChatSQL.exe`，安装包输出到 `packaging/output/ChatSQL-Setup-1.0.5.exe`。
