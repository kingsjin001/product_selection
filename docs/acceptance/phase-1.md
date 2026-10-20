# 第一期基线复验报告

日期：2026-10-21（Asia/Shanghai）。基线：`v1` / `360a9b3`；复验在其派生的 `v2` 工作区执行。

## 实测结果

- 指定解释器：`D:\Programs\anaconda3\envs\py12\python.exe`。
- `python -m pytest -q`：12 passed。
- `python -m ruff check app tests`：通过；受限缓存目录存在扫描提示。
- Docker：PostgreSQL、Redis、etcd、MinIO 正在运行；本次检查时 Milvus 未运行。
- 上一次会话完成过真实 Embedding 索引及中文检索；本报告不将历史结果冒充本次全链路测试。

## 交付完整性

发现 6 个第一期文件未被 `v1` 提交跟踪：
`app/core/logging.py`、`docs/cli-usage.md`、`docs/pycharm-run.md`、
`docs/sample-data.md`、`tests/fixtures/model-indirection.env`、`tests/test_milvus_client.py`。
在 `v2` 中补齐，不改写用户已发布的 `v1` 历史。
为便于单独检出第一期，另建立 `codex/v1` 补全基线分支，仅增加上述六个文件
及本报告。用户的原始 `v1` 分支保持在原提交；后续 `v2` 已包含同样的补全内容。

第六期收尾时从 `codex/v1` 的 `436c635` 提交导出独立源码目录，再以 py12 执行：
12 个测试通过，Ruff 通过，确认导入的 `app` 来自该导出目录。
这是独立源码快照验证，仍然复用了本机依赖，不能称为全新系统环境安装。

## 结论

本地单元测试通过。原 `v1` 提交缺少运行文件，因此不能声称独立克隆该提交即可完整运行。
真实聊天模型的完整 Agent 演示、本次干净数据库复现尚未在本次基线复验中执行。
