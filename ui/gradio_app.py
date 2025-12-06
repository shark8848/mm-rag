from __future__ import annotations

import os
from pathlib import Path, PurePosixPath
import base64
from typing import Any, Dict, List, Optional, Tuple
import html
import time
import json
import zipfile
import mimetypes
import re

import gradio as gr
from gradio_pdf import PDF
import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
DEFAULT_TIMEOUT = float(os.environ.get("API_TIMEOUT", "90"))
API_APP_ID = os.environ.get("API_APP_ID")
API_APP_KEY = os.environ.get("API_APP_KEY")

_AUTH_HEADERS = {"X-Appid": API_APP_ID, "X-Key": API_APP_KEY} if (API_APP_ID and API_APP_KEY) else {}

_MINERU_ZIP_CACHE: Dict[str, Tuple[float, Dict[str, Any]]] = {}

_MARKDOWN_IMAGE_PATTERN = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


UI_CSS = """
.pdf-preview-placeholder {
    padding: 1.5rem;
    border: 1px dashed #ccc;
    text-align: center;
    color: #777;
    background: #fafafa;
}
.pdf-preview-stack {
    width: 100%;
    max-width: 960px;
    margin: 0 auto;
    position: relative;
}
.pdf-preview-stack.has-overlay {
    position: relative;
}
.pdf-preview-sizer {
    display: none;
}
.pdf-preview-stack.has-overlay .pdf-preview-sizer {
    display: block;
    width: 100%;
    padding-top: calc(var(--pdf-total-ratio, 1) * 100%);
}
.pdf-preview-frame {
    width: 100%;
    height: 640px;
    border: none;
}
.pdf-preview-stack.has-overlay .pdf-preview-frame,
.pdf-preview-stack.has-overlay .pdf-overlay {
    position: absolute;
    inset: 0;
    width: 100%;
    height: 100%;
}
.pdf-overlay {
    pointer-events: none;
}
.pdf-overlay-canvas {
    position: relative;
    width: 100%;
    height: 100%;
}
.pdf-overlay-page {
    position: absolute;
    left: 0;
    width: 100%;
}
.pdf-overlay-box {
    position: absolute;
    border: 2px solid rgba(255, 0, 92, 0.85);
    background: rgba(255, 0, 92, 0.12);
    color: #fff;
    font-size: 0.65rem;
    line-height: 1;
    padding: 0.05rem 0.15rem;
    box-sizing: border-box;
}
#mineru_pdf_viewer, #mineru_overlay_viewer {
    position: relative;
}
#mineru_pdf_viewer iframe {
    display: block;
}
#mineru_overlay_viewer {
    position: absolute;
    top: 0;
    left: 0;
    width: 100%;
    height: 640px;
    pointer-events: none;
    z-index: 10;
}
#pdf_query_section {
    max-width: 1000px;
    margin: 0 auto 1rem;
}
#pdf_query_row {
    display: flex;
    gap: 1rem;
    flex-wrap: wrap;
}
#pdf_query_controls,
#pdf_hits_column {
    flex: 1 1 320px;
}
#pdf_hits_column {
    max-width: 420px;
}
#pdf_hits_panel {
    background: #fff;
    border: 1px solid #e0e0e0;
    padding: 1rem;
    min-height: 180px;
}
#pdf_section_left {
    display: flex;
    flex-direction: column;
    gap: 0.75rem;
}
"""

def _headers() -> Dict[str, str]:
    return dict(_AUTH_HEADERS)


def _format_request_error(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, requests.HTTPError) and exc.response is not None:
        try:
            payload = exc.response.json()
        except Exception:  # pylint: disable=broad-except
            payload = None
        if isinstance(payload, dict):
            detail = payload.get("message") or payload.get("detail")
            if detail:
                message = detail
            code = payload.get("error_code")
            if code:
                message = f"{code}: {message}"
    if not _AUTH_HEADERS:
        message = f"{message}（请设置 API_APP_ID/API_APP_KEY 环境变量以满足 FastAPI 认证）"
    return message


def _normalize_tags(raw: str) -> List[str]:
    if not raw:
        return []
    return [tag.strip() for tag in raw.split(",") if tag.strip()]


def _resolve_local_path(file_obj: Any) -> Path | None:
    if file_obj is None:
        return None
    if isinstance(file_obj, str):
        candidate = Path(file_obj)
    else:
        candidate = Path(getattr(file_obj, "name", ""))
    if candidate.exists():
        return candidate
    return None


def _file_tuple(file_obj: Any) -> Tuple[str, bytes]:
    path = _resolve_local_path(file_obj)
    if path is None:
        raise FileNotFoundError("无法读取文件: 未找到本地路径")
    content = path.read_bytes()
    return path.name, content


def _pdf_viewer_html(file_obj: Any) -> str:
    path = _resolve_local_path(file_obj)
    if path is None:
        return "<div class='pdf-preview-placeholder'>等待 PDF 预览</div>"
    try:
        data = path.read_bytes()
    except OSError:
        return "<div class='pdf-preview-placeholder'>PDF 预览加载失败</div>"
    b64 = base64.b64encode(data).decode("ascii")
    return (
        "<iframe title='pdf-preview' src='data:application/pdf;base64,"
        f"{b64}' style='width:100%;height:640px;' frameborder='0'></iframe>"
    )


def _decode_mineru_zip(zip_path: Path) -> Dict[str, Any] | None:
    if not zip_path.exists():
        return None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            result: Dict[str, Any] = {}
            image_map: Dict[str, bytes] = {}
            md_entry: Optional[str] = None
            for member in archive.namelist():
                lower = member.lower()
                data = archive.read(member)
                if lower.endswith(".md"):
                    result["md"] = data.decode("utf-8", errors="ignore")
                    md_entry = member
                elif lower.endswith("middle.json"):
                    result["middle_json"] = json.loads(data.decode("utf-8"))
                elif lower.endswith("content_list.json"):
                    result["content_list"] = json.loads(data.decode("utf-8"))
                elif lower.endswith((".jpg", ".jpeg", ".png", ".gif", ".webp")):
                    image_map[member] = data
            if image_map:
                result["__image_map"] = image_map
            if md_entry:
                result["__md_entry"] = md_entry
            return result
    except Exception:  # pylint: disable=broad-except
        return None


def _guess_mime(path: str) -> str:
    mime, _ = mimetypes.guess_type(path)
    return mime or "application/octet-stream"


def _find_markdown_file(asset_dir: Path | None) -> Optional[Path]:
    if not asset_dir or not asset_dir.exists():
        return None
    candidates = sorted(asset_dir.rglob("*.md"))
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    return None


