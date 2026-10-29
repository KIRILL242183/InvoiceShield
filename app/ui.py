"""Shared Jinja configuration for all authenticated HTML routes."""
from fastapi.templating import Jinja2Templates
from app.version import APP_VERSION


def make_templates() -> Jinja2Templates:
    templates = Jinja2Templates(directory="app/templates")
    templates.env.globals["app_version"] = APP_VERSION
    return templates
