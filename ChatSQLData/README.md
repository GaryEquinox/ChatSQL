# 公开版运行数据

当前仅保留空的 `meta.sqlite3` 和本地登录认证数据库 `auth/auth.sqlite3`。
数据集、表格、Schema、模型连接（含 API Key 和 Base URL）、历史对话、看板记录和原指标知识库均已清除。

保留账号：管理员 `admin / admin123`，普通用户 `user01 / user123`。
令牌签名密钥由每个部署实例首次使用时自行生成。

Git 忽略这里的运行数据库，下载源码后后端会自行初始化结构与默认账号。完整操作说明见 [项目 README](../README.md)。
