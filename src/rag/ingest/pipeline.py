"""建库流水线：解析 -> 分块 -> 增强(可选) -> Embedding -> 索引持久化。

对应设计方案 §4/§5：数据源解耦在外层（datasources），本模块只消费 Document。
"""
from __future__ import annotations

import json
from pathlib import Path

from llama_index.core import Settings, StorageContext, VectorStoreIndex, load_index_from_storage
from llama_index.core.extractors import (
    KeywordExtractor,
    QuestionsAnsweredExtractor,
    SummaryExtractor,
)
from llama_index.core.ingestion import IngestionPipeline
from llama_index.core.node_parser import SentenceSplitter
from llama_index.core.schema import TextNode
from llama_index.core.storage.docstore import SimpleDocumentStore
from llama_index.core.storage.index_store import SimpleIndexStore
from llama_index.core.vector_stores import SimpleVectorStore

from rag.config import Config
from rag.datasources import KnowledgeSource, create_source
from rag.ingest.q2q import build_q2q_index
from rag.ingest.readers import read_document


def build_embed_model(cfg: Config):
    """构建 Embedding 模型（默认 bge-m3）。

    - huggingface（默认）: sentence-transformers（BAAI/bge-m3，需 torch，见 pyproject
      [project.optional-dependencies] gpu-embed）。模型缓存于 cfg.embed_cache_dir
      （.data/models），device 自动选 CUDA（有 GPU 时）；
    - fastembed: 轻量 ONNX（CPU 可跑，缓存于 cfg.embed_cache_dir）——jina-zh 已弃用，
      仅保留代码路径供未来换轻量模型。
    """
    if cfg.embed_backend == "huggingface":
        from llama_index.embeddings.huggingface import HuggingFaceEmbedding

        device = "cpu"
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except ImportError:  # torch 未装（未启用 gpu-embed extra）
            pass
        return HuggingFaceEmbedding(
            model_name=cfg.embed_model,
            device=device,
            cache_folder=cfg.embed_cache_dir,  # 模型缓存在 .data/models
        )
    if cfg.embed_backend == "fastembed":
        from llama_index.embeddings.fastembed import FastEmbedEmbedding

        return FastEmbedEmbedding(model_name=cfg.embed_model, cache_dir=cfg.embed_cache_dir)
    raise ValueError(f"未知 embedding.backend: {cfg.embed_backend}")


def build_llm(cfg: Config):
    """构建 LLM（Ollama）。"""
    if cfg.llm_provider == "ollama":
        from llama_index.llms.ollama import Ollama

        return Ollama(model=cfg.llm_model, base_url=cfg.llm_base_url, request_timeout=cfg.llm_timeout_sec)
    raise ValueError(f"未知 llm.provider: {cfg.llm_provider}")


def ensure_settings_llm(cfg: Config) -> None:
    """显式注入 Settings.llm，避免 llama-index 默认解析 OpenAI（无 key 会炸）。

    - llm.enabled=true: 注入 Ollama 实例（懒连接，调用时才连）；
    - llm.enabled=false: 注入 MockLLM 占位（检索不触发 LLM；若误触发返回固定文本）。
    """
    from llama_index.core import Settings

    if cfg.llm_enabled:
        Settings.llm = build_llm(cfg)
    else:
        from llama_index.core.llms import MockLLM

        Settings.llm = MockLLM()


def load_documents(source: KnowledgeSource) -> list:
    """解析数据源全部文档，失败文档进 DLQ 记录、不静默丢弃。"""
    documents, dlq = [], []
    for doc in source.list_documents():
        try:
            documents.append(read_document(doc))
        except Exception as exc:  # noqa: BLE001 - 单个文档失败不影响整批
            dlq.append({"doc_id": doc.doc_id, "file": str(doc.file_path), "error": str(exc)})
    if dlq:
        print(f"[DLQ] {len(dlq)} 个文档解析失败，等待人工补录:")
        for item in dlq:
            print(f"  - {item['file']}: {item['error']}")
    return documents


def _has_child(n: TextNode) -> bool:
    return any("CHILD" in str(k) for k in n.relationships)


def _rel_ids(v) -> list[str]:
    if isinstance(v, list):
        return [r.node_id for r in v]
    return [v.node_id]


