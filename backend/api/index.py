"""Vercel entry point: the whole FastAPI app as one Python function (serverless profile, see README)."""

from app.main import create_app

app = create_app()
