# 第二期验收报告

日期：2026-10-21（Asia/Shanghai）。分支：v2。

## 已实现

- 固定 LangGraph 外层流程、不可变输入/证据快照、PostgreSQL 检查点。
- 主 Deep Agent 与商品/评论/计数/规则/证据五个工具；运行预算与工具白名单。
- 三种模式：fixed、prompt、agent；确定性 Decimal 利润、三种售价情景。
- Pydantic JSON 结构校验、引用范围校验、最多一次格式修复。
- 唯一报告、JSON/Markdown 同源导出、同步 API/CLI 与按运行恢复。

## 实测

| 检查 | 结果 | 证据 |
| --- | --- | --- |
| 全部单元测试 | 21 passed | pytest -q |
| 五个完整输入 | 5/5 通过 | phase-2-results.json |
| 三个缺失成本输入 | 3/3 通过；不生成利润 | 同上 |
| PostgreSQL 持久检查点 | 8/8 运行有 checkpoint | 官方 PostgresSaver 读取断言 |
| 已完成运行幂等重放 | 8/8 返回相同报告 | 同上 |
| 提交前注入故障后恢复 | 单元测试通过；研究只执行一次 | test_resume_after_persist_failure_skips_completed_research |
| 真实 Deep Agent | 完成，4 次模型、5 次工具调用 | run 4779e62c-83fa-416c-8e7b-85f8eff04bf1 |
| 真实规则检索 | 召回中文密封相关证据 | 上述运行的 search_rules 调用 |
| token 用量 | 输入 7010 / 输出 3362 | 数据库调用账本；费用未估算 |
| 伪造引用、错误费率、失败调用预算 | 拒绝/计数测试通过 | tests/test_analysis.py |

## 验收范围与待补

数据为合成样例；此次运行证明工程链路，不能证明商业效果。
五个完整和三个缺失案例使用 fixed 模式；仅单个案例执行真实 Agent。
prompt 基线入口已实现，但真实 A/B 质量比较留待第六期，未用单元测试代替。
外层提交失败恢复本次用内存 checkpointer 注入故障验证；PostgreSQL 已验证持久化和正常重放，
尚未执行真实 Worker 进程崩溃故障（第四期）。
当前运行时间限制按一次执行尝试计，恢复不会清零模型/工具次数；尚无跨重启总时长硬预算。
引用校验只验证存在性/快照归属，未自动证明每条声明的语义支撑。

本报告不将待补项标为已通过。后续必须在对应期次追加实测记录。
