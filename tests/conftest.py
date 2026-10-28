"""Independent SQLite database and authenticated administrator for each test."""
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app.auth import LOGIN_CSRF_COOKIE, create_user
from app.database import Base, get_db
from app.main import app


def login_as(client: TestClient, username: str, password: str) -> str:
    response = client.get("/login")
    assert response.status_code == 200
    csrf_token = client.cookies.get(LOGIN_CSRF_COOKIE)
    response = client.post("/login", data={"username": username, "password": password,
                                            "csrf_token": csrf_token}, follow_redirects=False)
    assert response.status_code == 303, response.text
    return client.get("/api/auth/me").json()["csrf_token"]


@pytest.fixture
def client(tmp_path):
    engine = create_engine(
        f"sqlite:///{tmp_path / 'test.db'}",
        connect_args={"check_same_thread": False},
    )
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        create_user(session, "admin", "secure_test_password_123", "admin")

    def test_db():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_db] = test_db
    try:
        test_client = TestClient(app)
        token = login_as(test_client, "admin", "secure_test_password_123")
        test_client.csrf_token = token
        test_client.test_engine = engine
        test_client.headers.update({"X-CSRF-Token": token})
        yield test_client
    finally:
        app.dependency_overrides.clear()
        engine.dispose()
