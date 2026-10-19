# TikTok 选品 Agent

这是一个面向个人项目与面试展示的证据驱动选品研究系统。项目当前已完成第一期：数据导入、证据可追溯、Milvus 规则索引与检索，以及可配置的 Deep Agent 规则研究入口。

系统不会把合成样例或检索相似度当作市场事实。报告、评分、真实数据 API、任务恢复和前端工作台属于后续迭代，完整路线见 [v2 技术方案](docs/TikTok选品Agent技术架构方案-v2.md)。

## 第一期能力

| 能力        | 已交付内容                                              |
| --------- | -------------------------------------------------- |
| 环境        | Docker Compose 启动 PostgreSQL、Redis、Milvus、FastAPI。 |
| 数据        | CSV / JSONL 示例导入，内容与整批数据均有 SHA-256 标识。             |
| 证据        | PostgreSQL 保存来源、版本、市场、观察时间、原始结构化信息。                |
| 检索        | Milvus `rule_chunks_v1` 集合，按市场过滤并返回证据 ID、来源和版本。    |
| Embedding | 无密钥可使用确定性 mock 验证管线；可切换至任意 OpenAI 兼容接口。              |
| Agent     | 提供真实 `deepagents` 入口，使用最小权限的 `search_rules_tool`。  |
| 验收        | PowerShell 自动验证脚本与合成样例。                            |

## 快速开始

需要 Docker Desktop 和你指定的 Python 3.12 Conda 环境。先复制配置：

```powershell
Copy-Item .env.example .env
docker compose up -d --build
```

组件启动后运行：

```powershell
.\scripts\verify-phase1.ps1
```

第一次准备 `py12` 环境时，手动执行：

```powershell
.\scripts\bootstrap-py12.ps1
.\scripts\export-lock.ps1
```

第二条命令会把已验证环境的完整依赖版本写入本地 `requirements.lock`；请在首次可运行验证后提交该文件，作为该机器实际可复现的依赖锁定记录。

查看接口文档：`http://localhost:8000/docs`；Milvus UI：`http://localhost:9091/webui/`。

完整操作、离线与真实模型的边界、验收预期和排错见 [第一期验证说明](docs/phase-1-verification.md)。

## 目录

```text
app/                 API、数据模型、导入、Milvus、工具、Deep Agent
data/sample/         合成的商品、评论与规则数据
docs/                技术方案与验收文档
scripts/             PowerShell 验证脚本
tests/               不依赖外部组件的单元测试
docker-compose.yml   本地依赖服务
```

## 真实模型模式

默认 `.env` 使用 `EMBEDDING_PROVIDER=mock`，只能验证工程链路。要启用真实 Deep Agent，请按 [第一期验证说明](docs/phase-1-verification.md) 配置通用的 `MODEL_API_KEY`、`MODEL_BASE_URL`、`CHAT_MODEL` 和 Embedding 模型；系统环境变量会覆盖 `.env` 的同名配置。更换向量维度后需重建 Milvus 集合。

Deep Agent 只能调用 `search_rules_tool`，该工具只读规则证据；没有授予任意 SQL、Shell 或任意文件写入能力。示例规则均为合成数据，模型输出不构成法律或合规意见。

## 本机开发检查

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
& $projectPython -m pip install -e '.[dev]'
& $projectPython -m pytest -q
& $projectPython -m ruff check app tests
```

如果上述 `pip install` 提示网络、权限或镜像错误，先修复该 Conda 环境的网络 / 镜像配置，再重试；依赖清单以 `pyproject.toml` 为准。

运行中遇到问题请先查看：

```powershell
docker compose logs api
docker compose logs milvus
```

Docker Desktop 的手动安装与启动步骤见 [Docker 环境说明](docs/docker-setup.md)。
