---
name: review-analysis
description: 分析商品评论、规格差异、评分分布与样本局限时使用。
---

# 评论分析

先用 read_file 阅读本文件，然后按需调用 summarize_review_counts、query_reviews 或 search_reviews。
先核对样本分母，再整理主要问题；一次研究最多两次检索，不猜测规格逐个查询。
每条观察保留 evidence_ids、来源与规格；没有销量序列不能推出增长趋势。
未记录的温度、时长和操作条件保持未知，不以生活常识补全；例如“装汤”不能改写成“热汤”。
合成评论明确写为“合成样例”，不能称为真实消费者调查。
相反反馈可同时成立，优先核对规格、日期和使用条件，不以多数票删除少数反馈。
输出简短 JSON 研究契约，引用缺失时写入 missing_data。
