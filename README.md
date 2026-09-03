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
├── config_rfc_bgem3.yaml       # RFC 压测配置（bge-m3，独立索引，测试用）
├── pyproject.toml              # uv 项目定义（[tool.uv] cache-dir + gpu-embed 可选组）
├── run.ps1                     # 便捷启动（路径自动推导，可移植）
├── 开发决策记录.md               # 两个阻塞问题的解法 + 环境踩坑记录
├── src/rag/
│   ├── __init__.py             # UTF-8 输出 + Windows 环境补丁加载
│   ├── _winfix.py              # 0700 目录补丁 + llama-index 缓存重定向（本机必需）
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

## 评测基线（Golden Set 58 条，含 Rerank，题型分类）

`eval/golden_set.py` 按设计方案 §7.1 组织题型，评测报告分类型汇总（已含 LLM Rerank）：

| 题型 | 数量 | hit_rate | mrr | 说明 |
| --- | --- | --- | --- | --- |
| 常规（事实） | 34 | 100% | 0.9706 | 制度/流程/产品/服务细节（含 HTML 帮助中心） |
| 问法差异 | 6 | 100% | 0.9167 | 口语问法 vs 书面措辞（Q2Q/BM25 补位） |
| 跨文档对比 | 5 | 100% | 0.9000 | 答案分布在多份文档（含 HTML 5TB 跨文档用例） |
| 多跳 | 4 | 100% | 1.0000 | 流程串联（申请→审批→报销） |
| 干扰项 | 6 | 100% | 1.0000 | 词面重叠但答案唯一（归一化 + Rerank 已修复） |
| 时效 | 3 | 100% | 1.0000 | 新旧版本冲突取新（对比类 require_all 两版都在） |
| **合计** | **58** | **100%** | **0.9655** | 无 Rerank 基线 mrr 0.9511 → +Rerank 提升至 0.9655 |

> 权限用例（越权类）独立 5 条，0 泄漏；对比类用例（require_all）要求期望文档**全部**出现才算命中。
> 说明：本机小语料上 Rerank 收益有限（mrr +0.014）；其价值在语料/候选规模放大后
> （真实知识库、候选更多、噪声更大）会更显著——模块为可插拔设计，后续可换 bge-reranker。

## Rerank（LLM 精排）

`retrieve/rerank.py`：融合 -> ACL -> 时效 -> **Rerank** -> top_k。LLM（qwen2.5:7b，
temperature=0 专用实例）对候选片段打分排序，只改序、不降召回：

- `config.retrieval.rerank`：`enabled / mode(llm|flag_embedding 预留) / candidates(10) / top_n(5) / choice_batch_size(10)`；
- **补足机制**：LLM 只选中几条时，按融合序补足到 top_k——rerank 是"改序"不是"过滤"，
  避免 LLM 判断失误导致召回下降（实测补足前后：hit_rate 98.3% → 100%）；
- 实测：58 条 hit_rate 100%、mrr 0.9511 → **0.9655**；确定性（temp 0）验证通过。

> 踩坑：0.14 内置 `LLMRerank` 对 chat model（Ollama）走 `context_messages` 聊天模板，
> 自定义纯文本 prompt（`{context_str}`）会错配导致提示词残缺 → 自研 `LLMNodeReranker`
> （自行拼装候选 + 解析 `Doc: N, Relevance: M`，完全可控）。

## HTML 文档解析

`ingest/html_parser.py`（bs4，零额外依赖）支持 .html/.htm：标题层级 → Markdown 标题、
表格 → Markdown 表格、列表 → 项目符号，并丢弃页面噪声（nav/footer/aside/form/script 等）。
对齐设计方案 §4.2：**表格不丢**（答案常以表格承载）、结构保留供分块。

- 样例库内置《云雀云服务帮助中心.html》（FAQ + 套餐对比表 + 导航/页脚噪声），解析质量
  7/7 断言通过（表格/标题/列表保留，导航/页脚丢弃）；
- 4 条 Golden 用例命中（含跨文档「对象存储单文件最大能传多大」→ cloud_intro + cloud_help）；
- 新格式接入只需：`readers.py` 加分支 + `local_dir.py` 扩展名 + manifest 一行。

## 融合分数归一化（重要调优结论）

`retrieve/service.py` 的三路召回在融合前各自**除以本路最大值**归一化到 [0,1]：

