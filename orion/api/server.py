"""FastAPI REST + WebSocket Backend for ORION Desktop Virtual Assistant."""

from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
import threading
from pathlib import Path
from typing import Any, AsyncIterator

import uvicorn
from fastapi import FastAPI, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, field_validator

from orion import __version__
from orion.core.assistant import OrionAssistant
from orion.core.models import InputMode

WEB_DIR = Path(__file__).resolve().parent.parent / "web"


# ------------------------------------------------------------------ #
# Pydantic Request Schemas
# ------------------------------------------------------------------ #
class ExecuteCommandRequest(BaseModel):
    text: str = Field(..., min_length=1, max_length=500)
    input_mode: str = Field(default=InputMode.API.value)
    speak_response: bool = Field(default=True)

    @field_validator("text")
    @classmethod
    def strip_text(cls, value: str) -> str:
        cleaned = value.strip()
        if not cleaned:
            raise ValueError("Command text cannot be empty.")
        return cleaned


class ConfirmActionRequest(BaseModel):
    token: str = Field(..., min_length=4, max_length=64)
    approved: bool


class AppUpsertRequest(BaseModel):
    alias: str = Field(..., min_length=1, max_length=60)
    display_name: str = Field(..., min_length=1, max_length=80)
    executable_path: str = Field(..., min_length=1, max_length=500)
    arguments: str = Field(default="", max_length=300)
    requires_confirmation: bool = Field(default=False)


class WebsiteUpsertRequest(BaseModel):
    alias: str = Field(..., min_length=1, max_length=60)
    display_name: str = Field(..., min_length=1, max_length=80)
    url: str = Field(..., min_length=3, max_length=500)


class NoteCreateRequest(BaseModel):
    content: str = Field(..., min_length=1, max_length=500)


class NoteToggleRequest(BaseModel):
    is_completed: bool | None = None


class SettingsUpdateRequest(BaseModel):
    settings: dict[str, Any]


class TTSTestRequest(BaseModel):
    text: str = Field(
        default="Hello! ORION text-to-speech is active and ready.",
        min_length=1,
        max_length=300,
    )


class TTSReplayRequest(BaseModel):
    text: str | None = Field(default=None, max_length=2000)


class WakeWordToggleRequest(BaseModel):
    enabled: bool


# ------------------------------------------------------------------ #
# WebSocket Connection Manager
# ------------------------------------------------------------------ #
class _WebSocketHub:
    def __init__(self) -> None:
        self._clients: set[WebSocket] = set()
        self._loop: asyncio.AbstractEventLoop | None = None
        self._lock = threading.Lock()

    def attach_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    async def connect(self, ws: WebSocket) -> None:
        await ws.accept()
        with self._lock:
            self._clients.add(ws)

    def disconnect(self, ws: WebSocket) -> None:
        with self._lock:
            self._clients.discard(ws)

    def publish_from_thread(self, event: dict[str, Any]) -> None:
        loop = self._loop
        if loop is None or loop.is_closed():
            return
        with self._lock:
            if not self._clients:
                return
        asyncio.run_coroutine_threadsafe(self._broadcast(event), loop)

    async def _broadcast(self, event: dict[str, Any]) -> None:
        with self._lock:
            targets = list(self._clients)
        stale: list[WebSocket] = []
        for ws in targets:
            try:
                await ws.send_json(event)
            except Exception:
                stale.append(ws)
        if stale:
            with self._lock:
                for ws in stale:
                    self._clients.discard(ws)


