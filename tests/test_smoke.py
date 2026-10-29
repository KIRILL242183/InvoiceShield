"""Smoke test utility does not fetch outside loopback or mutate data."""
import json
import urllib.request

import pytest

from scripts.smoke_check import smoke_check


@pytest.mark.parametrize("url", [
    "https://127.0.0.1:8000", "http://example.com:8000", "http://127.0.0.1/x",
    "http://user:password@localhost", "http://localhost?token=secret",
])
def test_smoke_check_rejects_external_or_sensitive_urls(url):
    with pytest.raises(ValueError):
        smoke_check(url)


def test_smoke_check_validates_headers_and_status(monkeypatch):
    class FakeResponse:
        def __init__(self, path):
            self.status = 200
            self.headers = {"X-Request-ID": "abc", "X-Content-Type-Options": "nosniff"}
            self.path = path

        def read(self, size):
            assert size == 2048
            status = "ready" if self.path.endswith("/ready") else "ok"
            return json.dumps({"status": status, "version": "0.8.0"}).encode()

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout: FakeResponse(req.full_url))
    assert smoke_check("http://127.0.0.1:8000") == {"/health": "0.8.0", "/ready": "0.8.0"}
