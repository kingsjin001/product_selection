# TikTok 选品研究工作台

当前版本 **0.6.0**，面向个人项目与面试展示：导入中文商品、评论和规则资料，
通过 LangGraph 编排研究、确定性成本计算与引用校验，生成可追溯报告。
保留 **LangChain Deep Agents** 与 **MilvusClient**，API 和 Worker 使用本机 Python，
Docker Compose 提供 PostgreSQL、Redis、Milvus 及依赖。

六期代码分别保存在本地分支，每期实测范围与未验收项见
[交付记录](docs/delivery-status.md)。项目使用合成样例，没有连接真实 TikTok 商品 API；
不能将样例评论、合成规则或模型输出作为真实市场事实。

## 阅读入口

| 想了解什么 | 文档 |
| --- | --- |
| 各期代码、测试与分支 | [逐期交付记录](docs/delivery-status.md) |
| 当前系统边界、数据流和恢复机制 | [架构说明](docs/architecture.md) |
| 为什么这样选型、面试讨论重点 | [决策记录](docs/decisions.md) |
| 模型/检索对照与原始结果 | [评测报告](docs/evaluation.md) |
| 三分钟演示、现场操作顺序 | [演示说明与视频](docs/demo/README.md) |
| PyCharm、环境变量、中文日志 | [本机运行](docs/pycharm-run.md) |
| Docker 依赖安装 | [Docker 说明](docs/docker-setup.md) |
| 中文样例字段与数据含义 | [样例数据字典](docs/sample-data.md) |
| 基础 CLI | [CLI 用法](docs/cli-usage.md) |
| 分析 / 索引 / 后台 / 工作台 | [第二期](docs/phase-2-guide.md)、[第三期](docs/phase-3-guide.md)、[第四期](docs/phase-4-guide.md)、[第五期](docs/phase-5-guide.md) |

早期文档描述对应分支；当前模式、入口和限制以本 README 为准。
原 README 保存在 [第一期历史存档](docs/phase-1-reference.md)。

## 已实现的功能

| 模块 | 当前行为 |
| --- | --- |
| 数据导入 | 商品 CSV、评论 CSV、规则 JSONL 或统一 JSON；批次摘要幂等；同 ID 不同资料拒绝静默覆盖 |
| 证据管理 | PostgreSQL 保存来源、市场、品类、原文、版本与摘要；更新/删除生成事务索引事件 |
| 检索 | 规则和评论两个 Milvus 集合；向量与中文词片段排序通过 RRF 融合；回查数据库过滤版本及有效性 |
| 研究 | 固定检索综合、单次提示词、主 Deep Agent、主 Agent + 评论/规则专项子 Agent |
| 成本 | Decimal 计算保守/基准/乐观情景；成本缺失保持缺失；报告呈现贡献利润 |
| 后台任务 | Celery/Redis、投递 outbox、幂等键、租约/心跳/epoch、检查点恢复、协作取消 |
| 工作台 | 上传、商品选择、阶段时间线、SSE 重连、报告库、证据展开、成本情景切换 |
| 报告 | 同一 JSON 源生成页面、Markdown、Word；重复导出复用制品；追问独立保存；修订成本创建新版本 |
| 验证 | 44 个测试、实际故障恢复脚本、空数据库与索引验证、冻结评测集及 A/B/C 原始结果 |

## 快速启动

所有 Python 命令在项目根目录执行。解释器使用你指定的
`D:\Programs\anaconda3\envs\py12\python.exe`。已有 `.env` 不要覆盖。

