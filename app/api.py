"""API 路由层：定义 HTTP 接口，处理文件上传、问答、文档管理与溯源查看。

- 文档上传：接收文件 → 落盘 → 解析（含位置）→ 分块（含 locator）→ 向量化入库
- 问答接口：返回 SSE 流（先推送含 locator 的来源列表，再逐 token 推送答案，最后推送 done）
- 文档删除：同步清理向量记录、结构化内容与原始文件
- 溯源查看：返回结构化内容与单块定位信息，供前端查看器渲染并高亮
"""
import json
import uuid
from pathlib import Path

from fastapi import APIRouter, UploadFile, File, HTTPException, Request
from fastapi.responses import StreamingResponse

from .config import DOCS_DIR, SUPPORTED_EXTS
from .document_loader import load_document
from .rag_engine import RAGEngine
from . import config as _config

router = APIRouter(prefix="/api")

# 支持上传的文件大小上限（50MB）
MAX_UPLOAD_SIZE = 50 * 1024 * 1024

# RAG 引擎单例（惰性初始化，避免导入时报 API Key 缺失）
_rag_engine: RAGEngine = None


def get_rag_engine() -> RAGEngine:
    global _rag_engine
    if _rag_engine is None:
        _rag_engine = RAGEngine()
    return _rag_engine


@router.post("/upload")
async def upload_document(file: UploadFile = File(...)):
    """上传文档入库：落盘 → 解析 → 分块 → 向量化。"""
    filename = file.filename or "untitled"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTS:
        raise HTTPException(
            status_code=400,
            detail=f"不支持的文件格式: {ext}（支持 {', '.join(sorted(SUPPORTED_EXTS))}）",
        )

    doc_id = uuid.uuid4().hex[:12]
    save_name = f"{doc_id}_{filename}"
    save_path = DOCS_DIR / save_name

    # 读取并校验大小
    content = await file.read()
    if len(content) == 0:
        raise HTTPException(status_code=400, detail="文件内容为空")
    if len(content) > MAX_UPLOAD_SIZE:
        raise HTTPException(status_code=400, detail="文件过大（>50MB），建议分批上传")

    try:
        with open(save_path, "wb") as f:
            f.write(content)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"文件保存失败: {e}")

    # 解析
    try:
        parsed = load_document(str(save_path))
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文档解析失败: {e}")

    # 入库（分块 + 向量化 + 持久化）
    try:
        engine = get_rag_engine()
        chunk_count = engine.index_document(doc_id, filename, parsed)
    except Exception as e:
        save_path.unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=f"文档入库失败: {e}")

    return {
        "doc_id": doc_id,
        "doc_name": filename,
        "chunk_count": chunk_count,
        "char_count": len(parsed.full_text),
        "total_chunks": engine.vector_store.count(),
    }


@router.post("/ask")
async def ask_question(request: Request):
    """RAG 问答：返回 SSE 流。

    流事件顺序：
      sources -> (token...)* -> done
      异常时在 token 阶段插入 error 事件。
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="请求体不是合法 JSON")
    question = (body.get("question") or "").strip() if isinstance(body, dict) else ""
    if not question:
        raise HTTPException(status_code=400, detail="问题不能为空")

    engine = get_rag_engine()
    gen, sources = engine.ask(question)

    async def event_stream():
        # 先推送来源列表（含 locator）
        yield f"data: {json.dumps({'type': 'sources', 'data': sources}, ensure_ascii=False)}\n\n"
        try:
            for token in gen:
                if not token:
                    continue
                yield f"data: {json.dumps({'type': 'token', 'data': token}, ensure_ascii=False)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'data': str(e)}, ensure_ascii=False)}\n\n"
        yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return StreamingResponse(event_stream(), media_type="text/event-stream")


@router.get("/documents")
async def list_documents():
    """文档列表。"""
    engine = get_rag_engine()
    docs = engine.vector_store.list_documents()
    return {
        "documents": docs,
        "total_chunks": engine.vector_store.count(),
        "embedding": engine.vector_store.meta or {
            "embedding_provider": engine.vector_store.embedding_service.provider,
            "embedding_model": engine.vector_store.embedding_service.model,
        },
    }


@router.get("/models")
async def get_models():
    """查询当前模型配置（LLM 与 Embedding 供应商/模型）。"""
    engine = get_rag_engine()
    return {
        "llm": {
            "provider": engine.llm.provider,
            "model": engine.llm.model,
        },
        "embedding": {
            "provider": engine.vector_store.embedding_service.provider,
            "model": engine.vector_store.embedding_service.model,
            "stored": engine.vector_store.meta or None,
        },
    }


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """删除文档：清理向量记录、结构化内容与原始文件。"""
    engine = get_rag_engine()
    removed = engine.vector_store.delete_by_doc(doc_id)
    # 删除以 doc_id 开头的原始文件
    for f in DOCS_DIR.glob(f"{doc_id}_*"):
        f.unlink(missing_ok=True)
    return {"doc_id": doc_id, "removed_chunks": removed}


@router.get("/documents/{doc_id}/content")
async def get_document_content(doc_id: str):
    """获取文档结构化内容（溯源查看器渲染依据）。"""
    engine = get_rag_engine()
    content = engine.vector_store.get_document_content(doc_id)
    if content is None:
        raise HTTPException(status_code=404, detail="文档结构化内容不存在")
    return content


@router.get("/documents/{doc_id}/chunk/{chunk_id}")
async def get_chunk_locator(doc_id: str, chunk_id: str):
    """获取块定位信息（溯源高亮）。"""
    engine = get_rag_engine()
    info = engine.vector_store.get_chunk_locator(doc_id, chunk_id)
    if info is None:
        raise HTTPException(status_code=404, detail="块定位信息不存在")
    return info
