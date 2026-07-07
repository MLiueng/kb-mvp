"""LLM 通用适配层：抽象多供应商 LLM 调用，支持无缝切换。

设计要点：
- BaseLLM 抽象基类定义统一接口 chat_stream
- DashScopeLLM：通义千问原生 SDK（流式 + 增量输出）
- OpenAICompatibleLLM：基于 openai SDK，覆盖 DeepSeek / GLM / Ollama / 任意 OpenAI 兼容端点
- create_llm() 工厂根据 LLM_PROVIDER 配置实例化，新增供应商只需扩展工厂

互不干扰：各供应商实现独立，配置隔离，切换仅改 .env 的 LLM_PROVIDER。
"""
from abc import ABC, abstractmethod
from typing import Generator, List

from . import config


class BaseLLM(ABC):
    """LLM 适配器抽象基类。"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """供应商标识。"""

    @property
    @abstractmethod
    def model(self) -> str:
        """模型名称。"""

    @abstractmethod
    def chat_stream(self, messages: List[dict]) -> Generator[str, None, None]:
        """流式生成：输入 OpenAI 格式消息列表，逐 token 返回。"""
        ...


class DashScopeLLM(BaseLLM):
    """通义千问（DashScope 原生 SDK）。"""

    def __init__(self):
        import dashscope
        self._api_key = config.llm_api_key()
        dashscope.api_key = self._api_key
        self._model = config.LLM_MODEL

    @property
    def provider_name(self) -> str:
        return "dashscope"

    @property
    def model(self) -> str:
        return self._model

    def chat_stream(self, messages: List[dict]) -> Generator[str, None, None]:
        if not self._api_key:
            yield "[LLM 错误: 未配置 DashScope API Key]"
            return
        import dashscope
        try:
            responses = dashscope.Generation.call(
                model=self._model,
                messages=messages,
                result_format="message",
                stream=True,
                incremental_output=True,
            )
            for resp in responses:
                if resp.status_code == 200:
                    try:
                        delta = resp.output.choices[0].message.content
                    except (AttributeError, IndexError, KeyError):
                        delta = None
                    if delta:
                        yield delta
                else:
                    yield f"\n[LLM 调用失败: code={resp.code}, message={resp.message}]"
                    return
        except Exception as e:
            yield f"\n[LLM 调用异常: {e}]"


class OpenAICompatibleLLM(BaseLLM):
    """OpenAI 兼容适配器：覆盖 DeepSeek / GLM / Ollama / 任意 OpenAI 兼容端点。

    通过统一 base_url + api_key 对接不同供应商，调用方式完全一致。
    """

    def __init__(self, provider: str, model: str, api_key: str, api_base: str):
        from openai import OpenAI
        if not api_base:
            raise ValueError(
                f"未配置 {provider} 的 API Base URL，请在 .env 设置 LLM_API_BASE"
            )
        self._provider = provider
        self._model = model
        # Ollama 本地部署无需 Key，但 openai SDK 要求非空，使用占位符
        self._api_key = api_key or "ollama"
        self._client = OpenAI(api_key=self._api_key, base_url=api_base)

    @property
    def provider_name(self) -> str:
        return self._provider

    @property
    def model(self) -> str:
        return self._model

    def chat_stream(self, messages: List[dict]) -> Generator[str, None, None]:
        try:
            stream = self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                stream=True,
            )
            for chunk in stream:
                if not chunk.choices:
                    continue
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        except Exception as e:
            yield f"\n[LLM 调用异常 ({self._provider}): {e}]"


def create_llm() -> BaseLLM:
    """工厂函数：根据 LLM_PROVIDER 配置创建 LLM 适配器。"""
    provider = config.LLM_PROVIDER
    if provider == "dashscope":
        return DashScopeLLM()
    if provider in ("deepseek", "glm", "ollama", "openai_compatible"):
        return OpenAICompatibleLLM(
            provider=provider,
            model=config.LLM_MODEL,
            api_key=config.llm_api_key(),
            api_base=config.llm_api_base(),
        )
    raise ValueError(
        f"不支持的 LLM 提供商: {provider}"
        f"（支持 dashscope/deepseek/glm/ollama/openai_compatible）"
    )
