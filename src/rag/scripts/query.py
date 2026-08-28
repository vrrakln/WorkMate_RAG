"""检索自测: uv run python -m rag.scripts.query --query "..." --top-k 3"""
from __future__ import annotations

import argparse
import json

from rag.config import Config
from rag.retrieve.service import RetrieverService


def main() -> None:
    parser = argparse.ArgumentParser(description="检索自测")
    parser.add_argument("--query", required=True)
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--department", default=None, help="调用方部门（权限过滤）")
    parser.add_argument("--confidentiality", default=None, help="调用方可见密级")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = Config.load(args.config)
    service = RetrieverService(cfg)
    result = service.retrieve(
        args.query,
        top_k=args.top_k,
        department=args.department,
        confidentiality=args.confidentiality,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
