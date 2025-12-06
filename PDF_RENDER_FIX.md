# PDF 渲染问题修复

## 问题描述

1. **PDF 预览区域自动刷新**：`pdf_poll_timer` 每 2.5 秒刷新一次，覆盖了 MinerU 分页预览内容
2. **组件冲突**：Timer 更新 `pdf_preview_panel`，而 slider 更新 `mineru_pdf_viewer`，导致显示错乱
3. **Slider 最大值固定**：固定为 100，无法动态适应实际文档页数

## 修复方案

### 1. 分离轮询目标
**修改前**：`pdf_poll_timer` 更新 7 个输出，包括 `pdf_preview_panel`  
**修改后**：创建 `_poll_pdf_status_only`，只更新状态、日志、Markdown，不触碰预览区域

```python
def _poll_pdf_status_only(task_id: str):
    """只轮询状态和日志，不更新预览区域"""
    status_line, result_block, log_text, _preview, extras = _poll_task_core(task_id)
    return (
        status_line,
        result_block,
        log_text,
        extras.get("md_render") or "",
        extras.get("md_text") or "",
        extras.get("bundle_path"),
    )
```

### 2. 动态更新 Slider 范围
**修改前**：Slider maximum=100 固定  
**修改后**：每次渲染时根据实际总页数动态更新

```python
def _update_page_view(task_id: str, page_num: int):
    pdf_html, overlay_html, current, total = render_pdf_page(task_id, int(page_num))
    info_text = f"第 {current} / {total} 页"
    # 动态更新 slider 最大值
    slider_update = gr.Slider(value=current, maximum=max(total, 1), minimum=1)
    return pdf_html, overlay_html, slider_update, info_text
```

### 3. 智能初始化预览
**新增功能**：任务成功完成后自动加载第一页

```python
def _init_mineru_preview(status: str, task_id: str):
    """任务成功完成后才初始化预览"""
    if not task_id or "success" not in status.lower():
        return (placeholder, "", gr.Slider(value=1, maximum=100), "第 1 / 1 页")
    # 渲染第一页并设置正确的 slider 范围
    pdf_html, overlay_html, current, total = render_pdf_page(task_id, 1)
    slider_update = gr.Slider(value=current, maximum=max(total, 1), minimum=1)
    return pdf_html, overlay_html, slider_update, f"第 {current} / {total} 页"

# 监听状态面板变化
pdf_status_panel.change(
    fn=_init_mineru_preview,
    inputs=[pdf_status_panel, pdf_task_state],
    outputs=[mineru_pdf_viewer, mineru_overlay_viewer, mineru_page_slider, mineru_page_info],
)
```

### 4. 增加用户提示
在 MinerU 分页预览区域添加说明文字：

```markdown
### MinerU 分页预览
*使用下方滑块浏览单页 + 坐标框叠加层*
```

## 修复效果

### Before
- ❌ 每 2.5 秒刷新一次，导致用户操作被打断
- ❌ Slider 拖动后立即被 timer 覆盖回原始状态
- ❌ Slider 最大值 100，无法浏览超过 100 页的文档
- ❌ 任务完成后需要手动拖动 slider 才能看到预览

### After
- ✅ 只更新状态和日志，不干扰预览区域
- ✅ Slider 操作流畅，实时响应用户输入
- ✅ Slider 范围自动适应实际页数（如 43 页文档最大值为 43）
- ✅ 任务成功后自动显示第一页预览
- ✅ 每次翻页时确保 slider 范围正确

## 技术细节

### 组件职责分离

| 组件 | 更新方式 | 更新频率 | 更新内容 |
|------|---------|---------|---------|
| `pdf_preview_panel` | 不再更新 | - | 保留用于未来全文档预览（已弃用） |
| `mineru_pdf_viewer` | slider.change | 用户操作时 | 单页 PDF + 坐标框 |
| `mineru_page_slider` | 动态返回 | 渲染时更新 | 当前页码 + 最大页数 |
| `pdf_status_panel` | Timer 轮询 | 每 3 秒 | 任务状态文本 |
| `pdf_log_panel` | Timer 轮询 | 每 3 秒 | Celery 日志 |

### 状态流转

```
1. 用户上传 PDF → pdf_task_state 赋值
2. Timer 开始轮询 → 更新 pdf_status_panel
3. 状态变为 "success" → 触发 _init_mineru_preview
4. 加载第一页 → 设置 slider 范围为 1-43
5. 用户拖动 slider → 触发 _update_page_view
6. 渲染新页面 → 同时更新 slider 确保范围一致
```

## 验证步骤

### 1. 重启 Gradio UI
```bash
cd /home/mm-rag
pkill -f gradio_app.py
nohup .venv/bin/python ui/gradio_app.py > logs/gradio.log 2>&1 &
```

### 2. 测试流程
1. 访问 http://localhost:7860
2. 切换到"PDF 管道"标签
3. 上传 PDF 文件（建议使用 43 页的测试文档）
4. 观察状态面板更新（不应影响预览区域）
5. 等待状态变为"success"
6. 检查是否自动显示第一页预览
7. 拖动页码 slider（1-43），观察：
   - 预览区域实时更新
   - 坐标框正确渲染
   - Slider 不会被 timer 重置
8. 快速拖动 slider，确认响应流畅

### 3. 预期结果
- ✅ 状态面板每 3 秒更新一次
- ✅ 预览区域只在 slider 变化时更新
- ✅ Slider 最大值显示实际页数（如 43）
- ✅ 页码信息正确显示"第 X / 43 页"
- ✅ 拖动 slider 流畅无卡顿

## 回滚方案

如果出现问题，可以快速回滚：

```bash
cd /home/mm-rag
git diff ui/gradio_app.py  # 查看更改
git checkout ui/gradio_app.py  # 恢复原始版本
pkill -f gradio_app.py
nohup .venv/bin/python ui/gradio_app.py > logs/gradio.log 2>&1 &
```

## 相关文件

- `ui/gradio_app.py` - 主要修改文件
- `MINERU_ARTIFACTS_FIX.md` - 相关的 artifacts 传递修复
- `logs/gradio.log` - Gradio 运行日志

## 注意事项

1. **首次加载可能较慢**：bundle ZIP 需要解压和缓存
2. **大文档内存占用**：PDF base64 编码会占用浏览器内存
3. **坐标框精度**：依赖 middle.json 中的 bbox 数据质量
4. **浏览器兼容性**：建议使用 Chrome/Edge 测试 PDF iframe 渲染

## 后续优化建议

1. **懒加载**：只在需要时加载 PDF 页面，避免一次性加载全部
2. **缓存策略**：缓存最近浏览的页面，减少重复渲染
3. **预加载**：预加载当前页的前后页，提升翻页体验
4. **错误重试**：网络失败时自动重试渲染
5. **键盘快捷键**：支持 ← → 键翻页
