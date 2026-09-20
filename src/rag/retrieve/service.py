"""检索服务：向量 + Q2Q + 中文 BM25 三路召回 -> 融合 -> 权限过滤 -> 时效感知 -> top_k。

对应设计方案 §6.3 Step 2/3/4、§5.4（Q2Q 索引）与时间维度（同族多版本取新）。
融合模式可配置（config.retrieval.fusion_mode）：默认 simple（实测优于 rrf——
rrf 的多路共识偏好会淹没"单路强命中"，见开发决策记录）。Rerank 在后续阶段开启。
"""
from __future__ import annotations

from typing import Iterable

from llama_index.core import VectorStoreIndex
from llama_index.core.retrievers import BaseRetriever, QueryFusionRetriever
from llama_index.core.retrievers.fusion_retriever import FUSION_MODES
from llama_index.core.schema import NodeWithScore, QueryBundle

from rag.config import Config
from rag.ingest.pipeline import ensure_settings_llm, load_index, load_nodes, load_parents, load_q2q_index
from rag.retrieve.bm25_zh import ChineseBM25Retriever
from rag.retrieve.q2q import Q2QRetriever
from rag.retrieve.recency import apply_time_awareness

_FUSION_MODES = {
    "rrf": FUSION_MODES.RECIPROCAL_RANK,
    "reciprocal_rank": FUSION_MODES.RECIPROCAL_RANK,
    "simple": FUSION_MODES.SIMPLE,
    "relative_score": FUSION_MODES.RELATIVE_SCORE,
    "dist_based": FUSION_MODES.DIST_BASED_SCORE,
}


class _ScoreNormRetriever(BaseRetriever):
    """分数归一化包装器：把每路召回结果的分数量纲统一到 [0,1]（除以本路最大值）。

    原因：三路分数尺度差异极大——BM25 原始分可达 0-3+，而向量/Q2Q 余弦相似度
    仅 0.3-0.5；SIMPLE 融合直接求和会被大尺度路（BM25）主导，导致"含大量
    高频词"的宽泛文档（如帮助中心 FAQ 反复出现"如何"）被过度抬升。
    归一化后各路贡献可比，融合更均衡（见开发决策记录）。
    """

    def __init__(self, base: BaseRetriever):
        super().__init__()
        self._base = base

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        hits = self._base.retrieve(query_bundle)
        scores = [h.score for h in hits if h.score is not None]
        if not scores:
            return hits
        mx = max(scores) or 1.0
        for h in hits:
            if h.score is not None:
                h.score = h.score / mx
        return hits


