"""RAG 引擎：编排"检索 → 构造提示词 → 生成"全流程，核心业务中枢。

问答返回的来源列表携带完整 locator 与 chunk_id，供前端点击溯源。
"""
from typing import Generator, List, Tuple

from .config import CHUNK_SIZE, CHUNK_OVERLAP, TOP_K
from .document_loader import ParsedDocument
from .text_splitter import RecursiveTextSplitter
from .vector_store import VectorStore
from .llm import LLMService


# System Prompt：角色 + 约束，集中管理便于迭代调优
SYSTEM_PROMPT = (
    "你是企业知识库问答助手。请严格根据下方【参考资料】回答用户问题。\n"
    "要求：\n"
    "1. 优先使用资料中的信息作答；\n"
    "2. 若资料中不包含答案，请如实说明\"未在知识库中找到相关信息\"，禁止编造；\n"
    "3. 回答时在关键信息后标注来源编号，例如 [资料1]；\n"
    "4. 保持回答简洁、准确、有条理。"
)


class RAGEngine:
    """RAG 编排引擎。"""

    def __init__(self):
        self.vector_store = VectorStore()
        self.splitter = RecursiveTextSplitter(CHUNK_SIZE, CHUNK_OVERLAP)
        self.llm = LLMService()
        self.top_k = TOP_K

    def index_document(self, doc_id: str, doc_name: str,
                       parsed_doc: ParsedDocument) -> int:
        """文档入库：分块 + 向量化 + 持久化。返回入库块数。"""
        chunks = self.splitter.split_text(parsed_doc.full_text, parsed_doc.blocks)
        count = self.vector_store.add_documents(doc_id, doc_name, chunks, parsed_doc)
        return count

    def ask(self, question: str) -> Tuple[Generator[str, None, None], List[dict]]:
        """问答：返回(流式答案, 来源列表)。

        来源列表中每个对象携带 chunk_id + locator，前端据此实现点击溯源高亮。
        """
        # 1. 检索 Top-K 相关片段（含 chunk_id 与 locator）
        results = self.vector_store.search(question, self.top_k)

        # 2. 构造来源摘要
        sources: List[dict] = []
        for r in results:
            preview = r["content"][:120].replace("\n", " ")
            sources.append({
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "chunk_id": r["chunk_id"],
                "score": round(r["score"], 4),
                "preview": preview,
                "locator": r["locator"],
            })

        # 3. 构造上下文（带来源标注的参考资料）
        context_parts = []
        for i, r in enumerate(results, 1):
            context_parts.append(
                f"[资料{i}] (来源: {r['doc_name']})\n{r['content']}"
            )
        context = "\n\n".join(context_parts) if context_parts else "（无相关资料）"

        # 4. 构造提示词
        user_prompt = (
            f"参考资料：\n{context}\n\n"
            f"用户问题：{question}"
        )
        messages = [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_prompt},
        ]

        # 5. 流式生成
        def answer_gen() -> Generator[str, None, None]:
            for token in self.llm.chat_stream(messages):
                yield token

        return answer_gen(), sources
