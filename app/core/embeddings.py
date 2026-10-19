import hashlib
import math
import re
from collections.abc import Iterable

from openai import OpenAI

from app.core.config import Settings


class EmbeddingService:
    """向量生成适配器：支持离线确定性向量和任意 OpenAI 兼容服务。"""

    def __init__(self, settings: Settings) -> None:
        """保存配置，实际客户端只在调用真实模型时创建。"""
        self.settings = settings

    def embed_many(self, texts: Iterable[str]) -> list[list[float]]:
        """将一批文本转为向量；mock 只用于工程验证，不能评估语义质量。"""
        values = list(texts)
        if self.settings.embedding_provider == "mock":
            return [self._mock_embedding(value) for value in values]
        if not self.settings.model_api_key or not self.settings.embedding_model.strip():
            raise RuntimeError(
                "MODEL_API_KEY and EMBEDDING_MODEL are required for openai_compatible embeddings"
            )

        # base_url 留空时由 OpenAI SDK 使用其默认地址；填入后可接任意兼容服务。
        client_options = {"api_key": self.settings.model_api_key.get_secret_value()}
        if self.settings.model_base_url:
            client_options["base_url"] = self.settings.model_base_url
        client = OpenAI(**client_options)
        response = client.embeddings.create(
            model=self.settings.embedding_model,
            input=values,
            dimensions=self.settings.embedding_dim,
        )
        return [item.embedding for item in response.data]

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
