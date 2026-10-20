# 第二期：单品分析与恢复

本文描述第二期分支。第六期新增 `workflow` 并将其作为 B 方案和默认入口；
`fixed` 仅用于无模型工程验证。当前模式和 120 秒单次模型上限见 [README](../README.md)。

本期在第一期基础上增加固定 LangGraph 流程：
冻结请求/商品/证据 → 研究 → Decimal 成本计算 → 引用校验 → 原子保存报告。
业务表由 Alembic 管理，图检查点由官方 PostgresSaver 管理。

## 升级

在项目根目录，使用原来的 py12 环境：

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
& $projectPython -m pip install -e '.[dev]'
& $projectPython -m alembic upgrade head
```

不需要覆盖 `.env`。已有 PostgreSQL 数据继续保留。真实 Agent 使用已有模型配置。

## 运行

```powershell
& $projectPython -m app.analysis_cli --input data/sample/analysis-request.json
```

样例默认 `fixed` 模式，不调用模型。控制台先打印 `run_id`，随后将 JSON 和 Markdown 写入 `exports/`。
复制请求文件并将 `mode` 改为 `prompt` 或 `agent` 可运行真实模型：

| 模式 | 行为 |
| --- | --- |
| fixed | B 确定性基线：提取评论原文及统计，计算成本，不请求聊天/向量模型 |
| prompt | A 单次提示词基线：把同一快照一次性输入真实模型，JSON 错误最多修复一次 |
| agent | 主 Deep Agent 自主使用商品、评论、规则和证据详情工具 |

任何模式都使用同一个成本计算器和引用校验器。引用存在只能证明可定位，不能证明语义支持；
需在第六期进行人工对照评测。规则文字来自合成数据时，不能宣称已完成真实法规核验。

## 成本口径

全部金额以 `currency` 表示的同一币种、每售出一件计算。
费率是小数（例如 6% 写 `0.06`），基数为该情景售价。
退货项 `return_loss` 是分摊到每售出一件的净损失，不再额外扣减收入。
`other` 必须显式填入，需考虑的税费等由用户包含在这里。
缺任意一项就输出缺失信息，不以零补齐；确认没有某项成本时显式填 `0`。

基准样例贡献利润为 `7.25 USD`，售价 ±10% 的保守和乐观情景分别为 `5.15` 和 `9.35 USD`。
这些是输入假设下的贡献利润，不是净利或市场预测。

## 恢复与复用

```powershell
& $projectPython -m app.analysis_cli --run-id <已有运行ID>
```

报告已存在则直接导出，不重复调用模型。失败运行沿用原请求、冻结证据、模型版本和已消费次数，
通过 PostgreSQL 检查点恢复。相同运行使用 PostgreSQL advisory lock 避免并发恢复。
改变商品、成本或问题应创建新运行，不修改原报告。

外层图使用 `run_id` 作为 thread_id；研究子图使用 `run_id:research`。
研究结果已完成时复用其消息状态。尚未持久化的在途模型调用可能重放，不保证请求严格只执行一次。

## API

- `POST /api/analyses`：请求体同样例 JSON，同步执行并返回报告。
- `GET /api/analyses/{run_id}`：状态、快照、消费次数、报告。
- `POST /api/analyses/{run_id}/resume`：恢复原运行。

本期是同步接口，长请求需等待；第四期再加入异步队列与任务 API。
原第一期所有接口和脚本继续可用。

## 调用预算与限制

`MAX_MODEL_CALLS`、`MAX_TOOL_CALLS` 在运行创建时冻结，调用前通过数据库行锁预留额度，
失败调用也消耗额度，SDK 的模型自动重试关闭，格式修复最多一次。
`AGENT_TIMEOUT_SECONDS` 在调用及节点边界检查，单次聊天请求最长等待 60 秒；
它目前约束一次执行尝试，尚不等同于强制终止整个运行生命周期的硬超时。
token 用量保存到运行记录；未配置价格表时不编造费用。

Deep Agents 默认工具通过中间件白名单过滤，当前研究只允许五个业务只读工具。
实际授权由应用执行，而不只依赖系统提示词。

## 验收

```powershell
& $projectPython -m pytest -q
& $projectPython scripts/accept_phase2.py
# 额外调用真实聊天及向量模型
& $projectPython scripts/accept_phase2.py --live
```

实测报告见 [第二期验收](acceptance/phase-2.md)，原始结果见 `acceptance/phase-2-results.json`。
