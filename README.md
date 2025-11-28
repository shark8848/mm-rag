# 多模态 RAG 流水线

端到端的音/视频 RAG 样例：按照 `mm-schema.json` 规范将原始素材切分、理解、落盘，向 Elasticsearch 写入可检索分块，并同时提供 FastAPI 服务与 Gradio 控制台，方便上传、监控日志、进行混合检索与媒体播放。

## 功能亮点

- **多模态解析**：FFmpeg 抽帧 + Whisper/DashScope ASR，按照 `mm-schema.json` 输出 keyframe、音频、文本段落。
- **灵活存储**：磁盘落地原始/中间/最终 JSON，Elasticsearch 存储分块并附带 `thumbnail`、`video_path`、`audio_path` 方便前端回放；若 ES 不可用自动退回内存索引。
- **任务可观测性**：`/tasks/{task_id}` + `/logs/{task_id}`/`/logs/tail` 暴露细粒度状态，Gradio UI 通过轮询展示实时日志。
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
| MinIO | 可选对象存储，用于同步 `data/` 目录的原始/中间/最终产物 |

## 项目结构

```
app/
  config.py              # 全局配置、数据路径、ES/阿里百炼参数
  logging_utils.py       # 统一日志初始化
  models/mm_schema.py    # 与 mm-schema.json 对齐的 Pydantic 模型
  pipeline/ingest.py     # 主处理入口（抽帧、ASR、分块、入 ES）
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
- `data/final_instances/`：最终符合 `mm-schema.json` 的 JSON，便于审计或重放。
- `data/logs/pipeline.log`：后端统一日志源，供 `/logs/*` 接口与 UI 读取。

## 环境准备

1. Python 3.10+，推荐虚拟环境：
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
2. 系统需安装 FFmpeg，并准备 GPU/CPU 以运行 Whisper（可按需替换为自建 ASR）。
3. 若需对接 DashScope/阿里百炼，请在 `.env` 中配置密钥及模型名称。

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

BAILIAN_API_KEY=sk-xxxx
BAILIAN_BASE_URL=https://dashscope.aliyuncs.com
BAILIAN_ASR_MODEL=paraformer-v1
BAILIAN_EMBEDDING_MODEL=text-embedding-v1
BAILIAN_MULTIMODAL_MODEL=qwen-vl-plus
BAILIAN_LLM_MODEL=qwen3

LOG_LEVEL=INFO

# 可选 MinIO 同步
MINIO_ENABLED=false
MINIO_ENDPOINT=http://localhost:9000
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
MINIO_BUCKET=mm-rag
```

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
```

### Gradio 控制台

```bash
API_BASE_URL=http://localhost:8000 .venv/bin/python ui/gradio_app.py
```

- **上传处理** 页签：上传音/视频、选择抽帧策略（`interval`/`scene`）、查看任务状态与实时日志。
- **混合检索** 页签：输入查询后由 Chatbot 返回命中段落，同时展示首个命中的视频、音频、关键帧画廊，便于复核。
- UI 默认每 2 秒轮询 `/tasks/{task_id}` 与 `/logs/{task_id}`，若任务专属日志缺失则自动降级到 `/logs/tail`。

## API 与日志

- `POST /ingest`：基于绝对路径触发处理。
- `POST /ingest/upload`：上传媒体并附带 `metadata` / `processing_options` JSON。
- `GET /tasks/{task_id}`：查询任务状态与最终 `mm-schema` 结果。
- `GET /logs/{task_id}`：返回包含 `task_id` 的最新日志片段。
- `GET /logs/tail`：全局日志尾部（默认 200 行），供 UI 回退或手动排障。
- `POST /query`：`{"query": "关键词", "top_k": 5}` 返回带 `thumbnail`/`audio_path`/`video_path` 的命中分块。
- `GET /health`：基础探活。

## MinIO 同步说明

- 设置 `MINIO_ENABLED=true` 且提供 `MINIO_ENDPOINT`、`MINIO_ACCESS_KEY`、`MINIO_SECRET_KEY`、`MINIO_BUCKET` 后，`app/services/storage.py` 会在以下场景同步文件到 MinIO：
  - `save_raw_upload` / `save_raw_path`：原始媒体副本 (`data/raw/`).
  - `persist_intermediate`：所有 `data/intermediate/...` 产物，如 `audio/<doc>.wav`、`video/<doc>/frame_XXXX.jpg`。
  - `persist_json`：最终 `data/final_instances/*.json`。
- 同步路径默认复用 `data/` 下的相对结构，例如 `data/intermediate/audio/foo.wav` 会写成对象 `intermediate/audio/foo.wav`。
- 处理完成后可在 MinIO 控制台检索 `intermediate/audio/` 与 `intermediate/video/` 前缀，确认音频与关键帧已经上传。
- MinIO 端可使用 `MINIO_OPTS="--address :9000 --console-address :9001"` 等参数启动，默认账号/密码为 `minioadmin/minioadmin`。

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
| v0.1.0 | 2025-11-28 | 首次公开版本：包含 FastAPI + Gradio、MinIO 同步、启动脚本与任务/日志 API。 | [源代码包](https://github.com/shark8848/mm-rag/archive/refs/tags/v0.1.0.zip) |

更多细节参见 `CHANGELOG.md`，新的标签发布后可在 [Releases 页面](https://github.com/shark8848/mm-rag/releases) 下载对应包。
