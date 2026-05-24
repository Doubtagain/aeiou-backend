"""FastAPI app entry (§6). PoC: SQLite, in-process background analysis, static
audio serving. No auth / multi-tenant (out of scope)."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from .config import AUDIO_DIR, settings
from .db import init_db, session_scope
from .routes import analysis, content, sessions
from .situations import sync_situations_to_db


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    with session_scope() as db:
        sync_situations_to_db(db)
    yield


app = FastAPI(title="VoiceUp PoC", version="0.1.0", lifespan=lifespan)

app.mount("/static/audio", StaticFiles(directory=str(AUDIO_DIR)), name="audio")

app.include_router(content.router)
app.include_router(sessions.router)
app.include_router(analysis.router)


@app.get("/health", tags=["meta"])
def health() -> dict:
    return {"status": "ok", "use_mocks": settings.use_mocks}
