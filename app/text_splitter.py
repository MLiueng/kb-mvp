"""文本分块模块：递归字符分块器，并继承解析阶段的位置信息。

复刻 LangChain RecursiveCharacterTextSplitter 思路，零依赖自实现。
中文优先：将 。！？；， 等纳入分隔符层级。
每个 Chunk 携带 locator 定位信息（页码、段落、行号、章节），支撑溯源高亮。
"""
from dataclasses import dataclass, asdict
from typing import List, Optional

from .document_loader import Block


@dataclass
class Locator:
    """文本块在源文档中的精确位置（溯源核心）。"""
    char_start: int
    char_end: int
    page_number: Optional[int] = None
    para_start: int = 0
    para_end: int = 0
    line_start: int = 0
    line_end: int = 0
    section: Optional[str] = None


@dataclass
class Chunk:
    """分块结果。"""
    chunk_index: int
    content: str
    locator: Locator

    def to_dict(self) -> dict:
        return {
            "chunk_index": self.chunk_index,
            "content": self.content,
            "locator": asdict(self.locator),
        }


# 分隔符层级（由粗到细）：段落 -> 换行 -> 中文句号 -> 中文标点 -> 英文标点 -> 空格 -> 字符硬切
DEFAULT_SEPARATORS: List[str] = [
    "\n\n", "\n", "。", "！", "？", "；", "，",
    ".", "!", "?", ";", ",", " ", "",
]


class RecursiveTextSplitter:
    """递归字符分块器。"""

    def __init__(self, chunk_size: int = 500, chunk_overlap: int = 50,
                 separators: Optional[List[str]] = None):
        self.chunk_size = chunk_size
        self.chunk_overlap = chunk_overlap
        self.separators = separators if separators is not None else DEFAULT_SEPARATORS

    def split_text(self, full_text: str, blocks: List[Block]) -> List[Chunk]:
        """将全文递归切分为带 locator 的块。"""
        # 1. 递归切分为带偏移的小片段
        pieces: List[tuple] = []  # [(text, start, end), ...]
        self._split_recursive(full_text, self.separators, 0, pieces)
        pieces = [p for p in pieces if p[0]]
        # 2. 合并至目标长度并保留重叠
        merged = self._merge_with_overlap(full_text, pieces)
        # 3. 计算每个块的 locator
        chunks: List[Chunk] = []
        for i, (content, start, end) in enumerate(merged):
            loc = self._compute_locator(full_text, blocks, start, end)
            chunks.append(Chunk(chunk_index=i, content=content, locator=loc))
        return chunks

    # ---- 递归切分 ----
    def _split_recursive(self, text: str, separators: List[str],
                         base_offset: int, out: list) -> None:
        if len(text) <= self.chunk_size:
            if text:
                out.append((text, base_offset, base_offset + len(text)))
            return
        if not separators:
            # 字符硬切兜底
            for i in range(0, len(text), self.chunk_size):
                piece = text[i:i + self.chunk_size]
                out.append((piece, base_offset + i, base_offset + i + len(piece)))
            return
        sep = separators[0]
        remaining = separators[1:]
        if sep == "":
            for i in range(0, len(text), self.chunk_size):
                piece = text[i:i + self.chunk_size]
                out.append((piece, base_offset + i, base_offset + i + len(piece)))
            return
        parts = text.split(sep)
        offset = 0
        for part in parts:
            if len(part) > self.chunk_size:
                self._split_recursive(part, remaining, base_offset + offset, out)
            elif part:
                out.append((part, base_offset + offset, base_offset + offset + len(part)))
            offset += len(part) + len(sep)

    # ---- 合并与重叠 ----
    def _merge_with_overlap(self, full_text: str,
                            pieces: List[tuple]) -> List[tuple]:
        """将小片段合并至 chunk_size，相邻块保留 chunk_overlap 字符重叠（按片段对齐）。"""
        merged: List[tuple] = []
        if not pieces:
            return merged
        current: List[tuple] = []  # [(text, start, end), ...]
        current_len = 0

        def emit():
            if not current:
                return
            s = current[0][1]
            e = current[-1][2]
            merged.append((full_text[s:e], s, e))

        for piece, start, end in pieces:
            piece_len = end - start
            if current and current_len + piece_len > self.chunk_size:
                emit()
                # 重叠：保留尾部片段，累计长度不超过 chunk_overlap
                overlap: List[tuple] = []
                overlap_len = 0
                for p_text, p_start, p_end in reversed(current):
                    plen = p_end - p_start
                    if overlap_len + plen > self.chunk_overlap:
                        break
                    overlap.insert(0, (p_text, p_start, p_end))
                    overlap_len += plen
                current = overlap
                current_len = overlap_len
            current.append((piece, start, end))
            current_len += piece_len
        emit()
        return merged

    # ---- locator 计算 ----
    def _compute_locator(self, full_text: str, blocks: List[Block],
                         char_start: int, char_end: int) -> Locator:
        # 找出与 [char_start, char_end] 区间重叠的 blocks
        overlap = [b for b in blocks
                   if b.char_end > char_start and b.char_start < char_end]
        if not overlap:
            overlap = [blocks[0]] if blocks else []
        first = overlap[0]
        last = overlap[-1]

        # 行号：统计换行符
        line_start = full_text.count("\n", 0, char_start) + 1
        line_end = full_text.count("\n", 0, char_end) + 1

        return Locator(
            char_start=char_start,
            char_end=char_end,
            page_number=first.page_number,
            para_start=first.para_index if first.para_index is not None else 0,
            para_end=last.para_index if last.para_index is not None else 0,
            line_start=line_start,
            line_end=line_end,
            section=self._detect_section(full_text, char_start),
        )

    def _detect_section(self, full_text: str, pos: int) -> Optional[str]:
        """向前查找最近的 Markdown 标题作为所属章节。"""
        text_before = full_text[:pos]
        for line in reversed(text_before.split("\n")):
            stripped = line.strip()
            if stripped.startswith("#"):
                return stripped.lstrip("# ").strip() or None
        return None
