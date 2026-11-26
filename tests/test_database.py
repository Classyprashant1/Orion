"""Unit tests for ORION SQLite persistence layer."""

from __future__ import annotations

from pathlib import Path

import pytest

from orion.db.database import OrionDatabase


def test_database_initializes_and_seeds_defaults(tmp_path: Path) -> None:
    db = OrionDatabase(tmp_path / "orion_test.db")
    apps = db.list_apps()
    sites = db.list_websites()
    settings = db.get_all_settings()

    assert len(apps) >= 10
    assert db.get_app_by_alias("notepad") is not None
    assert db.get_app_by_alias("command prompt")["requires_confirmation"] == 1

    assert len(sites) >= 8
    assert db.get_website_by_alias("youtube")["url"] == "https://www.youtube.com"
    assert settings["require_confirmation"] == "true"
    assert settings["tts_enabled"] == "true"


def test_apps_and_websites_crud(tmp_path: Path) -> None:
    db = OrionDatabase(tmp_path / "crud.db")

    app = db.upsert_app(
        alias="myeditor",
        display_name="My Custom Editor",
        executable_path="notepad.exe",
        requires_confirmation=True,
    )
    assert app["alias"] == "myeditor"
    assert app["requires_confirmation"] == 1
    assert db.get_app_by_alias("MYEDITOR")["display_name"] == "My Custom Editor"
    assert db.delete_app(app["id"]) is True
    assert db.get_app_by_alias("myeditor") is None

    site = db.upsert_website("portal", "University Portal", "lingayasvidyapeeth.edu.in")
    assert site["url"] == "https://lingayasvidyapeeth.edu.in"
    assert db.delete_website(site["id"]) is True

    with pytest.raises(ValueError):
        db.upsert_app("", "No Alias", "notepad.exe")


def test_notes_history_and_screenshots(tmp_path: Path) -> None:
    db = OrionDatabase(tmp_path / "records.db")

    note = db.add_note("Prepare ORION minor project demo")
    assert note["is_completed"] == 0
    toggled = db.toggle_note(note["id"])
    assert toggled is not None and toggled["is_completed"] == 1
    assert db.delete_note(note["id"]) is True

    hid = db.add_history(
        input_text="what time is it",
        input_mode="text",
        matched_intent="get_time",
        safety_level="safe",
        status="success",
        response_text="The current time is 10:00 AM.",
        execution_ms=12,
    )
    rows = db.get_history(search="time")
    assert len(rows) == 1 and rows[0]["id"] == hid

    shot = db.add_screenshot("shot1.png", str(tmp_path / "shot1.png"), 1920, 1080)
    assert db.get_screenshot(shot["id"])["width"] == 1920
    assert db.delete_screenshot(shot["id"]) is not None

    stats = db.get_stats()
    assert stats["total_commands"] == 1
    assert stats["successful_commands"] == 1
