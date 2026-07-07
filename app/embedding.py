"""向量化模块：通过通用适配层对接多供应商（含本地部署），对外保持统一接口。

实际调用委托给 embedding_provider.create_embedding() 工厂创建的适配器，
支持 DashScope 线上 API 与 Ollama 本地模型灵活切换。
查询向量化与文档向量化共用同一服务。
"""
from typing import List, Union

from .embedding_provider import BaseEmbedding, create_embedding


class EmbeddingService:
    """向量化服务（多供应商适配，对外接口不变）。"""

    def __init__(self):
        self._impl: BaseEmbedding = create_embedding()

    @property
    def provider(self) -> str:
        """当前 Embedding 供应商标识。"""
        return self._impl.provider_name

    @property
    def model(self) -> str:
        """当前 Embedding 模型名称。"""
        return self._impl.model

    def embed(self, texts: Union[str, List[str]]) -> List[List[float]]:
        """将文本转为向量列表。"""
        return self._impl.embed(texts)
