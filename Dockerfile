# 应用容器使用独立 Python 运行时；宿主机开发仍使用用户指定的 py12 环境。
FROM python:3.11-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app
COPY pyproject.toml README.md ./
COPY app ./app
COPY data ./data
COPY alembic.ini ./
COPY migrations ./migrations
RUN pip install --upgrade pip && pip install .

EXPOSE 8000
# 先应用结构迁移，再启动 API，避免运行时同时维护两套建表逻辑。
CMD ["sh", "-c", "alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port 8000"]