def _inline_markdown_images(
    markdown_text: str,
    *,
    asset_root: Path | None = None,
    zip_payload: Dict[str, Any] | None = None,
) -> str:
    if not markdown_text:
        return ""
    image_map = (zip_payload or {}).get("__image_map") if zip_payload else None
    md_entry = (zip_payload or {}).get("__md_entry") if zip_payload else None
    md_parent = str(PurePosixPath(md_entry).parent) if md_entry else None

    def _lookup_zip_image(rel_path: str) -> Optional[bytes]:
        if not image_map:
            return None
        normalized = rel_path.replace("\\", "/").lstrip("./")
        candidate_keys = [normalized]
        if md_parent:
            candidate_keys.append(f"{md_parent.rstrip('/')}/{normalized}")
            candidate_keys.append(str(PurePosixPath(md_parent) / normalized))
        for key in candidate_keys:
            if key in image_map:
                return image_map[key]
        return None

    def _replacer(match: re.Match[str]) -> str:
        alt_text = match.group(1) or ""
        rel_path = (match.group(2) or "").strip()
        if not rel_path:
            return match.group(0)
        data: Optional[bytes] = None
        mime: Optional[str] = None
        if asset_root is not None:
            file_path = (asset_root / rel_path).resolve()
            try:
                if file_path.is_file():
                    data = file_path.read_bytes()
                    mime = _guess_mime(file_path.name)
            except OSError:
                data = None
        if data is None:
            data = _lookup_zip_image(rel_path)
            if data:
                mime = _guess_mime(rel_path)
        if data is None:
            return match.group(0)
        encoded = base64.b64encode(data).decode("ascii")
        return f"![{alt_text}](data:{mime};base64,{encoded})"

    return _MARKDOWN_IMAGE_PATTERN.sub(_replacer, markdown_text)


def _read_file_bytes(file_path: Path) -> Optional[bytes]:
    try:
        return file_path.read_bytes()
    except OSError:
        return None


def _extract_pdf_from_zip(zip_path: Path) -> Optional[bytes]:
    if not zip_path.exists():
        return None
    try:
        with zipfile.ZipFile(zip_path) as archive:
            pdf_members = [name for name in archive.namelist() if name.lower().endswith(".pdf")]
            if not pdf_members:
                return None
            pdf_members.sort(key=lambda name: (0 if name.lower().endswith("_layout.pdf") else 1, len(name)))
            return archive.read(pdf_members[0])
    except Exception:  # pylint: disable=broad-except
        return None


def _get_mineru_zip_payload(zip_path: Path) -> Dict[str, Any]:
    cache_key = str(zip_path)
    try:
        mtime = zip_path.stat().st_mtime
    except OSError:
        return {}
    cached = _MINERU_ZIP_CACHE.get(cache_key)
    if cached and cached[0] == mtime:
        return cached[1]
    payload = _decode_mineru_zip(zip_path) or {}
    payload["__pdf_bytes"] = _extract_pdf_from_zip(zip_path)
    payload["__cached_at"] = time.time()
    _MINERU_ZIP_CACHE[cache_key] = (mtime, payload)
    return payload


def _extract_block_text(block: Dict[str, Any]) -> str:
    lines = block.get("lines") or []
    pieces: List[str] = []
    for line in lines:
        spans = line.get("spans") or []
        for span in spans:
            text = span.get("content") or span.get("text")
            if text:
                pieces.append(str(text))
    return "\n".join(piece.strip() for piece in pieces if str(piece).strip()).strip()


def _normalize_page_size(raw: Any) -> Optional[Tuple[float, float]]:
    width: Optional[float] = None
    height: Optional[float] = None
    if isinstance(raw, dict):
        width = raw.get("width") or raw.get("w") or raw.get("page_width")
        height = raw.get("height") or raw.get("h") or raw.get("page_height")
    elif isinstance(raw, (list, tuple)):
        numbers: List[float] = []
        for item in raw[:2]:
            if isinstance(item, (int, float)):
                numbers.append(float(item))
        if len(numbers) == 2:
            width, height = numbers
    if width is None or height is None:
        return None
    if width <= 0 or height <= 0:
        return None
    return float(width), float(height)


def _normalize_bbox_coords(raw: Any) -> Optional[Tuple[float, float, float, float]]:
    numbers: List[float] = []
    if isinstance(raw, dict):
        for key in ("x0", "y0", "x1", "y1"):
            val = raw.get(key)
            if isinstance(val, (int, float)):
                numbers.append(float(val))
    elif isinstance(raw, (list, tuple)):
        if len(raw) == 4 and all(isinstance(val, (int, float)) for val in raw):
            numbers = [float(val) for val in raw]  # type: ignore[list-item]
        elif len(raw) >= 2 and all(isinstance(val, (list, tuple)) for val in raw[:2]):
            try:
                numbers = [
                    float(raw[0][0]),
                    float(raw[0][1]),
                    float(raw[1][0]),
                    float(raw[1][1]),
                ]
            except (TypeError, ValueError, IndexError):
                numbers = []
        elif len(raw) >= 8 and all(isinstance(val, (int, float)) for val in raw[:8]):
            xs = [float(raw[idx]) for idx in range(0, len(raw), 2)]
            ys = [float(raw[idx + 1]) for idx in range(0, len(raw), 2)]
            numbers = [min(xs), min(ys), max(xs), max(ys)]
    if len(numbers) != 4:
        return None
    x0, y0, x1, y1 = numbers
    if x0 == x1 or y0 == y1:
        return None
    return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)


def _infer_vertical_origin(bbox_list: List[Tuple[float, float, float, float]], page_height: float) -> str:
    if not bbox_list or page_height <= 0:
        return "top-left"
    mids = [((bbox[1] + bbox[3]) / 2.0) / page_height for bbox in bbox_list]
    avg_mid = sum(mids) / len(mids)
    return "bottom-left" if avg_mid > 0.6 else "top-left"


