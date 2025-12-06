from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

import gradio as gr
import requests

API_BASE_URL = os.environ.get("API_BASE_URL", "http://localhost:8000")
DEFAULT_TIMEOUT = float(os.environ.get("API_TIMEOUT", "90"))
API_APP_ID = os.environ.get("API_APP_ID")
API_APP_KEY = os.environ.get("API_APP_KEY")

_AUTH_HEADERS = {"X-Appid": API_APP_ID, "X-Key": API_APP_KEY} if (API_APP_ID and API_APP_KEY) else {}


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


def _file_tuple(file_obj: Any) -> Tuple[str, bytes]:
    if file_obj is None:
        raise ValueError("未选择文件")
    if isinstance(file_obj, str):
        path = Path(file_obj)
    else:
        path = Path(getattr(file_obj, "name", ""))
    if not path.exists():
        raise FileNotFoundError(f"无法读取文件: {path}")
    content = path.read_bytes()
    return path.name, content


def submit_ingest(
    file_obj: Any,
    media_type: str,
    title: str,
    description: str,
    tags_text: str,
    frame_strategy: str,
    frame_interval: float,
    scene_threshold: float,
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


def poll_task(task_id: str) -> Tuple[str, str, str]:
    if not task_id:
        return "等待任务", "", ""
    try:
        resp = requests.get(f"{API_BASE_URL}/tasks/{task_id}", headers=_headers(), timeout=15)
        resp.raise_for_status()
        task = resp.json()
    except Exception as exc:  # pylint: disable=broad-except
        return f"任务查询失败：{_format_request_error(exc)}", "", ""

    status_line = f"状态：{task.get('status')}"
    detail = task.get("detail")
    if detail:
        status_line += f"\n说明：{detail}"
    result_block = json.dumps(task.get("result") or {}, ensure_ascii=False, indent=2) if task.get("result") else ""
    log_text = _fetch_logs(task_id)
    return status_line, result_block, log_text


def build_interface() -> gr.Blocks:
    with gr.Blocks(title="Multimodal RAG Console") as demo:
        gr.Markdown("# 多模态 RAG 控制台\n上传音/视频，查看任务进展，并进行混合检索。")
        task_state = gr.State("")
        chat_history = gr.State([])

        with gr.Tabs():
            with gr.Tab("上传处理"):
                with gr.Row():
                    with gr.Column(scale=2):
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
        )

        poll_timer = gr.Timer(value=2.0, active=True)
        poll_timer.tick(
            fn=poll_task,
            inputs=[task_state],
            outputs=[status_panel, result_panel, log_panel],
        )

        query_btn.click(
            handle_query,
            inputs=[query_box, topk_slider, chat_history],
            outputs=[chat_history, chatbot, video_preview, audio_preview, gallery],
        )

    return demo


def main() -> None:
    demo = build_interface()
    demo.queue().launch()


if __name__ == "__main__":
    main()
