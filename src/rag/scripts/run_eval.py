"""评测: uv run python -m rag.scripts.run_eval"""
from __future__ import annotations

import argparse

from rag.config import Config
from rag.eval.evaluate import evaluate, print_report


def main() -> None:
    parser = argparse.ArgumentParser(description="Golden Set 评测（hit_rate / mrr / 权限用例）")
    parser.add_argument("--top-k", type=int, default=5)
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = Config.load(args.config)
    summary = evaluate(cfg, top_k=args.top_k)
    print_report(summary)


if __name__ == "__main__":
    main()
