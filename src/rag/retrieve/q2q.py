"""Q2Q 检索器：问题向量命中 -> 经 source_chunk_id 映射回原 chunk。

作为 QueryFusionRetriever 的一路参与 RRF 融合；命中问题节点后返回原 chunk，
去重并按最高问题得分排序（rank 由 RRF 决定，score 绝对值仅用于排序）。
"""
from __future__ import annotations

from llama_index.core.retrievers import BaseRetriever
from llama_index.core.schema import NodeWithScore, QueryBundle


class Q2QRetriever(BaseRetriever):
    def __init__(self, base_retriever: BaseRetriever, nodes_by_id: dict[str, object]):
        super().__init__()
        self._base = base_retriever
        self._nodes_by_id = nodes_by_id

    def _retrieve(self, query_bundle: QueryBundle) -> list[NodeWithScore]:
        hits = self._base.retrieve(query_bundle)
        best: dict[str, NodeWithScore] = {}
        for qn in hits:
            src_id = qn.node.metadata.get("source_chunk_id")
            if not src_id or src_id not in self._nodes_by_id:
                continue
            score = qn.score
            if src_id not in best or (score or 0) > (best[src_id].score or 0):
                best[src_id] = NodeWithScore(node=self._nodes_by_id[src_id], score=score)
        return sorted(best.values(), key=lambda x: x.score or 0, reverse=True)
