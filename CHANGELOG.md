# 变更日志

## [Unreleased]

- 引入 Celery + Redis 队列，将流水线拆分为 `build_metadata`/`generate_chunks`/`generate_summary`/`persist_artifacts`/`index_document` 五个原子任务。
- FastAPI `/ingest` 统一交给 Celery workflow，`/tasks/{id}` 根据 Celery 状态返回结果。
- README/.env.example 补充 Redis/Celery 部署指引。
- `start_server.sh` / `stop_server.sh` 自动管理 Celery CPU/IO worker，可通过 `START_CELERY=false` 或 `STOP_CELERY=false` 关闭自动化。
- `start_server.sh` / `stop_server.sh` 支持参数化启动（如 `./start_server.sh gradio`/`flower`），默认仍会拉起全部服务。
- 新增 Flower 依赖与使用说明，可通过 `celery flower` 实时监控任务与 worker 健康。
- Flower 启动脚本支持 `FLOWER_HEALTH_RETRIES`、`FLOWER_STRICT`，默认仅警告健康检查失败，避免影响其他服务。

## v0.1.0 · 2025-11-28

- 首次开源发布，包含 FastAPI 后端与 Gradio 控制台。
- 新增 `start_server.sh` / `stop_server.sh`，一键管理 FastAPI + Gradio 进程，并自动做健康检查。
- 音频抽取、关键帧 JPEG 与最终 JSON 自动同步到 MinIO，方便对象存储对接。
- 任务状态在 `/tasks/{task_id}` 中实时查询，并提供 `/logs/{task_id}`、`/logs/tail` 用于排障。
- README 更新了部署指南与 MinIO 配置说明。
