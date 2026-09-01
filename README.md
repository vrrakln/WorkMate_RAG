# internal-rag — 公司内部 RAG 系统（本地离线开发版）

> 🚚 **要把代码搬到公司电脑跑（公司文档不出内网）？先看** [`部署到公司电脑.md`](部署到公司电脑.md)
> （数据边界、离线携带模型、LLM 可选、manifest 权限元数据）。

> 按 `RAG系统设计方案.md` 落地。RAG 是**工具不是 Agent**：以 MCP Server 形式对外暴露
> `retrieve` / `rag_answer` / `list_knowledge_bases`，后续注册进 AionCore `aionui-mcp`，
> 由 Hermes 等 Agent 在对话中自主调用。
>
> 当前为**本地离线开发闭环**：自编"虚拟公司"脱敏样例库 → LlamaIndex 建库/检索 →
> FastMCP 暴露工具。公司真实知识库通过**数据源适配器**（`datasources/`）接入，
> 拿到真实数据后只需替换数据源，流水线代码零改动。
>
> 📐 **整体架构（离线建索引 / 在线检索增强生成，含每步技术选型与决策差异）：**
> 见 [`架构说明.md`](架构说明.md)

## 目录结构

```
rag/
├── config.yaml                 # 全部配置（数据源/模型/分块/检索）
├── pyproject.toml              # uv 项目定义（含 [tool.uv] cache-dir 适配）
├── .env                        # uv run 环境变量（HF Hub 适配）
├── run.ps1                     # 便捷启动（设置缓存/镜像变量后转发 uv run）
├── 开发决策记录.md               # 两个阻塞问题的解法 + 环境踩坑记录
├── src/rag/
│   ├── __init__.py             # UTF-8 输出 + Windows 环境补丁加载
│   ├── _winfix.py              # tempfile.mkdtemp 0700 目录补丁（本机必需）
│   ├── config.py               # 配置加载（含 HF Hub 环境适配）
│   ├── datasources/            # ★ 数据源适配层（唯一随环境替换的部分）
│   │   ├── base.py             #   KnowledgeSource 抽象 + KbDocument
│   │   ├── local_dir.py        #   本地目录型（样例库）
│   │   └── company_stub.py     #   公司数据源占位（未实现）
│   ├── ingest/                 # 建库：解析→父子块→增强→Embedding→索引
│   │   └── q2q.py              #   Q2Q 索引（预设问题→问题节点→独立向量索引）
│   ├── retrieve/               # 检索：向量+Q2Q+中文BM25 三路融合→权限过滤→父块挂接→top_k
│   │   ├── bm25_zh.py          #   自研中文 BM25（CJK 二元组，官方对中文无效）
│   │   └── q2q.py              #   Q2Q 检索器（问题命中→source_chunk_id 映射回原 chunk）
│   ├── server/                 # FastMCP：retrieve/rag_answer/list_knowledge_bases
│   ├── eval/                   # Golden Set + hit_rate/mrr/权限用例评测
│   └── scripts/                # 一键脚本（见下方「命令速查」）
├── sample_data/                # （生成，gitignore）虚拟公司样例库
├── .data/                      # （生成，gitignore）索引 + 模型缓存
│   ├── index/                  #   正文索引 + nodes.jsonl
│   └── index_q2q/              #   Q2Q（预设问题）索引
├── .uv-cache/                  # （生成，gitignore）uv 项目内缓存
└── .venv/                      # （生成，gitignore）Python 虚拟环境
```

### 命令速查

