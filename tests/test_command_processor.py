"""Unit tests for ORION Rule-Based Command Processing Module."""

from __future__ import annotations

from pathlib import Path

from orion.core.models import SafetyLevel
from orion.db.database import OrionDatabase
from orion.modules.command_processor import CommandProcessorModule


def _make_processor(tmp_path: Path) -> tuple[OrionDatabase, CommandProcessorModule]:
    db = OrionDatabase(tmp_path / "cmd.db")
    return db, CommandProcessorModule(db)


def test_core_synopsis_intents(tmp_path: Path) -> None:
    _, proc = _make_processor(tmp_path)

    assert proc.parse("What time is it?").intent == "get_time"
    assert proc.parse("Hey Orion, tell me today's date").intent == "get_date"
    assert proc.parse("Take a screenshot").intent == "take_screenshot"
    assert proc.parse("Open Notepad").intent == "open_app"
    assert proc.parse("Open YouTube").intent == "open_website"

    g = proc.parse("Search Google for Python Tkinter tutorial")
    assert g.intent == "search_google"
    assert g.params["query"] == "Python Tkinter tutorial"

    yt = proc.parse("Search YouTube for lo-fi coding beats")
    assert yt.intent == "search_youtube"
    assert yt.params["query"] == "lo-fi coding beats"

    wiki = proc.parse("Wikipedia Alan Turing")
    assert wiki.intent == "wikipedia"
    assert wiki.params["topic"] == "Alan Turing"

    calc = proc.parse("Calculate 25 * 4 + 10")
    assert calc.intent == "calculate"
    assert calc.params["expression"] == "25 * 4 + 10"

    note = proc.parse("Take a note submit project synopsis on Monday")
    assert note.intent == "add_note"
    assert note.params["content"] == "submit project synopsis on Monday"


def test_safety_classification_policy(tmp_path: Path) -> None:
    _, proc = _make_processor(tmp_path)

    # Blocked destructive commands (Synopsis Sec. 6)
    blocked = proc.parse("delete all files in C: drive")
    assert blocked.safety_level == SafetyLevel.BLOCKED
    assert blocked.intent == "blocked_command"

    blocked_rm = proc.parse("run rm -rf /")
    assert blocked_rm.safety_level == SafetyLevel.BLOCKED

    # Confirmation-gated sensitive commands
    lock = proc.parse("Lock my screen")
    assert lock.intent == "lock_screen"
    assert lock.safety_level == SafetyLevel.CONFIRM_REQUIRED

    shutdown = proc.parse("Shutdown computer")
    assert shutdown.intent == "system_power"
    assert shutdown.safety_level == SafetyLevel.CONFIRM_REQUIRED

    cmd_app = proc.parse("Open command prompt")
    assert cmd_app.intent == "open_app"
    assert cmd_app.safety_level == SafetyLevel.CONFIRM_REQUIRED


def test_dynamic_custom_app_and_direct_url(tmp_path: Path) -> None:
    db, proc = _make_processor(tmp_path)
    db.upsert_app("myide", "My IDE", "code")
    db.upsert_website("docs", "Python Docs", "https://docs.python.org/3/")

    p_app = proc.parse("launch myide")
    assert p_app.intent == "open_app"
    assert p_app.params["app"]["display_name"] == "My IDE"

    p_site = proc.parse("open docs")
    assert p_site.intent == "open_website"
    assert p_site.params["url"] == "https://docs.python.org/3/"

    p_direct = proc.parse("go to python.org")
    assert p_direct.intent == "open_website"
    assert p_direct.params["url"] == "python.org"
