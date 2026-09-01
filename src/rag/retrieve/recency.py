"""时效感知：把时间作为关键属性，同族多版本知识"取新不取旧"。

对应设计方案时间维度的落地：知识会随版本演进（如制度手册 2025 版 → 2026 版），
语义检索会同时命中新旧版本——本模块在检索后（ACL 之后、top_k 之前）处理：

- **非对比查询**（默认）：同 family_id 组内只保留最新版本（effective_date 最大），
  旧版本丢弃——"取新不取旧"；
- **对比查询**（问法含"变化/区别/以前/相比/调整"等）：保留全部版本，
  旧版本分数按 decay 衰减（仍可被召回，支持"这两年变了吗"类问题）；
- **硬过滤**（可选）：effective_to 早于今天的版本直接丢弃（非对比查询）。

注意：llama-index 0.14 内置的 FixedRecencyPostprocessor 是"全局按 date 截断 top_k"，
不做 family 分组去重，语义不匹配，故自研本模块（思路参考其 date_key 约定）。
"""
from __future__ import annotations

from datetime import date

from llama_index.core.schema import NodeWithScore

# 问法中含这些词 → 判定为"对比/历史"类查询，放宽取新
_COMPARE_MARKERS = [
    "变化", "区别", "不同", "以前", "之前", "相比", "差异", "历史",
    "旧版", "新版", "对比", "改动", "更新", "调整",
    "变了吗", "变了", "变", "这两年", "这几年", "几年间", "改版", "新规", "旧规",
]

_TODAY = date.today().isoformat()  # 2026-08-26


def is_comparison_query(query: str) -> bool:
    return any(m in query for m in _COMPARE_MARKERS)


def apply_time_awareness(
    nodes: list[NodeWithScore],
    query: str,
    *,
    prefer_latest: bool = True,
    hard_filter: bool = False,
    decay: float = 0.5,
) -> list[NodeWithScore]:
    """按时效属性处理后返回（保持分数降序）。

    - prefer_latest: 非对比查询时同族只保留最新版本；
    - hard_filter: 非对比查询时丢弃已过期（effective_to < 今天）的节点；
    - decay: 对比查询时旧版本分数衰减系数（0-1）。
    """
    if not nodes:
        return nodes
    comparison = is_comparison_query(query)

    groups: dict[str, list[NodeWithScore]] = {}
    for n in nodes:
        md = n.node.metadata
        eff_to = md.get("effective_to") or ""
        if hard_filter and not comparison and eff_to and eff_to < _TODAY:
            continue  # 过期硬排除
        family = md.get("family_id") or md.get("doc_id") or "?"
        groups.setdefault(family, []).append(n)

    result: list[NodeWithScore] = []
    for family, items in groups.items():
        has_date = any(it.node.metadata.get("effective_date") for it in items)
        if len(items) <= 1 or not has_date:
            result.extend(items)
            continue

        # 组内按 effective_date 降序（最新在前）
        items_sorted = sorted(
            items,
            key=lambda x: x.node.metadata.get("effective_date") or "",
            reverse=True,
        )
        if comparison:
            # 对比/历史类：保留全部版本，旧版本衰减
            for i, it in enumerate(items_sorted):
                if i > 0 and it.score is not None:
                    it.score = float(it.score) * decay
            result.extend(items_sorted)
        elif prefer_latest:
            # 取新不取旧：只保留最新版本
            result.append(items_sorted[0])
        else:
            for i, it in enumerate(items_sorted):
                if i > 0 and it.score is not None:
                    it.score = float(it.score) * decay
            result.extend(items_sorted)

    result.sort(key=lambda x: x.score or 0, reverse=True)
    return result
