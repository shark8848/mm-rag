# 多模态 RAG 流水线

端到端的音/视频 RAG 样例：按照 `mm-schema.json` 规范将原始素材切分、理解、落盘，向 Elasticsearch 写入可检索分块，并同时提供 FastAPI 服务与 Gradio 控制台，方便上传、监控日志、进行混合检索与媒体播放。

## 功能亮点

- **多模态解析**：FFmpeg 抽帧 + Whisper/DashScope ASR，按照 `mm-schema.json` 输出 keyframe、音频、文本段落。
- **PDF 文档解析**：通过 MinerU API 拆解 PDF，生成结构化文本 chunk，并将 MinerU 原始 JSON 推送到对象存储，供下游直接消费。
- **PDF Bbox 可视化**：Gradio UI 集成 MinerU bbox 渲染，使用 pypdf + reportlab 在 PDF 上绘制彩色边界框，支持分页浏览，可直观查看表格、图片、标题、文本、公式、列表等元素的检测结果和阅读顺序。
- **插件化 PDF 处理**：`PDF_PARSER=mineru|local`，可在 MinerU 云端与本地 pdfminer 解析之间热切换，接口与上下文输出保持一致。
- **灵活存储**：磁盘落地原始/中间/最终 JSON，Elasticsearch 存储分块并附带 `thumbnail`、`video_path`、`audio_path` 方便前端回放；若 ES 不可用自动退回内存索引。
- **任务可观测性**：基于 Celery + Redis 的异步队列，`/tasks/{task_id}` 会实时拉取 Celery 状态，另有 `/logs/{task_id}`/`/logs/tail` 暴露细粒度日志。
- **交互式检索**：Gradio Chatbot 以对话形式呈现检索命中，并可直接播放命中视频/音频和浏览关键帧。
- **对象存储同步（可选）**：打开 `MINIO_ENABLED=true` 后，`data/` 下的原始文件、中间产物、最终 JSON 会自动镜像到 MinIO 指定 bucket。

## 核心组件清单

| 组件 | 作用 |
| --- | --- |
| FastAPI | 暴露 `/ingest`、`/query`、`/logs` 等服务端 API，并调度后台任务 |
| Uvicorn | 作为 ASGI 服务器运行 FastAPI 应用 |
| FFmpeg | 完成音频抽取、抽帧、场景切分等多媒体处理 |
| Whisper (openai-whisper) | 本地 ASR 备份方案，DashScope 不可用时回退 |
| DashScope (阿里百炼) | Paraformer ASR、向量、Qwen-VL/LLM 能力的云端入口 |
| Elasticsearch 8.x | 持久化检索分块，支持文本+媒体路径返回 |
| Gradio | 提供上传、日志监控、混合检索与媒体播放的前端控制台 |
| PDF Parser 插件 | MinerU/Local 等解析插件统一暴露 `PdfParser` 接口，保证 PDF 处理能力可插拔 |
| MinerU PDF API | 解析 PDF 并返回结构化文本/版式 JSON，供 PDF 任务构建 Chunk 与落地对象存储 |
| MinIO | 可选对象存储，用于同步 `data/` 目录的原始/中间/最终产物 |

## 项目结构

```
app/
  config.py              # 全局配置、数据路径、ES/阿里百炼参数
  logging_utils.py       # 统一日志初始化
  models/mm_schema.py    # 与 mm-schema.json 对齐的 Pydantic 模型
  pipeline/ingest.py     # 主处理入口（抽帧、ASR、分块、入 ES）
  pipeline/stages/       # Stage4 原子任务（validation/chunks/vector/persist/index）
  processors/            # 音视频处理模块（Whisper、DashScope、FFmpeg）
  services/              # 存储、Elasticsearch、阿里百炼客户端封装
  tasks.py               # 内存任务状态表
main.py                  # FastAPI 启动文件
ui/gradio_app.py         # 控制台：上传、日志、检索、媒体预览
requirements.txt         # Python 依赖
mm-schema.json           # 数据规范
```

## 数据落盘约定

- `data/raw/`：原始素材副本（上传或引用的源文件）。
- `data/intermediate/audio|video/`：抽取的 WAV、切分片段、缩略图等中间产物。
- `data/intermediate/pdf_*/`：PDF 解析插件输出的原始 JSON，自动同步到对象存储。
- `data/final_instances/`：最终符合 `mm-schema.json` 的 JSON，便于审计或重放。
- `data/logs/pipeline.log`：后端统一日志源，供 `/logs/*` 接口与 UI 读取。

## 环境准备

