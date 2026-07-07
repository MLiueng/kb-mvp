"""Embedding 通用适配层：支持本地部署（Ollama）与线上 API 灵活切换。

设计要点：
- BaseEmbedding 抽象基类定义统一接口 embed
- DashScopeEmbedding：通义千问 text-embedding 原生 SDK（分批 25 条）
- OpenAICompatibleEmbedding：基于 openai SDK，覆盖 Ollama 本地模型与其他兼容端点
- create_embedding() 工厂根据 EMBEDDING_PROVIDER 配置实例化

互不干扰：本地 Ollama 与线上 API 走同一接口，配置隔离；向量库通过
VectorStore 的元信息一致性校验，防止不同供应商/模型向量空间混用。
"""
from abc import ABC, abstractmethod
from typing import List, Union

from . import config


class BaseEmbedding(ABC):
    """Embedding 适配器抽象基类。"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """供应商标识。"""

    @property
    @abstractmethod
    def model(self) -> str:
        """模型名称。"""

    @abstractmethod
    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """将文本转为向量列表，查询向量化与文档向量化共用。"""
        ...


class DashScopeEmbedding(BaseEmbedding):
    """通义千问 text-embedding（DashScope 原生 SDK）。"""

    BATCH_SIZE = 25  # DashScope 单次上限

    def __init__(self):
        import dashscope
        self._api_key = config.embedding_api_key()
        dashscope.api_key = self._api_key
        self._model = config.EMBEDDING_MODEL

    @property
    def provider_name(self) -> str:
        return "dashscope"

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return []
        if not self._api_key:
            raise RuntimeError("未配置 DashScope API Key")
        import dashscope
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            resp = dashscope.TextEmbedding.call(model=self._model, input=batch)
            if resp.status_code != 200:
                raise RuntimeError(
                    f"Embedding API 调用失败: code={resp.code}, message={resp.message}"
                )
            items = sorted(resp.output["embeddings"], key=lambda x: x["text_index"])
            for item in items:
                all_embeddings.append(item["embedding"])
        return all_embeddings


class OpenAICompatibleEmbedding(BaseEmbedding):
    """OpenAI 兼容适配器：覆盖 Ollama 本地模型与其他兼容端点。

    Ollama 通过 OpenAI 兼容端点（/v1/embeddings）对接本地下载的模型，
    无需 API Key，零成本本地向量化。
    """

    BATCH_SIZE = 64  # OpenAI 兼容接口通常支持较大批量

    def __init__(self, provider: str, model: str, api_key: str, api_base: str):
        from openai import OpenAI
        if not api_base:
            raise ValueError(
                f"未配置 {provider} 的 API Base URL，请在 .env 设置 EMBEDDING_API_BASE"
            )
        self._provider = provider
        self._model = model
        # Ollama 本地无需 Key，使用占位符满足 SDK 要求
        self._api_key = api_key or "ollama"
        self._client = OpenAI(api_key=self._api_key, base_url=api_base)

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        if isinstance(texts, str):
            texts = [texts]
        if not texts:
            return []
        all_embeddings: List[List[float]] = []
        for i in range(0, len(texts), self.BATCH_SIZE):
            batch = texts[i:i + self.BATCH_SIZE]
            resp = self._client.embeddings.create(model=self._model, input=batch)
            # 按 index 排序确保顺序与输入一致
            for item in sorted(resp.data, key=lambda x: x.index):
                all_embeddings.append(item.embedding)
        return all_embeddings


def create_embedding() -> BaseEmbedding:
    """工厂函数：根据 EMBEDDING_PROVIDER 配置创建 Embedding 适配器。"""
    provider = config.EMBEDDING_PROVIDER
    if provider == "dashscope":
        return DashScopeEmbedding()
    if provider in ("ollama", "openai_compatible", "deepseek", "glm"):
        return OpenAICompatibleEmbedding(
            provider=provider,
            model=config.EMBEDDING_MODEL,
            api_key=config.embedding_api_key(),
            api_base=config.embedding_api_base(),
        )
    raise ValueError(
        f"不支持的 Embedding 提供商: {provider}"
        f"（支持 dashscope/ollama/openai_compatible/deepseek/glm）"
    )
