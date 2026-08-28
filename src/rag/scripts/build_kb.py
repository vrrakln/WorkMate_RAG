"""一键建库: uv run python -m rag.scripts.build_kb"""
from __future__ import annotations

import argparse

from rag.config import Config
from rag.ingest.pipeline import build_kb


def main() -> None:
    parser = argparse.ArgumentParser(description="建库：解析→分块→Embedding→索引持久化")
    parser.add_argument("--config", default=None, help="config.yaml 路径（默认项目根）")
    args = parser.parse_args()

    cfg = Config.load(args.config)
    index = build_kb(cfg)
    print(f"完成。索引包含 {len(index.ref_doc_info)} 个文档。")


if __name__ == "__main__":
    main()