1. Python 3.10+，推荐虚拟环境：
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. 安装并运行 Redis（默认使用 `redis://localhost:6379/{0,1}` 作为 Celery broker/result backend）。
3. 系统需安装 FFmpeg，并准备 GPU/CPU 以运行 Whisper（可按需替换为自建 ASR）。
4. 若需对接 DashScope/阿里百炼，请在 `.env` 中配置密钥及模型名称。

### `.env` 示例

```env
ES_HOST=https://localhost:9200
ES_USER=elastic
ES_PASSWORD=changeme
ES_INDEX=rag-mm-segments
ES_SKIP_TLS=true
ES_ENABLED=false          # 无 ES 时自动退回内存索引

WHISPER_MODEL=base
ASR_LANGUAGE=zh
EMBEDDING_MODEL=bge-m3:latest
EMBEDDING_PROVIDER=bailian       # bailian | ollama
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_TIMEOUT=60

BAILIAN_API_KEY=sk-xxxx
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com
BAILIAN_ASR_MODEL=paraformer-v1
BAILIAN_EMBEDDING_MODEL=text-embedding-v1
BAILIAN_MULTIMODAL_MODEL=qwen-vl-plus
BAILIAN_LLM_MODEL=qwen3

LOG_LEVEL=INFO

API_AUTH_REQUIRED=true
API_SECRETS_PATH=app_secrets.json
UPLOAD_MAX_FILES=4
UPLOAD_MAX_BATCH_MB=4096
AUDIO_MAX_SIZE_MB=2048
VIDEO_MAX_SIZE_MB=4096
PDF_MAX_SIZE_MB=512
AUDIO_MAX_DURATION_SEC=21600
VIDEO_MAX_DURATION_SEC=10800

# 可选 MinIO 同步
MINIO_ENABLED=false
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=mm-rag

# MinerU PDF 解析
MINERU_API_BASE=http://127.0.0.1:8000
MINERU_PARSE_PATH=/file_parse
MINERU_API_KEY=
MINERU_CALLBACK_URL=
MINERU_TIMEOUT=60
MINERU_HEALTH_PATH=/docs
MINERU_HEALTH_CHECK=true
MINERU_STRICT=false
PDF_PARSER=mineru

# Celery / Redis
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CELERY_DEFAULT_QUEUE=ingest_cpu
CELERY_IO_QUEUE=ingest_io
CELERY_CPU_QUEUE=ingest_cpu
```

当 `API_AUTH_REQUIRED=true` 时，FastAPI 会拒绝缺少头信息的请求。`API_SECRETS_PATH` 指向一个 JSON 列表，例如：

```json
[
  {"app_id": "demo", "app_key": "demo-secret", "name": "local"}
]
```

脚本 `start_server.sh` 会在启动后提示是否启用了认证，并指明密钥文件路径；客户端调用时需携带 `X-Appid: demo` 与 `X-Key: demo-secret` 头部。

> 向量模型可通过 `EMBEDDING_PROVIDER` 选择 `bailian` 或 `ollama`。当设置为 `ollama` 时会调用本地 `OLLAMA_BASE_URL/api/embeddings`，并使用 `OLLAMA_EMBEDDING_MODEL`；若选择 `bailian` 则延用 DashScope SDK/REST。当云端或本地服务不可用时，流水线会退回确定性伪随机向量以保证流程可继续。

## 运行服务

### FastAPI 后端

```bash
.venv/bin/uvicorn main:app --host 0.0.0.0 --port 8000
```

- `POST /ingest` 支持基于已有文件路径的离线处理。
- `POST /ingest/upload` 提供 multipart 上传，并将自定义参数（抽帧策略、标签等）写入任务。
- 后台任务完成后把 `mm-schema` 结果与媒体路径落入磁盘与 ES。

也可以使用脚本统一管理：

```bash
# 启动 FastAPI + Gradio（日志位于 data/logs/*.log，PID 文件在 .run/）
./start_server.sh

# 停止全部后台服务
./stop_server.sh

# 仅启动 Celery worker（默认也会停止历史 worker）
./start_server.sh celery

# 仅启动 Flower 监控
./start_server.sh flower

# 仅停止 Gradio UI
./stop_server.sh gradio

# 查看各服务当前状态
./show_server.sh
```

> 提示：脚本默认会拉起 `celery_cpu`/`celery_io` worker 以及 Flower 监控，并在 `./stop_server.sh` 中一并关闭。若需要手动管理，可在执行脚本前导出 `START_CELERY=false`、`START_FLOWER=false`（或 `STOP_CELERY=false`、`STOP_FLOWER=false`）跳过自动管理；`FLOWER_ADDRESS`/`FLOWER_PORT` 控制监听地址和端口，`FLOWER_HEALTH_RETRIES`/`FLOWER_STRICT` 调整健康检查与失败策略。

