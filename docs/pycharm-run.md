# PyCharm 本地启动 FastAPI

本项目使用 PyCharm 启动 FastAPI；Docker 仅运行 PostgreSQL、Redis 和 Milvus 等依赖服务。

## 首次准备

1. 在 PyCharm 中打开 `E:\my_object\product_selection`。
2. 将 Python Interpreter 设置为 `D:\Programs\anaconda3\envs\py12\python.exe`。
3. 复制配置并安装依赖：

```powershell
Copy-Item .env.example .env
& 'D:\Programs\anaconda3\envs\py12\python.exe' -m pip install -e '.[dev]'
docker compose up -d
& 'D:\Programs\anaconda3\envs\py12\python.exe' -m alembic upgrade head
```

`.env` 中的 `DATABASE_URL`、`REDIS_URL` 和 `MILVUS_HOST` 保持 `localhost`，这样本地 Python 进程会连接到 Docker 暴露的端口。

## 引用系统环境变量

`Settings` 会将字段名自动映射为大写环境变量。例如 `embedding_model` 对应 `EMBEDDING_MODEL`，并且系统环境变量的优先级高于 `.env`。最简单的方式是在 Windows 或 PyCharm 运行配置中直接设置同名变量：

```text
MODEL_API_KEY=...
MODEL_BASE_URL=...
CHAT_MODEL=...
EMBEDDING_MODEL=...
EMBEDDING_DIM=...
```

如果密钥已使用其他名称保存为系统环境变量，可以在 `.env` 中引用它，不必复制真实密钥：

```dotenv
MODEL_API_KEY=${LOCAL_MODEL_API_KEY}
```

其中 `LOCAL_MODEL_API_KEY` 是系统环境变量名。设置或修改 Windows 系统环境变量后，需要完全重启 PyCharm，或者在当前 Run Configuration 的 **Environment variables** 中补充该变量，运行进程才能读取到新值。

## 创建运行配置

在 **Run → Edit Configurations → + → Python** 中创建配置：

| 字段 | 值 |
| --- | --- |
| Name | `本地 FastAPI` |
| Run | `Module name` |
| Module name | `uvicorn` |
| Parameters | `app.main:app --host 127.0.0.1 --port 8000 --reload` |
| Working directory | `$PROJECT_DIR$` |
| Python interpreter | `D:\Programs\anaconda3\envs\py12\python.exe` |

点击运行后，访问 `http://127.0.0.1:8000/docs`。在另一个 PowerShell 窗口执行：

```powershell
.\scripts\verify-phase1.ps1
```

## 查看运行日志

默认 `LOG_LEVEL=INFO`，控制台会显示导入、向量生成、Milvus 写入和检索的关键步骤与数量。调试时，将 `.env` 中的 `LOG_LEVEL` 改为 `DEBUG`，或在 PyCharm Run Configuration 的 **Environment variables** 增加：

```text
LOG_LEVEL=DEBUG
```

`DEBUG` 会额外输出查询文本预览、前三条证据 ID 与相似度、导入批次摘要等少量样例数据；不会输出 API Key。修改后停止并重新运行 FastAPI 配置。

## 真实模型模式

在启动前将 `.env` 的 `EMBEDDING_PROVIDER` 改为 `openai_compatible`，并填写 `MODEL_API_KEY`、`MODEL_BASE_URL`、`CHAT_MODEL`、`EMBEDDING_MODEL` 和 `EMBEDDING_DIM`。修改 `.env` 后停止并重新运行 PyCharm 配置，使新环境变量生效。

## 百炼推荐起步配置

对于当前仅包含文本规则和评论的第一期项目，推荐使用 `text-embedding-v4` 生成 1024 维文本向量，并使用支持 Function Calling 的 `qwen3.7-plus` 驱动 Deep Agent。`.env` 可配置为：

```dotenv
EMBEDDING_PROVIDER=openai_compatible
EMBEDDING_MODEL=text-embedding-v4
EMBEDDING_DIM=1024
EMBEDDING_REQUEST_DIMENSIONS=1024
# 当前向量接口单次最多 10 条文本时保持默认值。
EMBEDDING_BATCH_SIZE=10
MODEL_API_KEY=${LOCAL_MODEL_API_KEY}
MODEL_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
CHAT_MODEL=qwen3.7-plus
```

上例使用北京共享域名；生产使用时应在百炼业务空间中复制与 API Key 同地域的专属 API Host。若选择新加坡、美国或其他地域，必须同步替换 `MODEL_BASE_URL`。模型与权限以 [百炼模型列表](https://help.aliyun.com/zh/model-studio/text-generation-model/) 和控制台实际可用范围为准。
