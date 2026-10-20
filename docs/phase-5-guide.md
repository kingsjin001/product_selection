# 第五期：导入到报告交付

先执行 `python -m alembic upgrade head`，再在 frontend 执行 `npm ci`、
`npm run build`。重启 API 后可直接打开 `http://127.0.0.1:8000/` 使用构建页面；
开发时仍可使用 `npm run dev`。后台进程启动方法沿用第四期指南。

## 工作台流程

1. **导入资料**：商品 CSV、评论 CSV、规则 JSONL 可以一起或分别上传。
   UTF-8 编码，每份最多 5 MiB。先有商品才能导入关联评论。
   “导入内置样例”仍走第一期的幂等样例入口。
2. **研究任务**：选择商品编号，固定流程先跑通后台链路，
   再选择单次模型、单 Agent 或多 Agent。动态研究需要第三期索引同步。
3. **报告库**：选择历史报告，展开引用，切换保守/基准/乐观成本情景，
   下载 Word、Markdown 或 JSON。
4. **追问**：默认“在报告中定位”仅摘录现有内容，不调用模型。
   切换“真实模型解读”后发起一次真实请求，独立保存 token 和回答。
   原报告 hash 保持不变，回答只允许引用原快照证据。
5. **成本修订**：编辑显式成本假设，创建新的后台任务。
   新任务保留原证据快照，并在 versions.parent_run_id 记录来源报告。
   若证据后来失效，发布校验会拒绝，需基于新资料重新研究。

## 上传样例

`data/workbench/` 提供同一份资料的 JSON 与 CSV/JSONL 两种表示：

| 商品 | 说明 |
| --- | --- |
| demo-v5-normal | 两条桌面收纳盒评论，展示普通研究 |
| demo-v5-missing | 两条宠物水杯评论，报告示例不提供成本 |
| demo-v5-conflict | 500ml 静置冷水无漏、1L 倾斜装汤漏水，规格和使用条件同时变化 |

全部为合成数据。第三种不能证明“大号导致漏水”，只适合展示条件差异与缺失识别。
三件商品、六条评论、三条规则是在原先各 20 条中文样例之外新增的专项场景。

`POST /api/imports` 接受 `import.json` 的对象；文件上传用
`POST /api/imports/files` 的 products/reviews/rules 字段。
相同批次返回 already_imported；相同 ID 不同正文整体拒绝，不静默覆盖资料。
修改证据请用第三期显式更新接口。上传第一期已导入的原始 CSV 到新通用入口时，
不同来源规范可能被识别为冲突；复用原样例时应使用“导入内置样例”。

## 导出与版本

`POST /api/reports/{id}/exports` 请求 `{"format":"docx"}`，也支持 json、md。
返回 download_url，GET 下载。导出以 run_id、report_hash、format、模板版本
生成稳定 ID，相同请求复用数据库内相同文件字节。导出不调用模型。
模板代码位于 `app/services/reports.py`，版本为 report-docx-v1。

`docs/examples/` 提供普通、缺失、冲突三份 JSON/Markdown/Word。
它们来自验收的真实运行记录，当前 Word 数值与引用已检查，打印分页尚未视觉验收，
原因见第五期验收报告。

接口默认只面向本机；暂无账号和多用户权限。数据库备份应同时包含
analysis_reports、report_exports 和 report_questions，才能保留完整交付历史。
