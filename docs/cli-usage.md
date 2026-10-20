# CLI 命令使用说明

`app.main` 与 `app.cli` 都会调用相同的服务层，但承担的职责不同：

| 入口 | 启动方式 | 适用场景 | 是否常驻运行 |
| --- | --- | --- | --- |
| `app.main` | `uvicorn app.main:app ...` | FastAPI 接口、Swagger 文档、供前端或 PowerShell 调用 | 是，监听 8000 端口 |
| `app.cli` | `python -m app.cli <命令>` | 初始化、导入、索引、命令行验收 | 否，完成命令后退出 |

在 PyCharm 中调试接口时启动 `app.main`。需要快速重复数据流程、查看 JSON 结果或在没有 API 服务时维护数据时使用 `app.cli`。CLI 不会启动 FastAPI，也不会占用 8000 端口。

## 前置条件

在项目根目录执行以下命令。PostgreSQL、Milvus 等依赖需已启动；首次使用还需要先安装 Python 依赖。

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
docker compose up -d
& $projectPython -m pip install -e '.[dev]'
```

CLI 和 FastAPI 都读取项目根目录的 `.env` 与系统环境变量。系统环境变量优先。若想看到更多过程信息，设置：

```dotenv
LOG_LEVEL=DEBUG
```

如果在 Windows 的外部 PowerShell 中看到中文日志乱码，可在当前窗口先执行以下两行；PyCharm 的 Run 控制台通常不需要此设置：

```powershell
chcp 65001
[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()
```

## 命令一览

先查看 CLI 的内置帮助：

```powershell
& $projectPython -m app.cli --help
```

### 1. 初始化数据库

将 Alembic 的所有迁移应用到 PostgreSQL。首次运行或新增迁移后执行。

```powershell
& $projectPython -m app.cli init-db
```

成功时输出：

```json
{"status": "database_migrated"}
```

### 2. 导入合成样例

读取 `data/sample` 中的 CSV 和 JSONL，写入商品、评论和规则证据。相同样例重复执行会返回 `already_imported`，不会增加重复数据。

```powershell
& $projectPython -m app.cli import-sample
```

### 3. 创建规则向量索引

从 PostgreSQL 读取 `rule` 类型证据，调用当前配置的 Embedding 服务，然后写入对应的 Milvus 集合。

```powershell
& $projectPython -m app.cli index-rules
```

`EMBEDDING_PROVIDER=mock` 时不会请求外部模型，适合流程调试。真实模型模式需要完整配置 `MODEL_API_KEY`、`EMBEDDING_MODEL` 和正确的 `EMBEDDING_DIM`。

### 4. 检索规则证据

在已索引的 Milvus 集合中检索，再回查 PostgreSQL，输出可追溯的证据 ID、来源、版本和相似度。

```powershell
& $projectPython -m app.cli verify --query 'food contact material labeling' --market US
```

可省略参数以使用默认查询与 `US` 市场：

```powershell
& $projectPython -m app.cli verify
```

### 5. 运行真实 Deep Agent

仅在已配置真实聊天模型后执行。该命令会发起真实模型请求；Agent 只能调用只读的规则检索工具。

```powershell
& $projectPython -m app.cli agent-demo --question 'What should I verify before selling a food storage product?' --market US
```

## 推荐执行顺序

```powershell
& $projectPython -m app.cli init-db
& $projectPython -m app.cli import-sample
& $projectPython -m app.cli index-rules
& $projectPython -m app.cli verify --query 'food contact material labeling' --market US
```

如果修改了 Embedding 模型或 `EMBEDDING_DIM`，CLI 会使用新的 Milvus 集合名；需要再次执行 `index-rules`，再进行检索。
