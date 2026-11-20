"""The web/API process. Serves the API and the built UI."""

from pathlib import Path

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from concierge.config import STATIC_DIR

app = FastAPI(title="Appointment Concierge (simulated)")


@app.get("/api/health")
async def health():
    return {"status": "ok"}


if Path(STATIC_DIR).is_dir():  # last: the API routes above win
    app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="ui")
