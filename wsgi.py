"""WSGI entry point for production servers, e.g. `gunicorn -w 1 wsgi:app` (see render.yaml)."""
from future_week_adjustment.app import app

__all__ = ['app']
