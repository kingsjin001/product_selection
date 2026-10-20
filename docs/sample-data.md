# 合成样例数据说明

`data/sample/` 是第一期的可重复验证数据集。它用于演示导入、证据追溯、向量索引和规则检索，所有记录均为人工编写的 `synthetic` 合成数据，不是平台抓取数据、用户真实评论或正式法规文本。

## 数据规模与覆盖范围

| 文件 | 条数 | 内容 | 主要用途 |
| --- | ---: | --- | --- |
| `products.csv` | 20 | 商品名称、市场、品类、结构化规格 | 作为商品主数据 |
| `reviews.csv` | 20 | 评分、规格变体、中文体验反馈 | 演示可追溯评论证据 |
| `rules.jsonl` | 20 | 市场、品类、版本、来源、中文核验提示 | 作为第一期 Milvus 规则索引输入 |

品类覆盖厨房收纳、家居整理、宠物用品、旅行配件、美妆工具、运动配件、母婴用品和数码配件；市场字段覆盖 `US`、`UK` 与 `DE`。中文内容方便本地演示，市场字段用于验证 Milvus 的元数据过滤逻辑，并不代表该中文内容是对应市场的真实规则。

## 文件字段

### 商品：`products.csv`

| 字段 | 说明 |
| --- | --- |
| `product_id` | 稳定商品 ID，供评论关联 |
| `product_name` | 商品展示名称 |
| `market` / `category` | 目标市场与品类，用于筛选与检索 |
| `specifications` | CSV 内嵌 JSON，保存材质、尺寸、数量及卖点等结构化规格 |
| `source_url` | 合成来源地址，占位域名为 `example.invalid` |

### 评论：`reviews.csv`

| 字段 | 说明 |
| --- | --- |
| `review_id` / `product_id` | 评论自身 ID 与关联商品 ID |
| `rating` / `variant` | 评分与被评价的规格变体 |
| `content` | 中文评论文本，包含正向体验和待核验问题 |
| `observed_at` | 合成观察时间，采用 ISO 8601 UTC 格式 |
| `data_kind` | 固定为 `synthetic`，标识它不是实测或真实评论 |

### 规则：`rules.jsonl`

每行是一个独立 JSON 对象。规则导入后会成为 `Evidence`，再由 `index-rules` 写入 Milvus。

| 字段 | 说明 |
| --- | --- |
| `rule_id` | 稳定规则片段 ID |
| `title` / `text` | 核验主题与中文正文 |
| `market` / `category` | 检索过滤字段 |
| `version` / `valid_from` / `observed_at` | 版本与时间追溯字段 |
| `source_url` / `data_kind` | 合成占位来源与数据性质标识 |

规则正文只用于演示“检索到证据后仍需要人工核验”的产品行为，不能作为合规、法律、安全、医疗或销售决策依据。

## 导入与重复运行

导入器会对三个文件计算组合 SHA-256，作为 `ImportBatch.manifest_hash`。同一批文件再次导入时返回 `already_imported`，不会重复创建该批证据。

本次中文扩充数据采用新的 `prod-cn-*`、`review-cn-*` 和 `*-cn-*` ID。因此，已在本地导入旧版样例的开发数据库可以直接导入新批次，不会与旧证据主键冲突：

```powershell
$projectPython = 'D:\Programs\anaconda3\envs\py12\python.exe'
& $projectPython -m app.cli import-sample
& $projectPython -m app.cli index-rules
```

第二条命令会按当前 Embedding 配置重新写入规则向量。真实 Embedding 模式会请求模型服务；只验证流程时可先使用 `EMBEDDING_PROVIDER=mock`。

## 替换为自己的数据

可以复制这三份文件后按相同字段导入。新数据应满足：

1. `product_id`、`review_id` 和 `rule_id` 在各自类型内保持唯一。
2. 每条评论引用存在的 `product_id`，并且市场和品类与商品一致。
3. `specifications` 是有效 JSON；时间字段使用 ISO 8601 格式。
4. 真实数据应使用正确的 `data_kind`，例如 `observed`、`manual` 或 `estimated`；不要继续标为 `synthetic`。
5. 对规则保留真实来源、版本、采集时间和适用市场，并在索引前完成人工核验。