| 命令 | 作用 |
| --- | --- |
| `uv run python -m rag.scripts.generate_sample` | 生成"虚拟公司"样例库（可重复，覆盖式重建） |
| `uv run python -m rag.scripts.build_kb` | 建库（解析→分块→增强→向量化→正文索引 + Q2Q 索引） |
| `uv run python -m rag.scripts.build_q2q` | 为已有知识库补建 Q2Q 索引（不重跑 LLM 增强） |
| `uv run python -m rag.scripts.query --query "..." [--top-k N] [--department X]` | 检索自测 |
| `uv run python -m rag.scripts.run_eval` | Golden Set 评测（hit_rate / mrr / 权限用例） |
| `uv run python -m rag.scripts.mcp_smoke` | MCP Server stdio 冒烟测试（initialize→tools→call） |
| `uv run python -m rag.scripts.dl_model` | 预取嵌入模型（首次建库前的模型引导） |
| `uv run python -m rag.server.rag_server` | 启动 MCP Server（stdio 传输） |
| `uv sync` | 安装/同步依赖（首次或改 pyproject 后） |

## 快速开始

```powershell
# 进入项目目录（示例；换机器/克隆位置以实际为准）
cd <你克隆或存放 rag 的目录>

# 0. 首次：创建 venv 并安装依赖（pypi 可达即可；若网络受限见"部署到公司电脑.md"）
uv sync
# 1. 生成"虚拟公司"脱敏样例库（多格式 + manifest.csv 元数据）
uv run python -m rag.scripts.generate_sample

# 2. 建库（解析→分块→向量化→索引持久化到 .data/index）
uv run python -m rag.scripts.build_kb

# 3. 检索自测（指定部门/密级走权限过滤）
uv run python -m rag.scripts.query --query "差旅住宿标准是多少" --top-k 3

# 4. 评测（Golden Set hit_rate / mrr）
uv run python -m rag.scripts.run_eval

# 5. 启动 MCP Server（stdio 传输，供 MCP 客户端/后续 aioncore 注册）
uv run python -m rag.server.rag_server
```

## MCP 工具接口

| 工具 | 说明 |
| --- | --- |
| `retrieve(query, top_k, department, confidentiality)` | 只检索，返回带来源的最相关片段（含 `parent_text` 父块上下文；首选，把"生成"留给 Agent） |
| `rag_answer(query, department)` | 检索+生成一体，父块上下文 + 权限过滤 + 引用（需 LLM，config `llm.enabled: true`） |
| `list_knowledge_bases()` | 列出可检索的文档范围（标题/部门/密级） |

> 实现说明：mcp 2.x 起 FastMCP 是独立包（`from fastmcp import FastMCP`），与设计方案文档里的
> `mcp.server.fastmcp`（mcp 1.x）导入路径不同，API 一致。

## Q2Q 索引（预设问题召回）

对应设计方案 §5.4：把每个 chunk 增强生成的预设问题（`questions_this_excerpt_can_answer`）
拆成独立「问题节点」，建独立向量索引（`.data/index_q2q`）；检索时问题命中 →
经 `source_chunk_id` 映射回原 chunk，消除「问法 vs 原文措辞」鸿沟。

- 构建：`build_kb` 全量建库时自动构建；已有知识库可用 `build_q2q` 补建（不重跑 LLM）；
- 召回：`retrieve` 三路融合 = 正文向量 + **Q2Q** + 中文 BM25；Q2Q 索引缺失时优雅降级为两路；
- 实测：「常用系统有哪些」这类问法差异查询向量路 rank 99（完全未命中）、BM25 路 rank 1 命中，
  体现多路互补价值。

> 踩坑：llama-index 0.14 的 `TextNode` 字段是 `id_`（`node_id=` 传参会静默忽略、生成随机 ID），
> 导致 Q2Q 的 `source_chunk_id` 与正文节点 ID 失配；`load_nodes` 已改用 `id_=` 修复。

## 评测基线（Golden Set 54 条，含题型分类）

`eval/golden_set.py` 按设计方案 §7.1 组织题型，评测报告分类型汇总：

