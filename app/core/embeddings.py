import hashlib
import logging
import math
import re
from collections.abc import Iterable

from openai import OpenAI

from app.core.config import Settings

logger = logging.getLogger(__name__)


class EmbeddingService:
    """向量生成适配器：支持离线确定性向量和任意 OpenAI 兼容服务。"""

    def __init__(self, settings: Settings) -> None:
        """保存配置，实际客户端只在调用真实模型时创建。"""
        self.settings = settings

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        """将一批文本转为向量；mock 只用于工程验证，不能评估语义质量。"""
        values = list(texts)
        logger.info(
            "开始生成向量 | provider=%s model=%s texts=%d dimension=%d batch_size=%d",
            self.settings.embedding_provider,
            self.settings.embedding_model or "mock",
            len(values),
            self.settings.embedding_dim,
            self.settings.embedding_batch_size,
        )
        logger.debug("向量化文本样例 | preview=%r", values[0][:120] if values else "")
        if self.settings.embedding_provider == "mock":
            vectors = [self._mock_embedding(value) for value in values]
            logger.debug("离线向量生成完成 | vectors=%d", len(vectors))
            return vectors
        if not self.settings.model_api_key or not self.settings.embedding_model.strip():
            raise RuntimeError(
                "MODEL_API_KEY and EMBEDDING_MODEL are required for openai_compatible embeddings"
            )

        # base_url 留空时由 OpenAI SDK 使用其默认地址；填入后可接任意兼容服务。
        client_options = {
            "api_key": self.settings.model_api_key.get_secret_value(),
            "timeout": 30, "max_retries": 0,
        }
        if self.settings.model_base_url:
            client_options["base_url"] = self.settings.model_base_url
        client = OpenAI(**client_options)
        request_options = {"model": self.settings.embedding_model}
        # 并非所有 OpenAI 兼容服务都接受 dimensions；未声明支持时不发送该参数。
        if self.settings.embedding_request_dimensions is not None:
            request_options["dimensions"] = self.settings.embedding_request_dimensions
        vectors: list[list[float]] = []
        # 部分兼容接口限制单次请求条数；分批后按原顺序拼接，保证证据与向量一一对应。
        for start in range(0, len(values), self.settings.embedding_batch_size):
            batch = values[start : start + self.settings.embedding_batch_size]
            logger.debug(
                "请求 Embedding 批次 | start=%d size=%d", start, len(batch)
            )
            response = client.embeddings.create(**request_options, input=batch)
            vectors.extend(item.embedding for item in response.data)
        if any(len(vector) != self.settings.embedding_dim for vector in vectors):
            actual_dimensions = sorted({len(vector) for vector in vectors})
            raise RuntimeError(
                "Embedding response dimension does not match EMBEDDING_DIM: "
                f"expected {self.settings.embedding_dim}, received {actual_dimensions}"
            )
        logger.info("真实向量生成完成 | vectors=%d", len(vectors))
        return vectors

    def embed_one(self, text: str) -> list[float]:
        """将单条文本转为向量，复用批量接口以保持行为一致。"""
        return self.embed_many([text])[0]

    def _mock_embedding(self, text: str) -> list[float]:
        """生成稳定的哈希词袋向量，仅用于离线测试，不代表语义向量。"""
        vector = [0.0] * self.settings.embedding_dim
        tokens = re.findall(r"[a-z0-9]+|[\u4e00-\u9fff]", text.lower())
        for token in tokens:
            digest = hashlib.sha256(token.encode("utf-8")).digest()
            position = int.from_bytes(digest[:4], "big") % self.settings.embedding_dim
            sign = 1.0 if digest[4] % 2 else -1.0
            vector[position] += sign
        norm = math.sqrt(sum(value * value for value in vector))
        return [value / norm for value in vector] if norm else vector
