# MinerU Artifacts 传递问题诊断与修复

## 问题现象
Gradio UI 显示"未找到 MinerU 数据"，即使 Celery 日志显示解析成功且 bundle ZIP 文件存在。

## 根本原因

### 1. **Artifacts 存储在 Context 顶层，未被包含在 Document payload 中**
   - `build_pdf_chunks` 正确返回 `(chunks, extras)`，extras 包含 artifacts
   - `ChunkStage.run` 正确将 extras 写入 `context["artifacts"]`
   - **BUT**: `build_document_payload` 只序列化 `Document` schema，不包含 context 的 extras/artifacts

### 2. **TaskStore.get() 提取逻辑过于简单**
   - 旧代码: `record.result = payload.get("document") or payload`
   - 这会丢失 context 中的所有非 Document 字段（artifacts、parser、mineru_endpoint 等）

### 3. **API 响应结构不一致**
   - 旧任务: `result.artifacts` (context 顶层)
   - 新任务: 应该是 `result.extras.artifacts` (符合 schema)
   - Gradio 只检查 `task.extras.artifacts`，漏检了 `result.artifacts`

## 文件位置验证

```bash
# 实际文件确实存在
$ ls -lh data/intermediate/mineru_bundle/84debcaf-44bd-4685-a4e7-a6d1c1ae9bac.zip
-rw-r--r-- 1 root root 1.9M Dec  6 19:58 ...

# Celery result 包含正确路径
$ python -c "from celery.result import AsyncResult; ..."
mineru_bundle_path (direct): /home/mm-rag/data/intermediate/mineru_bundle/84debcaf-44bd-4685-a4e7-a6d1c1ae9bac.zip
```

## 修复方案

### 修复 1: 保留 context extras/artifacts 在最终 payload 中
**文件**: `app/pipeline/stages/utils.py`

```python
def build_document_payload(context: Context) -> Dict[str, Any]:
    # ... 原有 Document 序列化代码 ...
    payload = document.model_dump(mode="json")
    
    # 新增: 保留 extras 和 artifacts
    if "extras" in context:
        payload["extras"] = context["extras"]
    if "artifacts" in context:
        payload.setdefault("extras", {})["artifacts"] = context["artifacts"]
    return payload
```

### 修复 2: TaskStore 返回完整 context
**文件**: `app/tasks.py`

```python
elif async_result.successful():
    payload = async_result.result or {}
    # 新增: 保留完整 payload 而不只是 document
    if isinstance(payload, dict):
        record.result = payload
    else:
        record.result = {"data": payload}
```

### 修复 3: Gradio UI 兼容多种 artifacts 结构
**文件**: `ui/gradio_app.py`

```python
def render_pdf_page(task_id, page_num):
    result = task.get("result") or {}
    
    # 优先级1: result.extras.artifacts (新结构)
    extras = result.get("extras") or {}
    artifacts = extras.get("artifacts") or {}
    
    # 优先级2: result.artifacts (context 顶层)
    if not artifacts:
        artifacts = result.get("artifacts") or {}
    
    # 优先级3: task.extras.artifacts (旧 API 结构)
    if not artifacts:
        task_extras = task.get("extras") or {}
        artifacts = task_extras.get("artifacts") or {}
    
    bundle_path = artifacts.get("mineru_bundle_path") or artifacts.get("mineru_zip_path")
```

### 修复 4: 增强日志记录
**多处新增日志**:
- `ChunkStage`: 记录收到和存储的 artifacts 键
- `mineru.py`: 记录生成的所有 artifact 路径
- `render_pdf_page`: 在找不到数据时输出详细调试信息

## 验证步骤

### 1. 重启服务应用新代码
```bash
./stop_server.sh
./start_server.sh
```

### 2. 提交新的 PDF 任务
通过 Gradio UI 或 API 上传 PDF，观察日志：

```bash
tail -f logs/celery_worker.log | grep -E "artifacts|MinerU"
```

预期日志:
```
INFO MinerU artifacts ready for document xxx: mineru_zip_path=xxx.zip, mineru_bundle_path=xxx.zip, ...
INFO ChunkStage received artifacts: ['mineru_zip_path', 'mineru_asset_dir', ...]
INFO ChunkStage context now has artifacts: ['mineru_zip_path', 'mineru_asset_dir', ...]
```

### 3. 检查 API 响应
```bash
curl http://localhost:8000/tasks/{task_id} | python -m json.tool | grep -A 20 artifacts
```

预期结构（新任务）:
```json
{
  "result": {
    "document_id": "...",
    "chunks": [...],
    "extras": {
      "artifacts": {
        "mineru_bundle_path": "/home/mm-rag/data/intermediate/mineru_bundle/xxx.zip",
        "mineru_zip_path": "...",
        "mineru_asset_dir": "...",
        ...
      }
    }
  }
}
```

或（旧任务兼容）:
```json
{
  "result": {
    "artifacts": {
      "mineru_bundle_path": "..."
    }
  }
}
```

### 4. 验证 Gradio 预览
- 打开 http://localhost:7860
- 上传 PDF 并等待解析完成
- 切换到"PDF 管道"标签
- 使用页码滑块测试分页预览
- 应显示 PDF 页面 + 坐标框覆盖层

## 影响范围

### 已修复的文件
1. `app/pipeline/stages/utils.py` - 保留 context extras
2. `app/tasks.py` - 返回完整 result
3. `ui/gradio_app.py` - 兼容多种结构 + 详细错误信息
4. `app/pipeline/stages/chunks.py` - 增强日志
5. `app/services/pdf_parsers/mineru.py` - 增强日志

### 向后兼容性
✅ 旧任务（`result.artifacts`）仍能正常读取  
✅ 新任务（`result.extras.artifacts`）符合规范  
✅ Gradio UI 同时支持两种结构

### 不影响
- 音频/视频处理流程
- 向量化和检索功能
- MinIO 同步逻辑

## 注意事项

1. **重启服务后才生效**: 需要重启 Celery worker 和 FastAPI 使新代码生效
2. **旧任务数据不变**: 已完成的任务不会重新处理，但 UI 能正确读取
3. **日志位置**: 关键日志在 `logs/celery_worker.log`，搜索 "artifacts" 关键字
4. **文件权限**: bundle ZIP 由 Celery worker (可能是 root) 创建，确保 Gradio 进程有读权限

## 后续优化建议

1. **统一 result 结构**: 定义明确的 `TaskResult` schema 包含 document + extras + artifacts
2. **添加 E2E 测试**: 覆盖 PDF 上传 → 解析 → API 查询 → Gradio 渲染全链路
3. **监控 artifacts 丢失**: 在 API 中添加健康检查，验证关键文件路径存在
4. **文档补充**: 在 README 中说明 artifacts 的存储和访问机制