| 题型 | 数量 | hit_rate | mrr | 说明 |
| --- | --- | --- | --- | --- |
| 常规（事实） | 31 | 100% | 1.0000 | 制度/流程/产品/服务细节 |
| 问法差异 | 6 | 100% | 1.0000 | 口语问法 vs 书面措辞（Q2Q/BM25 补位） |
| 跨文档对比 | 4 | 100% | 1.0000 | 答案分布在多份文档 |
| 多跳 | 4 | 100% | 1.0000 | 流程串联（申请→审批→报销） |
| 干扰项 | 6 | 100% | **0.8056** | 词面重叠但答案唯一，正确文档被压到 rank 2-3 |
| 时效 | 3 | 100% | 1.0000 | 新旧版本冲突取新（对比类 require_all 两版都在） |
| **合计** | **54** | **100%** | **0.9784** | 干扰类为当前唯一短板 |

> 干扰类正是**后续 Rerank 的 A/B 基准**：如「公司研发新功能之前要先做什么」正确文档
> （rnd_flow）被语义相近的 product_plan 压到 rank 3；接入 Rerank 后对比该项 mrr 即可量化收益。
> 权限用例（越权类）独立 5 条，0 泄漏；对比类用例（require_all）要求期望文档**全部**出现才算命中。

## 父子块（子块命中、父块作答）

对应设计方案 §5.2(4)：`HierarchicalNodeParser(chunk_sizes=[1536, 512])` 生成父块 + 子块。

- **子块（512）** 入正文/Q2Q/BM25 索引，负责精确命中；
- **父块（1536）** 落盘为 `parents.jsonl`（`leaf_id -> 父块` 映射），检索后挂接为结果
  的 `parent_text`——Agent 拿到的是"大而全"的作答上下文，子块文本保留为命中证据；
- `rag_answer`：检索（含 ACL 过滤）后用父块上下文生成，附来源引用；
- 说明：llama-index 0.14 的 `AutoMergingRetriever` 类型签名只接受 `VectorIndexRetriever`，
  无法包住三路融合检索器，故采用「检索后挂接父块」的等价实现；
- 实测：`差旅住宿标准` 命中 489 字子块 → 挂接 1152 字父块 → 完整回答
  （一线≤500/其他≤350/境外≤800，超出自理需特批），命中质量不变（hit_rate 100%）。

## 时效感知（时间作为关键属性，取新不取旧）

对应时间维度的落地：知识随版本演进（如制度手册 2025 版 → 2026 版），语义检索会同时命中
新旧版本。`retrieve/recency.py` 在检索后（ACL 之后、top_k 之前）处理：

- **版本标识**：文档 metadata 带 `family_id`（知识族）+ `effective_date`（生效日期）
  + `effective_to`（失效日期）；样例库已内置 `公司制度手册（2025版）.md` 与 2026 版构成冲突
  （旧值：住宿 400/300/600、报销周期 10 个工作日；其余文本一致，只有时间属性可区分）；
- **取新不取旧**：非对比查询，同 family 只保留最新版本（`prefer_latest: true`）；
- **对比放宽**：问法含"变化/区别/以前/相比/调整/变了吗/这两年"等 → 保留全部版本，
  旧版本分数衰减（`decay: 0.5`）——支持"这两年变了吗"类对比问题；
- **过期硬排除**（可选）：`hard_filter: true` 时非对比查询丢弃 `effective_to` 过期版本。

实测（Golden Set 54 条，新增"时效"类型 3 条）：
- 「现在的住宿标准是多少」→ 只返回 2026 版（2025 版被取新逻辑过滤）✓
- 「住宿标准这两年变了吗」「报销付款周期有什么调整」→ **新旧两版都返回**（require_all 断言）✓
- 整体 hit_rate 100% / mrr 0.9784，原 51 条无退化

> 说明：llama-index 0.14 内置的 `FixedRecencyPostprocessor` 是"全局按 date 截断 top_k"、
> 不做 family 分组去重，语义不匹配，故自研（参考其 date_key 约定）；对比判定用问法标记词表，
> 口语化表达（"变了吗/这两年"）需加入词表（已覆盖）。

## 上下文压缩（去噪 / 省 token / 提质量）