### 1. 依赖服务和配置

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
if (-not (Test-Path -LiteralPath .env)) { Copy-Item .env.example .env }
docker compose up -d
docker compose ps
```

首次安装 Docker 按上述 Docker 文档操作。本命令默认只启动基础设施，
不会启动容器 API；无需安装另一个 Python 环境。

Settings 从进程环境变量优先取值，再读取工作目录 `.env`，最后使用字段默认值。
例如已有系统变量 `qwen-api-key` 时，`.env` 可写：

```dotenv
MODEL_API_KEY="${qwen-api-key}"
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIM=1024
CHAT_MODEL=qwen3.7-plus
LOG_LEVEL=INFO
```

`MODEL_BASE_URL` 填当前账户地域对应的 OpenAI 兼容地址；模型名是本次实测配置，
能否使用仍取决于账户。密钥与连接字段均未绑定厂商名称。
系统变量必须被当前 PyCharm/终端进程继承，新增系统变量后重启它们。
若进程已有 `MODEL_API_KEY`，它优先于 `.env` 中的同名值。
`EMBEDDING_DIM` 是实际向量长度；模型或维度改变后需重新构建对应索引。
`EMBEDDING_REQUEST_DIMENSIONS` 仅在接口支持指定输出维度时设置。

### 2. Python 与数据库

已有环境只需更新项目依赖；安装操作可能调整该环境中的包版本：

```powershell
& $projectPython -m pip install -e '.[dev]'
& $projectPython -m alembic upgrade head
& $projectPython -m app.cli import-sample
& $projectPython -m app.index_cli rebuild
& $projectPython -m app.index_cli status
```

`rebuild` 同步规则和评论；真实 Embedding 会产生模型请求。
事件超过单批 100 条时再次 `sync`，或用下方常驻分发器持续消费。
旧的 `index-rules` 仅维护第一期规则索引，不能代替当前双集合初始化。

为了复现本次 Windows Python 3.12 版本组合，可在用于复现的环境中安装
`requirements.project.lock` 后执行 `pip install -e . --no-deps`。
它包含本项目及 dev/demo 的 115 个包；`requirements.lock` 是早期整个环境快照。
当前共享 py12 的两组无关包存在 `pip check` 冲突，详情见第六期验收；
没有擅自降级其他项目的包，也尚未验证全新操作系统安装。

### 3. 分别启动三个 Python 进程

每条长期运行命令使用一个独立终端，或者分别建 PyCharm 配置：

```powershell
# API
& D:\Programs\anaconda3\envs\py12\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

```powershell
# Windows 开发 Worker
& D:\Programs\anaconda3\envs\py12\python.exe -m celery -A app.workers.celery_app:celery_app worker --pool=solo --loglevel=INFO
```

```powershell
# 任务投递、过期租约恢复、证据索引同步
& D:\Programs\anaconda3\envs\py12\python.exe -m app.workers.dispatcher --indexes
```

PyCharm 的 API 配置选 **Module name: uvicorn**，参数为
`app.main:app --host 127.0.0.1 --port 8000 --reload`，
工作目录为项目根目录，不能直接将这些参数传给 `app/main.py`。
Worker 模块选 `celery`；分发器模块选 `app.workers.dispatcher`。
任务一直 `queued` 时先检查 Worker 和分发器，两者不会随 API 自动启动。

### 4. 前端

需要本机 Node.js；本项目使用 Vite 7，Node 版本要求见 `frontend/package-lock.json` 中的 engines。

```powershell
cd frontend
npm ci
npm run build
```

构建后重启 API，访问 `http://127.0.0.1:8000/`。
开发页面时改用 `npm run dev`，访问终端提示的地址（默认 5173），
Vite 将 API 请求代理到 8000。Swagger 在 `/docs`，数据库健康检查在 `/health`；
健康检查成功不代表 Worker、全部模型和 Milvus 都已通过检查。

## 第一次完整演示

1. 导入内置资料：原样例有 **20 商品、20 评论、20 规则**，主要为中文。
2. 在研究页选择商品，先用 `fixed` 检查任务、成本与报告链路；它不调用聊天或向量模型。
3. 索引同步后选择默认 `workflow`，执行真实检索和模型综合。
4. 完成后打开报告，展开证据原文与来源。研究表单初次提交不含成本，报告会提示缺失。
5. 在报告中“编辑成本假设”，确认或修改演示数字，再创建成本修订任务；
   新报告可切换三种成本情景，原缺失报告保留。
6. 用“在报告中定位”追问已有数字；选择“真实模型解读”会单独调用模型。
   再修订售价会生成新的版本。下载 JSON/Markdown/Word。

`data/workbench/` 另外提供 3 商品、6 评论、3 规则，包含普通、缺失、冲突场景，
可上传其中的 CSV/JSONL 或通过接口提交 `import.json`。
冲突案例同时改变规格和使用条件，不能据此得出“大号导致漏水”的因果结论。
代表性报告在 `docs/examples/`。Word 的关键数值与引用已检查，打印分页和字体尚未视觉验收。