def _hierarchical_nodes(cfg: Config, documents: list) -> tuple[list[TextNode], list[TextNode]]:
    """层级分块（设计方案 §5.2(4)）：父块(1536) + 子块(512)。

    HierarchicalNodeParser 只调用一次，保证父/子关系一致；
    返回 (leaves, parents) —— leaves 用于检索，parents 用于作答上下文。
    """
    from llama_index.core.node_parser import HierarchicalNodeParser

    parser = HierarchicalNodeParser.from_defaults(
        chunk_sizes=[cfg.parent_chunk_size, cfg.leaf_chunk_size],
        chunk_overlap=cfg.leaf_overlap,
    )
    all_nodes = parser.get_nodes_from_documents(documents)
    parents = [n for n in all_nodes if _has_child(n)]
    leaves = [n for n in all_nodes if not _has_child(n)]
    return leaves, parents


def chunk_nodes(cfg: Config, documents: list) -> list[TextNode]:
    """分块：hierarchical 时返回叶子节点（父块另存）；否则平铺 SentenceSplitter。"""
    if cfg.hierarchical:
        leaves, _ = _hierarchical_nodes(cfg, documents)
        return leaves
    splitter = SentenceSplitter(chunk_size=cfg.leaf_chunk_size, chunk_overlap=cfg.leaf_overlap)
    return splitter.get_nodes_from_documents(documents)


def persist_parents(cfg: Config, parents: list[TextNode]) -> Path:
    """把父块落盘为 leaf_id -> 父块 映射（parents.jsonl，随正文索引目录）。"""
    path = Path(cfg.index_persist_dir) / "parents.jsonl"
    if not parents:
        if path.exists():
            path.unlink()
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for p in parents:
            child_ids: list[str] = []
            for k, v in p.relationships.items():
                if "CHILD" in str(k):
                    child_ids = _rel_ids(v)
            for cid in child_ids:
                fh.write(
                    json.dumps(
                        {
                            "leaf_id": cid,
                            "parent_id": p.node_id,
                            "parent_text": p.text,
                            "parent_metadata": p.metadata,
                        },
                        ensure_ascii=False,
                    )
                    + "\n"
                )
    return path


def load_parents(cfg: Config) -> dict[str, dict]:
    """加载 leaf_id -> {parent_id, parent_text, parent_metadata} 映射（无则空）。"""
    path = Path(cfg.index_persist_dir) / "parents.jsonl"
    if not path.exists():
        return {}
    m: dict[str, dict] = {}
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            m[obj["leaf_id"]] = {
                "parent_id": obj["parent_id"],
                "parent_text": obj["parent_text"],
                "parent_metadata": obj.get("parent_metadata", {}),
            }
    return m


def enhance_nodes(cfg: Config, nodes: list[TextNode]) -> list[TextNode]:
    """Chunk 增强（摘要/预设问题/关键词），均需 LLM（设计方案 §5.3）。"""
    enabled = cfg.enable_summary or cfg.enable_questions or cfg.enable_keywords
    if not enabled:
        return nodes
    if not cfg.llm_enabled:
        print("[enhance] 提示: LLM 未启用，跳过增强（config llm.enabled=true 后生效）")
        return nodes
    Settings.llm = build_llm(cfg)
    extractors = []
    if cfg.enable_summary:
        extractors.append(
            SummaryExtractor(
                summaries=["self"],
                prompt_template=(
                    "以下是文档片段的内容：\n{context_str}\n\n"
                    "请用 1-3 句话概括该片段讲述的关键主题与涉及的主体/实体，语言与原文一致（中文）。\n概括："
                ),
            )
        )
    if cfg.enable_questions:
        extractors.append(
            QuestionsAnsweredExtractor(
                questions=5,
                embedding_only=False,
                prompt_template=(
                    "以下是上下文：\n{context_str}\n\n"
                    "请根据这段信息生成 {num_questions} 个该片段能回答的具体问题（用中文），"
                    "问题要贴近用户检索时可能的问法。\n问题列表："
                ),
            )
        )
    if cfg.enable_keywords:
        extractors.append(
            KeywordExtractor(
                keywords=8,
                prompt_template=(
                    "{context_str}\n请提取 {keywords} 个最能代表该文档的关键词，"
                    "用中文、逗号分隔。\n关键词："
                ),
            )
        )
    pipeline = IngestionPipeline(transformations=extractors)
    return pipeline.run(nodes=nodes, in_place=False)


