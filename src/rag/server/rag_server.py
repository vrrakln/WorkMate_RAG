"""RAG MCP Server：以 FastMCP 暴露 retrieve / rag_answer / list_knowledge_bases。

RAG 是"被 Agent 调用的工具"（设计方案 §6）：要不要查由 Agent 决定，
怎么查、查到后怎么组装封装在工具内部。工具 docstring 决定 Agent 的调用准确率，
务必保留"何时该用"的说明。

说明：mcp 2.x 起 FastMCP 为独立包（`fastmcp`），导入路径与设计方案文档
（`mcp.server.fastmcp`，mcp 1.x）不同，API 一致。

运行（stdio 传输）: uv run python -m rag.server.rag_server
"""
from __future__ import annotations

from fastmcp import FastMCP

from rag.config import Config
from rag.ingest.pipeline import build_llm
from rag.retrieve.service import RetrieverService

_cfg: Config | None = None
_service: RetrieverService | None = None


def _get_service() -> RetrieverService:
    global _cfg, _service
    if _service is None:
        _cfg = Config.load()
        _service = RetrieverService(_cfg)
    return _service


def create_server() -> FastMCP:
    cfg = Config.load()
    mcp = FastMCP(cfg.server_name)

    @mcp.tool()
    def retrieve(
        query: str,
        top_k: int = 5,
        department: str | None = None,
        confidentiality: str | None = None,
    ) -> list[dict]:
        """检索公司内部知识库（制度/流程/项目资料/产品细节），返回带来源的最相关片段。

        何时用：当回答需要内部资料支撑时，先调用本工具拿到原始依据，再据此作答。
        department 与 confidentiality 为调用方身份，用于权限过滤（部门匹配或公开文档）。
        """
        return _get_service().retrieve(
            query=query,
            top_k=top_k,
            department=department,
            confidentiality=confidentiality,
        )

    @mcp.tool()
    def rag_answer(query: str, department: str | None = None) -> dict:
        """基于内部知识库直接生成带引用的完整答案（检索+生成一体）。

        何时用：当用户需要直接、可信、带来源的回答时调用。
        依赖 LLM（config.yaml 的 llm.enabled=true）；未启用时返回错误说明。
        检索复用 retrieve 的完整链路（三路召回 + 权限过滤 + 父块 + 上下文压缩），
        生成时以压缩后的上下文为主（去噪/省 token），子块作为命中证据。
        """
        svc = _get_service()
        if not _cfg.llm_enabled:  # type: ignore[union-attr]
            return {
                "answer": "",
                "error": "LLM 未启用（config.yaml llm.enabled=false）。可先用 retrieve 工具获取片段。",
                "sources": [],
            }
        results = svc.retrieve(query, top_k=_cfg.top_k, department=department)  # type: ignore[union-attr]
        if not results:
            return {
                "answer": "",
                "error": "知识库未命中相关内容，请向用户如实说明「知识库未找到」。",
                "sources": [],
            }
        # 上下文压缩：优先用压缩后的文本（去噪/省 token），回退父块/原文
        context = "\n\n".join(
            f"【来源 {i+1}: {r['source']['title']} | {r['source']['department']} | {r['source']['confidentiality']}】\n"
            f"{r.get('compressed_text') or r.get('parent_text') or r['text']}"
            for i, r in enumerate(results)
        )
        llm = build_llm(_cfg)  # type: ignore[arg-type]
        prompt = (
            "你是企业内部的智能助手。请严格基于下面提供的内部知识片段回答用户问题；"
            "如果片段不足以回答，请如实说明。回答用中文，末尾列出引用来源编号。\n\n"
            f"【内部知识片段】\n{context}\n\n"
            f"【用户问题】{query}\n\n"
            "【回答】"
        )
        resp = llm.complete(prompt)
        sources = [
            {
                "text": (r.get("compressed_text") or r.get("parent_text") or r["text"])[:500],
                "source": r["source"],
            }
            for r in results
        ]
        return {"answer": str(resp).strip(), "sources": sources, "error": None}

    @mcp.tool()
    def list_knowledge_bases() -> list[dict]:
        """列出可检索的知识库/文档范围（标题/部门/密级），供 Agent 了解可查内容边界。"""
        return _get_service().list_documents()

    return mcp


def main() -> None:
    mcp = create_server()
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