# ------------------------------------------------------------------ #
# FastAPI Application Factory
# ------------------------------------------------------------------ #
def create_app(assistant: OrionAssistant | None = None) -> FastAPI:
    if assistant is None:
        assistant = OrionAssistant()
    hub = _WebSocketHub()

    def _on_assistant_event(event: dict[str, Any]) -> None:
        hub.publish_from_thread(event)

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        hub.attach_loop(asyncio.get_running_loop())
        assistant.subscribe(_on_assistant_event)
        try:
            yield
        finally:
            assistant.unsubscribe(_on_assistant_event)

    app = FastAPI(
        title="ORION Desktop Virtual Assistant API",
        version=__version__,
        description="Local REST & WebSocket API for ORION Voice-Controlled Desktop Virtual Assistant.",
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # ---------------- Health & Status ---------------- #
    @app.get("/api/health")
    def health() -> dict[str, Any]:
        return {"status": "ok", "app": "ORION", "version": __version__}

    @app.get("/api/status")
    def status() -> dict[str, Any]:
        return assistant.get_status()

    # ---------------- Commands & Voice ---------------- #
    @app.get("/api/commands/supported")
    def supported_commands() -> dict[str, Any]:
        return {"commands": assistant.command_processor.get_supported_commands()}

    @app.post("/api/commands/execute")
    async def execute_command(body: ExecuteCommandRequest) -> dict[str, Any]:
        result = await asyncio.to_thread(
            assistant.process_command,
            body.text,
            body.input_mode,
            False,
            body.speak_response,
        )
        return result.to_dict()

    @app.post("/api/commands/listen")
    async def listen_voice_command() -> dict[str, Any]:
        result = await asyncio.to_thread(assistant.listen_and_execute)
        return result.to_dict()

    @app.post("/api/commands/confirm")
    async def confirm_command(body: ConfirmActionRequest) -> dict[str, Any]:
        result = await asyncio.to_thread(
            assistant.confirm_action, body.token, body.approved, True
        )
        if result.intent == "confirmation_expired":
            raise HTTPException(status_code=404, detail=result.response_text)
        return result.to_dict()

    @app.post("/api/wake-word/toggle")
    def toggle_wake_word(body: WakeWordToggleRequest) -> dict[str, Any]:
        if body.enabled:
            started = assistant.start_wake_word_listener()
            if not started:
                raise HTTPException(
                    status_code=400,
                    detail="Cannot enable wake-word mode because no accessible microphone was detected.",
                )
            return {"active": True}
        assistant.stop_wake_word_listener()
        return {"active": False}

    # ---------------- History ---------------- #
    @app.get("/api/history")
    def list_history(
        limit: int = Query(default=100, ge=1, le=1000),
        search: str = Query(default=""),
        status_filter: str = Query(default="", alias="status"),
    ) -> dict[str, Any]:
        items = assistant.db.get_history(
            limit=limit, search=search, status=status_filter
        )
        return {"items": items, "count": len(items)}

    @app.delete("/api/history/{history_id}")
    def delete_history_entry(history_id: int) -> dict[str, Any]:
        deleted = assistant.db.delete_history_item(history_id)
        if not deleted:
            raise HTTPException(status_code=404, detail="History entry not found.")
        return {"deleted": True, "id": history_id}

    @app.delete("/api/history")
    def clear_history() -> dict[str, Any]:
        count = assistant.db.clear_history()
        return {"cleared": True, "deleted_count": count}

    # ---------------- Applications CRUD ---------------- #
    @app.get("/api/apps")
    def list_apps() -> dict[str, Any]:
        return {"apps": assistant.db.list_apps()}

    @app.post("/api/apps", status_code=201)
    def save_app(body: AppUpsertRequest) -> dict[str, Any]:
        try:
            row = assistant.db.upsert_app(
                alias=body.alias,
                display_name=body.display_name,
                executable_path=body.executable_path,
                arguments=body.arguments,
                requires_confirmation=body.requires_confirmation,
            )
            return {"app": row}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/apps/{app_id}")
    def remove_app(app_id: int) -> dict[str, Any]:
        if not assistant.db.delete_app(app_id):
            raise HTTPException(status_code=404, detail="Application not found.")
        return {"deleted": True, "id": app_id}

    # ---------------- Websites CRUD ---------------- #
    @app.get("/api/websites")
    def list_websites() -> dict[str, Any]:
        return {"websites": assistant.db.list_websites()}

    @app.post("/api/websites", status_code=201)
    def save_website(body: WebsiteUpsertRequest) -> dict[str, Any]:
        try:
            row = assistant.db.upsert_website(
                alias=body.alias,
                display_name=body.display_name,
                url=body.url,
            )
            return {"website": row}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.delete("/api/websites/{website_id}")
    def remove_website(website_id: int) -> dict[str, Any]:
        if not assistant.db.delete_website(website_id):
            raise HTTPException(status_code=404, detail="Website not found.")
        return {"deleted": True, "id": website_id}

    # ---------------- Screenshots ---------------- #
    @app.get("/api/screenshots")
    def list_screenshots(limit: int = Query(default=40, ge=1, le=200)) -> dict[str, Any]:
        return {"screenshots": assistant.db.list_screenshots(limit=limit)}

    @app.post("/api/screenshots/capture")
    async def capture_screenshot() -> dict[str, Any]:
        result = await asyncio.to_thread(
            assistant.process_command,
            "take a screenshot",
            InputMode.QUICK_ACTION.value,
            True,
            True,
        )
        return result.to_dict()

    @app.get("/api/screenshots/{screenshot_id}/file")
    def get_screenshot_file(screenshot_id: int) -> FileResponse:
        rec = assistant.db.get_screenshot(screenshot_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Screenshot record not found.")
        path = Path(rec["file_path"])
        if not path.exists():
            raise HTTPException(status_code=404, detail="Screenshot image file missing on disk.")
        return FileResponse(str(path), media_type="image/png", filename=rec["filename"])

    @app.post("/api/screenshots/{screenshot_id}/open")
    def open_screenshot_desktop(screenshot_id: int) -> dict[str, Any]:
        rec = assistant.db.get_screenshot(screenshot_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Screenshot not found.")
        try:
            msg, data = assistant.automation.open_screenshot_file(rec["file_path"])
            return {"success": True, "message": msg, "data": data}
        except Exception as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/screenshots/{screenshot_id}")
    def delete_screenshot(screenshot_id: int) -> dict[str, Any]:
        rec = assistant.db.delete_screenshot(screenshot_id)
        if not rec:
            raise HTTPException(status_code=404, detail="Screenshot not found.")
        path = Path(rec["file_path"])
        if path.exists():
            try:
                path.unlink()
            except OSError:
                pass
        return {"deleted": True, "id": screenshot_id}

    # ---------------- Notes CRUD ---------------- #
    @app.get("/api/notes")
    def list_notes(include_completed: bool = True) -> dict[str, Any]:
        return {"notes": assistant.db.list_notes(include_completed=include_completed)}

    @app.post("/api/notes", status_code=201)
    def create_note(body: NoteCreateRequest) -> dict[str, Any]:
        try:
            return {"note": assistant.db.add_note(body.content)}
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc

    @app.patch("/api/notes/{note_id}")
    def toggle_note(note_id: int, body: NoteToggleRequest) -> dict[str, Any]:
        updated = assistant.db.toggle_note(note_id, body.is_completed)
        if not updated:
            raise HTTPException(status_code=404, detail="Note not found.")
        return {"note": updated}

    @app.delete("/api/notes/{note_id}")
    def remove_note(note_id: int) -> dict[str, Any]:
        if not assistant.db.delete_note(note_id):
            raise HTTPException(status_code=404, detail="Note not found.")
        return {"deleted": True, "id": note_id}

    # ---------------- Settings & Hardware ---------------- #
    @app.get("/api/settings")
    def get_settings() -> dict[str, Any]:
        return {"settings": assistant.get_settings()}

    @app.put("/api/settings")
    def update_settings(body: SettingsUpdateRequest) -> dict[str, Any]:
        merged = assistant.update_settings(body.settings)
        return {"settings": merged}

    @app.get("/api/devices/microphones")
    def list_microphones() -> dict[str, Any]:
        return {
            "available": assistant.voice_input.is_microphone_available(),
            "microphones": assistant.voice_input.list_microphones(),
        }

    @app.post("/api/devices/calibrate")
    async def calibrate_mic() -> dict[str, Any]:
        return await asyncio.to_thread(assistant.calibrate_microphone)

    @app.get("/api/devices/voices")
    def list_voices() -> dict[str, Any]:
        return {
            "available": assistant.tts.is_available,
            "voices": assistant.tts.list_voices(),
        }

    @app.post("/api/tts/test")
    def test_tts(body: TTSTestRequest) -> dict[str, Any]:
        queued = assistant.tts.speak(body.text, force=True, interrupt=True)
        return {"queued": queued, "tts_available": assistant.tts.is_available}

    @app.post("/api/tts/replay")
    def replay_tts(body: TTSReplayRequest | None = None) -> dict[str, Any]:
        text = body.text if body is not None else None
        queued = assistant.replay_last_response(text=text)
        return {
            "queued": queued,
            "tts_available": assistant.tts.is_available,
            "text": (text or "").strip() or assistant.tts.last_spoken_text,
        }

    @app.post("/api/tts/stop")
    def stop_tts() -> dict[str, Any]:
        assistant.tts.stop()
        return {"stopped": True}

    # ---------------- Real-Time WebSocket ---------------- #
    @app.websocket("/ws/events")
    async def events_websocket(ws: WebSocket) -> None:
        await hub.connect(ws)
        try:
            await ws.send_json({"type": "status_snapshot", "status": assistant.get_status()})
            while True:
                # Keep connection alive; accept optional ping payloads
                await ws.receive_text()
        except WebSocketDisconnect:
            hub.disconnect(ws)
        except Exception:
            hub.disconnect(ws)

    # ---------------- Companion Web Frontend ---------------- #
    if WEB_DIR.exists():
        app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")

        @app.get("/")
        def serve_index() -> FileResponse:
            return FileResponse(str(WEB_DIR / "index.html"))

    return app


class OrionAPIServer:
    """Runs the FastAPI Companion Server in a clean background thread."""

    def __init__(
        self,
        assistant: OrionAssistant,
        host: str,
        port: int,
        app: FastAPI | None = None,
    ) -> None:
        self.assistant = assistant
        self.host = host
        self.port = port
        self.app = app or create_app(assistant)
        self._server: uvicorn.Server | None = None
        self._thread: threading.Thread | None = None

    @property
    def url(self) -> str:
        return f"http://{self.host}:{self.port}"

    @property
    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(self) -> None:
        if self.is_running:
            return
        config = uvicorn.Config(
            app=self.app,
            host=self.host,
            port=self.port,
            log_level="warning",
            access_log=False,
        )
        self._server = uvicorn.Server(config)
        self._thread = threading.Thread(
            target=self._server.run, name="OrionAPIServer", daemon=True
        )
        self._thread.start()

    def stop(self) -> None:
        if self._server is not None:
            self._server.should_exit = True
        if self._thread is not None:
            self._thread.join(timeout=3.0)
