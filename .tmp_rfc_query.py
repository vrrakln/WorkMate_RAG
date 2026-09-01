"""RFC 检索测试：经典协议问题 -> 命中哪个 RFC + 相关片段。"""
from __future__ import annotations

from rag.config import Config
from rag.retrieve.service import RetrieverService

QUERIES = [
    "TCP 三次握手的过程",
    "HTTP 状态码 404 的含义",
    "DNS 默认使用什么端口",
    "IPv6 地址有多少位",
    "TLS 1.3 的握手流程",
    "UDP 报文头部有哪些字段",
    "SMTP 使用什么端口",
    "DHCP 租约是什么",
    "CIDR 是什么",
    "SSH 默认使用什么端口",
]

if __name__ == "__main__":
    cfg = Config.load("config_rfc.yaml")
    svc = RetrieverService(cfg)
    print("=" * 70)
    for q in QUERIES:
        results = svc.retrieve(q, top_k=2)
        top = results[0] if results else None
        doc = top["source"]["doc_id"] if top else "（未命中）"
        snippet = (top["text"][:100].replace("\n", " ") if top else "")
        print(f"Q: {q}")
        print(f"   -> {doc}")
        print(f"      {snippet}")
    print("=" * 70)
