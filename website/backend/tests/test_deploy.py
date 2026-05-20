"""Smoke tests for the production WSGI deploy.

Fails if the production stack (gunicorn + the v2 WSGI entry point) is
not installable/importable in this environment. Keeps dev and server
envs in lockstep.
"""
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "../../.."))


def test_gunicorn_importable():
    """The production WSGI server must be present in the env."""
    import gunicorn  # noqa: F401


def test_wsgi_application_entry_point():
    """The callable gunicorn loads in production must be importable."""
    from website.backend.src import v2

    assert callable(v2.application)
