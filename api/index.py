"""Vercel Serverless Function entrypoint for ORION.

Allows Vercel to route requests either through `main.py` or `api/index.py`.
"""

from main import app

__all__ = ["app"]
