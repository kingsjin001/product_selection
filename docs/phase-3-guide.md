# 第三期：自主研究与版本化检索

在第二期基础上迁移数据库：

```powershell
& D:\Programs\anaconda3\envs\py12\python.exe -m alembic upgrade head
& D:\Programs\anaconda3\envs\py12\python.exe -m app.index_cli rebuild
```

`rebuild` 为现有证据登记 outbox，随后写入规则、评论两个集合；批次默认处理 100 条，
超过时继续执行 `sync`，直到 `status` 中 pending 为 0。重复执行会重新计算向量，
但相同版本只保留一个主键；因此也可用于集合丢失后的重建。

| 命令 | 用途 |
| --- | --- |
| `python -m app.index_cli enqueue` | 仅登记全部证据 |
| `python -m app.index_cli sync` | 消费到期事件，失败指数退避，最多 5 次 |
| `python -m app.index_cli status` | 查看事件状态和版本 manifest 数量 |
| `python -m app.index_cli retry` | 人工重置最终失败事件，之后执行 sync |

复制 `data/sample/analysis-request.json` 到自己命名的文件，将 `mode` 改为 `multi`，
再执行 `python -m app.analysis_cli --input 你的文件.json --output artifacts/研究`。
不必修改原始样例或 `.env`。

主 Deep Agent 可调用 `task` 委派 `reviews`、`rules` 两个专项 Agent。
每个子 Agent 只有对应业务工具，没有 Shell、任意文件或再次委派权限。
所有模型、工具调用共用数据库预算；子图检查点由父图管理。
`write_research_note` 将带引用的短笔记保存在 PostgreSQL，按 run_id 隔离。
委派属于模型决策，简单缺失问题可以直接结束，不强制执行所有工具。

检索先按类型、市场、品类和商品过滤，以向量和中文二元词组重合排名做 RRF 融合。
这只是轻量关键词基线，并非完整 BM25。Milvus 不可用会报错，不返回“无风险”。
数据量增大后应将当前内存关键词排序迁移到数据库全文检索。

集合名包含 Embedding 提供方式、模型、维度和预处理版本摘要。证据版本主键由
`evidence_id + content_hash` 构成。更新和软删除与 outbox 同事务提交，
旧事件始终同步数据库的最新状态；删除先从检索和新快照隐藏，再清理各集合的向量。
提交报告时锁定引用证据，拒绝已经更新或删除的版本；已提交报告保留历史快照。

`PATCH /api/evidence/{id}` 请求 `{"content":"新正文"}`；`DELETE` 软删除。
这些本地开发接口没有用户鉴权，保持 API 绑定 `127.0.0.1`。
服务不会自动恢复失败报告中的过时快照，应创建新分析。

A 使用 `prompt` 一次性输入快照，B 使用 `fixed` 展示原文和确定性计算，
C 使用 `multi`。目前 B 仍是保守原文基线，不能把它与 C 的差异直接宣称为智能收益。
第六期将用同一数据范围记录模型、调用、token、数值和引用指标。