### Celery Worker（必需）

Pipeline 已拆分为原子级 Celery 任务，需至少启动一个 CPU worker 与一个 IO worker：

```bash
# CPU/GPU 密集型（ASR、抽帧、摘要）
.venv/bin/celery -A app.celery_app worker -Q ingest_cpu -n ingest_cpu@%h -l info

# IO 密集型（文件落地、元数据、MinIO 同步）
.venv/bin/celery -A app.celery_app worker -Q ingest_io -n ingest_io@%h -l info
```

可按节点资源横向扩展 worker 数量；Flower 或 Prometheus exporter 可用于观测运行和队列堆积情况。

#### Flower 监控（可选）

安装依赖后，可借助 Flower 实时查看任务、队列与 worker 状态：

```bash
.venv/bin/celery -A app.celery_app flower --address 0.0.0.0 --port 5555
```

浏览器访问 `http://localhost:5555` 即可查看 Celery 任务曲线和失败重试细节。Flower 会复用 `.env` 中配置的 Redis broker/result backend，无需额外参数。

### Gradio 控制台

```bash
API_BASE_URL=http://localhost:8000 \
API_APP_ID=demo \
API_APP_KEY=demo-secret \
.venv/bin/python ui/gradio_app.py
```

- **上传处理** 页签：上传音/视频、选择抽帧策略（`interval`/`scene`）、查看任务状态与实时日志。
- **PDF 管道** 页签：上传 PDF 文档，配置 MinerU 解析参数（后端、语言、公式/表格识别等），解析完成后点击"🔄 加载分页预览"查看带彩色 bbox 标注的 PDF 页面，支持滑块翻页浏览。
- **混合检索** 页签：输入查询后由 Chatbot 返回命中段落，同时展示首个命中的视频、音频、关键帧画廊，便于复核。
- UI 默认轮询 `/tasks/{task_id}` 与 `/logs/{task_id}`，若任务专属日志缺失则自动降级到 `/logs/tail`。
- FastAPI 开启认证时（默认），请在启动 UI 或调用脚本前设置 `API_APP_ID`、`API_APP_KEY`，值需与 `app_secrets_path` 中的凭据一致，客户端会自动为所有请求附加 `X-Appid`/`X-Key` 头部。

#### PDF Bbox 渲染说明

Gradio UI 的"PDF 管道"页签提供了 PDF 可视化预览功能，基于 MinerU 的 `middle.json` 中的 bbox 坐标数据：

1. **颜色图例**：
   - 📊 表格(table): 黄色
   - 🖼️ 图片(image): 绿色
   - 📑 标题(title): 蓝色
   - 📝 文本(text): 紫色
   - 🔢 公式(equation): 绿色
   - 📋 列表(list): 深绿色

2. **操作流程**：
   - 上传 PDF 并点击"提交 PDF 处理"
   - 等待状态变为"success"
   - 点击"🔄 加载分页预览"按钮（按需加载，避免启动卡顿）
   - 使用滑块切换页码查看不同页面的标注

3. **技术实现**：
   - 使用 `app/utils/draw_bbox.py` 中的 MinerU 官方 bbox 绘制函数
   - 通过 `pypdf` 和 `reportlab` 在原始 PDF 上叠加彩色矩形和阅读顺序编号
   - 单页按需渲染，避免大文档内存占用

4. **相关文档**：
   - 完整实现说明：`BBOX_RENDERING_IMPLEMENTATION.md`
   - Artifacts 传递修复：`MINERU_ARTIFACTS_FIX.md`
   - 启动优化记录：`STARTUP_FREEZE_FIX.md`

## API 与日志

- `POST /ingest`：基于绝对路径触发处理，`media_type` 支持 `audio`/`video`/`pdf`，PDF 会自动走 MinerU Celery 流程。
- `POST /ingest/upload`：上传媒体并附带 `metadata` / `processing_options` JSON，同样支持 `media_type=pdf`。
- `GET /tasks/{task_id}`：查询任务状态与最终 `mm-schema` 结果。
- `GET /logs/{task_id}`：返回包含 `task_id` 的最新日志片段。
- `GET /logs/tail`：全局日志尾部（默认 200 行），供 UI 回退或手动排障。
- `POST /query`：`{"query": "关键词", "top_k": 5}` 返回带 `thumbnail`/`audio_path`/`video_path` 的命中分块。
- `GET /health`：基础探活。

