"""配置模块：统一加载 .env 配置，提供全局 Settings 与路径常量。

模型调用支持多供应商（互不干扰）：
- LLM: dashscope / deepseek / glm / ollama / openai_compatible
- Embedding: dashscope / ollama / openai_compatible（支持本地部署与线上 API 灵活切换）

向后兼容：当 *_API_KEY 为空且 provider=dashscope 时回退使用 DASHSCOPE_API_KEY。
"""
import os
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（kb-mvp/）
BASE_DIR = Path(__file__).resolve().parent.parent

# 加载 .env
load_dotenv(BASE_DIR / ".env")


def _get(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


# ============ 模型提供商配置 ============
# ---- LLM ----
LLM_PROVIDER: str = _get("LLM_PROVIDER", "dashscope").lower()
LLM_MODEL: str = _get("LLM_MODEL", "qwen-plus")
LLM_API_KEY: str = _get("LLM_API_KEY", "")
LLM_API_BASE: str = _get("LLM_API_BASE", "")

# ---- Embedding ----
EMBEDDING_PROVIDER: str = _get("EMBEDDING_PROVIDER", "dashscope").lower()
EMBEDDING_MODEL: str = _get("EMBEDDING_MODEL", "text-embedding-v2")
EMBEDDING_API_KEY: str = _get("EMBEDDING_API_KEY", "")
EMBEDDING_API_BASE: str = _get("EMBEDDING_API_BASE", "")

# 向后兼容：DashScope 通用 Key
DASHSCOPE_API_KEY: str = _get("DASHSCOPE_API_KEY", "")

# ---- 提供商默认 API Base URL ----
# dashscope 使用原生 SDK，无需 base_url；ollama 为本地 OpenAI 兼容端点
PROVIDER_DEFAULT_BASE = {
    "dashscope": "",
    "deepseek": "https://api.deepseek.com/v1",
    "glm": "https://open.bigmodel.cn/api/paas/v4",
    "ollama": "http://localhost:11434/v1",
    "openai_compatible": "",
}

# 提供商是否需要 API Key（本地部署无需）
PROVIDER_NEEDS_KEY = {
    "dashscope": True,
    "deepseek": True,
    "glm": True,
    "ollama": False,
    "openai_compatible": True,
}


def llm_api_key() -> str:
    """LLM 有效 API Key（含向后兼容回退）。"""
    if LLM_API_KEY:
        return LLM_API_KEY
    if LLM_PROVIDER == "dashscope":
        return DASHSCOPE_API_KEY
    return ""


def llm_api_base() -> str:
    """LLM 有效 API Base URL（显式配置优先，否则取提供商默认值）。"""
    return LLM_API_BASE or PROVIDER_DEFAULT_BASE.get(LLM_PROVIDER, "")


def embedding_api_key() -> str:
    """Embedding 有效 API Key（含向后兼容回退）。"""
    if EMBEDDING_API_KEY:
        return EMBEDDING_API_KEY
    if EMBEDDING_PROVIDER == "dashscope":
        return DASHSCOPE_API_KEY
    return ""


def embedding_api_base() -> str:
    """Embedding 有效 API Base URL。"""
    return EMBEDDING_API_BASE or PROVIDER_DEFAULT_BASE.get(EMBEDDING_PROVIDER, "")


# ============ 分块与检索配置 ============
CHUNK_SIZE: int = int(os.getenv("CHUNK_SIZE", "500"))
CHUNK_OVERLAP: int = int(os.getenv("CHUNK_OVERLAP", "50"))
TOP_K: int = int(os.getenv("TOP_K", "4"))
SERVER_PORT: int = int(os.getenv("SERVER_PORT", "8000"))

# ============ 路径配置（基于项目根目录自动推导）============
DATA_DIR = BASE_DIR / "data"
DOCS_DIR = DATA_DIR / "docs"                # 上传的原始文档
STORE_DIR = DATA_DIR / "store"              # 向量库持久化
DOC_CONTENT_DIR = STORE_DIR / "documents"   # 文档结构化内容（溯源查看器）
VECTORS_FILE = STORE_DIR / "vectors.json"   # 全量向量记录
STATIC_DIR = BASE_DIR / "static"

# 支持上传的文件扩展名
SUPPORTED_EXTS = {".pdf", ".docx", ".doc", ".txt", ".md", ".markdown"}


def ensure_dirs() -> None:
    """启动时自动创建 data/docs 与 data/store 目录。"""
    DOCS_DIR.mkdir(parents=True, exist_ok=True)
    STORE_DIR.mkdir(parents=True, exist_ok=True)
    DOC_CONTENT_DIR.mkdir(parents=True, exist_ok=True)


def _key_hint(provider: str) -> str:
    hints = {
        "dashscope": "请在 .env 设置 DASHSCOPE_API_KEY（https://bailian.console.aliyun.com/）",
        "deepseek": "请在 .env 设置 LLM_API_KEY（https://platform.deepseek.com/）",
        "glm": "请在 .env 设置 LLM_API_KEY（https://open.bigmodel.cn/）",
        "ollama": "请确保 Ollama 本地服务已启动（默认 http://localhost:11434）",
        "openai_compatible": "请在 .env 设置对应 *_API_KEY 与 *_API_BASE",
    }
    return hints.get(provider, "")


def check_api_key() -> bool:
    """启动时校验模型 API Key 配置，缺失则打印醒目警告（不阻止启动）。"""
    ok = True
    if PROVIDER_NEEDS_KEY.get(LLM_PROVIDER, True) and not llm_api_key():
        print("=" * 64)
        print(f"  [警告] LLM 提供商 [{LLM_PROVIDER}] 未配置 API Key")
        print(f"  {_key_hint(LLM_PROVIDER)}")
        print("=" * 64)
        ok = False
    if PROVIDER_NEEDS_KEY.get(EMBEDDING_PROVIDER, True) and not embedding_api_key():
        print("=" * 64)
        print(f"  [警告] Embedding 提供商 [{EMBEDDING_PROVIDER}] 未配置 API Key")
        print(f"  {_key_hint(EMBEDDING_PROVIDER)}")
        print("=" * 64)
        ok = False
    print(f"  模型配置: LLM={LLM_PROVIDER}/{LLM_MODEL}  "
          f"Embedding={EMBEDDING_PROVIDER}/{EMBEDDING_MODEL}")
    return ok
