"""Preview a supported product before creating a monitoring record."""

from fastapi import APIRouter, Depends, HTTPException, Query
from data.models import User
from engine.auth import current_user
from engine.addons.registry import AddonValidationError, resolve_addon
from engine.config import ADDONS_DIR
from engine.scraper import AddonScraper

router = APIRouter(prefix="/products", tags=["discovery"])


@router.get("/preview")
def preview_product(
    url: str = Query(..., min_length=12, max_length=2048),
    store_id: str = Query(..., pattern=r"^[a-z0-9_-]+$"),
    user: User = Depends(current_user),
):
    del user
    addon_path = ADDONS_DIR / f"{store_id}.json"
    if not addon_path.is_file():
        raise HTTPException(status_code=400, detail="Unsupported store addon")
    try:
        selected = resolve_addon(url, ADDONS_DIR)
    except AddonValidationError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if selected != store_id:
        raise HTTPException(status_code=400, detail="Product URL does not match the selected store")
    try:
        with AddonScraper(str(addon_path)) as scraper:
            result = scraper.scrape(url)
    except (ValueError, OSError, RuntimeError) as exc:
        raise HTTPException(status_code=502, detail=f"Unable to preview product: {exc}") from exc
    except Exception as exc:
        raise HTTPException(status_code=502, detail="Unable to reach the store") from exc
    return {
        "ok": bool(result.get("ok")),
        "status": result.get("status", "ok" if result.get("ok") else "unavailable"),
        "reason": result.get("reason"),
        "name": result.get("product_name"),
        "url": result.get("url") or url,
        "price": result.get("price"),
        "availability": result.get("availability") or "unknown",
        "currency": result.get("currency", "BRL"),
        "store_id": store_id,
        "image_url": result.get("image_url"),
        "variants": result.get("variants", []),
    }