> PDF 任务的 MinerU 定制参数可通过 `processing_options.mineru` 传入（例如 `{"mineru": {"split_mode": "page"}}`），服务会透传给 MinerU API。

### 身份认证与响应封装

- 默认开启 `API_AUTH_REQUIRED`，所有 API 必须附带 `X-Appid` 与 `X-Key` 头部；头部值会与 `app_secrets_path` 中的凭据匹配，可通过 `app/core/security.py` 的 `CredentialStore` 签发或吊销。
- 成功请求遵循 `TaskResponse`（`task_id`/`status`/`detail`/`result`）或 `QueryResponse`（`query`/`issued_at`/`hits[]`）结构，方便前端消费。
- 失败请求统一返回 `ErrorEnvelope`：

```json
{
  "status": "failure",
  "error_code": "ERR_AUTH_REQUIRED",
  "error_status": 401,
  "message": "Authentication is required",
  "zh_message": "缺少认证信息",
  "context": null
}
```

这样前端/脚本可以根据 `error_code` 精确提示用户，例如认证失败、媒体过大或限流（`ERR_THROTTLED`）。

### 原子化任务编排

Stage4 将流水线完全拆分为以下 7 个 Celery 任务，均在 `app/pipeline/stages/*.py` 中实现，并通过 `app/pipeline/celery_tasks.py` 动态串联：

1. `pipeline.validate_input`（`ingest_io`）：复用 `LimitChecker` 再次校验媒体体积/时长，确保后台队列可安全处理。
2. `pipeline.build_metadata`（`ingest_io`）：调用 `_build_metadata` 生成 `DocumentMetadata`，写入上下文供后续阶段使用。
3. `pipeline.generate_chunks`（`ingest_cpu`）：按 `processing_options` 调度音/视频处理器、Whisper/Bailian ASR，并在 `media_type=pdf` 时调用 MinerU 把 PDF 拆解为结构化 chunk；统一序列化 `mm-schema` 片段。
4. `pipeline.generate_summary`（`ingest_cpu`）：基于 chunk 文本构造摘要，默认走 Bailian/Qwen，失败时可自定义回退。
5. `pipeline.vector_enrichment`（`ingest_cpu`）：为 chunk 写入向量统计信息与 `vector_provider`，当前默认透传 `vector_service` 的模型标识。
6. `pipeline.persist_artifacts`（`ingest_io`）：借助 `build_document_payload` 保存最终 JSON，并同步 MinIO/记录落盘路径。
7. `pipeline.index_document`（`ingest_cpu`）：写入 Elasticsearch 或内存索引，并回传 `indexed_chunks` 计数。

每个 Stage 在执行时都会向上下文注入阶段指标（`metrics.chunks`、`metrics.vector_chunks` 等）与落盘信息，最终由 `/tasks/{task_id}` 返回。链路中的任意异常都会立即更新 Celery 状态并通过 API `detail` 字段暴露。

#### Stage4 验证示例

1. 启动 FastAPI 与 Celery Worker：
   ```bash
   ./start_server.sh api
   ./start_server.sh celery
   ```
2. 使用示例凭据（`app_secrets.json` 中的 `demo/demo-secret`）触发一次本地文件处理：
   ```bash
   curl -s -X POST http://127.0.0.1:8000/ingest \
     -H 'Content-Type: application/json' \
     -H 'X-Appid: demo' \
     -H 'X-Key: demo-secret' \
     -d '{
       "media_type": "video",
       "source_path": "/home/mm-rag/data/raw/<your-file>.mp4",
       "metadata": {
         "title": "Stage4 Validation",
         "tags": ["demo", "stage4"],
         "custom_attributes": {"source": "manual-test"}
       }
     }'
   ```
   返回 `task_id` 后可根据需要重复调用 `/ingest/upload` 上传新素材。
3. 轮询任务与日志：
   ```bash
   curl -s -H 'X-Appid: demo' -H 'X-Key: demo-secret' \
     http://127.0.0.1:8000/tasks/<task_id> | jq

   curl -s -H 'X-Appid: demo' -H 'X-Key: demo-secret' \
     http://127.0.0.1:8000/logs/<task_id> | jq
   ```
   `status` 变为 `success` 后，可到 `data/final_instances/<task_id>.json` 与 `data/logs/pipeline.log` 比对 Stage4 输出与性能信息。

## MinIO 同步说明

