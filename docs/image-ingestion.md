# 离线图片入库

## 范围与流程

图片能力是**入库时**的 OCR / 图片转文本，保留原有 BGE-M3 文本索引和回答模型。
支持独立 PNG/JPEG/WebP/BMP/TIFF、HTML 本地插图、PDF 页面。
不包含图片相似度索引、用户上传图片提问、DOCX/PPTX 内嵌图片、动态图帧解析。
HTML 的图片与原文档共享权限，描述在原图片位置插入。独立图片的权限须在 manifest 中设置；
默认不单独扫描图片，以免 HTML 引用图片重复入库或缺少父文档权限。

先用 OCR+视觉模型把页面/图片变成文本，再分块、向量化。视觉模型输出不保证连接关系正确，
原图是核验依据；没有清楚显示的连线、方向和接口必须标记不确定。

## 依赖与配置

安装 `uv sync --extra gpu-embed --extra images` 或使用服务器的离线 wheels。
OCR 使用现有 rapidocr-onnxruntime 包自带 ONNX 模型，CPU 执行，不需要 PaddlePaddle。
PDF 使用 pypdfium2（PDFium 随 wheel 提供），不需要系统安装 Poppler。
Ollama 必须已导入支持图片的模型；文本 qwen2.5:7b 不能用于此项。

在已有配置中增加：

```yaml
images:
  enabled: true
  include_standalone: false
  ocr_enabled: true
  vision_enabled: true
  model: qwen2.5vl:7b
  base_url: http://127.0.0.1:11435
  cache_dir: ../indexes/images/image_cache
  timeout_sec: 180
  max_side: 1600
  min_side: 48
  max_pixels: 40000000
  max_bytes: 30000000
  ocr_min_score: 0.5
  pdf_mode: all
```

`pdf_mode: all` 对所有页面执行图片解析，覆盖有文字也有图的页面；`scanned` 仅处理少文字页面。
`include_standalone: true` 另外扫描独立图片，应提供唯一来源和正确权限的 manifest。
可指定 `det_model_path`、`rec_model_path`、`cls_model_path` 使用自备本地 ONNX 文件。
配置路径以 YAML 所在目录为基准。图片缓存必须放在数据源目录之外。

## 缓存、失败和资源

每张图片/每页渲染结果成功后原子写入 JSON 缓存，模型失败不会写入成功标志。
缓存包括图片内容、模型 digest、提示词、配置、解析器和依赖版本；不缓存 ACL。
改动 HTML 引用的图片时，文档级断点续跑工具应调用 `image_dependency_signature` 更新父文档缓存键。
该部署工具在仓库外维护，不纳入版本控制。

OCR 在有超时的子进程执行（进程启动带来一定开销）；视觉调用有请求超时，解析默认串行。
一次页面失败会使所在文档进入失败列表，但此前完成的图片/页面仍有缓存。
长 PDF 的文档级超时应高于单页超时，重跑可以命中之前已完成的页面。
小图标按 min_side 跳过；外部 URL 不下载；越出数据源根目录的图片引用拒绝处理。
HTML 缺图不会悄悄标为完整成功，应修复文件后重试。

入库前应卸载同 GPU 的闲置文本模型；解析完成会卸载视觉模型，再加载 BGE-M3。
独立图片来源、HTML 图片相对路径、PDF 页码以文本标记保留，检索返回源文档 file_path。
长页面跨块时应结合 parent_text 查看完整来源。暂不提供每个子块独立的结构化图片坐标。

## 验证

`python -m unittest discover -s tests -v`

首次在新机器部署，先用人工样例验收独立图、HTML 内嵌图和扫描 PDF，再用少量真实资料评估。
新配置使用独立索引目录，避免覆盖原纯文本基线。第一次加入图片内容需要重新分块/向量化；
图片缓存可以复用，不意味着嵌入索引已实现增量更新。