检索得到 top_k 块后，不直接整块塞给 LLM，先按查询相关性**压缩每块**：
保留强相关句子、去掉无关句子/段落（`retrieve/compress.py`）。压缩作用于
`parent_text`（作答上下文），`compressed_text` 随结果返回；`rag_answer` 优先用压缩文本。

两种模式（`config.retrieval.compression`）：

| 模式 | 机制 | 特点 | 实测 |
| --- | --- | --- | --- |
| `embedding`（默认） | 中文分句 → 过滤标题/分隔行 → 与查询算余弦相似度 → 按 `keep_ratio` 保留最相关句 → **恢复原顺序** | 零 LLM 调用、快、确定性 | 上下文省 ~70-75%；答案质量不降（评测不变） |
| `llm` | 每块让 qwen 只摘录与查询直接相关的原句 | 精度最高、慢（每块一次 LLM 调用） | 1152 字父块 → 139 字，只留住宿标准表格+超出自理 |

关键参数：`threshold`（相似度绝对下限，过滤尾部噪声）、`keep_ratio`（超下限句子按相似度保留比例）、
`max_sentences`（每块句数上限）。

> 踩坑与结论：
> - 结构性过滤**不能丢 markdown 表格行**——制度手册的答案（住宿标准 500/350/800）就在表格里，
>   误过滤会导致答案内容丢失（已修，只过滤纯分隔行 `| --- |` 与标题）；
> - 单向量相似度对"同文档内语义噪声句"（查差旅却命中谈加班工资的句子）区分度有限，
>   embedding 模式做粗过滤（省 token 为主）；需要高精度摘录时切 `llm` 模式；
> - 压缩只影响送入 LLM 的上下文，**不改变检索排名**（评测 hit_rate/mrr 不受影响）。

## 融合模式（重要调优结论）

三路召回融合默认 **`simple`**（`config.retrieval.fusion_mode`）：

- 实测 `rrf`（设计方案原文推荐）在本语料上会**淹没单路强命中**：RRF 按排名给分，
  奖励"多路都出现"的文档；当向量/Q2Q 两路对某查询较弱时，一个在三条路都排中位
  的干扰文档能压过 BM25 单路 rank 1 的精确命中（「常用系统有哪些」因此脱靶）；
- `simple`（分数归一求和）实测 20/20、mrr 1.0000，`relative_score`/`dist_based` 次之；
- 切换：改 `fusion_mode: rrf | simple | relative_score | dist_based`，无需重建索引。

```jsonc
// MCP 客户端调用示例（stdio）：
// {"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"retrieve","arguments":{"query":"Q1 的产品目标是什么","top_k":3}}}
```

## 接入公司真实知识库（数据源适配器）

1. 按真实形态实现 `KnowledgeSource`（参考 `local_dir.py`；目录型直接改路径，
   Confluence/SharePoint/API 型参照 `company_stub.py` 的提示实现 `list_documents/open_stream`）。
2. `config.yaml` 里 `datasource.type` 指向新实现（或直接改 `params`）。
3. 重新 `build_kb` 建库即可，检索/工具/评测代码不动。

> 权限模型：每个文档带 `department` + `confidentiality` 元数据，检索时按调用方
> 部门/密级过滤（部门匹配 **或** 公开文档）。上线时用户身份由 AionCore 透传。

## 网络与模型（本机实测 + 踩坑记录）

| 项 | 结论 |
| --- | --- |
| pypi | 可达 ✓（依赖可装） |
| HuggingFace 直连 | 部分可达（走系统代理；`huggingface.co/api/*` 通，CDN 文件下载经重定向可达） |
| **hf-mirror 镜像** | **不要设 `HF_ENDPOINT` 镜像**：hf-mirror 会把请求 308 重定向回 huggingface.co，触发 hf_hub 1.28 的 `FileMetadataError` 域名校验，下载必失败 |
| xet 存储 | **必须 `HF_HUB_DISABLE_XET=1`**：xet 缓存路径在本机无写权限 |
| HF 缓存位置 | `HF_HOME` 指向工作区 `.data\hf`（默认 `~/.cache/huggingface` 无写权限） |
| 0700 目录陷阱 | 本机对 `mode=0o700` 创建的目录会收紧 ACL，之后无法写入（`tempfile.mkdtemp`/hf_hub 下载事务全中招）。已内置 `src/rag/_winfix.py` 补丁，包导入时自动生效 |
| 符号链接 | 无 Developer Mode → symlink 不可用，hf_hub 自动降级为复制（模型 ~150MB，可接受） |
| 中文控制台 | 已统一 UTF-8 输出（`rag/__init__.py` 里 reconfigure），避免 GBK 编码报错 |

