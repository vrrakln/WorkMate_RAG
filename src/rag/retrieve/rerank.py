"""Rerank 精排：融合后对候选片段做二次排序（设计方案 §6.3 Step 3）。

位置：融合 -> ACL -> 时效 -> Rerank -> top_k（权限/时效过滤必须在 Rerank 之前，
越权/过期内容不得进入精排与最终结果）。

模式（config.retrieval.rerank.mode）：
- llm（当前）：复用 qwen2.5:7b 对候选做相关性打分与排序，零新依赖；
  用 temperature=0 的专用 LLM 实例保证确定性。
- flag_embedding（预留）：bge-reranker-v2-m3 交叉编码器，需 torch，后续服务器/算力接入。

实现说明：未用 0.14 内置 LLMRerank——其内部对 chat model（Ollama 即 chat model）
走 `context_messages` 聊天模板，自定义纯文本 prompt（`{context_str}`）会错配导致
提示词残缺；自研后处理器自行拼装候选文本与解析 `Doc: N, Relevance: M`，完全可控。
"""
from __future__ import annotations

import re
from typing import Optional

from llama_index.core.postprocessor.node import BaseNodePostprocessor
from llama_index.core.schema import NodeWithScore, QueryBundle

_LINE = re.compile(r"Doc\s*:\s*(\d+)\s*,\s*Relevance\s*:\s*(\d+(?:\.\d+)?)", re.IGNORECASE)


def _zh_prompt(top_n: int) -> str:
    return (
        "下面是一组候选知识片段，每段前有编号（Document 编号，括号内是片段所属文档标题）。"
        "请根据用户问题，选出与问题最相关的片段。\n"
        "要求：\n"
        f"1. 只输出最相关的 {top_n} 个片段，按相关度从高到低，每行一个；\n"
        "2. 每行格式严格为：Doc: <编号>, Relevance: <1-10 的整数>；\n"
        "3. 不要输出无关片段，不要输出任何解释或多余文字。\n\n"
        "{context_str}\n问题：{query_str}\n回答：\n"
    )


class LLMNodeReranker(BaseNodePostprocessor):
    """LLM 候选重排：对候选片段打分并重排（temperature=0 确定性）。"""

    def __init__(self, llm, top_n: int = 5, batch_size: int = 10):
        super().__init__()
        self._llm = llm
        self._top_n = top_n
        self._batch_size = batch_size
        self._prompt = _zh_prompt(top_n)

    # ------------------------------------------------------------------
    def _postprocess_nodes(
        self, nodes: list[NodeWithScore], query_bundle: Optional[QueryBundle] = None
    ) -> list[NodeWithScore]:
        if query_bundle is None or not nodes:
            return []
        query = query_bundle.query_str
        scored: list[NodeWithScore] = []

        for start in range(0, len(nodes), self._batch_size):
            batch = nodes[start : start + self._batch_size]
            ctx = "\n\n".join(
                f"Document {i + 1}（{n.node.metadata.get('title') or '未知文档'}）:\n{n.node.text}"
                for i, n in enumerate(batch)
            )
            prompt = self._prompt.format(context_str=ctx, query_str=query)
            resp = str(self._llm.complete(prompt))
            scored.extend(self._parse(resp, batch))

        # 去重（同批内可能重复编号）并取 top_n
        best: dict[str, NodeWithScore] = {}
        for c in scored:
            key = c.node.node_id
            if key not in best or (c.score or 0) > (best[key].score or 0):
                best[key] = c
        return sorted(best.values(), key=lambda x: x.score or 0, reverse=True)[: self._top_n]

    # ------------------------------------------------------------------
    @staticmethod
    def _parse(resp: str, batch: list[NodeWithScore]) -> list[NodeWithScore]:
        """解析 'Doc: N, Relevance: M' 行（容错：扫描全文匹配，忽略噪声行）。"""
        out: list[NodeWithScore] = []
        seen: set[int] = set()
        for m in _LINE.finditer(resp):
            num = int(m.group(1))
            rel = float(m.group(2))
            if num < 1 or num > len(batch) or num in seen:
                continue
            seen.add(num)
            out.append(NodeWithScore(node=batch[num - 1].node, score=rel))
        return out


def build_reranker(cfg) -> Optional[BaseNodePostprocessor]:
    """按配置构建 Rerank 后处理器；未启用/模式不可用时返回 None。"""
    if not cfg.rerank_enabled:
        return None
    if cfg.rerank_mode == "llm":
        if not cfg.llm_enabled:
            print("[rerank] mode=llm 但 llm.enabled=false，跳过 Rerank")
            return None
        from llama_index.llms.ollama import Ollama

        llm = Ollama(
            model=cfg.llm_model,
            base_url=cfg.llm_base_url,
            request_timeout=cfg.llm_timeout_sec,
            temperature=0.0,
        )
        return LLMNodeReranker(
            llm=llm,
            top_n=cfg.rerank_top_n,
            batch_size=cfg.rerank_choice_batch_size,
        )
    if cfg.rerank_mode == "flag_embedding":
        raise NotImplementedError(
            "rerank.mode=flag_embedding 尚未接入（需 torch + bge-reranker-v2-m3，"
            "留待服务器/算力环境；届时在 build_reranker 中实现 FlagEmbeddingReranker 分支）"
        )
    print(f"[rerank] 未知模式: {cfg.rerank_mode}，跳过 Rerank")
    return None
