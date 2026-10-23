# ChatSQL 源码

当前版本：1.0.5。

完整的项目介绍、安装步骤、账号密码、源码运行与服务器部署说明见 [仓库首页 README](../README.md)。

- `backend`：Python / FastAPI 后端，包含认证、权限、SQL 校验、查询执行与看板服务。
- `frontend`：Vue 3 / TypeScript 前端，包含问数、图表、看板和管理页面。
- `packaging`：Windows EXE 与安装包构建，以及公开版空数据导出工具。
- `start-dev.ps1`、`status-dev.ps1`、`stop-dev.ps1`：开发服务管理。
- `VERSION`、`CHANGELOG.md`：版本号与变更记录。

公开版已移除原业务表格、模型连接和历史数据。登录账号保留为 `admin / admin123`、`user01 / user123`，使用前需自行导入数据并配置模型。
