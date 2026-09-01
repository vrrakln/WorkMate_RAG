"""评测：doc 级 hit_rate / mrr（设计方案 §7.3 落地）。

用业务关心的"命中文档"粒度评测（RetrieverEvaluator 是 node 级，
后续需要 node 级指标时可在其基础上加一层映射）。
"""
from __future__ import annotations

from rag.config import Config
from rag.retrieve.service import RetrieverService

_CONF_RANK = {"public": 0, "internal": 1, "secret": 2}


def evaluate(cfg: Config, top_k: int = 5) -> dict:
    from rag.eval.golden_set import GOLDEN_QUERIES, PERMISSION_CASES

    service = RetrieverService(cfg)

    def doc_ids(result: list[dict]) -> set[str]:
        return {r["source"]["doc_id"] for r in result if r["source"].get("doc_id")}

    def visible_ids(department: str | None, confidentiality: str | None) -> set[str]:
        """按服务 ACL 语义推导该调用方可看到的全部文档（单一事实来源）。"""
        max_rank = _CONF_RANK.get(confidentiality, _CONF_RANK["secret"])
        visible: set[str] = set()
        for d in service.list_documents():
            if _CONF_RANK.get(d["confidentiality"], 0) > max_rank:
                continue
            dept_ok = department is None or d["department"] == department
            public_ok = d["confidentiality"] == "public"
            if dept_ok or public_ok:
                visible.add(d["doc_id"])
        return visible

    # ---- 1. 常规检索质量（含分类型统计） ----
    hits, reciprocal = [], []
    per_query = []
    by_type: dict[str, dict] = {}
    for item in GOLDEN_QUERIES:
        query, expected, qtype = item["query"], item["expected"], item.get("type", "常规")
        require_all = bool(item.get("require_all", False))  # 对比类：期望文档全部出现才算命中
        result = service.retrieve(query, top_k=top_k)
        got = doc_ids(result)
        hit = (got >= set(expected)) if require_all else bool(got & set(expected))
        hits.append(hit)
        # mrr：首个命中文档的 1/排名
        rank = None
        for i, r in enumerate(result, start=1):
            if r["source"].get("doc_id") in expected:
                rank = i
                break
        reciprocal.append(1.0 / rank if rank else 0.0)
        per_query.append(
            {
                "query": query,
                "type": qtype,
                "hit": hit,
                "mrr": reciprocal[-1],
                "got": sorted(got),
                "expected": expected,
            }
        )
        bucket = by_type.setdefault(qtype, {"n": 0, "hits": 0, "rr_sum": 0.0})
        bucket["n"] += 1
        bucket["hits"] += int(hit)
        bucket["rr_sum"] += reciprocal[-1]

    by_type_summary = {
        t: {
            "n": b["n"],
            "hit_rate": round(b["hits"] / b["n"], 4),
            "mrr": round(b["rr_sum"] / b["n"], 4),
        }
        for t, b in sorted(by_type.items())
    }

    # ---- 2. 权限过滤用例 ----
    acl = []
    for query, department, confidentiality, expected in PERMISSION_CASES:
        result = service.retrieve(query, top_k=top_k, department=department, confidentiality=confidentiality)
        got = doc_ids(result)
        visible = visible_ids(department, confidentiality)
        leaked = bool(got - visible)                    # 出现不可见文档 = 越权
        missed_expected = sorted(set(expected) - got)   # 关键文档未召回（top_k 截断可容忍，弱断言）
        acl.append(
            {
                "query": query,
                "department": department,
                "confidentiality": confidentiality,
                "got": sorted(got),
                "visible": sorted(visible),
                "missed_expected": missed_expected,
                "leaked": leaked,
            }
        )

    summary = {
        "top_k": top_k,
        "queries": len(GOLDEN_QUERIES),
        "hit_rate": round(sum(hits) / len(hits), 4) if hits else 0.0,
        "mrr": round(sum(reciprocal) / len(reciprocal), 4) if reciprocal else 0.0,
        "by_type": by_type_summary,
        "acl_cases": len(acl),
        "acl_leaks": sum(1 for a in acl if a["leaked"]),
        "per_query": per_query,
        "acl": acl,
    }
    return summary


def print_report(summary: dict) -> None:
    print("=" * 60)
    print(f"检索评测报告（top_k={summary['top_k']}）")
    print(f"  hit_rate = {summary['hit_rate']:.2%}   ({summary['queries']} 条)")
    print(f"  mrr      = {summary['mrr']:.4f}")
    print("-" * 60)
    for t, b in summary.get("by_type", {}).items():
        print(f"  [{t}] n={b['n']}  hit_rate={b['hit_rate']:.2%}  mrr={b['mrr']:.4f}")
    print("-" * 60)
    for q in summary["per_query"]:
        mark = "✓" if q["hit"] else "✗"
        print(f"  [{mark}] ({q['type']}) {q['query']}")
        print(f"       got={q['got']}  expected={q['expected']}")
    print("-" * 60)
    print(f"权限过滤用例: {summary['acl_cases']} 条，越权泄漏: {summary['acl_leaks']}")
    for a in summary["acl"]:
        flag = "泄漏!" if a["leaked"] else "OK"
        miss = f"（漏召回: {a['missed_expected']}）" if a["missed_expected"] else ""
        print(f"  [{flag}] dept={a['department']} conf={a['confidentiality']} query={a['query']}{miss}")
        print(f"       got={a['got']}  visible={a['visible']}")
    print("=" * 60)