def persist_nodes(cfg: Config, nodes: list[TextNode]) -> Path:
    """把节点（text + metadata）落盘，供 BM25 重建与评测使用。"""
    path = Path(cfg.index_persist_dir) / "nodes.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        for n in nodes:
            fh.write(
                json.dumps(
                    {"node_id": n.node_id, "text": n.text, "metadata": n.metadata},
                    ensure_ascii=False,
                )
                + "\n"
            )
    return path


def load_nodes(cfg: Config) -> list[TextNode]:
    path = Path(cfg.index_persist_dir) / "nodes.jsonl"
    nodes = []
    if not path.exists():
        return nodes
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            obj = json.loads(line)
            nodes.append(
                # 注意: 0.14 的 TextNode 字段是 id_，传 node_id= 会被静默忽略（生成随机 ID）
                TextNode(text=obj["text"], id_=obj["node_id"], metadata=obj["metadata"])
            )
    return nodes


def build_kb(cfg: Config) -> VectorStoreIndex:
    """一键建库：数据源 -> 解析 -> 分块 -> 增强 -> 向量化 -> 持久化。

    正文索引持久化到 cfg.index_persist_dir，Q2Q 索引独立目录
    （cfg.index_q2q_persist_dir），互不干扰、单索引加载。
    """
    from rag.ingest.image_parser import configure_images
    configure_images(cfg)
    params = dict(cfg.datasource_params)
    if cfg.datasource_type == 'local_dir' and cfg.images.get('enabled'):
        params['include_images'] = cfg.images.get('include_standalone', False)
    source = create_source(cfg.datasource_type, **params)
    from rag.ingest.image_parser import release_vision
    try:
        documents = load_documents(source)
    finally:
        release_vision()
    if not documents:
        raise RuntimeError("数据源未提供任何可解析文档")

    embed = build_embed_model(cfg)
    Settings.embed_model = embed

    if cfg.hierarchical:
        leaves, parents = _hierarchical_nodes(cfg, documents)
        parents_file = persist_parents(cfg, parents)
        print(f"层级分块: {len(parents)} 个父块 + {len(leaves)} 个子块（父块映射 -> {parents_file.name}）")
    else:
        leaves = chunk_nodes(cfg, documents)
        persist_parents(cfg, [])
    nodes = enhance_nodes(cfg, leaves)
    print(f"分块完成: {len(documents)} 个文档 -> {len(nodes)} 个 chunk")

    storage_context = StorageContext.from_defaults(
        vector_store=SimpleVectorStore(),
        docstore=SimpleDocumentStore(),
        index_store=SimpleIndexStore(),
    )
    index = VectorStoreIndex(nodes, storage_context=storage_context, embed_model=embed)
    persist_dir = Path(cfg.index_persist_dir)
    index.storage_context.persist(persist_dir=persist_dir)
    nodes_file = persist_nodes(cfg, nodes)
    print(f"索引已持久化: {persist_dir}")
    print(f"节点已持久化: {nodes_file}")

    q2q = build_q2q_index(cfg, nodes, embed)
    if q2q is None:
        print("[q2q] 未检测到预设问题元数据，跳过 Q2Q 索引")
    else:
        n_q = len(q2q.index_struct.nodes_dict)
        print(f"[q2q] Q2Q 索引已构建: {n_q} 个问题节点 -> {cfg.index_q2q_persist_dir}")
    return index


def load_index(cfg: Config) -> VectorStoreIndex:
    """从磁盘加载正文索引（须先 build_kb）。"""
    persist_dir = Path(cfg.index_persist_dir)
    if not (persist_dir / "default__vector_store.json").exists():
        raise FileNotFoundError(
            f"索引不存在: {persist_dir}，请先运行: uv run python -m rag.scripts.build_kb"
        )
    embed = build_embed_model(cfg)
    Settings.embed_model = embed
    storage_context = StorageContext.from_defaults(persist_dir=persist_dir)
    return load_index_from_storage(storage_context, embed_model=embed)


def load_q2q_index(cfg: Config) -> VectorStoreIndex | None:
    """从磁盘加载 Q2Q 索引（独立目录）；不存在时返回 None（调用方优雅降级）。"""
    persist_dir = Path(cfg.index_q2q_persist_dir)
    if not (persist_dir / "default__vector_store.json").exists():
        return None
    embed = build_embed_model(cfg)
    Settings.embed_model = embed
    storage_context = StorageContext.from_defaults(persist_dir=persist_dir)
    return load_index_from_storage(storage_context, embed_model=embed)