- 原因：三路分数尺度差异极大（BM25 原始分 0-3+，向量/Q2Q 余弦 0.3-0.5），SIMPLE 融合
  直接求和会被 BM25 主导——宽泛文档（帮助中心 FAQ 反复出现"如何"）被过度抬升，
  「加班如何申请」甚至把帮助中心排到制度手册前面；
- 效果：干扰类 mrr 0.8056 → **1.0 完全修复**；「加班如何申请」恢复制度手册第一；
  整体 hit_rate 100% 不变；
- 残留：部分查询出现"同分并列/语义歧义"排序（计费方式、文档协作能力等）——留给 Rerank。

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
| llama-index 缓存 | 默认写 `%LOCALAPPDATA%\llama_index`（工作区外无写权限）→ `_winfix.py` 重定向到项目内 `.data/llama_cache` |
| download.pytorch.org | 直连被重置，**走代理可达**（CUDA torch 安装源：`https://download.pytorch.org/whl/cu126`） |
| 符号链接 | 无 Developer Mode → symlink 不可用，hf_hub 自动降级为复制（模型 ~150MB，可接受） |
| 中文控制台 | 已统一 UTF-8 输出（`rag/__init__.py` 里 reconfigure），避免 GBK 编码报错 |

以上适配已固化：uv 缓存走 `pyproject.toml` 的 `cache-dir`，HF 相关环境变量与缓存重定向
由 `config.py` / `_winfix.py` 按项目目录自动推导（无本机绝对路径，仓库可移植），
新环境只需保证 **pypi 可达**即可复现整个流程。

## Embedding 模型（双模型并存，可切换）

jina-zh（fastembed，`.data/models`）与 bge-m3（sentence-transformers，`.data/hf/hub`）**并存**，
切换只改配置 + 重建索引，互不删除：

| 模型 | 后端 | 特点 | 适用 |
| --- | --- | --- | --- |
| `jinaai/jina-embeddings-v2-base-zh`（默认） | fastembed/ONNX | 中英混合，CPU 可跑 | 公司电脑（无 torch）、中英混合语料 |
| `BAAI/bge-m3` | huggingface（sentence-transformers） | 多语种、8192 上下文、**GPU 嵌入快 ~7 倍** | 有 GPU 的机器、追求更高检索精度 |

切换配置（`config.yaml` 或专用 config）：

```yaml
embedding:
  backend: huggingface        # fastembed | huggingface
  model: BAAI/bge-m3          # 或 jinaai/jina-embeddings-v2-base-zh
```

改后必须重建索引：`uv run python -m rag.scripts.build_kb`（换模型 = 向量全变）。

**bge-m3 启用步骤**（本机已验证）：
1. 装依赖（可选组 `gpu-embed`——**公司电脑普通 `uv sync` 不会装 torch**）：
   `uv sync --extra gpu-embed`
2. 若解析到 CPU 版 torch（pypi 默认），换 CUDA 版（本机 RTX 3060；download.pytorch.org 需代理）：
   `$env:HTTP_PROXY="http://127.0.0.1:7897"; $env:HTTPS_PROXY=...; uv pip install --reinstall torch --index-url https://download.pytorch.org/whl/cu126`
3. 首次建库自动下载模型（2.3GB，公开模型，缓存在 `.data/hf/hub`，之后全离线）。

**实测**（50 个英文 RFC，5152 chunks）：GPU 嵌入 ~5 分钟（34k 字符/s）vs jina-zh CPU ~35 分钟；
检索精度 bge-m3 对英文技术语料明显更优（5/5 top1 命中正典 RFC，jina-zh 部分被通用文档抢占）。

模型下载引导（fastembed/jina-zh）：`uv run python -m rag.scripts.dl_model`。

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
- 阶段二（**已完成**）：LLM 增强（摘要/预设问题）✅、Q2Q 索引 ✅、父子块 ✅、上下文压缩 ✅、
  时效感知 ✅、HTML 解析 ✅、融合归一化 ✅、Golden Set 扩充 ✅（58 条）、**Rerank ✅**
  （LLM 精排，mrr 0.9511 → 0.9655；bge-reranker-v2-m3 作为 flag_embedding 模式预留）
- 阶段三：注册进 AionCore（hermes MCP 适配 + 前端），真数据源接入
- 阶段四：可观测（Phoenix/LlamaTrace）、A/B、CI 回归
