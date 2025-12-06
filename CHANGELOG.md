# 变更日志

## [Unreleased]

- 尚未发布的改动。

## v0.3.0 · 2025-12-06

- Stage 4：将流水线拆分为 `Validation`/`Metadata`/`Chunk`/`Summary`/`Vector`/`Persist`/`Index` 七个 Celery 阶段，统一放在 `app/pipeline/stages/*` 并通过 `celery_tasks.py` 串联，同时把阶段指标与落盘信息写回 `TaskResponse`。
- Celery worker 启动时即完成 Stage4 任务注册，避免 `Received unregistered task`，并确保 `pipeline.vector_enrichment`、`pipeline.validate_input` 等新任务按队列路由执行。
- README 新增 Stage4 验证示例与队列说明，帮助在本地通过 `./start_server.sh api|celery` + `/ingest` 快速完成端到端验证。
- Stage 3：FastAPI 路由拆分为 `app/api/routes_*` 并接入统一的认证、限额、请求追踪与 `ErrorEnvelope` 处理，`main.py` 仅负责挂载路由和中间件。
- 全局文档与 `.env` 模板新增 `API_AUTH_REQUIRED`、`API_SECRETS_PATH`、媒体大小/批量限制等配置说明，示例中给出 `X-Appid` / `X-Key` 头部与错误包络。
- Gradio 控制台读取 `API_APP_ID`、`API_APP_KEY` 环境变量，为所有请求附带认证头并在 401/429 时给出指引，便于接入受保护的 API。
- `start_server.sh` 启动后会提示当前认证配置并调用 `show_server.sh`；`show_server.sh` 新增 FastAPI/Gradio/Flower HTTP 健康列，方便排障。
- 引入 Celery + Redis 队列，将流水线拆分为 `build_metadata`/`generate_chunks`/`generate_summary`/`persist_artifacts`/`index_document` 五个原子任务。
- FastAPI `/ingest` 统一交给 Celery workflow，`/tasks/{id}` 根据 Celery 状态返回结果。
- README/.env.example 补充 Redis/Celery 部署指引。
- `start_server.sh` / `stop_server.sh` 自动管理 Celery CPU/IO worker，可通过 `START_CELERY=false` 或 `STOP_CELERY=false` 关闭自动化。
- `start_server.sh` / `stop_server.sh` 支持参数化启动（如 `./start_server.sh gradio`/`flower`），默认仍会拉起全部服务。
- 新增 Flower 依赖与使用说明，可通过 `celery flower` 实时监控任务与 worker 健康。
- Flower 启动脚本支持 `FLOWER_ADDRESS`、`FLOWER_PORT`、`FLOWER_HEALTH_RETRIES`、`FLOWER_STRICT`，默认仅警告健康检查失败，避免影响其他服务。

## v0.1.0 · 2025-11-28

- 首次开源发布，包含 FastAPI 后端与 Gradio 控制台。
- 新增 `start_server.sh` / `stop_server.sh`，一键管理 FastAPI + Gradio 进程，并自动做健康检查。
- 音频抽取、关键帧 JPEG 与最终 JSON 自动同步到 MinIO，方便对象存储对接。
- 任务状态在 `/tasks/{task_id}` 中实时查询，并提供 `/logs/{task_id}`、`/logs/tail` 用于排障。
- README 更新了部署指南与 MinIO 配置说明。
