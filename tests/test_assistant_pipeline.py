"""Integration tests for the ORION 5-step assistant pipeline."""

from __future__ import annotations

from pathlib import Path

from orion.config import OrionConfig
from orion.core.assistant import OrionAssistant
from orion.core.models import InputMode
from orion.db.database import OrionDatabase


def _make_assistant(tmp_path: Path) -> OrionAssistant:
    cfg = OrionConfig(
        project_root=tmp_path,
        db_path=tmp_path / "orion.db",
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
    db = OrionDatabase(cfg.db_path)
    return OrionAssistant(config=cfg, db=db, enable_tts=False)


def test_end_to_end_safe_commands_and_events(tmp_path: Path) -> None:
    assistant = _make_assistant(tmp_path)
    events: list[dict] = []
    assistant.subscribe(events.append)

    try:
        r_time = assistant.process_command("What time is it?", InputMode.TEXT.value, speak_response=False)
        assert r_time.success is True
        assert r_time.intent == "get_time"
        assert "current time is" in r_time.response_text.lower()

        r_calc = assistant.process_command("Calculate 15 * 12", InputMode.TEXT.value, speak_response=False)
        assert r_calc.success is True
        assert r_calc.data["result"] == "180"

        r_note = assistant.process_command("Take a note buy headphones", InputMode.TEXT.value, speak_response=False)
        assert r_note.success is True
        r_list = assistant.process_command("Read my notes", InputMode.TEXT.value, speak_response=False)
        assert "buy headphones" in r_list.response_text

        r_sys = assistant.process_command("System status", InputMode.TEXT.value, speak_response=False)
        assert r_sys.success is True
        assert "cpu_percent" in r_sys.data

        assert any(e["type"] == "command_result" for e in events)
        assert len(assistant.db.get_history()) == 5
    finally:
        assistant.shutdown()


def test_confirmation_and_blocking_workflow(tmp_path: Path) -> None:
    assistant = _make_assistant(tmp_path)
    try:
        # 1. Blocked command never executes
        blocked = assistant.process_command("delete all files on C: drive", speak_response=False)
        assert blocked.success is False
        assert blocked.status == "blocked"

        # 2. Restricted command asks for confirmation first
        pending = assistant.process_command("Clear command history", speak_response=False)
        assert pending.requires_confirmation is True
        assert pending.status == "pending_confirmation"
        assert pending.confirmation_request is not None

        # Cancel it first -> history must still exist
        token = pending.confirmation_request.token
        cancelled = assistant.confirm_action(token, approved=False, speak_response=False)
        assert cancelled.status == "cancelled"
        assert len(assistant.db.get_history()) >= 2

        # Trigger again and approve -> history cleared
        pending2 = assistant.process_command("Clear command history", speak_response=False)
        token2 = pending2.confirmation_request.token
        approved = assistant.confirm_action(token2, approved=True, speak_response=False)
        assert approved.success is True
        assert approved.status == "success"
        assert "Cleared" in approved.response_text
    finally:
        assistant.shutdown()


def test_real_screenshot_capture(tmp_path: Path) -> None:
    assistant = _make_assistant(tmp_path)
    try:
        res = assistant.process_command("Take a screenshot", speak_response=False)
        assert res.success is True
        assert res.intent == "take_screenshot"
        shot = res.data["screenshot"]
        shot_path = Path(shot["file_path"])
        assert shot_path.exists()
        assert shot_path.stat().st_size > 0
        assert shot["width"] > 0 and shot["height"] > 0
    finally:
        assistant.shutdown()


def test_voice_output_dedup_mute_interrupt_and_replay(tmp_path: Path) -> None:
    assistant = _make_assistant(tmp_path)
    spoken_calls: list[tuple[str, bool, bool]] = []

    def fake_speak(text: str, force: bool = False, interrupt: bool = True) -> bool:
        if not assistant.tts.enabled and not force:
            return False
        assistant.tts._last_spoken_text = text
        spoken_calls.append((text, force, interrupt))
        return True

    assistant.tts.enabled = True
    assistant.tts._available = True
    assistant.tts.speak = fake_speak  # type: ignore[method-assign]

    try:
        # Normal question speaks aloud and matches displayed text
        r1 = assistant.process_command("Who are you?", speak_response=True)
        assert r1.success is True
        assert spoken_calls[-1][0] == r1.response_text
        assert spoken_calls[-1][2] is True  # interrupts any prior speech

        # Re-finalizing the exact same result must NOT cause duplicate speech
        count_before = len(spoken_calls)
        assistant._finalize_result(r1, speak_response=True)
        assert len(spoken_calls) == count_before

        # Replay speaks the last response even if called explicitly
        assert assistant.replay_last_response() is True
        assert len(spoken_calls) == count_before + 1
        assert spoken_calls[-1][0] == r1.response_text

        # Mute preference respected on subsequent responses
        assistant.set_tts_enabled(False)
        assert assistant.tts.enabled is False
        count_muted = len(spoken_calls)
        r2 = assistant.process_command("What time is it?", speak_response=True)
        assert r2.success is True
        assert len(spoken_calls) == count_muted  # muted -> no speech, text still returned

        # Unmute restores automatic speech
        assistant.set_tts_enabled(True)
        r3 = assistant.process_command("What is today's date?", speak_response=True)
        assert len(spoken_calls) == count_muted + 1
        assert spoken_calls[-1][0] == r3.response_text
    finally:
        assistant.shutdown()
