"""Q2Q 索引：把每个 chunk 的预设问题拆成独立「问题节点」，建独立向量索引。

对应设计方案 §5.4：检索命中问题节点后经 `source_chunk_id` 映射回原 chunk，
消除「问法 vs 原文措辞」的鸿沟（用户问法更像预设问题，而非正文原文）。
"""
from __future__ import annotations

import re
from typing import Sequence

from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode

_NUM_PREFIX = re.compile(r"^\s*\d+[.、)）]\s*")


def parse_questions(text: str | None) -> list[str]:
    """从 Extractor 输出中解析问题列表。

    兼容两种格式（qwen 生成）：带说明开头行的（「根据提供的信息…：」）和纯列表；
    统一规则：按行切分 → 去掉编号前缀 → 保留含问号的行。
    """
    if not text:
        return []
    questions: list[str] = []
    for line in text.splitlines():
        line = line.strip()
        if not line:
            continue
        line = _NUM_PREFIX.sub("", line).strip()
        if not line:
            continue
        if "？" in line or "?" in line:
            questions.append(line)
    return questions


def build_question_nodes(nodes: Sequence[TextNode]) -> list[TextNode]:
    """从增强后的 chunk 节点提取预设问题，生成问题节点。

    问题节点 metadata 记录 source_chunk_id 与来源文档的权限元数据
    （部门/密级沿用原 chunk，保证 Q2Q 命中后的 ACL 过滤语义一致）。
    """
    q_nodes: list[TextNode] = []
    for n in nodes:
        raw = n.metadata.get("questions_this_excerpt_can_answer")
        for q in parse_questions(raw):
            q_nodes.append(
                TextNode(
                    text=q,
                    metadata={
                        "source_chunk_id": n.node_id,
                        "doc_id": n.metadata.get("doc_id"),
                        "title": n.metadata.get("title"),
                        "department": n.metadata.get("department"),
                        "confidentiality": n.metadata.get("confidentiality"),
                        "is_question": "true",
                    },
                )
            )
    return q_nodes


def build_q2q_index(cfg, nodes: Sequence[TextNode], embed_model) -> VectorStoreIndex | None:
    """构建 Q2Q 索引并持久化到独立目录（cfg.index_q2q_persist_dir）。

    llama-index 0.14 的 index_id 在创建时不可指定（自动 UUID），多索引共享
    StorageContext 会带来加载歧义，故 Q2Q 索引独立成目录、单索引加载。
    无预设问题时返回 None（调用方跳过）。
    """
    from pathlib import Path

    from llama_index.core import StorageContext
    from llama_index.core.storage.docstore import SimpleDocumentStore
    from llama_index.core.storage.index_store import SimpleIndexStore
    from llama_index.core.vector_stores import SimpleVectorStore

    q_nodes = build_question_nodes(nodes)
    if not q_nodes:
        return None
    persist_dir = Path(cfg.index_q2q_persist_dir)
    storage_context = StorageContext.from_defaults(
        vector_store=SimpleVectorStore(),
        docstore=SimpleDocumentStore(),
        index_store=SimpleIndexStore(),
    )
    index = VectorStoreIndex(q_nodes, storage_context=storage_context, embed_model=embed_model)
    storage_context.persist(persist_dir=persist_dir)
    return index
