"""Release-candidate regression tests for shared navigation and human-facing pages."""
from html.parser import HTMLParser

import pytest

from app.version import APP_VERSION
from tests.test_incidents import high_case


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__()
        self.main_ids = []
        self.current_pages = []
        self.nav_targets = []
        self.skip_targets = []
        self.column_headers = 0

    def handle_starttag(self, tag, attrs):
        data = dict(attrs)
        if tag == "main":
            self.main_ids.append(data.get("id"))
        if tag == "a" and data.get("class") == "skip-link":
            self.skip_targets.append(data.get("href"))
        if tag == "a" and "nav" in (data.get("class") or "").split():
            self.nav_targets.append(data.get("href"))
            if data.get("aria-current") == "page":
                self.current_pages.append(data.get("href"))
        if tag == "th" and data.get("scope") == "col":
            self.column_headers += 1


@pytest.mark.parametrize("path, expected", [
    ("/", "/"),
    ("/analytics", "/analytics"),
    ("/incidents", "/incidents"),
    ("/pdf-import", "/pdf-import"),
])
def test_shared_navigation_accessible_on_main_pages(client, path, expected):
    response = client.get(path)
    assert response.status_code == 200
    html = response.text
    parsed = PageParser()
    parsed.feed(html)
    assert parsed.main_ids == ["main-content"]
    assert parsed.skip_targets == ["#main-content"]
    assert parsed.current_pages == [expected]
    assert {"/", "/analytics", "/incidents", "/pdf-import"}.issubset(parsed.nav_targets)
    assert f"v{APP_VERSION}" in html
    assert "УЧЕБНАЯ СРЕДА" in html


def test_case_detail_has_shared_navigation_and_structured_table(client):
    case = high_case(client)
    response = client.get(f"/incidents/{case['id']}")
    assert response.status_code == 200
    parser = PageParser()
    parser.feed(response.text)
    assert parser.current_pages == ["/incidents"]
    assert parser.main_ids == ["main-content"]
    assert "Управление расследованием" in response.text


def test_table_column_headers_have_scope(client):
    for path in ["/", "/analytics", "/incidents"]:
        parser = PageParser()
        parser.feed(client.get(path).text)
        assert parser.column_headers >= 4, path


def test_release_version_consistent_across_api_and_health(client):
    assert client.get("/openapi.json").json()["info"]["version"] == APP_VERSION
    assert client.get("/health").json()["version"] == APP_VERSION
    assert client.get("/ready").json()["version"] == APP_VERSION


def test_responsive_nav_and_focus_styles_are_served(client):
    response = client.get("/static/styles.css")
    assert response.status_code == 200
    for selector in [".sidebar .nav-links", ".sidebar .nav", ":focus-visible", "prefers-reduced-motion"]:
        assert selector in response.text


def test_login_view_uses_same_version_and_skip_target(client):
    client.cookies.clear()
    response = client.get("/login")
    assert response.status_code == 200
    parser = PageParser()
    parser.feed(response.text)
    assert parser.main_ids == ["main-content"]
    assert parser.skip_targets == ["#main-content"]
    assert f"v{APP_VERSION}" in response.text
