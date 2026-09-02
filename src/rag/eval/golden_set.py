"""Golden Set：与样例库内容对齐的检索评测问题集（doc 级）。

按设计方案 §7.1 的题型覆盖组织：常规（事实）/ 问法差异 / 跨文档对比 / 多跳 / 干扰项。
每条带 type 字段，评测报告按类型汇总 hit_rate / mrr，便于定位短板与评估
后续增强（Rerank 等）的分类型收益。
"""
from __future__ import annotations

import json
from pathlib import Path

# 每项: {"query", "expected": [doc_ids], "type"}
GOLDEN_QUERIES = [
    # ---------------- 常规（事实型） ----------------
    {"query": "Q1 的产品核心目标是什么", "expected": ["product_plan_q1"], "type": "常规"},
    {"query": "新增用户的目标是多少，重点投入哪个市场", "expected": ["product_plan_q1"], "type": "常规"},
    {"query": "Q1 的商业化收入目标是多少", "expected": ["product_plan_q1"], "type": "常规"},
    {"query": "差旅住宿标准是多少", "expected": ["policy_handbook", "expense_note"], "type": "常规"},
    {"query": "报销需要什么样的发票", "expected": ["policy_handbook", "expense_note"], "type": "常规"},
    {"query": "报销时限是多久", "expected": ["expense_note"], "type": "常规"},
    {"query": "新员工入职第一天要做什么", "expected": ["onboarding_guide"], "type": "常规"},
    {"query": "常用系统有哪些", "expected": ["onboarding_guide"], "type": "常规"},
    {"query": "代码评审有什么要求", "expected": ["rnd_flow"], "type": "常规"},
    {"query": "发布流程怎么走", "expected": ["rnd_flow"], "type": "常规"},
    {"query": "云雀云服务的可用性承诺是什么", "expected": ["cloud_intro"], "type": "常规"},
    {"query": "云服务支持哪些数据库", "expected": ["cloud_intro"], "type": "常规"},
    {"query": "五一假期怎么安排", "expected": ["holiday_notice"], "type": "常规"},
    {"query": "加班如何申请", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "秘密级数据如何传输", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "数据分几级", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "员工的工作时间是怎么规定的", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "迟到有什么处罚", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "出差坐高铁有什么标准", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "报销流程分几个步骤", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "公开级数据有哪些例子", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "办公电脑有什么安全要求", "expected": ["policy_handbook"], "type": "常规"},
    {"query": "云服务器的计费方式有哪些", "expected": ["cloud_intro"], "type": "常规"},
    {"query": "对象存储支持多大的文件", "expected": ["cloud_intro"], "type": "常规"},
    {"query": "文档协作有哪些能力", "expected": ["cloud_intro"], "type": "常规"},
    {"query": "产品规划里有哪些风险", "expected": ["product_plan_q1"], "type": "常规"},
    {"query": "需求满足什么条件才能排期", "expected": ["rnd_flow"], "type": "常规"},
    {"query": "线上故障分几级，怎么响应", "expected": ["rnd_flow"], "type": "常规"},
    {"query": "新员工有哪些福利", "expected": ["onboarding_guide"], "type": "常规"},
    {"query": "入职前需要准备哪些材料", "expected": ["onboarding_guide"], "type": "常规"},
    {"query": "年假怎么申请", "expected": ["policy_handbook"], "type": "常规"},
    # ---------------- 问法差异（口语问法 vs 书面措辞） ----------------
    {"query": "请假一天需要谁审批", "expected": ["policy_handbook"], "type": "问法差异"},
    {"query": "五一放几天假", "expected": ["holiday_notice"], "type": "问法差异"},
    {"query": "加班要提前多久申请", "expected": ["policy_handbook"], "type": "问法差异"},
    {"query": "报销发票的抬头开什么", "expected": ["policy_handbook", "expense_note"], "type": "问法差异"},
    {"query": "请了年假要找谁批", "expected": ["policy_handbook"], "type": "问法差异"},
    {"query": "五一加班有没有三倍工资", "expected": ["policy_handbook"], "type": "问法差异"},
    # ---------------- 跨文档对比 ----------------
    {"query": "差旅住宿和市内打车分别有什么标准", "expected": ["policy_handbook", "expense_note"], "type": "跨文档"},
    {"query": "发票抬头和税号的要求在哪份文件里", "expected": ["policy_handbook", "expense_note"], "type": "跨文档"},
    {"query": "云服务的安全合规和公司的信息安全制度有什么关系", "expected": ["cloud_intro", "policy_handbook"], "type": "跨文档"},
    {"query": "员工福利和差旅标准分别在哪查看", "expected": ["onboarding_guide", "policy_handbook"], "type": "跨文档"},
    # ---------------- 多跳 ----------------
    {"query": "我要去北京出差一周，从申请到报销的全流程是什么", "expected": ["policy_handbook", "expense_note"], "type": "多跳"},
    {"query": "新员工第一天要领办公电脑，电脑有哪些安全要求", "expected": ["onboarding_guide", "policy_handbook"], "type": "多跳"},
    {"query": "五一值班遇到突发情况怎么联系行政部", "expected": ["holiday_notice"], "type": "多跳"},
    {"query": "代码要合入主干需要满足哪些条件", "expected": ["rnd_flow"], "type": "多跳"},
    # ---------------- 干扰项（词面重叠但答案唯一） ----------------
    {"query": "OA 系统可以提交哪些申请", "expected": ["policy_handbook"], "type": "干扰"},
    {"query": "哪些发票需要额外附上合同", "expected": ["policy_handbook"], "type": "干扰"},
    {"query": "哪些资料属于秘密级", "expected": ["policy_handbook"], "type": "干扰"},
    {"query": "公司研发新功能之前要先做什么", "expected": ["rnd_flow"], "type": "干扰"},
    {"query": "云雀科技的产品有哪些", "expected": ["cloud_intro"], "type": "干扰"},
    {"query": "加班到深夜回家，交通费怎么报", "expected": ["expense_note"], "type": "干扰"},
    # ---------------- 时效（新旧版本冲突，取新不取旧） ----------------
    {"query": "现在的住宿标准是多少", "expected": ["policy_handbook"], "type": "时效"},
    {"query": "住宿标准这两年变了吗", "expected": ["policy_handbook", "policy_handbook_2025"], "type": "时效", "require_all": True},
    {"query": "报销付款周期有什么调整", "expected": ["policy_handbook", "policy_handbook_2025"], "type": "时效", "require_all": True},
    # ---------------- HTML 文档（帮助中心，解析质量验证） ----------------
    {"query": "如何重置账号密码", "expected": ["cloud_help"], "type": "常规"},
    {"query": "云服务器配置怎么选择", "expected": ["cloud_help"], "type": "常规"},
    {"query": "SLA 未达标如何申请补偿", "expected": ["cloud_help"], "type": "常规"},
    {"query": "对象存储单文件最大能传多大", "expected": ["cloud_intro", "cloud_help"], "type": "跨文档"},
]

