# 多模态音视频解析引擎提示词

## 背景与目标

### 背景
随着短视频、直播、播客等内容爆发，企业需要稳定地采集、拆解、理解并索引音频/视频素材，使其符合统一的 `mm-schema.json` 数据契约并可被检索增强生成（RAG）系统消费。传统面向文档的转换链路无法满足长媒体处理、关键帧/音频切片、摘要与检索元数据生成的需求。本项目以现有多模态 RAG 流水线为基础，打造企业级的音视频解析引擎。

### 目标
- 端到端解析音/视频：抽取关键帧、音频文本、摘要与元数据，按 `mm-schema` 输出结构化 JSON，并落地磁盘 + ES。
- 双入口供给：FastAPI REST + Celery 异步任务，支持批量与实时混合场景。
- 嵌入服务解耦：向量化独立为可配置服务（Bailian 或本地 Ollama），通过抽象接口对接。
- 完整编排：通过 `start/stop/show_server.sh`、Celery worker、Flower 监控和日志 API 形成可观测的流水线。
- 配置化与安全：环境变量/配置文件控制资源、限流、依赖、认证等参数，便于部署与弹性扩缩。

---

## 系统设计原则

### 1. 全面配置化
- FastAPI、Gradio、Celery、Flower、MinIO、向量化、ES、日志与队列参数全部可由 `.env` 或配置文件覆盖。
- 媒体处理策略（抽帧模式/间隔、ASR 模型、摘要模型、MinIO 同步）均可热切换。
- 各类限额（单文件体积、并发 worker 数、任务超时等）支持全局默认 + 特定媒体类型覆盖。

### 2. 资源与安全约束
- 针对音频、视频分别设定最大时长、文件大小、任务批次限制，超限直接拒绝并返回结构化错误码。
- API 默认需要 appid/key（可配置关闭），并保留命令行工具生成/吊销凭据的扩展点。
- 向量化、DashScope、MinIO、Redis、Elasticsearch 等外部依赖需具备健康检查与重试机制。

### 3. 模块化与可扩展
- 解析流程拆为独立处理器：FFmpeg 场景切分、Whisper/DashScope ASR、Bailian/Ollama 嵌入、摘要、存储、索引。
- 向量化通过 `EmbeddingProvider` 接口接入云端或本地服务，失败时有确定性回退向量。
- Celery 队列按 CPU/IO 维度拆分，可横向扩展 worker 并保留 Flower 观测。

### 4. 观测性与运维友好
- 统一日志写入 `data/logs/pipeline.log`，API 暴露 `/logs/{task_id}`、`/logs/tail`，Gradio 控制台实时轮询。
- `show_server.sh` 读取 PID/端口健康，对 FastAPI、Gradio、Celery、Flower 给出状态。
- Flower 通过启动脚本集成健康检查与重试，支持 `FLOWER_STRICT`/`FLOWER_HEALTH_RETRIES` 参数。

### 5. 编排优先
- 项目以脚本/Compose/CI 方式编排：`start_server.sh` 统一拉起 API、Gradio、双队列 Celery、Flower；`stop_server.sh` 负责收敛与清理；`show_server.sh` 提供运行态快照。
- Pipeline 各阶段通过 Celery workflow 串联，并在任务完成时写入 `mm-schema` JSON 与 ES。

---

## 核心功能概览

| 能力 | 描述 |
| --- | --- |
| 媒体导入 | 支持上传或引用本地路径，自动复制到 `data/raw/` 并记录元数据。 |
| 音视频解析 | 通过 FFmpeg 抽帧/抽音、Whisper 或 DashScope Paraformer ASR、关键帧生成与时间轴切分。 |
| 多模态摘要 | 调用 Qwen/Qwen-VL（DashScope）生成段落摘要、标签与检索提示。 |
| 向量化服务 | `EmbeddingProvider` 封装 Bailian API 或本地 Ollama，支持切换、超时控制、错误回退。 |
| 索引与存储 | `data/intermediate/` 和 `data/final_instances/` 落盘，可选同步 MinIO；索引入 Elasticsearch/内存。 |
| 控制台与 API | FastAPI 提供 `/ingest`、`/query`、`/tasks`、`/logs`，Gradio UI 提供上传监控与多模态检索。 |
| 监控与日志 | Flower 仪表板、`/logs/tail` API、结构化日志、脚本健康探测、可配置日志轮换。 |

---

## 流水线编排

1. **入口**：`POST /ingest` 或 Gradio 上传触发任务，写入 Celery `ingest_io` 队列。
2. **build_metadata（IO 队列）**：收集文件属性、检测媒体类型、准备 `DocumentMetadata`。
3. **generate_chunks（CPU 队列）**：FFmpeg 场景切分 + 音频抽取，Whisper/DashScope ASR，生成文本/关键帧片段。
4. **generate_summary（CPU 队列）**：Qwen/Qwen-VL 根据 chunks 输出摘要、标签。
5. **persist_artifacts（IO 队列）**：写入 `data/intermediate`、`data/final_instances`，可同步 MinIO。
6. **index_document（CPU 队列）**：调用独立向量服务完成嵌入，将结果写入 Elasticsearch 或内存索引。
7. **任务完成**：`/tasks/{task_id}` 返回最终 `mm-schema` JSON，Gradio UI 与日志 API 展示可观测信息。