以上适配已固化在 `.env`（uv run 自动加载）、`run.ps1` 与 `config.py`，新环境只需保证
**pypi 可达**即可复现整个流程。

## Embedding 模型

- v1 默认 **jinaai/jina-embeddings-v2-base-zh**（fastembed/ONNX，中英混合，~150MB，CPU 可跑）。
  实测命中质量好（Golden Set hit_rate 100%）。
- fastembed 0.8 不支持 bge-m3。升级到设计方案指定的 **BAAI/bge-m3**：
  `config.yaml` 里 `embedding.backend: huggingface` + `model: BAAI/bge-m3`
  （需先 `uv add torch sentence-transformers llama-index-embeddings-huggingface`，代码零改动）。
- 模型下载引导：`uv run python -m rag.scripts.dl_model`（模型缓存后建库/检索全离线）。

## LLM（Ollama，已启用）

本机已安装并启用：**Ollama 0.33.0 + qwen2.5:7b**（RTX 3060 Laptop 6GB，实测约 9 tok/s）。

- 安装：本机 winget 不可用（App Installer 损坏），改为官方安装包静默安装：
  `OllamaSetup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART`（装到 `%LOCALAPPDATA%\Programs\Ollama`）；
- 模型拉取：`ollama pull qwen2.5:7b`（4.7GB；网络受限时给 `ollama serve` 配 `HTTP_PROXY/HTTPS_PROXY`）；
- `config.yaml`：`llm.enabled: true` + 三个增强开关已打开；
- 三个 Extractor 的 prompt 已本地化为中文（`ingest/pipeline.py` 的 `enhance_nodes`），
  生成的中文摘要/预设问题/关键词写入节点 metadata；
- `rag_answer` 工具：检索+生成一体，返回带来源的答案（已在 MCP 冒烟测试中验证）；
- 日常使用：直接启动 Ollama app 即可（模型已缓存本地，无需代理）；未启用 LLM 时
  `Settings.llm` 注入 MockLLM 占位，检索链路不受影响。

## 与 AionCore 的对接（后续阶段）

1. 本仓库 `mcp.server.fastmcp` 实现，stdio 传输，独立可测；
2. AionCore `crates/aionui-mcp/src/adapters/` 增加 hermes 适配器（目前只有
   aionrs/claude/codex/gemini/qwen 等，**无 hermes**），把 RAG Server 注册为
   stdio 型 MCP Server；
3. 前端工具页面（ToolsSettings）注册/启停 RAG Server；
4. 用户身份（部门/密级）由 AionCore 透传到 MCP 调用，供权限过滤。

## 路线图对照（设计方案 §8）

- 阶段一（已完成）：样例库 → 分块 → VectorStoreIndex + BM25 → 检索 → MCP 工具 → 评测
- 阶段二（进行中）：LLM 增强（摘要/预设问题/Q2Q 索引）✅、父子块 ✅、Golden Set 扩充 ✅（51 条）
  → **剩余：Rerank**（候选 LLMRerank 复用 qwen / bge-reranker-v2-m3 torch 两条路径，
  以「干扰类 mrr 0.8056」为 A/B 基准）
- 阶段三：注册进 AionCore（hermes MCP 适配 + 前端），真数据源接入
- 阶段四：可观测（Phoenix/LlamaTrace）、A/B、CI 回归