PERMISSION_CASES = [
    # (query, department, confidentiality, 期望 doc_id 集合)
    ("差旅住宿标准是多少", "财务部", None, {"expense_note"}),          # 内部文档仅本部门可见
    ("云雀云服务的可用性承诺是什么", "市场部", None, {"cloud_intro"}),  # 公开文档人人可见
    ("Q1 的产品核心目标是什么", "产品部", None, {"product_plan_q1"}),   # 部门匹配
    ("Q1 的产品核心目标是什么", "财务部", None, set()),                # 密级 internal 且部门不符 -> 应被过滤
    ("Q1 的产品核心目标是什么", None, "internal", {"product_plan_q1"}),  # 仅凭密级授权（内部及以上）
]


def load_golden(path: str | Path | None = None) -> list[dict]:
    p = Path(path) if path else Path(__file__).resolve().parent / "golden_set.json"
    if not p.exists():
        return []
    with open(p, encoding="utf-8") as fh:
        return json.load(fh)


def save_golden(path: str | Path | None = None) -> Path:
    p = Path(path) if path else Path(__file__).resolve().parent / "golden_set.json"
    with open(p, "w", encoding="utf-8") as fh:
        json.dump(GOLDEN_QUERIES, fh, ensure_ascii=False, indent=2)
    return p
