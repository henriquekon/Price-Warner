"""Persistently cache allowed store images and serve them from our own origin."""

from __future__ import annotations

import hashlib
import logging
import os
import tempfile
import threading
import time
from pathlib import Path
from urllib.parse import urlencode

import httpx
from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse, Response

from data.models import User
from engine.addons.registry import AddonValidationError, load_addon
from engine.auth import current_user
from engine.config import ADDONS_DIR
from engine.media import validate_product_image_url

router = APIRouter(prefix="/media", tags=["media"])
logger = logging.getLogger(__name__)

CACHE_ROOT = Path(os.getenv("PRICE_WARNER_DATA_DIR", "data")) / "image-cache"
MAX_IMAGE_BYTES = 3 * 1024 * 1024
RETRY_FAILURE_AFTER_SECONDS = 6 * 60 * 60
MIN_REQUEST_SPACING_SECONDS = 1.5
_lock = threading.Lock()
_last_request = 0.0


def image_proxy_url(source_url: str | None, store_id: str) -> str | None:
    """Give browsers a same-origin URL without changing the stored source URL."""
    if not source_url:
        return None
    try:
        addon = load_addon(ADDONS_DIR / f"{store_id}.json")
    except (AddonValidationError, OSError, ValueError):
        return None
    if validate_product_image_url(source_url, addon) is None:
        return None
    return "/media/image?" + urlencode({"store_id": store_id, "url": source_url})


def _image_media_type(data: bytes) -> str | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp"
    if len(data) >= 12 and data[4:8] == b"ftyp" and data[8:12] in (b"avif", b"avis"):
        return "image/avif"
    return None


def _download_image(url: str) -> bytes:
    headers = {"User-Agent": "Price-Warner/1.0 (self-hosted image cache)",
               "Accept": "image/avif,image/webp,image/png,image/jpeg,image/gif"}
    chunks = bytearray()
    with httpx.Client(timeout=10, follow_redirects=False, headers=headers, trust_env=False) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()
            if response.is_redirect:
                raise ValueError("Image redirects are not supported")
            if not response.headers.get("content-type", "").lower().startswith("image/"):
                raise ValueError("The store did not return image content")
            for part in response.iter_bytes():
                if len(chunks) + len(part) > MAX_IMAGE_BYTES:
                    raise ValueError("Image exceeds the allowed size")
                chunks.extend(part)
    if not _image_media_type(chunks):
        raise ValueError("Unsupported image format")
    return bytes(chunks)


def cached_image_path(url: str) -> Path | None:
    """Cache once per distinct URL; store failed attempts briefly to avoid retry storms."""
    global _last_request
    key = hashlib.sha256(url.encode("utf-8")).hexdigest()
    path = CACHE_ROOT / f"{key}.img"
    failed = CACHE_ROOT / f"{key}.failed"
    with _lock:
        if path.is_file():
            return path
        if failed.exists() and time.time() - failed.stat().st_mtime < RETRY_FAILURE_AFTER_SECONDS:
            return None
        CACHE_ROOT.mkdir(parents=True, exist_ok=True)
        remaining = MIN_REQUEST_SPACING_SECONDS - (time.monotonic() - _last_request)
        if _last_request and remaining > 0:
            time.sleep(remaining)
        _last_request = time.monotonic()
        try:
            content = _download_image(url)
            temporary = None
            try:
                with tempfile.NamedTemporaryFile(dir=CACHE_ROOT, prefix=".image-", delete=False) as handle:
                    temporary = Path(handle.name)
                    handle.write(content)
                os.replace(temporary, path)
            finally:
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
            failed.unlink(missing_ok=True)
            return path
        except (httpx.HTTPError, OSError, ValueError) as exc:
            logger.warning("Unable to cache store image: %s", type(exc).__name__)
            try:
                failed.touch()
            except OSError:
                logger.warning("Unable to record image cache failure")
            return None


@router.get("/image", include_in_schema=False)
def serve_image(
    store_id: str = Query(..., pattern=r"^[a-z0-9_-]+$"),
    url: str = Query(..., min_length=12, max_length=1024),
    user: User = Depends(current_user),
):
    del user
    if image_proxy_url(url, store_id) is None:
        raise HTTPException(400, "Unsupported product image")
    path = cached_image_path(url)
    if path is None:
        return Response(status_code=404, headers={"Cache-Control": "private, max-age=300"})
    with path.open("rb") as handle:
        media_type = _image_media_type(handle.read(32))
    if media_type is None:
        raise HTTPException(404, "Invalid cached image")
    return FileResponse(path, media_type=media_type,
                        headers={"Cache-Control": "private, max-age=86400",
                                 "X-Content-Type-Options": "nosniff"})
