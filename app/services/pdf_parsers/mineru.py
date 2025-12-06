"""MinerU PDF parser plugin."""
from __future__ import annotations

import json
import shutil
from io import BytesIO
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple
import zipfile

import requests

from app.config import settings
from app.logging_utils import get_pipeline_logger
from app.services import storage

logger = get_pipeline_logger("pdf_parser.mineru")


class MinerUPdfParser:
    name = "mineru"

    def __init__(self) -> None:
        base = (settings.mineru_api_base or "http://127.0.0.1:8000").rstrip("/")
        self.base_url = base or None
        self.api_key = settings.mineru_api_key
        self.parse_path = settings.mineru_parse_path or "/file_parse"

    @property
    def enabled(self) -> bool:
        return bool(self.base_url)

    def _headers(self, content_type: Optional[str] = None) -> Dict[str, str]:
        headers: Dict[str, str] = {}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        if content_type:
            headers["Content-Type"] = content_type
        return headers

    @staticmethod
    def _normalize_langs(raw: Any) -> List[str]:
        if raw is None:
            return []
        if isinstance(raw, str):
            candidates: Sequence[str] = [raw]
        elif isinstance(raw, Sequence):
            candidates = raw
        else:
            return []
        langs: List[str] = []
        for item in candidates:
            text = str(item).strip()
            if text:
                langs.append(text)
        return langs

    @staticmethod
    def _bool_flag(value: Any) -> Optional[str]:
        if value is None:
            return None
        return "true" if bool(value) else "false"

    @staticmethod
    def _int_value(value: Any) -> Optional[str]:
        if value is None or value == "":
            return None
        try:
            return str(int(float(value)))
        except (ValueError, TypeError):
            return None

    @staticmethod
    def _block_text(block: Dict[str, Any]) -> str:
        lines = block.get("lines") or []
        pieces: List[str] = []
        for line in lines:
            spans = line.get("spans") or []
            for span in spans:
                text = span.get("content")
                if text:
                    pieces.append(str(text))
        return "\n".join(piece.strip() for piece in pieces if str(piece).strip()).strip()

    @classmethod
    def _pages_from_middle_json(cls, middle_json: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if not isinstance(middle_json, dict):
            return []
        pages: List[Dict[str, Any]] = []
        for idx, info in enumerate(middle_json.get("pdf_info", []) or [], start=1):
            page_idx = info.get("page_idx")
            page_number = int(page_idx) + 1 if isinstance(page_idx, (int, float)) else idx
            blocks_payload = []
            for block in info.get("preproc_blocks", []) or []:
                text = cls._block_text(block)
                if not text:
                    continue
                blocks_payload.append(
                    {
                        "text": text,
                        "type": block.get("type"),
                        "bbox": block.get("bbox"),
                    }
                )
            if blocks_payload:
                pages.append({"page_number": page_number, "blocks": blocks_payload})
        return pages

    @staticmethod
    def _pages_from_content_list(content_list: Optional[List[Dict[str, Any]]]) -> List[Dict[str, Any]]:
        if not isinstance(content_list, list):
            return []
        by_page: Dict[int, List[Dict[str, Any]]] = {}
        for item in content_list:
            text = item.get("text") or item.get("content")
            if not text:
                continue
            page_idx = item.get("page_idx")
            page_number = int(page_idx) + 1 if isinstance(page_idx, (int, float)) else 1
            block = {
                "text": str(text).strip(),
                "type": item.get("type"),
                "bbox": item.get("bbox"),
            }
            if not block["text"]:
                continue
            by_page.setdefault(page_number, []).append(block)
        pages: List[Dict[str, Any]] = []
        for page_number in sorted(by_page.keys()):
            pages.append({"page_number": page_number, "blocks": by_page[page_number]})
        return pages

    def _decode_zip_payload(
        self,
        raw_bytes: bytes,
        document_id: Optional[str] = None,
    ) -> Tuple[Dict[str, Any], Dict[str, bytes]]:
        buffer = BytesIO(raw_bytes)
        md_content: Optional[str] = None
        middle_json: Optional[Dict[str, Any]] = None
        content_list: Optional[List[Dict[str, Any]]] = None
        asset_map: Dict[str, bytes] = {}
        entry_records: List[str] = []
        with zipfile.ZipFile(buffer) as archive:
            for info in archive.infolist():
                entry_records.append(f"{info.filename} ({info.file_size}B)")
                member = info.filename
                lower = member.lower()
                if member.endswith("/"):
                    continue
                data = archive.read(member)
                asset_map[member] = data
                if lower.endswith(".md"):
                    md_content = data.decode("utf-8", errors="ignore")
                elif lower.endswith("middle.json"):
                    middle_json = json.loads(data.decode("utf-8"))
                elif lower.endswith("content_list.json"):
                    content_list = json.loads(data.decode("utf-8"))
        if entry_records:
            preview = entry_records[:20]
            if len(entry_records) > 20:
                preview.append("...")
            logger.info(
                "MinerU ZIP entries for %s: %s",
                document_id or "<unknown>",
                ", ".join(preview),
            )
        pages = self._pages_from_content_list(content_list)
        if not pages:
            pages = self._pages_from_middle_json(middle_json)
        payload: Dict[str, Any] = {
            "pages": pages,
            "md_content": md_content,
            "middle_json": middle_json,
            "content_list": content_list,
            "source": "mineru_zip",
            "zip_entries": list(asset_map.keys()),
        }
        logger.info(
            "MinerU ZIP decode summary for %s -> pages=%d, has_md=%s, has_middle_json=%s, has_content_list=%s",
            document_id or "<unknown>",
            len(pages),
            bool(md_content),
            bool(middle_json),
            bool(content_list),
        )
        return payload, asset_map

    def _persist_mineru_assets(
        self,
        document_id: str,
        asset_map: Dict[str, bytes],
        pdf_path: Path,
    ) -> Tuple[Optional[Path], Optional[Path], Optional[Path]]:
        if not asset_map:
            artifacts_dir = None
        else:
            artifacts_dir = settings.data_root / "intermediate" / "mineru_assets" / document_id
            if artifacts_dir.exists():
                shutil.rmtree(artifacts_dir)
            artifacts_dir.mkdir(parents=True, exist_ok=True)
            for name, data in asset_map.items():
                safe_name = name.strip("/\n\r") or "payload.bin"
                target = artifacts_dir / safe_name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
        layout_pdf: Optional[Path] = None
        if artifacts_dir:
            for candidate in artifacts_dir.rglob("*_layout.pdf"):
                layout_pdf = candidate
                break
        if pdf_path.exists():
            if artifacts_dir is None:
                artifacts_dir = settings.data_root / "intermediate" / "mineru_assets" / document_id
                if artifacts_dir.exists():
                    shutil.rmtree(artifacts_dir)
                artifacts_dir.mkdir(parents=True, exist_ok=True)
            original_target = artifacts_dir / "original_pdf.pdf"
            shutil.copy(pdf_path, original_target)
            if layout_pdf is None:
                layout_pdf = original_target
        bundle_path: Optional[Path] = None
        if artifacts_dir and any(artifacts_dir.rglob("*")):
            buffer = BytesIO()
            with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
                for file_path in artifacts_dir.rglob("*"):
                    if file_path.is_file():
                        archive.write(file_path, file_path.relative_to(artifacts_dir).as_posix())
            buffer.seek(0)
            bundle_dir = settings.data_root / "intermediate" / "mineru_bundle"
            bundle_path = storage.persist_intermediate(buffer, bundle_dir, f"{document_id}.zip")
        return artifacts_dir, bundle_path, layout_pdf

    @staticmethod
    def _log_payload_overview(document_id: str, payload: Any, source: str) -> None:
        if not isinstance(payload, dict):
            logger.info(
                "MinerU %s payload for %s is non-dict (%s)",
                source,
                document_id,
                type(payload).__name__,
            )
            return
        keys = list(payload.keys())
        preview = keys[:10]
        if len(keys) > 10:
            preview.append("...")
        target = payload.get("result") if isinstance(payload.get("result"), dict) else payload
        pages = target.get("pages") if isinstance(target, dict) else None
        page_count = len(pages) if isinstance(pages, list) else 0
        artifacts = target.get("artifacts")
        artifacts_preview = ""
        if isinstance(artifacts, dict):
            artifacts_keys = list(artifacts.keys())
            artifacts_preview = ", ".join(artifacts_keys[:10])
            if len(artifacts_keys) > 10:
                artifacts_preview += ", ..."
        logger.info(
            "MinerU %s payload for %s -> keys=[%s], pages=%d, artifacts_keys=%s",
            source,
            document_id,
            ", ".join(preview) or "(none)",
            page_count,
            artifacts_preview or "(none)",
        )

    def parse(
        self,
        pdf_path: Path,
        document_id: str,
        options: Dict[str, Any] | None = None,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        if not self.enabled or not self.base_url:
            raise RuntimeError("MinerU base URL is not configured")

        opts = options or {}
        backend = str(opts.get("backend") or "pipeline")
        parse_method = str(opts.get("parse_method") or "auto")
        langs = self._normalize_langs(opts.get("lang_list")) or ["ch"]

        form_entries: List[Tuple[str, Any]] = [
            ("document_id", document_id),
            ("backend", backend),
            ("parse_method", parse_method),
        ]
        for lang in langs:
            form_entries.append(("lang_list", lang))

        bool_fields = [
            "formula_enable",
            "table_enable",
            "return_md",
            "return_middle_json",
            "return_model_output",
            "return_content_list",
            "return_images",
            "response_format_zip",
        ]
        for field in bool_fields:
            flag = self._bool_flag(opts.get(field))
            if flag is not None:
                form_entries.append((field, flag))

        if settings.mineru_callback_url:
            form_entries.append(("callback_url", settings.mineru_callback_url))

        for key in ("output_dir", "server_url"):
            value = str(opts.get(key) or "").strip()
            if value:
                form_entries.append((key, value))

        for page_key in ("start_page_id", "end_page_id"):
            page_value = self._int_value(opts.get(page_key))
            if page_value is not None:
                form_entries.append((page_key, page_value))

        endpoint = f"{self.base_url}{self.parse_path}"
        with pdf_path.open("rb") as handler:
            files = [("files", (pdf_path.name, handler, "application/pdf"))]
            logger.info("Submitting %s to MinerU endpoint %s", pdf_path.name, endpoint)
            response = requests.post(
                endpoint,
                headers=self._headers(),
                data=form_entries,
                files=files,
                timeout=settings.mineru_timeout,
            )
        try:
            response.raise_for_status()
        except requests.HTTPError as exc:  # type: ignore[attr-defined]
            detail = response.text.strip()
            logger.error(
                "MinerU parse request failed with status %s: %s",
                response.status_code,
                detail or "(empty response)",
            )
            raise requests.HTTPError(
                f"MinerU error {response.status_code}: {detail or exc}", response=response
            ) from exc

        payload: Dict[str, Any]
        artifacts: Dict[str, Any] = {}
        try:
            payload = response.json()
            self._log_payload_overview(document_id, payload, "json")
        except requests.exceptions.JSONDecodeError:
            content_type = (response.headers.get("Content-Type") or "").lower()
            raw_bytes = response.content or b""
            if not raw_bytes:
                raw_bytes = (response.text or "").encode("utf-8")
            if "zip" in content_type or raw_bytes.startswith(b"PK"):
                artifact_path = storage.persist_auxiliary_bytes(
                    document_id,
                    raw_bytes,
                    suffix=".zip",
                    category="mineru_raw",
                )
                logger.info("MinerU returned ZIP payload, saved to %s", artifact_path)
                try:
                    payload, asset_map = self._decode_zip_payload(raw_bytes, document_id=document_id)
                except Exception as exc:  # pylint: disable=broad-except
                    logger.exception("Failed to decode MinerU ZIP payload: %s", exc)
                    raise RuntimeError(
                        f"MinerU ZIP payload could not be parsed (saved to {artifact_path})"
                    ) from exc
                self._log_payload_overview(document_id, payload, "zip")
                artifacts["mineru_zip_path"] = str(artifact_path)
                asset_dir, bundle_path, layout_pdf = self._persist_mineru_assets(
                    document_id,
                    asset_map,
                    pdf_path,
                )
                if asset_dir:
                    artifacts["mineru_asset_dir"] = str(asset_dir)
                if bundle_path:
                    artifacts["mineru_bundle_path"] = str(bundle_path)
                if layout_pdf:
                    artifacts["mineru_layout_pdf_path"] = str(layout_pdf)
            else:
                if "json" in content_type:
                    suffix = ".json"
                elif "html" in content_type or "text" in content_type:
                    suffix = ".txt"
                else:
                    suffix = ".bin"
                artifact_path = storage.persist_auxiliary_bytes(
                    document_id,
                    raw_bytes,
                    suffix=suffix,
                    category="mineru_raw",
                )
                logger.error(
                    "MinerU returned non-JSON payload (Content-Type=%s). Raw response saved to %s",
                    content_type or "unknown",
                    artifact_path,
                )
                raise RuntimeError(
                    f"MinerU returned non-JSON payload (saved to {artifact_path})"
                )

        extras = {
            "parser": self.name,
            "mineru_endpoint": endpoint,
        }
        artifacts.setdefault("original_pdf_path", str(pdf_path))
        artifacts.setdefault("pdf_source_path", str(pdf_path))
        if artifacts:
            logger.info(
                "MinerU artifacts ready for document %s: %s",
                document_id,
                ", ".join(f"{k}={Path(v).name if isinstance(v, str) else v}" for k, v in artifacts.items())
            )
            extras.setdefault("artifacts", {}).update(artifacts)
        return payload.get("result") or payload, extras