## 研究模式与费用

| mode | 用途 | 外部请求 |
| --- | --- | --- |
| `fixed` | 工程验证：摘录冻结原文、统计与计算 | 无模型请求 |
| `prompt`（A） | 一次输入冻结资料进行综合 | 聊天；格式错误可能补一次修复 |
| `workflow`（B，默认） | 固定检索评论与规则，再综合 | Embedding + 聊天 |
| `agent` | 单主 Agent 使用业务工具 | 聊天及按需 Embedding |
| `multi`（C） | 自主研究，按需委派评论/规则专项 | 聊天及按需 Embedding |

Deep Agents 的默认文件、Shell 等工具被执行层白名单限制。
调用次数上限共享并持久化，失败请求也消耗次数；单次聊天等待上限 120 秒，
并受剩余任务时间约束。后台任务第一次领取时冻结截止时间，恢复不重置。
取消不会撤销已发送给供应商的请求，也不保证不产生该次费用。

本次 3 个商品 × 3 方案均完成，43/43 引用可解析，18/18 完整成本情景数值一致。
这不等于引用语义支持率，独立人工复核尚未执行。B 的聊天 token 总量较低，
但每方案只有 3 次，不宣称稳定速度优势或质量提升。模型金额尚未换算：
`evals/pricing.example.json` 的单价为空，不能把未知费用写成零。

## CLI、API 与验收

`app.main` 是常驻服务；CLI 执行一次后退出，维护和同步分析不需要 API 先启动。
后台任务则需要上述服务进程。

```powershell
# 无聊天模型的单品报告，输出到 exports/
& $projectPython -m app.analysis_cli --input data/sample/analysis-request.json
# 恢复已有同步运行；后台任务应通过任务 API 恢复
& $projectPython -m app.analysis_cli --run-id <run_id>
# 索引维护：enqueue / sync / rebuild / status / retry
& $projectPython -m app.index_cli sync
# 无外部服务单元测试与静态检查
& $projectPython -m pytest -q
& $projectPython -m ruff check app tests scripts
```

`verify-phase1.ps1` 只检查第一期 API 链路，执行后不必重复相同 CLI 命令，
但它不能代替六期验收。当前验收入口和原始记录见
[第六期报告](docs/acceptance/phase-6.md)，真实模型评测会消耗额度。

| 入口 | 行为 |
| --- | --- |
| `POST /api/imports`、`/api/imports/files` | 通用资料导入 |
| `GET /api/products` | 商品列表 |
| `POST /api/tasks` | 后台任务，支持 `Idempotency-Key` |
| `GET /api/tasks/{id}`、`/{id}/events` | 状态与持久 SSE |
| `POST /api/tasks/{id}/cancel`、`/{id}/resume` | 协作取消、失败恢复 |
| `GET /api/reports`、`/{id}` | 历史报告与详情 |
| `POST /api/reports/{id}/exports` | 复用 JSON/Markdown/Word 制品 |
| `POST /api/reports/{id}/questions`、`/{id}/revisions` | 独立追问、成本新版本 |
| `/api/analyses` | 第二期同步分析入口，适合 CLI/小范围调试 |

完整请求字段以 Swagger 为准。`LOG_LEVEL=DEBUG` 展示本项目更多中间状态，
日常用 `INFO`；第三方日志保持克制。调用账本包含次数、工具参数片段和返回的 token，
任务事件记录阶段变化。不要把密钥写进问题或上传样例。

## 目录与边界

```text
app/agents/       Deep Agents 与模型调用边界
app/workflows/    LangGraph 固定编排和检查点
app/services/     成本、报告、任务、索引与融合检索
app/workers/      Celery Worker、outbox 分发和恢复扫描
app/api/          导入、分析、证据、任务与报告接口
app/db/           ORM、会话及迁移入口
frontend/         Vue 工作台
data/             中文基础样例与专项场景
evals/            冻结语料、查询、原始指标与人工复核表
docs/             架构、决策、使用说明、验收和演示
scripts/          复现、故障注入、评测与视频生成
```

这是单用户本机演示项目，尚无多租户权限、生产部署运维和真实外部商品数据接入。
版本控制与模型调用记录用于说明工程可追溯性，不构成生产可靠性承诺。
