"""LLM 调用模块：通过通用适配层对接多供应商，对外保持统一接口。

实际调用委托给 llm_provider.create_llm() 工厂创建的适配器，
支持 DashScope / DeepSeek / GLM / Ollama / OpenAI 兼容端点无缝切换。
"""
from typing import Generator, List

from .llm_provider import BaseLLM, create_llm


class LLMService:
    """LLM 调用服务（多供应商适配，对外接口不变）。"""

    def __init__(self):
        self._impl: BaseLLM = create_llm()

    @property
    def provider(self) -> str:
        """当前 LLM 供应商标识。"""
        return self._impl.provider_name

    @property
    def model(self) -> str:
        """当前 LLM 模型名称。"""
        return self._impl.model

    def chat_stream(self, messages: List[dict]) -> Generator[str, None, None]:
        """输入 OpenAI 格式消息列表，输出逐 token 生成内容的生成器。"""
        yield from self._impl.chat_stream(messages)
