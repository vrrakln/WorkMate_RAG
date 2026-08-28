"""下载/预取 Embedding 模型（fastembed），供首次建库前手动引导。

用法: uv run python -m rag.scripts.dl_model
说明: 模型缓存到 config.yaml 的 embedding.cache_dir（.data/models），
      之后建库/检索离线可用，不再访问网络。
"""
from __future__ import annotations

from rag.config import Config


def main() -> None:
    cfg = Config.load()
    from llama_index.embeddings.fastembed import FastEmbedEmbedding

    embed = FastEmbedEmbedding(model_name=cfg.embed_model, cache_dir=cfg.embed_cache_dir)
    probe = embed._model.embed(["模型下载验证"]) if hasattr(embed, "_model") else None
    if probe is None:
        # FastEmbedEmbedding 内部是懒加载，先触发一次 embed 确保模型就绪
        import fastembed

        from fastembed import TextEmbedding

        TextEmbedding(model_name=cfg.embed_model, cache_dir=cfg.embed_cache_dir)
        print(f"模型已就绪: {cfg.embed_model} -> {cfg.embed_cache_dir}")
        return
    print(f"模型已就绪: {cfg.embed_model} -> {cfg.embed_cache_dir}")


if __name__ == "__main__":
    main()
