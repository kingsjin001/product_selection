# 第七期使用说明

完整设计见 [第七期方案](phase7-design.md)，实测范围见 [验收报告](acceptance/phase-7.md)。
解释器继续使用 `D:\Programs\anaconda3\envs\py12\python.exe`；所有命令从项目根目录执行。
本期没有安装 Docker，也没有覆盖用户 `.env`。已有 API、Worker 和 Dispatcher 需要重启才能加载新代码。

## 1. 升级与启动

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
& $projectPython -m pip install -e '.[dev]'
& $projectPython -m alembic upgrade head
```

迁移 `20261021_07` 只增加四张表，不修改已发布报告。使用锁定环境复现时按 README 的依赖锁步骤安装。

本地工具模式不需要启动 MCP 服务，直接运行原 API、Worker、Dispatcher 即可。
在 PyCharm 中均使用 **Module name**，工作目录是项目根目录：

| 进程 | 模块 | 参数 |
| --- | --- | --- |
| API | `uvicorn` | `app.main:app --host 127.0.0.1 --port 8000 --reload` |
| Worker | `celery` | `-A app.workers.celery_app:celery_app worker --pool=solo --loglevel=INFO` |
| Dispatcher | `app.workers.dispatcher` | 参见 `--help`，常驻循环使用默认参数 |
| MCP（启用时） | `app.mcp.server` | 无 |

以上 Python 服务均在本机启动。PostgreSQL、Redis、Milvus 仍使用已有基础设施。

## 2. 启用 MCP

在自己的 `.env` 中**手动追加或调整**：

```dotenv
EVIDENCE_TRANSPORT="mcp"
MCP_URL="http://127.0.0.1:8765/mcp"
MCP_PORT=8765
MCP_SHARED_SECRET="${RESEARCH_MCP_SECRET}"
MILVUS_DATABASE="default"
```

`RESEARCH_MCP_SECRET` 是你自己的系统环境变量，值至少 32 字符。生成随机值可运行：

```powershell
& $projectPython -c "import secrets; print(secrets.token_hex(32))"
```

把生成值保存为系统环境变量，再重启 PyCharm，确保 API、Worker、MCP 三个进程继承同一值。
也可以直接在 `.env` 的 `MCP_SHARED_SECRET` 中填写随机值；`.env` 已忽略，不提交到 Git。
模型密钥仍用原来的 `MODEL_API_KEY`，不要把 MCP 密钥和模型密钥混用。

启动：

```powershell
& $projectPython -m app.mcp.server
```

服务地址 `/mcp`，使用 Streamable HTTP。浏览器直接 GET 不是工具验证方法；通过研究任务或验收脚本验证。
端口冲突时同时修改 `MCP_PORT` 和 `MCP_URL`。localhost 请求明确绕过系统 HTTP 代理，避免代理产生 502。

工具：`get_product_snapshot`、`query_reviews`、`summarize_review_counts`、`search_reviews`、`search_rules`、`get_evidence`。
无结果返回 `no_results`；连接、签名、过期运行、证据变更等失败明确报错，没有自动降级成本地查询。
每次业务调用只计一次工具预算，MCP 服务本身不重复计数。

`EVIDENCE_TRANSPORT=local` 可恢复本地工具。传输方式在创建任务时冻结，所以切换后请创建新任务。
`fixed` 无模型与检索，`prompt` 直接读取冻结证据；`workflow`、`agent`、`multi` 使用所选传输方式。

## 3. Skills 如何使用

原生技能存放在 `app/skills/`：

| 技能 | 使用场景 | 工具方向 |
| --- | --- | --- |
| review-analysis | 评论、规格与样本分布 | 评论查询、计数、混合检索 |
| rule-verification | 市场规则和宣传依据 | 规则检索、证据全文 |
| conflict-research | 主 Agent 综合冲突和缺失 | 专项委派、冲突核验参考文档 |

创建任务时将 Markdown 内容和总摘要写入 `AnalysisRun.versions.skills`。
Deep Agents 原生 SkillsMiddleware 初始提供技能描述，模型按需调用 `read_file` 阅读全文。
专项 Agent 显式配置自己的技能目录，后端仅包含冻结的内存文件；没有项目磁盘访问权限。
`read_file` 同样记录工具次数与耗时。修改技能后创建新任务生效，旧运行恢复仍使用原内容。
固定流程与单次提示词模式不声称执行原生技能发现。

## 4. 人工复核（HITL）

工作台“发布前复核”有三种选择：

- **缺失或冲突时复核（auto）**：成本不完整、研究有缺失项，或结论含冲突提示时暂停。
- **始终复核（always）**：每次生成草稿后暂停。
- **直接生成报告（off）**：保持原流程。为了兼容旧脚本，API 省略该字段时为 off。

暂停后任务状态为 `waiting_for_review`，工作台展示草稿、原始证据、成本与复核理由。
人工等待释放 Worker，不占用租约，也不消耗剩余计算时间和模型/工具调用额度。
本期没有自动审批和自动超时发布，等待任务可随时取消。

**批准发布**：决定与投递记录同事务保存，Worker 使用原 PostgreSQL 检查点继续；发布时再次检查证据版本。
**拒绝发布**：结束原任务，保留草稿审计记录。
**要求修改**：填写意见，创建沿用证据快照的新任务，带父运行 ID；新草稿仍须复核，原草稿保持不变。
若证据本身已经更新，请重新创建研究，不能靠批准旧草稿绕过证据校验。

API 示例（先导入工作台样例）：

```powershell
$body = Get-Content -Raw -Encoding UTF8 data/phase7/review-request.json
$task = Invoke-RestMethod http://127.0.0.1:8000/api/tasks -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($body))
$review = Invoke-RestMethod "http://127.0.0.1:8000/api/tasks/$($task.id)/review"
$decision = @{draft_hash=$review.draft_hash; action='approve'; feedback='已核对样例来源'} | ConvertTo-Json
Invoke-RestMethod "http://127.0.0.1:8000/api/tasks/$($task.id)/review" -Method Post -ContentType 'application/json; charset=utf-8' -Body ([Text.Encoding]::UTF8.GetBytes($decision))
```

读取草稿前需等任务进入等待状态；尚未生成草稿时 GET 返回 404。
相同决定重复提交幂等；错误草稿摘要、已取消任务或相反决定返回 409。
CLI 同步分析也会返回等待状态，不导出假报告；通过复核接口批准后再执行 `app.analysis_cli --run-id ...`。
演示和日常操作推荐后台任务入口，完整的租约与等待时限管理以后台任务为准。

## 5. 连续追问与偏好

报告页的模型追问会带入同一会话最近 **6 轮成功问答**，每轮问题最多 2000 字、回答上下文最多 4000 字。
历史回答用来理解“它”“刚才”等指代，引用仍只允许当前报告证据。
引用定位模式不使用模型，不进行指代推理。点击“开始新会话”清空后续上下文，原问答审计记录仍保留。
页面刷新通过 localStorage 恢复当前报告会话编号；另一报告不能复用该编号。
并发追问返回 409；模型请求最多 120 秒，会话占用租约为 3 分钟，失败后释放。

接口 `/api/reports/{run_id}/questions` 新字段：

```json
{
  "question": "它与另一规格的测试条件有什么不同？",
  "mode": "model",
  "conversation_id": "上一轮返回的编号；首轮省略此字段",
  "request_key": "本轮稳定幂等键",
  "suggest_memory": false
}
```

相同会话最近六轮内的成功键重试复用回答；历史问答完整保存在 `report_questions`，不修改原报告。
追问费用单独记录，不重置或消耗原研究账本；每轮显式提交才产生一次模型调用。

“偏好与记忆”页可以查看、修改、清空：目标市场、排除品类、回答语言。
这些是建议条件，不能把美国商品改成英国商品，也不会拦截用户明确要求研究的品类。
新任务冻结偏好版本，已有任务不随设置变化漂移。

勾选“允许模型提出偏好候选”后，模型可以建议长期偏好，但只保存为 pending 候选。
你可以编辑后确认或忽略。普通模型结论不会自动写入长期记忆，MCP 工具也没有写记忆权限。
这是本地单用户功能；没有账号系统、跨用户授权或向量化长期事实记忆。

## 6. 日志与测试

`LOG_LEVEL=INFO` 显示阶段与调用耗时；`DEBUG` 额外显示受限长度的工具参数和模型用量。
MCP 服务日志显示运行 ID、工具名；不会打印签名上下文、模型密钥。
真实模型异常只向业务 API 暴露类别，MCP 服务端日志用于排查具体失败。

```powershell
New-Item -ItemType Directory -Force artifacts | Out-Null
& $projectPython -m pytest -q --basetemp "artifacts/pytest-v7-$([guid]::NewGuid().ToString('N'))"
& $projectPython scripts/accept_phase7.py
# 明确开启真实模型，会产生供应商调用费用
& $projectPython scripts/accept_phase7.py --live --output docs/acceptance/phase-7-live.json
```

集成脚本要求 PostgreSQL/Milvus 可用且有创建独立数据库权限。它创建随机命名的临时数据库，
启动专属 MCP 子进程，用全新 Worker 进程验证检查点恢复，最后清理自己创建的库。
不向现有业务库写入验收数据。临时运行日志在忽略目录 `artifacts/`。
真实样例仅证明调用链与约束工作，不代表已完成市场结论准确率评测。
