"""Discovery preview endpoint tests without external requests."""
from unittest.mock import patch

from fastapi.testclient import TestClient
from data.models import User
from engine.auth import current_user
from main import app


def test_preview_uses_registered_addon_without_network():
    app.dependency_overrides[current_user] = lambda: User(id=1, email="test@example.test")
    try:
        with patch("engine.discovery_api.AddonScraper") as scraper:
            scraper.return_value.__enter__.return_value.scrape.return_value = {
                "ok": True, "status": "ok", "product_name": "Demo item", "price": 35.91,
                "url": "https://www.amazon.com.br/dp/B08KK3FB5G", "availability": "in_stock",
            }
            with TestClient(app) as client:
                response = client.get("/products/preview", params={"store_id": "amazon_br", "url": "https://www.amazon.com.br/dp/B08KK3FB5G"})
            assert response.status_code == 200
            assert response.json()["name"] == "Demo item"
            assert response.json()["price"] == 35.91
            scraper.return_value.__enter__.return_value.scrape.assert_called_once()
    finally:
        app.dependency_overrides.clear()


def test_preview_rejects_foreign_domain():
    app.dependency_overrides[current_user] = lambda: User(id=1, email="test@example.test")
    try:
        with TestClient(app) as client:
            response = client.get("/products/preview", params={"store_id":"amazon_br", "url":"https://example.com/dp/B08KK3FB5G"})
        assert response.status_code == 400
    finally:
        app.dependency_overrides.clear()
