"""Read-only loopback smoke check for a running InvoiceShield deployment."""
from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from urllib.parse import urlsplit


def smoke_check(base_url: str) -> dict[str, str]:
    parsed = urlsplit(base_url)
    if parsed.scheme != "http" or parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
        raise ValueError("Поддерживается только локальный HTTP адрес 127.0.0.1/localhost")
    if parsed.username or parsed.password or parsed.query or parsed.fragment or parsed.path not in ("", "/"):
        raise ValueError("Адрес не должен содержать логин, пароль, путь или параметры")
    result = {}
    for route, expected in (("/health", "ok"), ("/ready", "ready")):
        req = urllib.request.Request(base_url.rstrip("/") + route, method="GET")
        with urllib.request.urlopen(req, timeout=5) as response:
            payload = json.loads(response.read(2048))
            if response.status != 200 or payload.get("status") != expected:
                raise ValueError(f"Неверный ответ от {route}")
            if response.headers.get("X-Content-Type-Options") != "nosniff":
                raise ValueError("Отсутствует заголовок X-Content-Type-Options")
            if not response.headers.get("X-Request-ID"):
                raise ValueError("Отсутствует заголовок X-Request-ID")
            result[route] = payload.get("version", "unknown")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="Проверка запущенного локального InvoiceShield")
    parser.add_argument("--url", default="http://127.0.0.1:8000")
    args = parser.parse_args()
    try:
        result = smoke_check(args.url)
    except (ValueError, urllib.error.URLError, OSError, json.JSONDecodeError) as exc:
        parser.exit(1, f"Smoke check failed: {exc}\n")
    print(f"InvoiceShield OK: {result}")


if __name__ == "__main__":
    main()