def _prepare_overlay_payload(zip_payload: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    middle_json = zip_payload.get("middle_json")
    if not isinstance(middle_json, dict):
        return None
    pdf_info = middle_json.get("pdf_info") or []
    if not isinstance(pdf_info, list):
        return None
    overlay_pages: List[Dict[str, Any]] = []
    total_ratio = 0.0
    for idx, info in enumerate(pdf_info, start=1):
        page_size = _normalize_page_size(info.get("page_size"))
        if not page_size:
            continue
        width, height = page_size
        if width <= 0 or height <= 0:
            continue
        page_ratio = height / width
        if page_ratio <= 0:
            continue
        raw_blocks = info.get("preproc_blocks") or []
        if not isinstance(raw_blocks, list):
            continue
        normalized_blocks: List[Dict[str, Any]] = []
        bbox_samples: List[Tuple[float, float, float, float]] = []
        for block in raw_blocks:
            if not isinstance(block, dict):
                continue
            bbox = _normalize_bbox_coords(block.get("bbox"))
            if not bbox:
                continue
            bbox_samples.append(bbox)
            normalized_blocks.append(
                {
                    "bbox": bbox,
                    "text": block.get("text") or _extract_block_text(block),
                    "type": block.get("type"),
                }
            )
        if not normalized_blocks:
            continue
        page_number = int(info.get("page_idx", idx - 1)) + 1
        overlay_pages.append(
            {
                "page_number": page_number,
                "width": width,
                "height": height,
                "ratio": page_ratio,
                "blocks": normalized_blocks,
                "origin": _infer_vertical_origin(bbox_samples, height),
            }
        )
        total_ratio += page_ratio
    if not overlay_pages or total_ratio <= 0:
        return None
    return {"pages": overlay_pages, "total_ratio": total_ratio}


def _build_overlay_markup(zip_payload: Dict[str, Any]) -> Tuple[Optional[str], Optional[float]]:
    overlay_payload = _prepare_overlay_payload(zip_payload)
    if not overlay_payload:
        return None, None
    pages = overlay_payload["pages"]
    total_ratio = overlay_payload["total_ratio"]
    cumulative = 0.0
    parts = ["<div class='pdf-overlay-canvas'>"]
    for page in pages:
        page_ratio = page["ratio"]
        page_height_percent = (page_ratio / total_ratio) * 100.0
        page_top_percent = (cumulative / total_ratio) * 100.0
        parts.append(
            (
                "<div class='pdf-overlay-page' data-page='"
                f"{page['page_number']}' style='top:{page_top_percent:.6f}%;"
                f"height:{page_height_percent:.6f}%;'>"
            )
        )
        for block in page["blocks"]:
            style = _compute_block_style(block["bbox"], page, page_top_percent, page_height_percent)
            if not style:
                continue
            left_pct, top_pct, width_pct, height_pct = style
            label = block.get("type") or "block"
            tooltip = block.get("text") or label
            parts.append(
                (
                    "<div class='pdf-overlay-box' style='"
                    f"left:{left_pct:.3f}%;top:{top_pct:.3f}%;width:{width_pct:.3f}%;"
                    f"height:{height_pct:.3f}%;' title='{html.escape(tooltip[:240])}'>" 
                    f"{html.escape(label)}"
                    "</div>"
                )
            )
        parts.append("</div>")
        cumulative += page_ratio
    parts.append("</div>")
    return "".join(parts), total_ratio


def _build_single_page_overlay(zip_payload: Dict[str, Any], page_num: int) -> Tuple[Optional[str], int]:
    """Build overlay for a single page, returns HTML and total page count."""
    overlay_payload = _prepare_overlay_payload(zip_payload)
    if not overlay_payload:
        return None, 0
    pages = overlay_payload["pages"]
    total_pages = len(pages)
    target_page = None
    for page in pages:
        if page["page_number"] == page_num:
            target_page = page
            break
    if not target_page:
        return None, total_pages
    parts = ["<div class='pdf-overlay-canvas' style='position:relative;width:100%;height:100%;'>"]
    for block in target_page["blocks"]:
        bbox = block["bbox"]
        width = float(target_page.get("width") or 0)
        height = float(target_page.get("height") or 0)
        if width <= 0 or height <= 0:
            continue
        x0, y0, x1, y1 = bbox
        frac_space = max(abs(v) for v in bbox) <= 1.2
        if frac_space:
            left_pct = min(x0, x1) * 100.0
            width_pct = abs(x1 - x0) * 100.0
            top_pct = min(y0, y1) * 100.0
            height_pct = abs(y1 - y0) * 100.0
        else:
            left_pct = (min(x0, x1) / width) * 100.0
            width_pct = (abs(x1 - x0) / width) * 100.0
            origin = target_page.get("origin") or "top-left"
            if origin == "bottom-left":
                top_pct = (1.0 - max(y0, y1) / height) * 100.0
            else:
                top_pct = (min(y0, y1) / height) * 100.0
            height_pct = (abs(y1 - y0) / height) * 100.0
        left_pct = max(0.0, min(left_pct, 100.0))
        width_pct = max(0.2, min(width_pct, 100.0))
        top_pct = max(0.0, min(top_pct, 100.0))
        height_pct = max(0.2, min(height_pct, 100.0))
        label = block.get("type") or "block"
        tooltip = block.get("text") or label
        parts.append(
            f"<div class='pdf-overlay-box' style='left:{left_pct:.3f}%;top:{top_pct:.3f}%;"
            f"width:{width_pct:.3f}%;height:{height_pct:.3f}%;' "
            f"title='{html.escape(tooltip[:240])}'>{html.escape(label)}</div>"
        )
    parts.append("</div>")
    return "".join(parts), total_pages
def _compute_block_style(
    bbox: Tuple[float, float, float, float],
    page: Dict[str, Any],
    page_top_percent: float,
    page_height_percent: float,
) -> Optional[Tuple[float, float, float, float]]:
    width = float(page.get("width") or 0)
    height = float(page.get("height") or 0)
    if width <= 0 or height <= 0:
        return None
    x0, y0, x1, y1 = bbox
    frac_space = max(abs(value) for value in bbox) <= 1.2
    if frac_space:
        left_pct = min(x0, x1) * 100.0
        width_pct = abs(x1 - x0) * 100.0
    else:
        left_pct = (min(x0, x1) / width) * 100.0
        width_pct = (abs(x1 - x0) / width) * 100.0
    y_min = min(y0, y1)
    y_max = max(y0, y1)
    if frac_space:
        y_top_page = y_min * height
        y_height_page = abs(y1 - y0) * height
    else:
        origin = page.get("origin") or "top-left"
        if origin == "bottom-left":
            y_top_page = height - y_max
        else:
            y_top_page = y_min
        y_height_page = abs(y1 - y0)
    if height <= 0:
        return None
    y_top_percent = page_top_percent + (y_top_page / height) * page_height_percent
    height_percent = (y_height_page / height) * page_height_percent
    for value in (left_pct, width_pct, y_top_percent, height_percent):
        if not (value or value == 0):
            return None
    left_pct = max(0.0, min(left_pct, 100.0))
    width_pct = max(0.2, min(width_pct, 100.0))
    y_top_percent = max(0.0, min(y_top_percent, 100.0))
    height_percent = max(0.2, min(height_percent, 100.0))
    return left_pct, y_top_percent, width_pct, height_percent


def _build_remote_pdf_preview(task: Dict[str, Any]) -> str | None:
    if not isinstance(task, dict):
        return None
    result = task.get("result") or {}
    extras = result.get("extras") or {}
    artifacts = extras.get("artifacts") or {}
    # Fallback 1: result.artifacts
    if not artifacts:
        artifacts = result.get("artifacts") or {}
    # Fallback 2: task.extras.artifacts
    if not artifacts:
        task_extras = task.get("extras") or {}
        artifacts = task_extras.get("artifacts") or {}
    pdf_path = (
        artifacts.get("mineru_layout_pdf_path")
        or artifacts.get("pdf_source_path")
        or artifacts.get("original_pdf_path")
    )
    result = task.get("result") or {}
    if not pdf_path:
        pdf_path = result.get("pdf_preview_path")
    pdf_bytes = _read_file_bytes(Path(pdf_path)) if pdf_path else None
    zip_payload: Optional[Dict[str, Any]] = None
    zip_path = artifacts.get("mineru_bundle_path") or artifacts.get("mineru_zip_path")
    if zip_path:
        zip_payload = _get_mineru_zip_payload(Path(zip_path))
        if not pdf_bytes and zip_payload:
            pdf_bytes = zip_payload.get("__pdf_bytes")  # type: ignore[assignment]
    if not pdf_bytes:
        return "<div class='pdf-preview-placeholder'>未找到 PDF 预览资源</div>"
    overlay_html = None
    total_ratio = None
    if zip_payload:
        overlay_html, total_ratio = _build_overlay_markup(zip_payload)
    b64 = base64.b64encode(pdf_bytes).decode("ascii")
    classes = ["pdf-preview-stack"]
    sizer = ""
    if overlay_html and total_ratio:
        classes.append("has-overlay")
        sizer = "<div class='pdf-preview-sizer'></div>"
    iframe_tag = (
        "<iframe class='pdf-preview-frame' title='pdf-preview' src='data:application/pdf;base64,"
        f"{b64}'></iframe>"
    )
    style_attr = f" style='--pdf-total-ratio:{total_ratio:.6f};'" if total_ratio else ""
    parts = [f"<div class='{' '.join(classes)}'{style_attr}>", sizer, iframe_tag]
    if overlay_html:
        parts.append(f"<div class='pdf-overlay'>{overlay_html}</div>")
    parts.append("</div>")
    return "".join(parts)


def _build_mineru_markdown_preview(task: Dict[str, Any]) -> Tuple[Optional[str], Optional[str], Optional[str]]:
    if not isinstance(task, dict):
        return None, None, None
    result = task.get("result") or {}
    extras = result.get("extras") or {}
    artifacts = extras.get("artifacts") or {}
    # Fallback 1: result.artifacts
    if not artifacts:
        artifacts = result.get("artifacts") or {}
    # Fallback 2: task.extras.artifacts
    if not artifacts:
        task_extras = task.get("extras") or {}
        artifacts = task_extras.get("artifacts") or {}
    asset_dir_value = artifacts.get("mineru_asset_dir")
    asset_dir = Path(asset_dir_value) if asset_dir_value else None
    bundle_path = artifacts.get("mineru_bundle_path") or artifacts.get("mineru_zip_path")
    zip_payload = None
    if bundle_path:
        zip_payload = _get_mineru_zip_payload(Path(bundle_path))
    md_path = _find_markdown_file(asset_dir)
    md_text: Optional[str] = None
    md_rendered: Optional[str] = None
    if md_path:
        try:
            md_text = md_path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            md_text = md_path.read_text(encoding="utf-8", errors="ignore")
        md_rendered = _inline_markdown_images(md_text, asset_root=md_path.parent)
    elif zip_payload and isinstance(zip_payload.get("md"), str):
        md_text = zip_payload.get("md")  # type: ignore[assignment]
    if md_text and not md_rendered:
        md_rendered = _inline_markdown_images(md_text, asset_root=asset_dir, zip_payload=zip_payload)
    return md_rendered, md_text, bundle_path


def _save_pdf_to_temp(pdf_bytes: bytes, task_id: str) -> str:
    """Save PDF to Gradio temp directory and return relative path."""
    temp_dir = Path(os.environ.get("GRADIO_TEMP_DIR", "/tmp/gradio"))
    temp_dir.mkdir(parents=True, exist_ok=True)
    
    # Use task_id as filename to enable caching
    pdf_file = temp_dir / f"pdf_{task_id}.pdf"
    
    # Only write if file doesn't exist or is different
    if not pdf_file.exists() or pdf_file.stat().st_size != len(pdf_bytes):
        pdf_file.write_bytes(pdf_bytes)
    
    return str(pdf_file)


def render_pdf_page(
    task_id: str,
    page_num: int,
) -> Tuple[Optional[str], str, int, int]:
    """Render a single PDF page with MinerU bbox overlays. Returns (pdf_file_path, overlay_info_md, current_page, total_pages)."""
    if not task_id:
        return None, "⚠️ 等待任务", 1, 1
    try:
        resp = requests.get(f"{API_BASE_URL}/tasks/{task_id}", headers=_headers(), timeout=15)
        resp.raise_for_status()
        task = resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        import traceback
        error_detail = f"❌ 加载失败: {exc}\n\n```\n{traceback.format_exc()}\n```"
        return None, error_detail, 1, 1
    
    # Check task structure - artifacts can be at multiple levels
    result = task.get("result") or {}
    
    # Try result.extras.artifacts (new structure)
    extras = result.get("extras") or {}
    artifacts = extras.get("artifacts") or {}
    
    # Fallback 1: result.artifacts (context level)
    if not artifacts:
        artifacts = result.get("artifacts") or {}
    
    # Fallback 2: task.extras.artifacts (old API structure)
    if not artifacts:
        task_extras = task.get("extras") or {}
        artifacts = task_extras.get("artifacts") or {}
    
    bundle_path = artifacts.get("mineru_bundle_path") or artifacts.get("mineru_zip_path")
    
    if not bundle_path:
        debug_info = (
            f"❌ 未找到 MinerU 数据\n\n"
            f"- **Task ID**: {task_id}\n"
            f"- **Status**: {task.get('status')}\n"
            f"- **Result keys**: {list(result.keys())}\n"
            f"- **Extras keys**: {list(extras.keys())}\n"
            f"- **Artifacts keys**: {list(artifacts.keys())}"
        )
        return None, debug_info, 1, 1
    zip_payload = _get_mineru_zip_payload(Path(bundle_path))
    pdf_bytes = zip_payload.get("__pdf_bytes")
    if not pdf_bytes:
        pdf_path_value = artifacts.get("mineru_layout_pdf_path") or artifacts.get("pdf_source_path")
        if pdf_path_value:
            pdf_bytes = _read_file_bytes(Path(pdf_path_value))
    if not pdf_bytes:
        return None, "❌ 未找到 PDF 文件", 1, 1
    
    # Parse middle.json for pdf_info (note: key is "middle_json" with underscore, not "middle.json")
    middle_json = zip_payload.get("middle_json")
    if not middle_json:
        return None, "❌ 未找到 middle.json", 1, 1
    
    pdf_info = middle_json.get("pdf_info", [])
    total_pages = len(pdf_info)
    if total_pages == 0:
        return None, "❌ pdf_info 为空", 1, 1
    
    current_page = max(1, min(page_num, total_pages))
    page_index = current_page - 1  # 0-based index
    
    # Get page info
    pdf_info_page = pdf_info[page_index]
    
    # 调试信息
    pdf_size_kb = len(pdf_bytes) / 1024
    print(f"[DEBUG] render_pdf_page: task_id={task_id}, page={current_page}/{total_pages}, pdf_size={pdf_size_kb:.2f}KB")
    
    # Generate annotated PDF with bbox overlays using MinerU's approach
    try:
        # Add parent directory to path for app imports
        import sys
        project_root = Path(__file__).parent.parent
        if str(project_root) not in sys.path:
            sys.path.insert(0, str(project_root))
        
        from app.utils.draw_bbox import draw_layout_bbox_on_single_page
        
        temp_dir = Path(os.environ.get("GRADIO_TEMP_DIR", "/tmp/gradio"))
        temp_dir.mkdir(parents=True, exist_ok=True)
        
        output_filename = f"pdf_{task_id}_page{current_page}_layout.pdf"
        output_path = temp_dir / output_filename
        
        annotated_pdf_path = draw_layout_bbox_on_single_page(
            pdf_info_page=pdf_info_page,
            pdf_bytes=pdf_bytes,
            page_index=page_index,
            output_path=str(output_path)
        )
        
        if not annotated_pdf_path or not Path(annotated_pdf_path).exists():
            return None, f"❌ 生成带标注的 PDF 失败", current_page, total_pages
        
        print(f"[DEBUG] Annotated PDF generated: {annotated_pdf_path}")
        
        # 统计检测到的元素
        para_blocks = pdf_info_page.get("para_blocks", [])
        block_types = {}
        for block in para_blocks:
            block_type = block.get("type", "unknown")
            block_types[block_type] = block_types.get(block_type, 0) + 1
        
        # 生成 overlay 信息摘要
        overlay_info = f"### 📊 第 {current_page} / {total_pages} 页\n\n"
        overlay_info += f"- 📄 文件大小: **{pdf_size_kb:.1f} KB**\n"
        overlay_info += f"- ✅ 检测到 **{len(para_blocks)}** 个文档块:\n"
        
        type_labels = {
            "table": "📊 表格",
            "image": "🖼️ 图片",
            "title": "📑 标题",
            "text": "📝 文本",
            "equation": "🔢 公式",
            "list": "📋 列表",
            "reference": "📚 引用",
        }
        
        for btype, count in sorted(block_types.items()):
            label = type_labels.get(btype, btype)
            overlay_info += f"  - {label}: **{count}**\n"
        
        overlay_info += "\n**图例**: 表格(黄)、图片(绿)、标题(蓝)、文本(紫)、公式(绿)、列表(绿)\n"
        overlay_info += "**提示**: 可使用滑块切换页码查看不同页面的标注。\n"
        
        return annotated_pdf_path, overlay_info, current_page, total_pages
        
    except Exception as exc:  # pylint: disable=broad-except
        import traceback
        error_detail = f"❌ 生成 bbox 标注失败: {exc}\n\n```\n{traceback.format_exc()}\n```"
        return None, error_detail, current_page, total_pages


def submit_ingest(
    file_obj: Any,
    media_type: str,
    title: str,
    description: str,
    tags_text: str,
    frame_strategy: str,
    frame_interval: float,
    scene_threshold: float,
    pdf_options: Dict[str, Any] | None = None,
) -> Tuple[str, str, Dict[str, Any]]:
    try:
        filename, payload = _file_tuple(file_obj)
    except Exception as exc:  # pylint: disable=broad-except
        return f"❌ 上传失败: {exc}", "", {}

    metadata: Dict[str, Any] = {
        "title": title or filename,
        "description": description or None,
        "tags": _normalize_tags(tags_text),
    }
    proc_opts = {
        "frame_strategy": frame_strategy,
        "frame_interval_seconds": frame_interval,
        "scene_threshold": scene_threshold,
    }
    if pdf_options:
        proc_opts.update(pdf_options)
    files = {"file": (filename, payload)}
    data = {
        "media_type": media_type,
        "metadata": json.dumps(metadata, ensure_ascii=False),
        "processing_options": json.dumps(proc_opts, ensure_ascii=False),
    }
    try:
        response = requests.post(
            f"{API_BASE_URL}/ingest/upload",
            files=files,
            data=data,
            headers=_headers(),
            timeout=DEFAULT_TIMEOUT,
        )
        response.raise_for_status()
    except Exception as exc:  # pylint: disable=broad-except
        return f"❌ 创建任务失败: {_format_request_error(exc)}", "", {}

    payload = response.json()
    task_id = payload.get("task_id", "")
    status = payload.get("status", "pending")
    message = f"✅ 任务 {task_id} 已创建，当前状态：{status}"
    return message, task_id, payload


def _build_pdf_options(
    backend: str,
    parse_method: str,
    lang_choice: str | None,
    formula_enable: bool,
    table_enable: bool,
    return_md: bool,
    return_middle_json: bool,
    return_model_output: bool,
    return_content_list: bool,
    return_images: bool,
    response_format_zip: bool,
    output_dir: str,
    server_url: str,
    start_page_id: float | int | None,
    end_page_id: float | int | None,
) -> Dict[str, Any]:
    normalized_lang = (lang_choice or "ch").strip() or "ch"
    options: Dict[str, Any] = {
        "backend": backend or "pipeline",
        "parse_method": parse_method or "auto",
        "lang_list": [normalized_lang],
        "formula_enable": formula_enable,
        "table_enable": table_enable,
        "return_md": return_md,
        "return_middle_json": return_middle_json,
        "return_model_output": return_model_output,
        "return_content_list": return_content_list,
        "return_images": return_images,
        "response_format_zip": response_format_zip,
    }
    if output_dir.strip():
        options["output_dir"] = output_dir.strip()
    if server_url.strip():
        options["server_url"] = server_url.strip()
    normalized_start: Optional[int] = None
    normalized_end: Optional[int] = None
    if start_page_id is not None:
        normalized_start = int(start_page_id)
        if normalized_start < 0:
            raise ValueError("起始页不能为负数")
        options["start_page_id"] = normalized_start
    if end_page_id is not None:
        normalized_end = int(end_page_id)
        if normalized_end < 0:
            raise ValueError("结束页不能为负数")
        options["end_page_id"] = normalized_end
    if (
        normalized_start is not None
        and normalized_end is not None
        and normalized_end < normalized_start
    ):
        raise ValueError("结束页必须大于等于起始页")
    return {"mineru": options}


def submit_pdf_pipeline(
    file_obj: Any,
    title: str,
    description: str,
    tags_text: str,
    backend: str,
    parse_method: str,
    lang_choice: str | None,
    formula_enable: bool,
    table_enable: bool,
    return_md: bool,
    return_middle_json: bool,
    return_model_output: bool,
    return_content_list: bool,
    return_images: bool,
    response_format_zip: bool,
    output_dir: str,
    server_url: str,
    start_page_id: float | int | None,
    end_page_id: float | int | None,
) -> Tuple[str, str, Dict[str, Any]]:
    try:
        pdf_options = _build_pdf_options(
        backend,
        parse_method,
        lang_choice,
        formula_enable,
        table_enable,
        return_md,
        return_middle_json,
        return_model_output,
        return_content_list,
        return_images,
        response_format_zip,
        output_dir,
        server_url,
        start_page_id,
        end_page_id,
        )
    except ValueError as exc:
        return f"❌ 参数错误：{exc}", "", {}
    return submit_ingest(
        file_obj=file_obj,
        media_type="pdf",
        title=title,
        description=description,
        tags_text=tags_text,
        frame_strategy="interval",
        frame_interval=1.0,
        scene_threshold=0.3,
        pdf_options=pdf_options,
    )


def format_hits(hits: List[Dict[str, Any]]) -> str:
    if not hits:
        return "暂无匹配结果"
    blocks: List[str] = []
    for idx, hit in enumerate(hits, start=1):
        lines = [f"**结果 {idx}**"]
        title = hit.get("title") or hit.get("document_id")
        media_path = hit.get("path")
        lines.append(f"标题：{title}")
        if media_path:
            lines.append(f"来源：`{media_path}`")
        snippet = hit.get("content")
        if isinstance(snippet, str):
            snippet = snippet[:500]
        lines.append(f"内容：{snippet}")
        temporal = hit.get("temporal")
        if temporal:
            start = temporal.get("start_time")
            end = temporal.get("end_time")
            lines.append(f"时间段：{start:.2f}s - {end:.2f}s")
        video_path = hit.get("video_path") or hit.get("path")
        if video_path:
            lines.append(f"视频：`{video_path}`")
        audio_path = hit.get("audio_path")
        if audio_path:
            lines.append(f"音频：`{audio_path}`")
        blocks.append("\n".join(lines))
    return "\n\n".join(blocks)


def run_query(query: str, top_k: int) -> str:
    if not query.strip():
        return "请输入查询语句"
    try:
        response = requests.post(
            f"{API_BASE_URL}/query",
            json={"query": query, "top_k": top_k},
            headers=_headers(),
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:  # pylint: disable=broad-except
        return f"查询失败：{_format_request_error(exc)}"
    data = response.json()
    hits = data.get("hits", [])
    return format_hits(hits)


def run_pdf_query(query: str, top_k: int) -> str:
    if not query.strip():
        return "请输入查询语句"
    try:
        response = requests.post(
            f"{API_BASE_URL}/query",
            json={"query": query, "top_k": top_k},
            headers=_headers(),
            timeout=30,
        )
        response.raise_for_status()
    except Exception as exc:  # pylint: disable=broad-except
        return f"查询失败：{_format_request_error(exc)}"
    hits = response.json().get("hits", [])
    pdf_hits = [hit for hit in hits if hit.get("media_type") == "pdf"]
    if not pdf_hits:
        return "暂无 PDF 匹配结果"
    return format_hits(pdf_hits)


def _append_message(messages: List[Dict[str, Any]], role: str, text: str) -> None:
    messages.append({"role": role, "content": [{"type": "text", "text": text}]})


def handle_query(query: str, top_k: int, history: List[Dict[str, Any]] | None):
    history = history or []
    messages = history.copy()
    user_query = query.strip()
    if not user_query:
        return messages, messages, None, None, []
    _append_message(messages, "user", user_query)
    try:
        response = requests.post(
            f"{API_BASE_URL}/query",
            json={"query": user_query, "top_k": top_k},
            headers=_headers(),
            timeout=30,
        )
        response.raise_for_status()
        hits = response.json().get("hits", [])
        answer = format_hits(hits)
    except Exception as exc:  # pylint: disable=broad-except
        answer = f"查询失败：{_format_request_error(exc)}"
        hits = []
    _append_message(messages, "assistant", answer)
    video_path = None
    audio_path = None
    gallery: List[str] = []
    if hits:
        first_hit = hits[0]
        video_path = first_hit.get("video_path") or first_hit.get("path")
        audio_path = first_hit.get("audio_path")
        for hit in hits:
            thumb = hit.get("thumbnail")
            if thumb and os.path.exists(thumb):
                gallery.append(thumb)
    return messages, messages, video_path, audio_path, gallery


def _fetch_logs(task_id: str, lines: int = 200) -> str:
    endpoints = [
        (f"{API_BASE_URL}/logs/{task_id}", {"lines": lines}),
        (f"{API_BASE_URL}/logs/tail", {"lines": lines}),
    ]
    for url, params in endpoints:
        try:
            resp = requests.get(url, params=params, headers=_headers(), timeout=15)
            if resp.status_code == 404:
                continue
            resp.raise_for_status()
            data = resp.json()
            return "\n".join(data.get("lines", []))
        except Exception:  # pylint: disable=broad-except
            continue
    return ""


def _poll_task_core(task_id: str) -> Tuple[str, str, str, str, Dict[str, Optional[str]]]:
    empty = {"md_render": None, "md_text": None, "bundle_path": None}
    if not task_id:
        return "等待任务", "", "", "", empty
    try:
        resp = requests.get(f"{API_BASE_URL}/tasks/{task_id}", headers=_headers(), timeout=15)
        resp.raise_for_status()
        task = resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        return f"任务查询失败：{_format_request_error(exc)}", "", "", "", empty

    status_line = f"状态：{task.get('status')}"
    detail = task.get("detail")
    if detail:
        status_line += f"\n说明：{detail}"
    result_payload = task.get("result") or {}
    result_block = json.dumps(result_payload, ensure_ascii=False, indent=2) if result_payload else ""
    log_text = _fetch_logs(task_id)
    remote_preview = _build_remote_pdf_preview(task) or ""
    md_render, md_text, bundle_path = _build_mineru_markdown_preview(task)
    extras = {"md_render": md_render, "md_text": md_text, "bundle_path": bundle_path}
    return status_line, result_block, log_text, remote_preview, extras


def poll_basic_task(task_id: str) -> Tuple[str, str, str]:
    status_line, result_block, log_text, _preview, _extras = _poll_task_core(task_id)
    return status_line, result_block, log_text


def poll_pdf_task(task_id: str) -> Tuple[str, str, str, str, str, str, Optional[str]]:
    status_line, result_block, log_text, preview, extras = _poll_task_core(task_id)
    return (
        status_line,
        result_block,
        log_text,
        preview,
        extras.get("md_render") or "",
        extras.get("md_text") or "",
        extras.get("bundle_path"),
    )


def build_interface() -> gr.Blocks:
    with gr.Blocks(title="Multimodal RAG Console") as demo:
        gr.HTML(f"<style>{UI_CSS}</style>")
        gr.Markdown("# 多模态 RAG 控制台\n上传音/视频/PDF，查看任务进展，并进行混合检索。")
        task_state = gr.State("")
        chat_history = gr.State([])
        pdf_task_state = gr.State("")

        with gr.Tabs():
            with gr.Tab("上传处理"):
                with gr.Row():
                    with gr.Column(scale=2, elem_id="pdf_section_left"):
                        gr.Markdown("### 上传与参数")
                        file_input = gr.File(label="音频/视频文件", file_types=[".mp3", ".wav", ".mp4", ".mov"])
                        media_type = gr.Radio(["audio", "video"], value="video", label="媒体类型")
                        title = gr.Textbox(label="标题", placeholder="自动使用文件名")
                        description = gr.Textbox(label="描述", lines=2)
                        tags = gr.Textbox(label="标签（逗号分隔）")

                        gr.Markdown("#### 抽帧策略")
                        frame_strategy = gr.Radio(["interval", "scene"], value="interval", label="策略")
                        frame_interval = gr.Slider(label="间隔（秒）", minimum=0.5, maximum=10.0, value=2.0, step=0.1)
                        scene_threshold = gr.Slider(label="场景阈值", minimum=0.05, maximum=1.0, value=0.3, step=0.05)

                        submit_btn = gr.Button("提交处理", variant="primary")
                        ingest_status = gr.Markdown()
                        task_payload = gr.JSON(label="任务响应")
                    with gr.Column(scale=1):
                        gr.Markdown("### 进度 & 日志")
                        status_panel = gr.Markdown("等待任务")
                        result_panel = gr.Code(label="结果 (完成后显示)")
                        log_panel = gr.Textbox(label="实时日志", lines=20)

            with gr.Tab("PDF 管道"):
                gr.Markdown("### PDF 上传与解析")
                with gr.Row():
                    with gr.Column(scale=2):
                        pdf_file = gr.File(label="PDF 文档", file_types=[".pdf"])
                        pdf_title = gr.Textbox(label="标题", placeholder="默认使用文件名")
                        pdf_description = gr.Textbox(label="描述", lines=2)
                        pdf_tags = gr.Textbox(label="标签（逗号分隔）")

                        gr.Markdown("#### MinerU 参数")
                        pdf_backend = gr.Dropdown(
                            choices=[
                                "pipeline",
                                "vlm-transformers",
                                "vlm-mlx-engine",
                                "vlm-vllm-async-engine",
                                "vlm-lmdeploy-engine",
                                "vlm-http-client",
                            ],
                            value="pipeline",
                            label="解析后端",
                        )
                        pdf_parse_method = gr.Radio(
                            ["auto", "txt", "ocr"], value="auto", label="解析方式 (pipeline 后端)"
                        )
                        pdf_lang_choice = gr.Dropdown(
                            choices=[
                                "ch",
                                "ch_server",
                                "ch_lite",
                                "en",
                                "korean",
                                "japan",
                                "chinese_cht",
                                "ta",
                                "te",
                                "ka",
                                "th",
                                "el",
                                "latin",
                                "arabic",
                                "east_slavic",
                                "cyrillic",
                                "devanagari",
                            ],
                            value="ch",
                            label="语言",
                        )
                        pdf_formula_enable = gr.Checkbox(label="启用公式解析", value=True)
                        pdf_table_enable = gr.Checkbox(label="启用表格解析", value=True)
                        pdf_return_md = gr.Checkbox(label="返回 Markdown", value=True)
                        pdf_return_middle_json = gr.Checkbox(label="返回中间 JSON", value=True)
                        pdf_return_model_output = gr.Checkbox(label="返回模型输出", value=False)
                        pdf_return_content_list = gr.Checkbox(label="返回内容列表", value=True)
                        pdf_return_images = gr.Checkbox(label="返回图片资源", value=False)
                        pdf_response_zip = gr.Checkbox(label="返回 ZIP", value=False)
                        pdf_output_dir = gr.Textbox(label="输出目录", placeholder="可选，默认临时目录")
                        pdf_server_url = gr.Textbox(label="VLM HTTP 服务 URL", placeholder="仅 http-client 需要")
                        with gr.Row():
                            pdf_start_page = gr.Number(
                                label="起始页 (0-based)",
                                precision=0,
                                value=0,
                                minimum=0,
                            )
                            pdf_end_page = gr.Number(
                                label="结束页 (0-based)",
                                precision=0,
                                value=500,
                                minimum=0,
                            )

                        pdf_submit = gr.Button("提交 PDF 处理", variant="primary")
                        pdf_status = gr.Markdown()
                        pdf_payload = gr.JSON(label="任务响应")

                        pdf_preview_panel = gr.HTML("<div class='pdf-preview-placeholder'>等待 PDF 预览</div>")

                        gr.Markdown("### MinerU 分页预览")
                        gr.Markdown("*解析完成后，点击下方按钮加载预览*")
                        mineru_load_btn = gr.Button("🔄 加载分页预览", size="sm")
                        mineru_page_slider = gr.Slider(
                            label="页码",
                            minimum=1,
                            maximum=100,
                            value=1,
                            step=1,
                            interactive=True,
                        )
                        mineru_pdf_viewer = PDF(label="PDF 预览", interactive=False, visible=True, height=800)
                        mineru_overlay_viewer = gr.Markdown("", label="坐标覆盖层信息")

                        gr.Markdown("### PDF 检索 (解析→切片→向量化 后查询)")
                        with gr.Column(scale=1):
                            pdf_query = gr.Textbox(label="查询", lines=2)
                            pdf_topk = gr.Slider(label="TopK", minimum=1, maximum=10, value=5, step=1)
                            pdf_query_btn = gr.Button("检索 PDF", variant="primary")

                        with gr.Column(scale=1):
                            pdf_hits_panel = gr.Markdown("", elem_id="pdf_hits_panel")
                    
                    with gr.Column(scale=1):
                        gr.Markdown("### 解析进度 & 日志")
                        pdf_status_panel = gr.Markdown("等待任务")
                        pdf_log_panel = gr.Textbox(label="实时日志", lines=20)
                        pdf_result_panel = gr.Textbox(label="结果 (完成后显示)", lines=20)
                        gr.Markdown("### MinerU 解析文档")
                        pdf_markdown_render = gr.Markdown(
                            value="尚无 Markdown 渲染结果",
                        )
                        pdf_markdown_text = gr.TextArea(
                            label="Markdown 文本",
                            lines=12,
                        )
                        pdf_bundle_file = gr.File(label="MinerU 结果 ZIP", interactive=False)
                        



            with gr.Tab("混合检索"):
                gr.Markdown("### 查询参数")
                with gr.Row():
                    query_box = gr.Textbox(label="查询", lines=2)
                    topk_slider = gr.Slider(label="TopK", minimum=1, maximum=10, value=5, step=1)
                    query_btn = gr.Button("检索", variant="primary")
                with gr.Row():
                    with gr.Column(scale=2):
                        chatbot = gr.Chatbot(label="检索对话", height=400)
                    with gr.Column(scale=1):
                        video_preview = gr.Video(label="视频预览", interactive=False)
                        audio_preview = gr.Audio(label="音频预览", interactive=False)
                        gallery = gr.Gallery(label="关键帧", columns=2, height=200)

        # 先定义 Timer，避免 UnboundLocalError
        poll_timer = gr.Timer(value=2.0, active=False)  # 默认不激活
        poll_timer.tick(
            fn=poll_basic_task,
            inputs=[task_state],
            outputs=[status_panel, result_panel, log_panel],
        )

        submit_btn.click(
            fn=submit_ingest,
            inputs=[
                file_input,
                media_type,
                title,
                description,
                tags,
                frame_strategy,
                frame_interval,
                scene_threshold,
            ],
            outputs=[ingest_status, task_state, task_payload],
        ).then(
            fn=lambda: gr.Timer(active=True),
            inputs=None,
            outputs=[poll_timer],
        )

        pdf_file.change(
            fn=_pdf_viewer_html,
            inputs=[pdf_file],
            outputs=[pdf_preview_panel],
        )

        # PDF 任务轮询 - 只更新状态、日志、Markdown，不影响预览区域
        # 先定义 Timer，避免 UnboundLocalError
        pdf_poll_timer = gr.Timer(value=3.0, active=False)  # 默认不激活
        
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
        
        pdf_poll_timer.tick(
            fn=_poll_pdf_status_only,
            inputs=[pdf_task_state],
            outputs=[
                pdf_status_panel,
                pdf_result_panel,
                pdf_log_panel,
                pdf_markdown_render,
                pdf_markdown_text,
                pdf_bundle_file,
            ],
        )

        pdf_submit.click(
            fn=submit_pdf_pipeline,
            inputs=[
                pdf_file,
                pdf_title,
                pdf_description,
                pdf_tags,
                pdf_backend,
                pdf_parse_method,
                pdf_lang_choice,
                pdf_formula_enable,
                pdf_table_enable,
                pdf_return_md,
                pdf_return_middle_json,
                pdf_return_model_output,
                pdf_return_content_list,
                pdf_return_images,
                pdf_response_zip,
                pdf_output_dir,
                pdf_server_url,
                pdf_start_page,
                pdf_end_page,
            ],
            outputs=[pdf_status, pdf_task_state, pdf_payload],
        ).then(
            fn=lambda: gr.Timer(active=True),
            inputs=None,
            outputs=[pdf_poll_timer],
        )
        
        # 手动加载 MinerU 预览（避免自动触发导致卡顿）
        def _load_mineru_preview(task_id: str):
            """手动加载预览"""
            if not task_id:
                return (
                    None,
                    "⚠️ 请先提交 PDF 任务",
                    gr.Slider(value=1, maximum=100)
                )
            try:
                pdf_file, overlay_info, current, total = render_pdf_page(task_id, 1)
                slider_update = gr.Slider(value=current, maximum=max(total, 1), minimum=1, step=1)
                return pdf_file, overlay_info, slider_update
            except Exception as exc:  # pylint: disable=broad-except
                import traceback
                error_msg = f"预览加载失败: {exc}\n\n{traceback.format_exc()}"
                return (
                    None,
                    error_msg,
                    gr.Slider(value=1, maximum=100, minimum=1, step=1)
                )

        def _update_page_view(task_id: str, page_num: int):
            """更新页面视图（翻页）"""
            if not task_id:
                return (
                    None,
                    "⚠️ 请先加载预览",
                    gr.Slider(value=1, maximum=100, minimum=1, step=1)
                )
            try:
                pdf_file, overlay_info, current, total = render_pdf_page(task_id, int(page_num))
                # 确保 slider 最大值正确，且 maximum > minimum
                safe_total = max(total, 1)
                safe_current = max(1, min(current, safe_total))
                slider_update = gr.Slider(value=safe_current, maximum=safe_total, minimum=1, step=1)
                return pdf_file, overlay_info, slider_update
            except Exception as exc:  # pylint: disable=broad-except
                import traceback
                error_msg = f"⚠️ 翻页失败: {exc}\n\n```\n{traceback.format_exc()}\n```"
                # 保持当前页码，不改变 slider
                return (
                    None,
                    error_msg,
                    gr.Slider(value=int(page_num), maximum=100, minimum=1, step=1)
                )

        # 手动加载按钮事件
        mineru_load_btn.click(
            fn=_load_mineru_preview,
            inputs=[pdf_task_state],
            outputs=[mineru_pdf_viewer, mineru_overlay_viewer, mineru_page_slider],
        )
        
        # 滑块变化事件
        mineru_page_slider.change(
            fn=_update_page_view,
            inputs=[pdf_task_state, mineru_page_slider],
            outputs=[mineru_pdf_viewer, mineru_overlay_viewer, mineru_page_slider],
        )

        pdf_query_btn.click(
            fn=run_pdf_query,
            inputs=[pdf_query, pdf_topk],
            outputs=[pdf_hits_panel],
        )

        query_btn.click(
            handle_query,
            inputs=[query_box, topk_slider, chat_history],
            outputs=[chat_history, chatbot, video_preview, audio_preview, gallery],
        )

    return demo


def main() -> None:
    # 设置 Gradio 临时目录以避免 /tmp/gradio 权限问题
    gradio_temp = Path("/home/mm-rag/data/gradio_temp")
    gradio_temp.mkdir(parents=True, exist_ok=True)
    os.environ["GRADIO_TEMP_DIR"] = str(gradio_temp)
    
    demo = build_interface()
    demo.queue().launch(server_port=7861)


if __name__ == "__main__":
    main()
