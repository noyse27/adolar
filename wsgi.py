"""WSGI entry point used by Gunicorn and other production servers."""

from adolar.application import app

__all__ = ["app"]
