# Docker Desktop 手动安装与启动

第一期依赖 PostgreSQL、Redis、Milvus、etcd 和 MinIO，均由 `docker-compose.yml` 拉起。FastAPI 由 PyCharm 在宿主机启动，不使用 Docker API 容器。项目不需要单独安装这些中间件。

## 1. 安装 Docker Desktop

1. 从 [Docker Desktop for Windows 官方页面](https://www.docker.com/products/docker-desktop/) 下载并安装。
2. 安装过程中选择 WSL 2 backend；如果安装程序提示启用 WSL 2 或虚拟化，按其引导完成并重启 Windows。
3. 启动 Docker Desktop，等待界面显示 Engine 正在运行。
4. 在新的 PowerShell 中确认：

```powershell
docker version
docker compose version
```

`docker version` 必须同时显示 Client 和 Server。若只显示 Client 或提示 `docker_engine` 不存在，说明 Docker Desktop 尚未完全启动。

## 2. 启动项目组件

在项目根目录执行：

```powershell
Copy-Item .env.example .env
docker compose up -d
docker compose ps
```

默认命令只启动依赖服务，不会启动 `api` 容器。数据库迁移与 FastAPI 由 PyCharm 本地运行配置执行，步骤见 [PyCharm 本地启动说明](pycharm-run.md)。

首期默认使用 `EMBEDDING_PROVIDER=mock`，不需要模型 Key。容器、端口和用途：

| 服务 | 主机端口 | 用途 |
| --- | --- | --- |
| postgres | 5432 | 证据、导入批次和业务数据 |
| redis | 6379 | 后续任务队列预留 |
| milvus | 19530 | 规则向量检索 |
| Milvus Web UI | 9091 | 查看向量集合 |
| minio | 9000 / 9001 | Milvus 对象存储及控制台 |

端口全部绑定到 `127.0.0.1`，不会暴露到局域网。

如需连接真实模型服务，在 `.env` 中使用通用字段 `MODEL_API_KEY`、`MODEL_BASE_URL`、`CHAT_MODEL` 和 `EMBEDDING_MODEL`。同名系统环境变量会覆盖 `.env`，因此密钥也可以只保存到当前终端或 CI 的安全变量中。

若确实需要容器化 API，可显式运行下面的命令；它不是本地开发默认方式：

```powershell
docker compose --profile container-api up -d --build api
```

## 3. 验证与停止

```powershell
.\scripts\verify-phase1.ps1
docker compose logs milvus
```

停止但保留数据：

```powershell
docker compose down
```

删除本项目所有容器数据卷并重新开始：

```powershell
docker compose down -v
```

最后一条会删除本项目 PostgreSQL、Redis 与 Milvus 的本地数据，只有确定不需要保留导入记录和索引时才执行。

