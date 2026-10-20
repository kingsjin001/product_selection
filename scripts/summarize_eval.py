"""生成可审阅评测摘要和未填写的引用支持率复核表。"""

import csv
import json
from pathlib import Path


def main():
    """不自动填写人工判断，也不覆盖已经存在的复核表。"""
    comparison = json.loads(Path("evals/compare-results.json").read_text(encoding="utf-8"))
    retrieval = json.loads(Path("evals/retrieval-results.json").read_text(encoding="utf-8"))
    rows = comparison["cases"]
    lines = [
        "# 第六期评测记录", "", "日期：2026-10-21。数据均为合成样例，目标是验证工程行为。",
        "", "## 数据与实验约束", "",
        "- 冻结 20 个商品：12 个开发、8 个留出；语料库 56 条证据。",
        "- 40 条检索查询：24 个开发、16 个留出。预期相关项由开发者根据合成原文编写，"
        "未经独立人工复核，也不保证穷尽相关项。",
        "- 生成对照预先选择留出商品 013、017、020，每方案各运行一次，共 9 次。"
        "其余 5 个留出商品只参加无模型工程回归，不能称为全部留出集生成评测。",
        "- A 单次输入全部冻结资料；B 固定评论/规则 RRF 后一次模型综合；"
        "C Deep Agent 自主调用相同业务工具，可选专项委派。三者共享证据可访问范围、"
        "模型及预算，但实际读取内容和次数不同。",
        "- A 包含同市场的全部冻结规则；B/C 检索再按品类过滤。"
        "这是端到端策略对照，token 差异包含资料筛选效果，不能视为隔离变量的 Agent 能力实验。",
        "- 输入快照、提示词摘要、模型和索引身份保存在 frozen-v1.json 与原始结果中。"
        "复现前会检查文件和数据库语料摘要。",
        "", "## 生成对照", "",
        "| 方案 | 完成 | 中位耗时 s | 最大耗时 s | 模型调用 | 工具调用 | 输入 token | "
        "输出 token | 引用可解析 |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    for label in ("A", "B", "C"):
        item = comparison["summary"][label]
        lines.append(
            f"| {label} | {item['completed']}/{item['total']} | {item['median_seconds']:.3f} | "
            f"{item['max_seconds']:.3f} | {item['model_calls']} | {item['tool_calls']} | "
            f"{item['input_tokens']} | {item['output_tokens']} | "
            f"{item['citations_valid']}/{item['citations_total']} |"
        )
    numeric = [r for r in rows if r.get("report", {}).get("economics", {}).get("status") == "ok"]
    missing = [r for r in rows if r.get("missing_ok") is not None]
    delegated = sum(c["name"] == "task" for r in rows for c in r["calls"])
    lines.extend([
        "", f"完整成本报告 {len(numeric)} 份，共 {len(numeric) * 3} 个情景的贡献利润与"
        "独立固定预期一致；缺失成本识别 "
        f"{sum(r['missing_ok'] for r in missing)}/{len(missing)}。",
        f"本组 C 的专项委派次数为 {delegated}，因此这里衡量的是自主工具路径，"
        "不能把差异归因于子 Agent。专项委派的真实轨迹另见第三期报告。",
        "", "费用保持未知：未提供账户单价。pricing.example.json 支持填写单价后估算"
        "已返回的聊天 token 费用，不包括 Embedding、失败请求未返回的用量及基础设施。"
        "不能把未知费用填写为零。",
        "", "## 检索实验", "",
        "| 子集 | 方法 | 查询数 | Recall@5 | nDCG@5 |",
        "| --- | --- | --- | --- | --- |",
    ])
    for split in ("dev", "holdout"):
        for method, item in retrieval["summary"][split].items():
            lines.append(f"| {split} | {method} | {item['queries']} | "
                         f"{item['recall_at_5']:.4f} | {item['ndcg_at_5']:.4f} |")
    lines.extend([
        "", "每条查询只有一个预期相关项。开发集关键词命中 23/24，向量和融合命中 24/24；"
        "留出集三者都命中 16/16。部分市场候选很少，指标偏容易，不能外推到真实开放语料。",
        "RRF 的 k=20/60/100 在本组结果相同，保留预设 k=60；没有按留出结果选择最优参数。",
        "", "## 结论与产品选择", "",
        "本组 B 使用的总聊天 token 少于 A/C，且保留固定的证据检索与计算链路，"
        "因此将默认研究入口设为 B。C 保留给多规格、冲突或需要补查的任务，"
        "不强制委派简单问题。本组 C 耗时更短，但每组仅 3 次且模型存在缓存与随机性，"
        "不能宣称它稳定更快，也不报告有统计意义的 P95。",
        "", "本次没有证据证明自主研究或融合检索带来整体质量提升。"
        "引用可解析率不等于引用支持率；所有方案的利润来自同一个确定性计算器，"
        "数值一致也不是模型更智能的证据。",
        "", "## 语义复核与失败案例", "",
        "evals/human-review.csv 提供 43 个声明与引用关系的原文复核行，supported 留空，"
        "未完成独立人工支持率测量，因此不宣称达到 ≥90%。"
        "evals/blind-mapping.json 保留方案映射供复核结束后解盲。",
        "第三期观察到合成规则被写成市场要求、无效 JSON、修复超时和过度补查。"
        "保留原始失败轨迹，并分别以合成数据提示、JSON 输出模式、120 秒单次上限"
        "及补查限制修正。九次当前对照没有失败，不代表历史失败不存在。",
        "", "## 复现", "", "```powershell",
        "& D:\\Programs\\anaconda3\\envs\\py12\\python.exe scripts/evaluate.py retrieval "
        "--output evals/retrieval-new.json",
        "& D:\\Programs\\anaconda3\\envs\\py12\\python.exe scripts/evaluate.py compare "
        "--output evals/compare-new.json", "```", "",
        "冻结文件与旧结果不会由评测命令覆盖。第二条会调用真实聊天模型；"
        "语料发生变化时必须另建评测版本。恢复回归见第六期验收报告。",
    ])
    Path("docs/evaluation.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    path = Path("evals/human-review.csv")
    if not path.exists():
        mapping = {}
        with path.open("w", encoding="utf-8-sig", newline="") as output:
            writer = csv.DictWriter(output, fieldnames=[
                "review_id", "case", "statement", "evidence_id", "evidence_text",
                "supported", "notes", "reviewer",
            ])
            writer.writeheader()
            count = 0
            for row in rows:
                evidence = {item["id"]: item for item in row["report"]["evidence"]}
                for claim in row["report"]["research"]["claims"]:
                    for eid in claim["evidence_ids"]:
                        count += 1
                        identity = f"review-{count:03}"
                        mapping[identity] = {"method": row["method"], "run_id": row["run_id"]}
                        writer.writerow({"review_id": identity, "case": row["case"],
                                         "statement": claim["statement"], "evidence_id": eid,
                                         "evidence_text": evidence[eid]["text"]})
        Path("evals/blind-mapping.json").write_text(
            json.dumps(mapping, ensure_ascii=False, indent=2), encoding="utf-8",
        )
    print("evaluation summary saved")


if __name__ == "__main__":
    main()
