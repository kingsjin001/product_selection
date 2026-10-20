# 第五期验收报告

日期：2026-10-21；分支 `codex/v5`。

## 通过项目

- 37 项单元测试通过、ruff 通过、Vue/Vite 构建通过。
- 通用导入覆盖三种类型、重复批次、同 ID 冲突、整批回滚、市场与商品关系校验，
  导入同时登记索引 outbox。通过真实 PG 的 multipart CSV/JSONL 重复导入验证。
- 生成三份代表性报告，普通和缺失使用固定流程，冲突案例使用真实多 Agent；
  冲突报告 ID 为 `c811bd44-1fed-40ee-ad81-34e8b9104ec1`。
- 三种格式的导出重复请求返回相同制品 ID。逐一解析 Word，
  检查贡献利润数值及全部声明引用 ID 与报告 JSON 一致。
  通过 HTTP 下载检查 DOCX 字节和响应。
- 所有报告进行了无需模型的追问，并确认 report_hash 不变。
  冲突报告另完成一次真实模型追问，结果和用量独立保存。
  原始记录：[phase-5-results.json](phase-5-results.json)。
- 真实浏览器验证报告选择、证据展开、基准与保守情景切换、
  引用定位追问、成本修订任务创建。
  原售价 25 时基准利润 7.25；改为 26 后新报告 8.09，
  原报告保持 7.25。修订任务 ID `dad72902-8fa6-4f6a-9356-901744bfe24a`，
  parent_run_id 指向原报告。截图见 [工作台](phase-5-workbench.png)。

三份 JSON/Markdown/Word 文件位于 `docs/examples/`。
操作与样例解释见 [第五期指南](../phase-5-guide.md)。

## 未验证项目

已调用 documents 技能的 render_docx.py，但当前 Windows 运行环境缺少
LibreOffice soffice.exe，返回 FileNotFoundError。因此本期 **Word 打印分页、
字体替代及视觉版式未验收**，不能以 XML/正文检查替代截图检查。
未安装额外桌面办公软件，未声称已经完成视觉验收。

真实追问仅做一次调用和引用范围验证；语义支持仍需人工核验。
当前样例均为合成数据，不代表真实商品销量或真实法规。
