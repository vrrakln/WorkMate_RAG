"""MCP Server 冒烟测试：直接以 stdio JSON-RPC 调用工具（不依赖任何宿主）。

用法: uv run python -m rag.scripts.mcp_smoke

验证链路: initialize -> tools/list -> tools/call(retrieve) -> tools/call(list_knowledge_bases)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent


def _request(p, req: dict) -> dict:
    p.stdin.write(json.dumps(req, ensure_ascii=False) + "\n")
    p.stdin.flush()
    line = p.stdout.readline()
    if not line:
        raise RuntimeError("MCP server 无响应（已退出）")
    return json.loads(line)


def main() -> None:
    cmd = [sys.executable, "-m", "rag.server.rag_server"]
    env = dict(os.environ)
    env.update(
        {
            "PYTHONPATH": str(PROJECT_ROOT / "src"),
            "HF_HUB_DISABLE_XET": "1",
            "HF_HUB_DISABLE_SYMLINKS_WARNING": "1",
            "HF_HOME": str(PROJECT_ROOT / ".data" / "hf"),
        }
    )
    p = subprocess.Popen(
        cmd,
        cwd=PROJECT_ROOT,
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        encoding="utf-8",
        env=env,
    )

    try:
        # 1. initialize
        resp = _request(
            p,
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "initialize",
                "params": {
                    "protocolVersion": "2024-11-05",
                    "capabilities": {},
                    "clientInfo": {"name": "rag-smoke", "version": "0.1.0"},
                },
            },
        )
        assert "result" in resp, f"initialize 失败: {resp}"
        p.stdin.write('{"jsonrpc":"2.0","method":"notifications/initialized"}\n')
        p.stdin.flush()

        # 2. tools/list
        resp = _request(p, {"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
        tools = [t["name"] for t in resp["result"]["tools"]]
        print("tools:", tools)
        assert "retrieve" in tools and "rag_answer" in tools and "list_knowledge_bases" in tools

        # 3. tools/call retrieve（产品部身份，验证权限过滤）
        resp = _request(
            p,
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {
                    "name": "retrieve",
                    "arguments": {
                        "query": "Q1 的产品核心目标是什么",
                        "top_k": 3,
                        "department": "产品部",
                    },
                },
            },
        )
        content = resp["result"]["content"]
        text = content[0]["text"]
        print("\nretrieve(产品部) ->")
        print(text[:800])

        # 4. tools/call rag_answer（检索+生成一体，需 LLM 已启用）
        resp = _request(
            p,
            {
                "jsonrpc": "2.0",
                "id": 4,
                "method": "tools/call",
                "params": {
                    "name": "rag_answer",
                    "arguments": {"query": "差旅住宿标准是多少", "department": "财务部"},
                },
            },
        )
        text = resp["result"]["content"][0]["text"]
        print("\nrag_answer(财务部) ->")
        print(text[:500])

        # 5. tools/call list_knowledge_bases
        resp = _request(
            p,
            {"jsonrpc": "2.0", "id": 5, "method": "tools/call", "params": {"name": "list_knowledge_bases", "arguments": {}}},
        )
        print("\nlist_knowledge_bases ->")
        print(resp["result"]["content"][0]["text"][:600])

        print("\nMCP 冒烟测试通过 ✓")
    finally:
        p.stdin.close()
        p.terminate()
        try:
            p.wait(timeout=5)
        except subprocess.TimeoutExpired:
            p.kill()
        err = p.stderr.read() if p.stderr else ""
        if err.strip():
            print("\n[server stderr tail]\n" + err[-1500:])


if __name__ == "__main__":
    main()
