"""FastAPI REST API & static frontend integration tests."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from orion.api.server import create_app
from orion.config import OrionConfig
from orion.core.assistant import OrionAssistant
from orion.db.database import OrionDatabase


def _make_client(tmp_path: Path) -> tuple[OrionAssistant, TestClient]:
    cfg = OrionConfig(
        project_root=tmp_path,
        db_path=tmp_path / "api_test.db",
        screenshot_dir=tmp_path / "screenshots",
        api_host="127.0.0.1",
        api_port=8765,
        auto_start_api=False,
        stt_language="en-IN",
        wake_word="orion",
        openweather_api_key="",
        default_city="Delhi",
        ai_provider="none",
        gemini_api_key="",
        gemini_model="gemini-2.0-flash",
        openai_api_key="",
        openai_model="gpt-4o-mini",
    )
    assistant = OrionAssistant(config=cfg, db=OrionDatabase(cfg.db_path), enable_tts=False)
    app = create_app(assistant)
    return assistant, TestClient(app)


def test_health_status_and_frontend_served(tmp_path: Path) -> None:
    assistant, client = _make_client(tmp_path)
    try:
        with client:
            r_health = client.get("/api/health")
            assert r_health.status_code == 200
            assert r_health.json()["status"] == "ok"

            r_status = client.get("/api/status")
            assert r_status.status_code == 200
            assert r_status.json()["state"] == "idle"

            r_index = client.get("/")
            assert r_index.status_code == 200
            assert "ORION" in r_index.text
    finally:
        assistant.shutdown()


def test_api_command_execution_confirmation_and_crud(tmp_path: Path) -> None:
    assistant, client = _make_client(tmp_path)
    try:
        with client:
            # Execute command
            r_exec = client.post(
                "/api/commands/execute",
                json={"text": "What is today's date?", "speak_response": False},
            )
            assert r_exec.status_code == 200
            payload = r_exec.json()
            assert payload["success"] is True
            assert payload["intent"] == "get_date"

            # Validation error on blank command
            r_blank = client.post("/api/commands/execute", json={"text": "   "})
            assert r_blank.status_code == 422

            # Confirmation flow via API
            r_conf = client.post(
                "/api/commands/execute",
                json={"text": "Clear command history", "speak_response": False},
            )
            assert r_conf.json()["requires_confirmation"] is True
            token = r_conf.json()["confirmation_request"]["token"]

            r_cancel = client.post(
                "/api/commands/confirm", json={"token": token, "approved": False}
            )
            assert r_cancel.status_code == 200
            assert r_cancel.json()["status"] == "cancelled"

            # Apps CRUD
            r_app = client.post(
                "/api/apps",
                json={
                    "alias": "demoapp",
                    "display_name": "Demo App",
                    "executable_path": "notepad.exe",
                    "requires_confirmation": False,
                },
            )
            assert r_app.status_code == 201
            app_id = r_app.json()["app"]["id"]
            assert client.delete(f"/api/apps/{app_id}").status_code == 200

            # Websites CRUD
            r_site = client.post(
                "/api/websites",
                json={
                    "alias": "demo",
                    "display_name": "Demo Site",
                    "url": "example.com",
                },
            )
            assert r_site.status_code == 201
            site_id = r_site.json()["website"]["id"]
            assert client.delete(f"/api/websites/{site_id}").status_code == 200

            # Notes CRUD
            r_note = client.post("/api/notes", json={"content": "Test API note"})
            assert r_note.status_code == 201
            note_id = r_note.json()["note"]["id"]
            r_patch = client.patch(f"/api/notes/{note_id}", json={"is_completed": True})
            assert r_patch.json()["note"]["is_completed"] == 1
            assert client.delete(f"/api/notes/{note_id}").status_code == 200

            # Settings update
            r_set = client.put(
                "/api/settings",
                json={"settings": {"user_name": "Prashant", "tts_rate": "190"}},
            )
            assert r_set.status_code == 200
            assert r_set.json()["settings"]["user_name"] == "Prashant"

            # TTS replay & stop endpoints
            r_replay = client.post("/api/tts/replay", json={"text": "Replay test"})
            assert r_replay.status_code == 200
            assert r_replay.json()["text"] == "Replay test"

            r_stop = client.post("/api/tts/stop")
            assert r_stop.status_code == 200
            assert r_stop.json()["stopped"] is True
    finally:
        assistant.shutdown()
