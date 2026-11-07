"""Image cache behavior without network access or personal browser state."""

import hashlib
from unittest.mock import patch

from fastapi.testclient import TestClient
from data.models import User
from engine import image_cache
from engine.auth import current_user
from main import app

PNG = (b'\x89PNG\r\n\x1a\n' + b'\x00' * 26)
URL = 'https://images.kabum.com.br/produtos/fotos/123.png'


def test_image_cache_downloads_only_once_and_serves_local_copy(tmp_path, monkeypatch):
    monkeypatch.setattr(image_cache, 'CACHE_ROOT', tmp_path)
    monkeypatch.setattr(image_cache, 'MIN_REQUEST_SPACING_SECONDS', 0)
    app.dependency_overrides[current_user] = lambda: User(id=1, email='user@example.test')
    try:
        with patch.object(image_cache, '_download_image', return_value=PNG) as get_image:
            with TestClient(app) as client:
                params = {'store_id': 'kabum', 'url': URL}
                first = client.get('/media/image', params=params)
                second = client.get('/media/image', params=params)
                denied = client.get('/media/image', params={
                    'store_id': 'kabum', 'url': 'https://example.com/picture.png'})
        assert first.status_code == 200
        assert first.headers['content-type'].startswith('image/png')
        assert first.content == PNG
        assert second.status_code == 200
        assert get_image.call_count == 1
        assert denied.status_code == 400
        assert list(tmp_path.glob('*.img'))
    finally:
        app.dependency_overrides.clear()


def test_image_cache_failure_is_not_retried_for_each_render(tmp_path, monkeypatch):
    monkeypatch.setattr(image_cache, 'CACHE_ROOT', tmp_path)
    monkeypatch.setattr(image_cache, 'MIN_REQUEST_SPACING_SECONDS', 0)
    with patch.object(image_cache, '_download_image', side_effect=ValueError('Not an image')) as get_image:
        assert image_cache.cached_image_path(URL) is None
        assert image_cache.cached_image_path(URL) is None
    assert get_image.call_count == 1
    assert list(tmp_path.glob('*.failed'))


def test_browser_image_source_is_local_without_download():
    with patch.object(image_cache, '_download_image') as get_image:
        proxy = image_cache.image_proxy_url(URL, 'kabum')
        assert proxy.startswith('/media/image?store_id=kabum&url=')
        assert image_cache.image_proxy_url('https://evil.test/a.png', 'kabum') is None
        get_image.assert_not_called()
