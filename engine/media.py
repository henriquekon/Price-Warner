"""Allow only store-declared HTTPS hosts for product images."""
from urllib.parse import urlsplit


def validate_product_image_url(value, addon):
    if isinstance(value, list):
        value = next((item for item in value if isinstance(item, str) and item), None)
    if not isinstance(value, str) or len(value) > 1024:
        return None
    try:
        parsed = urlsplit(value)
        allowed = addon.get("store", {}).get("image_hosts", [])
        if (parsed.scheme != "https" or not parsed.hostname or parsed.username
                or parsed.password or parsed.port is not None or not allowed
                or parsed.hostname.lower().rstrip(".") not in allowed):
            return None
    except ValueError:
        return None
    return value
