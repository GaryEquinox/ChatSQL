# 公开初始化内容

`meta.sqlite3` 只保留空表结构；`auth/auth.sqlite3` 保留本地登录账号。
管理员 `admin / admin123`，普通用户 `user01 / user123`。

不含业务表格、数据集 Schema、模型连接、API Key、实际服务地址、历史对话、看板快照、索引或指标字典。
Windows 首次启动将此内容复制到本机运行数据目录，已有数据不会被覆盖。
