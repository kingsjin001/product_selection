# 第六期验收报告

日期：2026-10-21；分支 `codex/v6`，版本 0.6.0。
解释器使用 `D:\Programs\anaconda3\envs\py12\python.exe`。

## 本期交付

冻结开发/留出集、A/B/C 对照、检索融合参数实验、模型调用用量与延迟、
失败案例修正、恢复回归、空数据库复现、项目依赖闭包锁定、
当前架构与选型文档、README 和 3 分 04 秒字幕演示视频。
默认研究模式调整为 `workflow`，保留 Deep Agents 自主研究。
数据库引擎和会话工厂按进程缓存，避免每次请求重新建立连接池。

## 验收结果

| 检查 | 结果 | 证据与范围 |
| --- | --- | --- |
| 单元/边界测试 | 44 passed | pytest；含预算、非法 JSON、异常、引用、删除、导出、追问和状态边界 |
| 静态检查 | 通过 | Ruff，app/tests/scripts；受限的旧 tests/pytest_cache 目录产生扫描提示 |
| 前端构建 | 通过 | Vite production build |
| 留出工程回归 | 8/8 | `phase-6-regression.json`；fixed 后台任务、重复领取、成本/缺失与 SSE 游标 |
| 真实恢复回归 | 5/5 | `phase-6-recovery.json`；真实 PG/Redis/Celery，故障注入与实际子进程退出 |
| 空数据库复现 | 通过 | `reproduction-results.json`；临时 PG 库迁移、20/20/20 导入、后台报告利润 7.25 |
| Milvus 生命周期 | 4/4 | 重复事件、连续更新/晚到事件、软删除过滤、物理清理；真实 Milvus，隔离 mock 16 维向量 |
| 生成对照 | 9/9 完成 | `evals/compare-results.json`；3 个预选留出商品 × A/B/C，真实聊天模型 |
| 数字与引用 | 18/18、43/43 | 六份完整成本报告的三情景；引用可解析，非语义支持率 |
| 缺失识别 | 3/3 | 一个缺失商品 × 三方案 |
| 检索实验 | 40/40 查询完成 | `evals/retrieval-results.json`；真实 Embedding，开发 24/留出 16 |
| 项目依赖闭包 | 115 包约束通过 | `dependency-results.json` 与 `requirements.project.lock` |
| 视频 | 184 秒、1280×720 | `video-results.json`；无音轨字幕版，逐场景视觉检查 |
| 第一期补全分支 | 独立源码测试通过 | `codex/v1` 导出目录执行 12 测试、Ruff，复用现有环境 |

恢复五项覆盖幂等投递、发送后事务中断重投、Worker 退出/检查点恢复、
取消与旧 epoch 写入拒绝、SSE 断点补发。脚本保留故障注入过程，
不能用最终成功掩盖过程中的预期异常。

## 评测口径

详见 [评测报告](../evaluation.md)。20 个商品按 12/8 冻结；生成对照只覆盖
留出集中的 013、017、020，不能称为全部八个商品都做了真实模型对照。
40 个查询均只有一个开发者编写的预期相关项，候选集小，未独立复核。

A/B/C 引用可解析率都达到本组 100%，成本数字来自相同确定性计算器。
本组 C 没有专项委派，不证明子 Agent 的效果；保留第三期真实委派轨迹。
融合与纯向量/关键词在留出查询均为 16/16 命中，没有观察到融合收益。
RRF k=20/60/100 同结果，保留预先设定的 60，没有在留出集调优。

已记录模型、提示词、数据摘要和索引身份。没有提供账户单价，
金额保持未知，token 不代表完整账单，失败请求或 Embedding 费用不能算作零。

## 未完成或受限项

- **独立人工引用支持率未测量**：已输出 43 行原文复核表，supported/reviewer 留空；
  不宣称达到设计中的 ≥90% 语义支持目标。
- **Word 打印版式未验收**：数值和引用的结构性检查通过；当前可用运行依赖没有
  LibreOffice，render_docx 尝试失败，不能确认分页、字体及表格视觉效果，见第五期报告。
- **不是全新操作系统复现**：已验证空 PostgreSQL 库及隔离 Milvus 集合，
  但仍复用 py12 和现有 Docker，未全新安装整个环境。
- **共享环境不是 pip check 全通过**：langchain-redis 0.2.5 与 hf-xet 1.5.1，
  opentelemetry-semantic-conventions 0.60b1 与 opentelemetry-api 1.45.1
  存在非本项目依赖闭包内的组合冲突。未擅自调整这些包。
- **没有真实商品数据 API 接入**：未提供相关授权；保留文件导入模式。
- **视频为字幕讲解版**：实际截图与验收记录合成，无实时点击录屏和音轨。

代码交付完成，以上验收项仍保留明确状态，不能称“所有设计质量指标全部达标”。

## 重放命令

先完成根 README 的依赖、迁移、样例导入和索引步骤：

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
& $projectPython -m pytest -q
& $projectPython -m ruff check app tests scripts
& $projectPython scripts/accept_phase6.py
& $projectPython scripts/accept_phase4.py --output exports/recovery-new.json
& $projectPython scripts/verify_reproduction.py
& $projectPython scripts/evaluate.py retrieval --output evals/retrieval-new.json
& $projectPython scripts/evaluate.py compare --output evals/compare-new.json
```

`verify_reproduction.py` 需要当前 PostgreSQL 账号有创建数据库权限，
只删除本次刚创建的随机命名临时库和专用向量集合；现有业务库不清空。
该脚本和 `accept_phase6.py` 会更新对应验收 JSON；
评测命令拒绝覆盖已存在的输出，重复运行请换文件名。
运行比较会产生真实模型费用；冻数据发生变化时应建立新的评测版本。