class RetrieverService:
    """把检索封装成可独立评测、可被 MCP 工具调用的服务。"""

    def __init__(self, cfg: Config, index: VectorStoreIndex | None = None, nodes: list | None = None):
        self.cfg = cfg
        ensure_settings_llm(cfg)
        self.index = index or load_index(cfg)
        self.nodes = nodes if nodes is not None else load_nodes(cfg)
        self.parents = load_parents(cfg)  # leaf_id -> {parent_id, parent_text, ...}

        retrievers = [_ScoreNormRetriever(self.index.as_retriever(similarity_top_k=cfg.fusion_top_k))]

        # Q2Q 路：问题索引命中 -> 映射回原 chunk（索引缺失时优雅降级为两路）
        q2q_index = load_q2q_index(cfg)
        if q2q_index is not None:
            nodes_by_id = {n.node_id: n for n in self.nodes}
            q2q_retriever = Q2QRetriever(
                q2q_index.as_retriever(similarity_top_k=cfg.fusion_top_k),
                nodes_by_id,
            )
            retrievers.append(_ScoreNormRetriever(q2q_retriever))
            n_q = len(q2q_index.index_struct.nodes_dict)
            print(f"[retrieve] 已启用 Q2Q 路召回（{n_q} 个问题节点）")
        else:
            print("[retrieve] 未检测到 Q2Q 索引，降级为两路召回")

        retrievers.append(_ScoreNormRetriever(ChineseBM25Retriever(nodes=self.nodes, similarity_top_k=cfg.fusion_top_k)))

        mode = _FUSION_MODES.get(cfg.fusion_mode, FUSION_MODES.SIMPLE)
        self.hybrid = QueryFusionRetriever(
            retrievers=retrievers,
            similarity_top_k=cfg.fusion_top_k,
            mode=mode,
            num_queries=1,
        )

        # 上下文压缩器（检索后按查询相关性压缩每块）
        self._compressor = self._build_compressor(cfg)
        # Rerank 精排器（融合后、top_k 前，LLM 二次排序）
        self._reranker = self._build_reranker(cfg)

    # ------------------------------------------------------------------
    @staticmethod
    def _build_reranker(cfg: Config):
        from rag.retrieve.rerank import build_reranker

        return build_reranker(cfg)
    @staticmethod
    def _build_compressor(cfg: Config):
        if not cfg.compression_enabled:
            return None
        from rag.retrieve.compress import ContextCompressor

        if cfg.compression_mode == "llm":
            if not cfg.llm_enabled:
                print("[compress] mode=llm 但 llm.enabled=false，跳过压缩（或改为 embedding）")
                return None
            from rag.ingest.pipeline import build_llm

            return ContextCompressor(
                mode="llm",
                llm=build_llm(cfg),
                max_sentences=cfg.compression_max_sentences,
            )
        from rag.ingest.pipeline import build_embed_model

        return ContextCompressor(
            mode="embedding",
            threshold=cfg.compression_threshold,
            keep_ratio=cfg.compression_keep_ratio,
            max_sentences=cfg.compression_max_sentences,
            embed_model=build_embed_model(cfg),
        )

    # ------------------------------------------------------------------
    def retrieve(
        self,
        query: str,
        top_k: int | None = None,
        department: str | None = None,
        confidentiality: str | None = None,
    ) -> list[dict]:
        """多路召回 + 过滤，返回结构化片段列表。

        权限语义（设计方案 §6.3 Step 4）：
          - 部门匹配 或 公开文档 可见；
          - 调用方声明密级时，仅返回不高于该密级的文档（public < internal < secret）。
        """
        top_k = top_k or self.cfg.top_k
        raw = self.hybrid.retrieve(query)
        nodes = self._apply_acl(raw, department=department, confidentiality=confidentiality)
        # 时效感知：同族多版本"取新不取旧"（对比类查询放宽）
        if self.cfg.time_aware_enabled:
            nodes = apply_time_awareness(
                nodes,
                query,
                prefer_latest=self.cfg.time_aware_prefer_latest,
                hard_filter=self.cfg.time_aware_hard_filter,
                decay=self.cfg.time_aware_decay,
            )
        # Rerank 精排：对候选片段做 LLM 二次排序（权限/时效已过滤，安全）
        if self._reranker is not None and nodes:
            candidates = nodes[: self.cfg.rerank_candidates]
            reranked = self._reranker.postprocess_nodes(
                candidates, query_bundle=QueryBundle(query_str=query)
            )
            # 补足：rerank 是"改序"不是"过滤"——LLM 可能只选了几条，
            # 不足 top_k 时按融合序补足，保证召回不因 LLM 判断而下降
            if len(reranked) < top_k:
                seen = {n.node.node_id for n in reranked}
                for n in candidates:
                    if len(reranked) >= top_k:
                        break
                    if n.node.node_id not in seen:
                        reranked.append(n)
                        seen.add(n.node.node_id)
            nodes = reranked
            print(f"[rerank] {len(candidates)} 候选 -> LLM 选 {len(reranked)} 条（含融合序补足）")
        results = [self._to_dict(n, query) for n in nodes[:top_k]]

        # 上下文压缩：对每块按查询相关性压缩（仅作用于最终 top_k，节省 LLM 调用）
        if self._compressor is not None:
            for r in results:
                src = r.get("parent_text") or r["text"]
                comp, stats = self._compressor.compress(query, src)
                r["compressed_text"] = comp
                r["compression"] = stats.as_dict
        return results

    # ------------------------------------------------------------------
    _CONF_RANK = {"public": 0, "internal": 1, "secret": 2}

    def _apply_acl(
        self,
        nodes: Iterable[NodeWithScore],
        department: str | None,
        confidentiality: str | None,
    ) -> list[NodeWithScore]:
        max_rank = self._CONF_RANK.get(confidentiality, self._CONF_RANK["secret"])
        out = []
        for n in nodes:
            md = n.node.metadata
            doc_dept = md.get("department", "unknown")
            doc_conf = md.get("confidentiality", "public")
            doc_rank = self._CONF_RANK.get(doc_conf, 0)
            if doc_rank > max_rank:
                continue
            dept_ok = department is None or doc_dept == department
            public_ok = doc_conf == "public"
            if dept_ok or public_ok:
                out.append(n)
        return out

    def _to_dict(self, n: NodeWithScore, query: str) -> dict:
        md = n.node.metadata
        p = self.parents.get(n.node.node_id)
        return {
            "text": n.node.text,
            "score": round(float(n.score), 4) if n.score is not None else None,
            "source": {
                "doc_id": md.get("doc_id"),
                "title": md.get("title"),
                "department": md.get("department"),
                "confidentiality": md.get("confidentiality"),
                "effective_date": md.get("effective_date"),
                "effective_to": md.get("effective_to"),
                "family_id": md.get("family_id"),
                "file_path": md.get("file_path"),
            },
            "node_id": n.node.node_id,
            # 父子块：子块用于命中，父块用于作答（设计方案 §5.2(4)）
            "parent_id": p["parent_id"] if p else None,
            "parent_text": p["parent_text"] if p else None,
        }

    def list_documents(self) -> list[dict]:
        """枚举知识库文档范围（供 list_knowledge_bases 工具）。"""
        seen: dict[str, dict] = {}
        for n in self.nodes:
            md = n.metadata
            doc_id = md.get("doc_id") or "unknown"
            seen.setdefault(
                doc_id,
                {
                    "doc_id": doc_id,
                    "title": md.get("title"),
                    "department": md.get("department"),
                    "confidentiality": md.get("confidentiality"),
                    "effective_date": md.get("effective_date"),
                    "family_id": md.get("family_id"),
                },
            )
        return sorted(seen.values(), key=lambda d: d["doc_id"])
