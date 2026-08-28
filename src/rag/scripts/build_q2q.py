"""给已有知识库补建 Q2Q 索引（不重新跑 LLM 增强）。

适用：build_kb 是在增强功能启用前构建的（nodes.jsonl 里已有预设问题元数据），
或 Q2Q 索引缺失时。用法: uv run python -m rag.scripts.build_q2q
"""
from __future__ import annotations

import argparse

from rag.config import Config
from rag.ingest.pipeline import build_embed_model, load_nodes
from rag.ingest.q2q import build_q2q_index


def main() -> None:
    parser = argparse.ArgumentParser(description="为现有知识库补建 Q2Q 索引")
    parser.add_argument("--config", default=None)
    args = parser.parse_args()

    cfg = Config.load(args.config)
    nodes = load_nodes(cfg)
    if not nodes:
        raise SystemExit("nodes.jsonl 为空，请先 build_kb")

    q_count = sum(
        1
        for n in nodes
        if n.metadata.get("questions_this_excerpt_can_answer")
    )
    print(f"已加载 {len(nodes)} 个节点，含预设问题的节点: {q_count}")

    embed = build_embed_model(cfg)
    q2q = build_q2q_index(cfg, nodes, embed)
    if q2q is None:
        print("没有可用预设问题（节点缺 questions_this_excerpt_can_answer），跳过")
        return
    n_q = len(q2q.index_struct.nodes_dict)
    print(f"Q2Q 索引已写入: {cfg.index_q2q_persist_dir} ({n_q} 个问题节点)")


if __name__ == "__main__":
    main()
