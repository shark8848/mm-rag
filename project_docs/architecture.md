# 多模态音视频解析引擎架构设计

> 对应阶段：重新设计解析流程 / API / 向量服务的第 1 阶段产出。后续阶段会基于本设计逐步实现。

## 1. 架构分层

```
app/
  api/                 # FastAPI 路由层、响应封装、认证依赖
  core/                # 错误码、认证、限额、追踪等横切能力
  pipeline/
    stages/            # Celery workflow 每个阶段的可插拔实现
    celery_tasks.py    # 通过 Chain/Chord 编排 stages
  services/
    asr.py             # Bailian/Whisper ASR
    embedding_provider.py  # 将迁移为 VectorService
    storage.py         # MinIO/磁盘存储
    ...
```

- **API 层**：负责 appid/key 校验、限额、请求追踪、错误码响应，暴露 `/ingest`、`/ingest/upload`、`/query`、`/logs/*`、`/metrics` 等接口。
- **Core 横切**：`ErrorCode`、`APIError`、`AuthManager`、`LimitChecker`、`RequestContext`，供 API 与 Pipeline 共用。
- **Pipeline stages**：拆解为 `validate_input` → `build_metadata` → `generate_chunks` → `generate_summary` → `vector_enrichment` → `persist_artifacts` → `index_document`，每个 stage 单独封装队列、指标、重试策略。
- **服务层**：ASR、关键帧理解、向量服务、存储、搜索，均通过依赖注入以便替换和测试。

## 2. 请求/任务链路

1. **入口**：FastAPI 对请求进行认证、限额、追踪 ID 打点，写入 `task_store` 并 copy 文件到 `data/raw/`。
2. **Celery workflow**：
   - `ValidationStage`：检查文件大小/批次/时长等策略。
   - `MetadataStage`：生成 `DocumentMetadata`、source info。
   - `ChunkStage`（沿用 `build_audio_chunks`/`build_video_chunks`）。
   - `SummaryStage`：依赖 Bailian/Qwen 生成摘要或 fallback。
   - `VectorStage`：调用独立向量服务补齐 chunk/keyframe 向量。
   - `PersistStage`：写入 `data/final_instances/`、MinIO。
   - `IndexStage`：落 ES 或内存索引。
3. **可观测性**：`app/core/tracking.py` 记录 request/task ID；日志写入 `pipeline.log`；后续阶段会加入 Prometheus 指标与 Flower 观测。

## 3. 认证与限额

- `AuthManager`：默认要求客户端在每个请求头里携带 `X-Appid`、`X-Key`，并与 `app_secrets_path`（JSON 列表 `[{"app_id": ..., "app_key": ...}]`）对照，可通过 `CredentialStore` 签发/吊销。
- `LimitChecker`：支持默认/按媒体类型的大小、时长、批次限制，超限抛 `APIError(ERR_MEDIA_TOO_LARGE)`。
- `APIError` → `ErrorEnvelope`：所有异常都以统一 JSON 返回（`status/error_code/error_status/message/zh_message/context`），方便 Gradio、CLI 或第三方客户端解析。

## 4. 向量服务抽象

- `embedding_provider.py` 将演进为 `VectorService`：支持 Bailian、Ollama、未来的托管服务，通过配置选择，具备重试和确定性 fallback。
- Pipeline `VectorStage` 将仅依赖该服务，避免在其他模块重复嵌入逻辑。

## 5. 后续阶段计划

| 阶段 | 目标 | 主要改动 |
| --- | --- | --- |
| 1 | 定义架构 & 基础模块 | ✔️ 完成 core/api/stage skeleton 与设计文档 |
| 2 | 底层服务改造 | ✔️ VectorService 替换旧 embedding client，ASR/关键帧/MinIO 增加计时日志 |
| 3 | API & 脚本实现 | FastAPI 路由拆分、认证限额接入、启动脚本重写、`show_server` 健康检查 |
| 4 | Pipeline/Celery 重构 | stage 组合、重试策略、指标、向量服务全面接入 |
| 5 | UI & 文档 | Gradio UI 更新、README/CHANGELOG/配置样例同步 |

## 阶段 2 更新摘要

- 新的 `VectorService`（`app/services/vector_service.py`）统一管理 Bailian/Ollama 向量化，提供重试、确定性回退与健康快照；旧 `embedding_provider` 退化为兼容层。
- 音视频处理模块现统一调用 `vector_service`，并把模型名称/维度写入 Chunk 元数据。
- ASR 与关键帧描述流程加入 `log_timing`，便于监控 Bailian/Whisper 及图像理解耗时；MinIO 同步在禁用时记录调试日志。
- 这些改动为后续 Pipeline 阶段和 API 层提供可观测的、可配置的底层能力。

本设计文档会在后续阶段更新，以记录新组件的契约和依赖。