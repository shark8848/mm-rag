# MinerU Bbox 渲染实现说明

## 概述

已成功实现 MinerU 官方 demo 的 PDF bbox 渲染功能，可在 Gradio 界面中显示带有彩色边界框标注的 PDF 预览。

## 核心功能

### 1. Bbox 绘制模块 (`app/utils/draw_bbox.py`)

基于 MinerU 官方 `draw_bbox.py` 实现，支持：

- **单页 PDF 标注生成**: `draw_layout_bbox_on_single_page()`
- **坐标转换**: `cal_canvas_rect()` - 处理 PDF 页面旋转
- **多种块类型识别**，使用不同颜色标注：
  - 📊 表格 (table_body): 黄色 `[204, 204, 0]`
  - 📑 表格标题 (table_caption): 浅黄 `[255, 255, 102]`
  - 📄 表格脚注 (table_footnote): 淡绿 `[229, 255, 204]`
  - 🖼️ 图片 (image_body): 绿色 `[153, 255, 51]`
  - 🏷️ 图片标题 (image_caption): 蓝色 `[102, 178, 255]`
  - 📝 图片脚注 (image_footnote): 橙色 `[255, 178, 102]`
  - 🔵 标题 (title): 深蓝 `[102, 102, 255]`
  - 🟣 文本 (text): 紫色 `[153, 0, 76]`
  - 🟢 公式 (equation): 绿色 `[0, 255, 0]`
  - 📋 列表 (list): 深绿 `[40, 169, 92]`
- **阅读顺序编号**: 红色数字显示块的阅读顺序

### 2. Gradio UI 集成 (`ui/gradio_app.py`)

**核心修改**:

```python
def render_pdf_page(task_id: str, page_num: int):
    """
    生成带 bbox 标注的 PDF 预览
    
    流程:
    1. 从 API 获取任务结果
    2. 提取 artifacts 中的 middle.json 和原始 PDF
    3. 解析 pdf_info 获取指定页的 para_blocks
    4. 调用 draw_layout_bbox_on_single_page() 生成标注 PDF
    5. 返回标注 PDF 路径给 PDF 组件显示
    """
```

**特性**:
- 使用 `gradio-pdf` 包的 `PDF` 组件显示
- 支持分页浏览（滑块切换页码）
- 显示元素统计信息（标题、文本、表格、图片等数量）
- 懒加载机制（点击"加载分页预览"按钮触发）

### 3. 数据流

```
用户上传 PDF 
  → FastAPI 调用 MinerU API 解析
  → 生成 middle.json (包含 pdf_info with bbox 数据)
  → 打包成 mineru_bundle.zip
  → 存储 artifacts (middle.json, images, markdown)
  → Gradio 加载预览时:
     → 读取 middle.json 的 pdf_info
     → 提取指定页的 para_blocks
     → 使用 reportlab 在原始 PDF 上绘制彩色 bbox
     → 使用 pypdf 合并覆盖层
     → 生成 {task_id}_page{N}_layout.pdf
     → PDF 组件显示标注后的 PDF
```

## 依赖项

```bash
pip install pypdf reportlab gradio-pdf
```

## 测试验证

### 测试脚本: `test_bbox_render.py`

```bash
python test_bbox_render.py
```

**测试结果**:
```
✅ Found middle.json
✅ PDF has 4 pages
✅ Page 1 has 6 blocks
✅ Block types: {'title': 4, 'list': 2}
✅ Successfully imported draw_layout_bbox_on_single_page
✅ Generated annotated PDF: /tmp/test_bbox_layout.pdf, size=586040 bytes
✅ All tests passed!
```

## 使用方法

### 1. 启动服务

```bash
# FastAPI (port 8000)
uvicorn app.main:app --reload

# Celery Worker
celery -A app.celery_app worker --loglevel=info

# Gradio UI (port 7861)
python ui/gradio_app.py
```

### 2. 上传并解析 PDF

1. 访问 http://localhost:7861
2. 切换到"PDF 管道"标签
3. 上传 PDF 文件
4. 配置 MinerU 参数（默认即可）
5. 点击"提交 PDF 处理"
6. 等待解析完成（状态变为 `completed`）

### 3. 查看 Bbox 标注预览

1. 解析完成后，点击"🔄 加载分页预览"按钮
2. 使用滑块切换页码
3. PDF 预览区域显示带彩色 bbox 的标注
4. 下方显示检测到的元素统计信息

## 技术细节

### PDF 坐标系统

- MinerU 返回的 bbox 格式: `[x0, y0, x1, y1]`
- PDF 坐标原点在左下角
- 需要根据页面旋转角度调整坐标
- `cal_canvas_rect()` 处理 0°, 90°, 180°, 270° 旋转

### 性能优化

- 单页渲染（按需生成）
- 临时文件缓存（`GRADIO_TEMP_DIR`）
- 文件名包含 task_id 和页码，避免冲突

### 错误处理

- 多级 artifacts 查找（result.extras.artifacts → result.artifacts → task.extras.artifacts）
- 缺失数据时显示详细诊断信息
- 异常时返回错误消息和堆栈跟踪

## 已知限制

1. **单页渲染**: 每次只渲染一页，大文档切换页面需要时间
2. **临时文件**: 生成的 PDF 存储在临时目录，需定期清理
3. **内存占用**: 大 PDF 文件可能占用较多内存

## 未来优化方向

1. **多页预渲染**: 预先生成所有页面的标注 PDF
2. **增量更新**: 只在首次加载时生成，后续从缓存读取
3. **可配置颜色**: 允许用户自定义 bbox 颜色方案
4. **交互功能**: 点击 bbox 显示块详细信息
5. **导出功能**: 下载完整的标注 PDF

## 参考资料

- [MinerU 官方仓库](https://github.com/opendatalab/MinerU)
- [MinerU draw_bbox.py](https://github.com/opendatalab/MinerU/blob/master/mineru/utils/draw_bbox.py)
- [gradio-pdf 文档](https://huggingface.co/spaces/freddyaboulton/gradio-pdf)
- [ReportLab 文档](https://www.reportlab.com/docs/reportlab-userguide.pdf)
- [pypdf 文档](https://pypdf.readthedocs.io/)

## 更新日志

### 2024-12-06

- ✅ 实现 `draw_layout_bbox_on_single_page()` 函数
- ✅ 集成到 `render_pdf_page()` 函数
- ✅ 修改 Gradio UI 使用 PDF 组件
- ✅ 添加元素统计信息显示
- ✅ 创建测试脚本并验证功能
- ✅ 所有测试通过，功能正常运行
