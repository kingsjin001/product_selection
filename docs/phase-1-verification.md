# 第一期验证说明

第一期验证的是可复现的工程链路：证据导入、PostgreSQL 持久化、Milvus 向量索引、规则检索，以及配置密钥后的真实 Deep Agent 工具调用。

示例数据均为合成数据。离线验证不能证明模型、平台数据或商业结论质量。

## 前置条件

- Docker Desktop 已启动，建议使用 Linux containers / WSL2 后端。
- 使用 `D:\Programs\anaconda3\envs\py12\python.exe`（Python 3.12）。
- PowerShell 位于项目根目录。

## 1. 启动组件

```powershell
Copy-Item .env.example .env
docker compose up -d --build
docker compose ps
```

首次启动 Milvus 会晚于 PostgreSQL 就绪。确认 `milvus` 状态为 running 后再进行索引；如果 API 容器因 Milvus 尚未就绪而启动失败，执行：

```powershell
docker compose up -d api
```

API 容器启动前会自动执行 `alembic upgrade head`。使用宿主机 CLI 时，先显式执行迁移：

```powershell
& 'D:\Programs\anaconda3\envs\py12\python.exe' -m alembic upgrade head
```

检查 API：

```powershell
Invoke-RestMethod http://localhost:8000/health
```

预期看到 `status: ok`、`embedding_provider: mock`、`embedding_dimension: 16`。Milvus Web UI 位于 `http://localhost:9091/webui/`。

## 2. 离线完整验证

离线模式使用确定性的 hashed embedding，仅用于验证数据与 Milvus 管线，不能衡量语义检索效果。

```powershell
Invoke-RestMethod -Method Post http://localhost:8000/api/imports/sample
Invoke-RestMethod -Method Post http://localhost:8000/api/indexes/rules

$body = @{ query = 'food contact material labeling'; market = 'US'; top_k = 3 } | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $body http://localhost:8000/api/rules/search
```

最后一个请求应返回至少一条结果，且结果含 `evidence_id`、`source_url`、`version` 与 `score`。再次调用导入接口应返回 `already_imported`；再次调用索引接口不应增加新的证据记录。

等价的本机 Python 命令：

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
& $projectPython -m pip install -e '.[dev]'
& $projectPython -m alembic upgrade head
& $projectPython -m app.cli import-sample
& $projectPython -m app.cli index-rules
& $projectPython -m app.cli verify --query 'food contact material labeling' --market US
```

首次安装成功后，可保存当前实际依赖版本：

```powershell
.\scripts\export-lock.ps1
```

它会将 `py12` 环境的完整依赖清单写到项目根目录 `requirements.lock`。在未完成成功安装前，不手工伪造 lock 文件。

如果 Python 在宿主机运行，它通过 `.env` 中的 `localhost` 连接到 Compose 服务；不要在 API 容器内执行这些命令。

## 3. 真实 Deep Agent 验证

真实验证需要一个支持 OpenAI 兼容接口的模型服务、相应模型权限和 API Key。将下列值写入本机 `.env`，不要提交该文件：

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=<服务中可用的文本向量模型>
EMBEDDING_DIM=<该模型实际输出维度>
MODEL_API_KEY=<你的密钥>
MODEL_BASE_URL=<兼容接口地址；使用默认地址时可留空>
CHAT_MODEL=<服务中可用且支持工具调用的模型>
```

配置值既可以来自 `.env`，也可以来自系统环境变量；系统环境变量优先。模型能力、模型名或 Embedding 维度以服务实际返回为准。更换 Embedding 模型或维度后，清空本地 Compose 卷并重新创建集合，避免混用向量空间：

```powershell
docker compose down -v
docker compose up -d --build
```

导入并索引后，执行：

```powershell
$body = @{ question = 'What should I verify before selling a food storage product?'; market = 'US' } | ConvertTo-Json
Invoke-RestMethod -Method Post -ContentType 'application/json' -Body $body http://localhost:8000/api/agent-demo
```

验收时查看 Agent 输出或追踪日志，确认它调用了 `search_rules_tool`，并且回答携带工具返回的证据 ID。工具检索的是合成规则，输出不是法律意见。

## 4. 常见故障

| 现象 | 排查方式 |
| --- | --- |
| API 启动失败 | `docker compose logs api`，确认 PG 已健康、环境变量正确。 |
| 索引连接失败 | `docker compose logs milvus`，等待 Milvus 完成启动后重试索引。 |
| 搜索返回 no_results | 确认已依次导入和索引；使用样例查询；检查 market 是否为 `US`。 |
| 模型服务调用失败 | 确认 Key、兼容接口地址、模型权限、模型名、Embedding 维度和网络环境；以实际模型响应为准。 |
| 改完 DIM 后报向量维度错误 | 必须重建 Milvus 集合，不能复用旧向量。 |