- 设置 `MINIO_ENABLED=true` 且提供 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET` 后，`app/services/storage.py` 会在以下场景同步文件到 MinIO：
  - `save_raw_upload` / `save_raw_path`：原始媒体副本 (`data/raw/`).
  - `persist_intermediate`：所有 `data/intermediate/...` 产物，如 `audio/<doc>.wav`、`video/<doc>/frame_XXXX.jpg`。
  - `persist_json`：最终 `data/final_instances/*.json`。
- 同步路径默认复用 `data/` 下的相对结构，例如 `data/intermediate/audio/foo.wav` 会写成对象 `intermediate/audio/foo.wav`。
- 处理完成后可在 MinIO 控制台检索 `intermediate/audio/` 与 `intermediate/video/` 前缀，确认音频与关键帧已经上传。
- MinIO 端可使用 `MINIO_OPTS="--address :9000 --console-address :9001"` 等参数启动，默认账号/密码为 `minioadmin/minioadmin`。

## PDF 解析插件

- `PDF_PARSER` 选择 `mineru`（默认）或 `local`。MinerU 插件调用外部服务默认直连 `http://127.0.0.1:8000/file_parse`（可用 `MINERU_API_BASE` + `MINERU_PARSE_PATH` 覆盖），本地插件则使用 pdfminer/纯文本回退，保证无外部依赖也能产出 Chunk。
- 插件输出统一的结构化 payload，会被持久化到 `data/intermediate/pdf_<parser>/<document_id>.json`，并同步到对象存储；落盘路径可在任务 `artifacts.pdf_payload_path` 字段中查看。
- `processing_options.mineru` 仅在选择 MinerU 插件时生效，用于透传页范围、表格格式等参数；若后续扩展更多插件，也可复用同一接口。
- `start_server.sh` 在启用 MinerU 插件时会预先探测其健康（可通过 `MINERU_HEALTH_CHECK`/`MINERU_STRICT` 控制），避免 PDF 任务落到离线服务上。

## 典型流程

1. 启动 FastAPI 与 Gradio 控制台，确保 `API_BASE_URL` 指向后端。
2. 在“上传处理”页签上传媒体，选择抽帧策略及参数，等待任务完成。
3. 任务完成后于 `data/final_instances/` 查看结构化结果，必要时手动将生成的音频/关键帧同步到对象存储。
4. 切换到“混合检索”，输入自然语言问题验证 ES 命中情况，并通过内置视频/音频组件回放片段。
5. 若需要重新索引旧数据，可重新触发 `/ingest` 或编写脚本遍历 `data/raw/`。

## 扩展方向

- `app/services/asr.py` 可自定义云端/本地 ASR 组合策略，DashScope 异常时会自动回退 Whisper。
- `app/services/search_client.py` 已预留 `embedding_dimension`，可快速替换为 KNN/向量数据库。
- 在 `processors/video.py` 中追加多模态描述模型（例如 `qwen-vl-plus`），并把描述写入每个分块的 `keyframes`，供检索与 UI 使用。
- 使用 `mm-schema.json` 做数据契约，可无缝对接更多前后端模块。

借助这些组件，可以按需迭代成生产级的多模态 RAG 系统，确保数据产出始终满足 `mm-schema.json` 规范并具备良好的可观测性与交互体验。

## 版本历史与下载

| 版本 | 日期 | 亮点 | 下载 |
| --- | --- | --- | --- |
| v0.4.0 | 2025-12-06 | MinerU PDF Bbox 可视化：Gradio UI 集成 bbox 渲染，支持分页预览、彩色元素标注和阅读顺序显示；优化 UI 导航，移除冗余翻页按钮和页码显示；修复 artifacts 传递、启动卡顿和中间 JSON 键错误等多个问题。 | [源代码包](https://github.com/shark8848/mm-rag/archive/refs/tags/v0.4.0.zip) |
| v0.3.0 | 2025-12-06 | Stage4：七段式 Celery 流水线、认证/日志文档更新、Gradio Chatbot 修复 | [源代码包](https://github.com/shark8848/mm-rag/archive/refs/tags/v0.3.0.zip) |
| v0.2.0 | 2025-12-05 | 引入 `start/stop/show_server.sh` 一键脚本、Celery/Flower 健康检查、可切换的 Bailian/Ollama 向量服务、`.env`/日志文档完善。 | [源代码包](https://github.com/shark8848/mm-rag/archive/refs/tags/v0.2.0.zip) |
| v0.1.0 | 2025-11-28 | 首次公开版本：包含 FastAPI + Gradio、MinIO 同步、启动脚本与任务/日志 API。 | [源代码包](https://github.com/shark8848/mm-rag/archive/refs/tags/v0.1.0.zip) |

更多细节参见 `CHANGELOG.md`，新的标签发布后可在 [Releases 页面](https://github.com/shark8848/mm-rag/releases) 下载对应包。
