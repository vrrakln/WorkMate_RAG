"""上下文压缩：检索后对每块文本按查询相关性压缩（设计方案 §6.3 上下文组装的增强）。

核心思路：检索得到 top_k 块后，不把整块塞给 LLM，而是先压缩——
只保留与当前查询强相关的内容，去掉无关句子/段落，降低噪声、省 token、提质量。

两种模式（config.retrieval.compression.mode）：
- embedding（默认，快）：中文按句切分 -> 结构性噪声过滤（标题/表格线/短碎片）
  -> 与查询算余弦相似度 -> 按比例保留最相关句 -> 恢复原顺序；
- llm（更准，慢）：每块让 LLM 只摘录与查询直接相关的原句（不改写）。

说明：单向量相似度对"同文档内的语义噪声句"（如查询是差旅、噪声句谈加班工资）
区分度有限——embedding 模式做粗过滤（省 40-60% token、去标题与尾部噪声），
需要高精度摘录时用 llm 模式。

安全性：过滤后为空时至少保留相似度最高的一句，避免上下文真空；
压缩结果附统计（原/压缩字数、保留比例），便于观测 token 节省。
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass

_SENT_END = re.compile(r"(?<=[。！？!?])\s*|\n+")
_HEADER = re.compile(r"^\s*(#+\s|Title\s*:|Speaker Notes\s*:|-{3,}|={3,})")
_TABLE_SEP = re.compile(r"^\s*\|[\s:|-]+\|?\s*$")  # 纯表格分隔行 | --- | --- |


def split_sentences(text: str, min_len: int = 6) -> list[str]:
    """中文分句：按句末标点（保留标点）/换行切分，过滤短碎片与结构性噪声。

    注意：markdown 表格**行**（| 一线城市 | 不超过 500 |）是内容不是噪声，
    必须保留（制度手册的答案常以表格承载）；只过滤纯分隔行与标题。
    保留句末标点，压缩重排后仍可自然拼接。
    """
    parts = [p.strip() for p in _SENT_END.split(text) if p.strip()]
    out = []
    for p in parts:
        if len(p) < min_len:
            continue
        if _HEADER.match(p) or _TABLE_SEP.match(p) or p.startswith(">"):
            continue
        out.append(p)
    return out


def _cosine(a: list[float], b: list[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(x * x for x in b))
    if na == 0 or nb == 0:
        return 0.0
    return dot / (na * nb)


@dataclass
class CompressionStats:
    original_chars: int = 0
    compressed_chars: int = 0
    total_sentences: int = 0
    kept_sentences: int = 0
    ratio: float = 1.0  # 压缩后/压缩前

    @property
    def as_dict(self) -> dict:
        return {
            "original_chars": self.original_chars,
            "compressed_chars": self.compressed_chars,
            "total_sentences": self.total_sentences,
            "kept_sentences": self.kept_sentences,
            "ratio": round(self.ratio, 3),
        }


class ContextCompressor:
    """按查询压缩单块文本。"""

    def __init__(
        self,
        mode: str = "embedding",
        threshold: float = 0.15,   # embedding 模式：相似度绝对下限（过滤尾部噪声）
        keep_ratio: float = 0.6,   # embedding 模式：超过下限的句子按相似度保留的比例
        max_sentences: int = 0,
        llm=None,
        embed_model=None,
    ):
        self.mode = mode
        self.threshold = threshold
        self.keep_ratio = keep_ratio
        self.max_sentences = max_sentences
        self._llm = llm
        self._embed_model = embed_model

    # ------------------------------------------------------------------
    def compress(self, query: str, chunk: str) -> tuple[str, CompressionStats]:
        if not chunk or not chunk.strip():
            return chunk, CompressionStats()
        if self.mode == "llm":
            if self._llm is None:
                raise RuntimeError("compression.mode=llm 需要配置 LLM（llm.enabled=true）")
            return self._compress_llm(query, chunk)
        return self._compress_embedding(query, chunk)

    # ------------------------------------------------------------------
    def _compress_embedding(self, query: str, chunk: str) -> tuple[str, CompressionStats]:
        sents = split_sentences(chunk)
        stats = CompressionStats(
            original_chars=len(chunk), total_sentences=len(sents)
        )
        if len(sents) <= 1:
            stats.compressed_chars = len(chunk)
            stats.kept_sentences = len(sents)
            return chunk, stats

        emb = self._embed_model
        if emb is None:
            raise RuntimeError("compression.mode=embedding 需要可用的 Embedding 模型")
        q_vec = emb.get_query_embedding(query)
        s_vecs = emb.get_text_embedding_batch(sents)

        scored = [(s, _cosine(q_vec, sv)) for s, sv in zip(sents, s_vecs)]
        # 1) 绝对下限过滤明显无关句
        above = [(s, sim) for s, sim in scored if sim >= self.threshold]
        if not above:
            above = [max(scored, key=lambda x: x[1])]
        # 2) 按相似度保留 top 比例
        n_keep = max(1, int(len(above) * self.keep_ratio))
        keep_ids = {id(s) for s, _ in sorted(above, key=lambda x: x[1], reverse=True)[:n_keep]}
        # 3) 恢复原顺序
        kept = [s for s, _ in scored if id(s) in keep_ids]
        if self.max_sentences > 0:
            kept = kept[: self.max_sentences]

        out = "".join(kept)
        stats.compressed_chars = len(out)
        stats.kept_sentences = len(kept)
        stats.ratio = len(out) / max(len(chunk), 1)
        return out, stats

    # ------------------------------------------------------------------
    _LLM_PROMPT = (
        "以下是企业知识片段。请只摘录与问题【{query}】**直接相关**的句子原文"
        "（可多句，必须保持原句不变、按原文顺序，不要改写、不要总结、不要补充）；"
        "无关内容一律不要输出；若片段与问题完全无关，只输出「无」。\n\n"
        "片段：\n{chunk}\n\n相关句子："
    )

    def _compress_llm(self, query: str, chunk: str) -> tuple[str, CompressionStats]:
        resp = str(self._llm.complete(self._LLM_PROMPT.format(query=query, chunk=chunk))).strip()
        stats = CompressionStats(
            original_chars=len(chunk),
            compressed_chars=len(resp),
            total_sentences=len(split_sentences(chunk)),
            kept_sentences=len(split_sentences(resp)),
        )
        stats.ratio = len(resp) / max(len(chunk), 1)
        if resp in ("", "无", "「无」", "无关"):
            first = split_sentences(chunk)
            if first:
                resp = first[0]
                stats.compressed_chars = len(resp)
                stats.kept_sentences = 1
                stats.ratio = len(resp) / max(len(chunk), 1)
        return resp, stats
