"""下载/预取 Embedding 模型（按 config 的 backend），供首次建库前手动引导。

用法: uv run python -m rag.scripts.dl_model
说明: 默认 bge-m3（huggingface 后端 + torch），模型缓存在 .data/models，
      之后建库/检索离线可用，不再访问网络。
"""
from __future__ import annotations

from rag.config import Config
from rag.ingest.pipeline import build_embed_model


def main() -> None:
    cfg = Config.load()
    embed = build_embed_model(cfg)          # 构造即触发模型下载/加载（未缓存时）
    embed.get_text_embedding("模型就绪探测")  # 确保真正加载完成
    print(
        f"模型已就绪: {cfg.embed_model} "
        f"(backend={cfg.embed_backend}, 缓存 {cfg.embed_cache_dir})"
    )


if __name__ == "__main__":
    main()
