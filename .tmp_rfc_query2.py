"""RFC 检索测试 v2：显示 top-3 命中文档。"""
from __future__ import annotations

from rag.config import Config
from rag.retrieve.service import RetrieverService

QUERIES = [
    "TCP 三次握手的过程",
    "HTTP 状态码 404 的含义",
    "DNS 默认使用什么端口",
    "IPv6 地址有多少位",
    "UDP 报文头部有哪些字段",
    "DHCP 租约是什么",
]

# 期望的正典 RFC
EXPECT = {
    "TCP 三次握手的过程": "rfc0793",
    "HTTP 状态码 404 的含义": "rfc9110",
    "DNS 默认使用什么端口": "rfc1035",
    "IPv6 地址有多少位": "rfc4291",
    "UDP 报文头部有哪些字段": "rfc0768",
    "DHCP 租约是什么": "rfc2131",
}

if __name__ == "__main__":
    cfg = Config.load("config_rfc.yaml")
    svc = RetrieverService(cfg)
    print("=" * 74)
    for q in QUERIES:
        results = svc.retrieve(q, top_k=3)
        docs = [r["source"]["doc_id"] for r in results]
        exp = EXPECT[q]
        mark = "✓" if exp in docs else "✗"
        print(f"[{mark}] {q}")
        print(f"   期望 {exp} | top3: {docs}")
        for r in results[:3]:
            print(f"     - {r['source']['doc_id']}: {r['text'][:70].replace(chr(10),' ')}")
    print("=" * 74)
