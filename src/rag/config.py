"""配置加载：config.yaml -> Config dataclass。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml


@dataclass
class Config:
    project_dir: Path
    raw: dict

    datasource_type: str = "local_dir"
    datasource_params: dict = field(default_factory=dict)

    embed_backend: str = "fastembed"
    embed_model: str = "BAAI/bge-m3"
    embed_cache_dir: str = ".data/models"

    llm_enabled: bool = False
    llm_provider: str = "ollama"
    llm_base_url: str = "http://localhost:11434"
    llm_model: str = "qwen2.5:7b"
    llm_timeout_sec: int = 120

    leaf_chunk_size: int = 512
    leaf_overlap: int = 64
    parent_chunk_size: int = 1536
    parent_overlap: int = 128
    hierarchical: bool = True

    enable_summary: bool = False
    enable_questions: bool = False
    enable_keywords: bool = False

    index_persist_dir: str = ".data/index"
    index_q2q_persist_dir: str = ".data/index_q2q"

    top_k: int = 5
    fusion_top_k: int = 20
    fusion_mode: str = "simple"
    similarity_cutoff: float = 0.5
    compression_enabled: bool = True
    compression_mode: str = "embedding"
    compression_threshold: float = 0.15
    compression_keep_ratio: float = 0.6
    compression_max_sentences: int = 0
    time_aware_enabled: bool = True
    time_aware_prefer_latest: bool = True
    time_aware_hard_filter: bool = False
    time_aware_decay: float = 0.5
    rerank_enabled: bool = False
    rerank_mode: str = "llm"
    rerank_candidates: int = 10
    rerank_top_n: int = 5
    rerank_choice_batch_size: int = 10
    rerank_model: str = "BAAI/bge-reranker-v2-m3"

    server_name: str = "internal-rag"

    @classmethod
    def load(cls, path: str | Path | None = None) -> "Config":
        p = Path(path) if path else Path(__file__).resolve().parent.parent.parent / "config.yaml"
        with open(p, encoding="utf-8") as fh:
            raw = yaml.safe_load(fh) or {}
        project_dir = p.parent
        cfg = cls(project_dir=project_dir, raw=raw)

        ds = raw.get("datasource", {})
        cfg.datasource_type = ds.get("type", "local_dir")
        cfg.datasource_params = dict(ds.get("params", {}))
        if cfg.datasource_type == "local_dir" and "root" in cfg.datasource_params:
            cfg.datasource_params["root"] = str(project_dir / cfg.datasource_params["root"])
        if cfg.datasource_type == "local_dir" and "manifest" in cfg.datasource_params:
            cfg.datasource_params["manifest"] = str(project_dir / cfg.datasource_params["manifest"])

        emb = raw.get("embedding", {})
        cfg.embed_backend = emb.get("backend", "fastembed")
        cfg.embed_model = emb.get("model", "BAAI/bge-m3")
        cfg.embed_cache_dir = str(project_dir / emb.get("cache_dir", ".data/models"))

        llm = raw.get("llm", {})
        cfg.llm_enabled = bool(llm.get("enabled", False))
        cfg.llm_provider = llm.get("provider", "ollama")
        cfg.llm_base_url = llm.get("base_url", "http://localhost:11434")
        cfg.llm_model = llm.get("model", "qwen2.5:7b")
        cfg.llm_timeout_sec = int(llm.get("timeout_sec", 120))

        ch = raw.get("chunking", {})
        leaf = ch.get("leaf", {})
        parent = ch.get("parent", {})
        cfg.leaf_chunk_size = int(leaf.get("chunk_size", 512))
        cfg.leaf_overlap = int(leaf.get("chunk_overlap", 64))
        cfg.parent_chunk_size = int(parent.get("chunk_size", 1536))
        cfg.parent_overlap = int(parent.get("chunk_overlap", 128))
        cfg.hierarchical = bool(ch.get("hierarchical", True))

        en = raw.get("enhance", {})
        cfg.enable_summary = bool(en.get("enable_summary", False))
        cfg.enable_questions = bool(en.get("enable_questions", False))
        cfg.enable_keywords = bool(en.get("enable_keywords", False))

        idx = raw.get("index", {})
        cfg.index_persist_dir = str(project_dir / idx.get("persist_dir", ".data/index"))
        cfg.index_q2q_persist_dir = str(project_dir / idx.get("q2q_persist_dir", ".data/index_q2q"))

        rt = raw.get("retrieval", {})
        cfg.top_k = int(rt.get("top_k", 5))
        cfg.fusion_top_k = int(rt.get("fusion_top_k", 20))
        cfg.fusion_mode = rt.get("fusion_mode", "simple")
        cfg.similarity_cutoff = float(rt.get("similarity_cutoff", 0.5))
        cp = rt.get("compression", {})
        cfg.compression_enabled = bool(cp.get("enabled", True))
        cfg.compression_mode = cp.get("mode", "embedding")
        cfg.compression_threshold = float(cp.get("threshold", 0.15))
        cfg.compression_keep_ratio = float(cp.get("keep_ratio", 0.6))
        cfg.compression_max_sentences = int(cp.get("max_sentences", 0))
        ta = rt.get("time_aware", {})
        cfg.time_aware_enabled = bool(ta.get("enabled", True))
        cfg.time_aware_prefer_latest = bool(ta.get("prefer_latest", True))
        cfg.time_aware_hard_filter = bool(ta.get("hard_filter", False))
        cfg.time_aware_decay = float(ta.get("decay", 0.5))
        rr = rt.get("rerank", {})
        cfg.rerank_enabled = bool(rr.get("enabled", False))
        cfg.rerank_mode = rr.get("mode", "llm")
        cfg.rerank_candidates = int(rr.get("candidates", 10))
        cfg.rerank_top_n = int(rr.get("top_n", 5))
        cfg.rerank_choice_batch_size = int(rr.get("choice_batch_size", 10))
        cfg.rerank_model = rr.get("model", "BAAI/bge-reranker-v2-m3")

        srv = raw.get("server", {})
        cfg.server_name = srv.get("name", "internal-rag")

        # HuggingFace Hub 本机环境适配（详见 README「网络与模型」）：
        # - 不要设置 HF_ENDPOINT 镜像：hf-mirror 会把请求 308 重定向回 huggingface.co，
        #   触发 hf_hub 1.28 的 FileMetadataError 域名校验；
        # - 禁用 xet 存储（其缓存路径在本机被拒）、HF 缓存放工作区内、符号链接降级提示关闭。
        os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
        os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
        os.environ.setdefault("HF_HOME", str(project_dir / ".data" / "hf"))
        return cfg

    def resolve(self, rel: str) -> Path:
        return self.project_dir / rel