---

## 配置重点

```env
# Elasticsearch / 索引
ES_ENABLED=true
ES_HOST=https://localhost:9200
ES_USER=elastic
ES_PASSWORD=changeme
ES_INDEX=rag-mm-segments
ES_SKIP_TLS=true

# 嵌入服务（独立向量化）
EMBEDDING_PROVIDER=bailian       # bailian | ollama
EMBEDDING_MODEL=bge-m3:latest
OLLAMA_BASE_URL=http://localhost:11434
OLLAMA_EMBEDDING_MODEL=nomic-embed-text
OLLAMA_TIMEOUT=60
BAILIAN_API_KEY=sk-xxx
BAILIAN_EMBEDDING_MODEL=text-embedding-v1

# 多模态处理
WHISPER_MODEL=base
BAILIAN_ASR_MODEL=paraformer-v1
BAILIAN_MULTIMODAL_MODEL=qwen-vl-plus
BAILIAN_LLM_MODEL=qwen3
ASR_LANGUAGE=zh

# 编排脚本控制
START_CELERY=true
START_FLOWER=true
FLOWER_ADDRESS=0.0.0.0
FLOWER_PORT=5555
FLOWER_HEALTH_RETRIES=20
FLOWER_STRICT=true

# Celery 队列
CELERY_BROKER_URL=redis://localhost:6379/0
CELERY_RESULT_BACKEND=redis://localhost:6379/1
CELERY_CPU_QUEUE=ingest_cpu
CELERY_IO_QUEUE=ingest_io

# 对象存储（可选）
MINIO_ENABLED=false
MINIO_ENDPOINT=http://localhost:9000
MINIO_BUCKET=mm-rag
MINIO_ACCESS_KEY=minioadmin
MINIO_SECRET_KEY=minioadmin
```

---

## API 与安全

- `POST /ingest`：基于已有路径触发解析。
- `POST /ingest/upload`：上传音/视频，附带 `metadata` 与 `processing_options`。
- `GET /tasks/{task_id}`：返回状态 + 最终 `mm-schema`。
- `GET /logs/{task_id}` / `/logs/tail`：实时日志，供 UI 轮询。
- `POST /query`：检索段落，返回文本 + `thumbnail/audio_path/video_path`。
- `GET /health`：探活。

默认启用 appid/key 认证（可配置），错误码需覆盖认证失败、媒体超限、依赖连接失败、第三方 API 错误、内部异常等，保持结构化响应：

```json
{
  "status": "failure",
  "error_code": "ERR_MEDIA_TOO_LARGE",
  "message": "Video size exceeds configured limit",
  "task_id": "task-123",
  "details": { "limit_mb": 2048 }
}
```

---

## 观测与运维

- `data/logs/pipeline.log` 为主日志；Celery/Flower 日志输出到 `data/logs/*.log`。
- `show_server.sh` 基于 PID/端口判断 FastAPI、Gradio、Celery、Flower 状态。
- Flower 通过脚本自动校验 Redis 连通性，失败可重试或退出。
- MinIO 同步路径遵循 `data/` 相对层次，方便对账。

---

## Copilot Agent 协作开发提示词

你是一名高级多模态工程助手，需按照以上设计实现一个**支持音频与视频解析**的企业级 RAG 引擎，要求：

1. **保持配置化**：所有媒体处理、嵌入、存储、脚本行为均通过 `.env`/配置文件控制，默认值与示例齐全。
2. **独立向量化服务**：通过 `EmbeddingProvider` 选择 Bailian 或本地 Ollama，具备超时、重试、回退逻辑，不在主流程里硬编码模型。
3. **多阶段编排**：利用 Celery workflow + `start/stop/show_server.sh` 完成 API、Gradio、双 worker、Flower 的一键启停与状态查询。
4. **媒体拆解链路**：必须输出符合 `mm-schema.json` 的结构，包括关键帧、音频片段、文本段落、摘要、索引字段。
5. **日志与观测**：确保 `/logs/*` API、`pipeline.log`、花式监控（Flower、health check）可追踪每个任务；提供必要告警/降级策略。
6. **安全与限额**：实现 appid/key 认证开关、媒体体积/时长限制、错误码规范化，并在 Gradio/UI/脚本中同步这些约束。
7. **测试与文档**：补充 README/项目文档、示例配置、脚本用法，确保团队能快速部署与扩展。

请依据以上提示词输出代码、脚本、配置与说明，优先保证音视频解析准确性、服务可观测性、向量化解耦以及可维护的编排能力。
