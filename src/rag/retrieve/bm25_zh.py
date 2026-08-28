"""中文 BM25 检索器：CJK 二元组 + 英文单词分词（零依赖）。

官方 llama-index-retrievers-bm25 的 bm25s.tokenize 按空白/标点分词，对中文
（无空格）几乎无效。本检索器使用 CJK 字符的相邻二元组（bigram）+ 英文数字
单词作为 token，去掉了单字噪音（是/多/少/的），中文关键词/专名召回效果稳定，
且不引入 jieba 等额外依赖（jieba 在本机无 wheel 且源码构建失败）。
"""
from __future__ import annotations

import bm25s
from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle


def _bigrams(chars: list[str]) -> list[str]:
    return [chars[i] + chars[i + 1] for i in range(len(chars) - 1)]


def zh_tokens(text: str) -> list[str]:
    """分词：连续 CJK 字符 → 相邻二元组；连续字母/数字 → 单词（小写）。"""
    tokens: list[str] = []
    cjk_buf: list[str] = []
    word_buf: list[str] = []
    for ch in text:
        if "\u4e00" <= ch <= "\u9fff":
            if word_buf:
                tokens.append("".join(word_buf).lower())
                word_buf = []
            cjk_buf.append(ch)
        elif ch.isalnum():
            if cjk_buf:
                tokens.extend(_bigrams(cjk_buf))
                cjk_buf = []
            word_buf.append(ch)
        else:
            if cjk_buf:
                tokens.extend(_bigrams(cjk_buf))
                cjk_buf = []
            if word_buf:
                tokens.append("".join(word_buf).lower())
                word_buf = []
    if cjk_buf:
        tokens.extend(_bigrams(cjk_buf))
    if word_buf:
        tokens.append("".join(word_buf).lower())
    return tokens


class ChineseBM25Retriever(BaseRetriever):
    """基于 bm25s 的中文 BM25 检索器。"""

    def __init__(self, nodes, similarity_top_k: int = 20):
        super().__init__()
        self.nodes = list(nodes)
        self.similarity_top_k = min(similarity_top_k, len(self.nodes)) if self.nodes else 0
        corpus = [zh_tokens(n.text) for n in self.nodes]
        self._bm25 = bm25s.BM25()
        self._bm25.index(corpus, show_progress=False)

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        if not self.nodes:
            return []
        query_tokens = [zh_tokens(query_bundle.query_str)]
        # bm25s 0.3.x retrieve 返回 (indices, scores)
        indexes, scores = self._bm25.retrieve(
            query_tokens, k=self.similarity_top_k, show_progress=False
        )
        out: list[NodeWithScore] = []
        for idx, score in zip(indexes[0], scores[0]):
            node = self.nodes[int(idx)]
            out.append(NodeWithScore(node=node, score=float(score)))
        return out
