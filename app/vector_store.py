"""向量存储模块：JSON 文件持久化 + numpy 矩阵化检索。

存储方案：
- vectors.json：全量向量记录（含 locator）
- documents/{doc_id}.json：文档结构化内容（ParsedDocument），溯源查看器渲染依据

检索：全量向量构建 numpy 矩阵，L2 归一化后矩阵乘法计算余弦相似度，万级瞬时完成。
"""
import json
from dataclasses import asdict
from pathlib import Path
from typing import List, Optional

import numpy as np

from .config import VECTORS_FILE, DOC_CONTENT_DIR
from .document_loader import ParsedDocument
from .embedding import EmbeddingService


class VectorStore:
    """向量本地持久化存储与检索。"""

    def __init__(self):
        self.vectors_file: Path = VECTORS_FILE
        self.doc_content_dir: Path = DOC_CONTENT_DIR
        self.records: List[dict] = []
        # 向量库元信息：记录入库时使用的 embedding 供应商/模型/维度，供一致性校验
        self.meta: dict = {}
        self.embedding_service = EmbeddingService()
        self._load()

    # ---- 持久化 ----
    def _load(self) -> None:
        if self.vectors_file.exists():
            try:
                with open(self.vectors_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                # 兼容旧格式（纯列表）与新格式（{meta, records}）
                if isinstance(data, list):
                    self.records = data
                    self.meta = {}
                elif isinstance(data, dict):
                    self.records = data.get("records", [])
                    self.meta = data.get("meta", {}) or {}
            except (json.JSONDecodeError, OSError):
                self.records = []
                self.meta = {}

    def _save(self) -> None:
        self.vectors_file.parent.mkdir(parents=True, exist_ok=True)
        payload = {"meta": self.meta, "records": self.records}
        with open(self.vectors_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    # ---- Embedding 一致性校验 ----
    def _check_embedding_consistency(self) -> None:
        """校验当前 Embedding 配置与已入库向量元信息是否一致。

        切换 Embedding 供应商/模型后，向量空间不再对齐，混用会导致检索结果失真。
        此处主动拦截，提示用户清空向量库后用当前配置重新入库。
        """
        if not self.meta:
            return
        cur_provider = self.embedding_service.provider
        cur_model = self.embedding_service.model
        stored_provider = self.meta.get("embedding_provider")
        stored_model = self.meta.get("embedding_model")
        if cur_provider != stored_provider or cur_model != stored_model:
            raise RuntimeError(
                f"Embedding 配置与已入库向量不一致：当前={cur_provider}/{cur_model}，"
                f"已入库={stored_provider}/{stored_model}。"
                f"请删除 data/store/vectors.json 后用当前配置重新入库，"
                f"或在 .env 中切回原配置。"
            )

    # ---- 入库 ----
    def add_documents(self, doc_id: str, doc_name: str,
                      chunks: list, parsed_doc: ParsedDocument) -> int:
        """向量化并入库（含 locator + 持久化结构化内容）。"""
        texts = [c.content for c in chunks]
        embeddings = self.embedding_service.embed(texts)

        # 库为空时（首次入库或清空后重新入库）记录 embedding 元信息
        if not self.records and embeddings:
            self.meta = {
                "embedding_provider": self.embedding_service.provider,
                "embedding_model": self.embedding_service.model,
                "dim": len(embeddings[0]),
            }

        for chunk, emb in zip(chunks, embeddings):
            locator = chunk.locator
            locator_dict = asdict(locator) if not isinstance(locator, dict) else locator
            record = {
                "doc_id": doc_id,
                "doc_name": doc_name,
                "chunk_id": f"{doc_id}_{chunk.chunk_index}",
                "chunk_index": chunk.chunk_index,
                "content": chunk.content,
                "locator": locator_dict,
                "embedding": emb,
            }
            self.records.append(record)

        # 持久化文档结构化内容（溯源查看器）
        self._save_document_content(doc_id, doc_name, parsed_doc)
        self._save()
        return len(chunks)

    def _save_document_content(self, doc_id: str, doc_name: str,
                               parsed_doc: ParsedDocument) -> None:
        self.doc_content_dir.mkdir(parents=True, exist_ok=True)
        payload = {
            "doc_id": doc_id,
            "doc_name": doc_name,
            "file_type": parsed_doc.file_type,
            "total_chars": len(parsed_doc.full_text),
            "total_pages": parsed_doc.total_pages,
            "blocks": [b.__dict__ if hasattr(b, "__dict__") else b
                       for b in parsed_doc.blocks],
        }
        content_file = self.doc_content_dir / f"{doc_id}.json"
        with open(content_file, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False)

    # ---- 检索 ----
    def search(self, query: str, top_k: int) -> List[dict]:
        if not self.records:
            return []
        # 校验当前 Embedding 与已入库向量一致，避免不同供应商/模型向量空间混用
        self._check_embedding_consistency()
        query_emb = self.embedding_service.embed(query)[0]
        matrix = np.array([r["embedding"] for r in self.records], dtype=np.float32)
        # L2 归一化
        norms = np.linalg.norm(matrix, axis=1, keepdims=True)
        norms[norms == 0] = 1.0
        matrix_norm = matrix / norms
        q = np.array(query_emb, dtype=np.float32)
        q_norm = q / (np.linalg.norm(q) or 1.0)
        # 余弦相似度 = 归一化后的内积
        scores = matrix_norm @ q_norm
        top_k = min(top_k, len(self.records))
        top_indices = np.argsort(scores)[::-1][:top_k]
        results = []
        for idx in top_indices:
            r = self.records[idx]
            results.append({
                "content": r["content"],
                "doc_id": r["doc_id"],
                "doc_name": r["doc_name"],
                "chunk_id": r["chunk_id"],
                "chunk_index": r["chunk_index"],
                "score": float(scores[idx]),
                "locator": r["locator"],
            })
        return results

    # ---- 文档管理 ----
    def delete_by_doc(self, doc_id: str) -> int:
        before = len(self.records)
        self.records = [r for r in self.records if r["doc_id"] != doc_id]
        removed = before - len(self.records)
        # 库清空后重置元信息，允许切换 Embedding 供应商后重新入库
        if not self.records:
            self.meta = {}
        self._save()
        # 清理结构化内容
        content_file = self.doc_content_dir / f"{doc_id}.json"
        if content_file.exists():
            content_file.unlink(missing_ok=True)
        return removed

    def list_documents(self) -> List[dict]:
        docs: dict = {}
        for r in self.records:
            d = docs.setdefault(
                r["doc_id"],
                {"doc_id": r["doc_id"], "doc_name": r["doc_name"], "chunk_count": 0},
            )
            d["chunk_count"] += 1
        return list(docs.values())

    def count(self) -> int:
        return len(self.records)

    # ---- 溯源查询 ----
    def get_document_content(self, doc_id: str) -> Optional[dict]:
        content_file = self.doc_content_dir / f"{doc_id}.json"
        if not content_file.exists():
            return None
        with open(content_file, "r", encoding="utf-8") as f:
            return json.load(f)

    def get_chunk_locator(self, doc_id: str, chunk_id: str) -> Optional[dict]:
        for r in self.records:
            if r["doc_id"] == doc_id and r["chunk_id"] == chunk_id:
                return {
                    "chunk_id": r["chunk_id"],
                    "doc_id": r["doc_id"],
                    "chunk_index": r["chunk_index"],
                    "content": r["content"],
                    "locator": r["locator"],
                }
        return None
