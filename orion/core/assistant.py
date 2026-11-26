"""ORION Core Assistant Orchestrator (Synopsis Section 7 Pipeline).

Coordinates the 5-step working pipeline:
  1. Input (Microphone or Text Entry)
  2. Speech Recognition
  3. Command Processing & Safety Classification
  4. Confirmation Gate (for sensitive actions) & Task Execution
  5. Display, Database Persistence & Spoken Response (TTS)
"""

from __future__ import annotations

import threading
import time
import uuid
from datetime import datetime, timezone
from typing import Any, Callable

from orion.config import OrionConfig
from orion.core.models import (
    AssistantState,
    CommandResult,
    ConfirmationRequest,
    InputMode,
    ParsedCommand,
    SafetyLevel,
)
from orion.db.database import OrionDatabase
from orion.modules.ai_provider import AIProviderModule
from orion.modules.command_processor import CommandProcessorModule
from orion.modules.desktop_automation import DesktopAutomationModule
from orion.modules.info_services import InfoServices
from orion.modules.speech_recognition_engine import (
    SpeechNotUnderstoodError,
    SpeechRecognitionError,
    SpeechRecognitionModule,
    SpeechServiceUnavailableError,
)
from orion.modules.tts_engine import TextToSpeechModule
from orion.modules.voice_input import (
    VoiceInputError,
    VoiceInputModule,
    VoiceInputTimeout,
)

EventCallback = Callable[[dict[str, Any]], None]


class OrionAssistant:
    """Central service coordinating all six ORION synopsis modules."""

    def __init__(
        self,
        config: OrionConfig | None = None,
        db: OrionDatabase | None = None,
        enable_tts: bool = True,
    ) -> None:
        self.config = config or OrionConfig.load()
        self.db = db or OrionDatabase(self.config.db_path)

        self._state = AssistantState.IDLE
        self._state_detail = "Ready for voice or text command"
        self._state_lock = threading.RLock()
        self._subscribers: list[EventCallback] = []
        self._subscribers_lock = threading.RLock()

        # Pending confirmation tokens: token -> (ConfirmationRequest, ParsedCommand)
        self._pending_confirmations: dict[str, tuple[ConfirmationRequest, ParsedCommand]] = {}
        self._confirm_lock = threading.RLock()

        # Listening & wake-word concurrency guards
        self._listen_lock = threading.Lock()
        self._wake_stop_event = threading.Event()
        self._wake_thread: threading.Thread | None = None
        self._last_spoken_key: str | None = None
        self._last_response_text: str = ""

        # Load persisted settings
        settings = self.db.get_all_settings()
        mic_idx_raw = settings.get("stt_mic_index", "").strip()
        mic_idx = int(mic_idx_raw) if mic_idx_raw.isdigit() else None

        # Instantiate the 6 Synopsis Modules + modular extensions
        self.voice_input = VoiceInputModule(device_index=mic_idx)
        self.speech_recognizer = SpeechRecognitionModule(
            recognizer=self.voice_input.recognizer,
            language=settings.get("stt_language") or self.config.stt_language,
            engine=settings.get("stt_engine", "google"),
        )
        self.command_processor = CommandProcessorModule(self.db)
        self.automation = DesktopAutomationModule(self.config, self.db)
        self.info_services = InfoServices(self.config)
        self.ai_provider = AIProviderModule(self.config)

        tts_enabled = enable_tts and (settings.get("tts_enabled", "true").lower() == "true")
        self.tts = TextToSpeechModule(
            enabled=tts_enabled,
            rate=int(settings.get("tts_rate", "175") or 175),
            volume=float(settings.get("tts_volume", "0.95") or 0.95),
            voice_id=settings.get("tts_voice_id", ""),
            on_speaking_change=self._handle_tts_speaking_change,
        )

    # ------------------------------------------------------------------ #
    # Event Bus & State Management
    # ------------------------------------------------------------------ #
    def subscribe(self, callback: EventCallback) -> None:
        with self._subscribers_lock:
            if callback not in self._subscribers:
                self._subscribers.append(callback)

    def unsubscribe(self, callback: EventCallback) -> None:
        with self._subscribers_lock:
            if callback in self._subscribers:
                self._subscribers.remove(callback)

    def _emit(self, event_type: str, payload: dict[str, Any]) -> None:
        event = {
            "type": event_type,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            **payload,
        }
        with self._subscribers_lock:
            callbacks = list(self._subscribers)
        for cb in callbacks:
            try:
                cb(event)
            except Exception:
                pass

    def _set_state(self, state: AssistantState, detail: str = "") -> None:
        with self._state_lock:
            self._state = state
            self._state_detail = detail or state.value.replace("_", " ").title()
        self._emit(
            "state_changed",
            {"state": self._state.value, "detail": self._state_detail},
        )

    def _handle_tts_speaking_change(self, speaking: bool) -> None:
        with self._state_lock:
            if speaking:
                if self._state in {AssistantState.IDLE, AssistantState.EXECUTING}:
                    self._state = AssistantState.SPEAKING
                    self._state_detail = "Speaking response..."
                    self._emit(
                        "state_changed",
                        {"state": self._state.value, "detail": self._state_detail},
                    )
            else:
                if self._state == AssistantState.SPEAKING:
                    self._state = AssistantState.IDLE
                    self._state_detail = "Ready for voice or text command"
                    self._emit(
                        "state_changed",
                        {"state": self._state.value, "detail": self._state_detail},
                    )

    def get_status(self) -> dict[str, Any]:
        with self._state_lock:
            state = self._state.value
            detail = self._state_detail
        with self._confirm_lock:
            pending = [req.to_dict() for req, _ in self._pending_confirmations.values()]
        return {
            "state": state,
            "detail": detail,
            "tts_available": self.tts.is_available,
            "tts_enabled": self.tts.enabled,
            "tts_speaking": self.tts.is_speaking,
            "microphone_available": self.voice_input.is_microphone_available(),
            "wake_word_active": self.is_wake_word_running(),
            "ai_provider": self.ai_provider.status_info(),
            "weather_api_configured": bool(self.config.openweather_api_key),
            "pending_confirmations": pending,
            "stats": self.db.get_stats(),
        }

    # ------------------------------------------------------------------ #
    # Settings Synchronization
    # ------------------------------------------------------------------ #
    def get_settings(self) -> dict[str, str]:
        return self.db.get_all_settings()

    def update_settings(self, updates: dict[str, Any]) -> dict[str, str]:
        merged = self.db.update_settings(updates)

        # Reconfigure TTS
        self.tts.configure(
            enabled=merged.get("tts_enabled", "true").lower() == "true",
            rate=int(float(merged.get("tts_rate", "175") or 175)),
            volume=float(merged.get("tts_volume", "0.95") or 0.95),
            voice_id=merged.get("tts_voice_id", ""),
        )
        # Reconfigure Speech Recognition & Mic
        self.speech_recognizer.configure(
            language=merged.get("stt_language", "en-IN"),
            engine=merged.get("stt_engine", "google"),
        )
        mic_raw = merged.get("stt_mic_index", "").strip()
        self.voice_input.set_device_index(int(mic_raw) if mic_raw.isdigit() else None)

        # Sync wake-word state if toggled via settings
        if "wake_word_enabled" in updates:
            should_run = str(updates["wake_word_enabled"]).lower() in {"true", "1", "yes"}
            if should_run and not self.is_wake_word_running():
                self.start_wake_word_listener()
            elif not should_run and self.is_wake_word_running():
                self.stop_wake_word_listener()

        self._emit("settings_updated", {"settings": merged})
        return merged

    # ------------------------------------------------------------------ #
    # Step 1 & 2: Voice Input + Speech Recognition
    # ------------------------------------------------------------------ #
    def calibrate_microphone(self) -> dict[str, Any]:
        self._set_state(AssistantState.CALIBRATING, "Calibrating microphone for ambient noise...")
        try:
            threshold = self.voice_input.calibrate(duration=0.8)
            self._set_state(AssistantState.IDLE, f"Microphone calibrated (threshold {threshold:.0f})")
            return {"success": True, "energy_threshold": round(threshold, 1)}
        except VoiceInputError as exc:
            self._set_state(AssistantState.ERROR, str(exc))
            return {"success": False, "error": str(exc)}

    def listen_and_execute(self) -> CommandResult:
        """Execute full voice pipeline synchronously (call from worker thread in GUI/API)."""
        if not self._listen_lock.acquire(blocking=False):
            return CommandResult(
                success=False,
                status="error",
                intent="voice_busy",
                input_text="",
                response_text="ORION is already listening. Please wait a moment.",
            )
        try:
            # Stop any active TTS playback before opening microphone so speech never interferes with input
            if self.tts.is_speaking:
                self.tts.stop()
                deadline = time.monotonic() + 0.4
                while self.tts.is_speaking and time.monotonic() < deadline:
                    time.sleep(0.04)

            settings = self.db.get_all_settings()
            timeout = float(settings.get("stt_timeout", "6") or 6)
            phrase_limit = float(settings.get("stt_phrase_limit", "10") or 10)

            self._set_state(AssistantState.LISTENING, "Listening... speak your command")
            audio = self.voice_input.capture_audio(
                timeout=timeout,
                phrase_time_limit=phrase_limit,
                auto_calibrate=True,
            )

            self._set_state(AssistantState.RECOGNIZING, "Converting speech to text...")
            recognized_text = self.speech_recognizer.recognize(audio)
            self._emit("transcript", {"text": recognized_text, "mode": InputMode.VOICE.value})

            return self.process_command(recognized_text, input_mode=InputMode.VOICE.value)

        except VoiceInputTimeout as exc:
            msg = str(exc)
            self._set_state(AssistantState.IDLE, msg)
            result = CommandResult(
                success=False,
                status="error",
                intent="voice_timeout",
                input_text="(no speech detected)",
                response_text=msg,
            )
            self._emit("command_result", {"result": result.to_dict()})
            return result

        except (VoiceInputError, SpeechNotUnderstoodError, SpeechServiceUnavailableError, SpeechRecognitionError) as exc:
            msg = str(exc)
            self._set_state(AssistantState.ERROR, msg)
            result = CommandResult(
                success=False,
                status="error",
                intent="speech_error",
                input_text="(voice input error)",
                response_text=msg,
                spoken_text=msg,
            )
            self.tts.speak(msg)
            self._emit("command_result", {"result": result.to_dict()})
            self._set_state(AssistantState.IDLE, "Ready for voice or text command")
            return result
        finally:
            self._listen_lock.release()

    # ------------------------------------------------------------------ #
    # Wake-Word Continuous Listener (Synopsis Section 15 Foundation)
    # ------------------------------------------------------------------ #
    def is_wake_word_running(self) -> bool:
        return self._wake_thread is not None and self._wake_thread.is_alive()

    def start_wake_word_listener(self) -> bool:
        if self.is_wake_word_running():
            return True
        if not self.voice_input.is_microphone_available():
            return False
        self._wake_stop_event.clear()
        self._wake_thread = threading.Thread(
            target=self._wake_word_loop, name="OrionWakeWordLoop", daemon=True
        )
        self._wake_thread.start()
        self.db.set_setting("wake_word_enabled", "true")
        self._emit("wake_word_status", {"active": True})
        return True

    def stop_wake_word_listener(self) -> None:
        self._wake_stop_event.set()
        self.db.set_setting("wake_word_enabled", "false")
        self._emit("wake_word_status", {"active": False})

    def _wake_word_loop(self) -> None:
        while not self._wake_stop_event.is_set():
            # Avoid capturing audio while ORION is speaking aloud
            if self.tts.is_speaking:
                time.sleep(0.25)
                continue
            if not self._listen_lock.acquire(blocking=False):
                time.sleep(0.4)
                continue
            try:
                wake_phrase = (
                    self.db.get_setting("wake_word_phrase", self.config.wake_word)
                    .strip()
                    .lower()
                    or "orion"
                )
                audio = self.voice_input.capture_audio(
                    timeout=3.0, phrase_time_limit=6.0, auto_calibrate=True
                )
                if self._wake_stop_event.is_set():
                    break
                text = self.speech_recognizer.recognize(audio)
                if wake_phrase in text.lower():
                    self._emit(
                        "transcript",
                        {"text": text, "mode": InputMode.WAKE_WORD.value},
                    )
                    self.process_command(text, input_mode=InputMode.WAKE_WORD.value)
            except (VoiceInputTimeout, SpeechNotUnderstoodError):
                pass
            except (VoiceInputError, SpeechServiceUnavailableError):
                # Back off slightly if mic or internet is temporarily unavailable
                time.sleep(2.5)
            except Exception:
                time.sleep(1.0)
            finally:
                self._listen_lock.release()

    # ------------------------------------------------------------------ #
    # Steps 3, 4 & 5: Command Processing -> Safety/Execution -> Response
    # ------------------------------------------------------------------ #
    def process_command(
        self,
        raw_text: str,
        input_mode: str = InputMode.TEXT.value,
        bypass_confirmation: bool = False,
        speak_response: bool = True,
    ) -> CommandResult:
        """Process a text or transcribed voice command through the full pipeline."""
        start_ns = time.perf_counter_ns()
        cleaned = (raw_text or "").strip()
        if not cleaned:
            return CommandResult(
                success=False,
                status="error",
                intent="empty_input",
                input_text="",
                response_text="Please enter or speak a command.",
            )

        self._set_state(AssistantState.PROCESSING, f"Processing: {cleaned}")
        parsed = self.command_processor.parse(cleaned)

        # Handle BLOCKED commands immediately (Synopsis Section 6)
        if parsed.safety_level == SafetyLevel.BLOCKED:
            elapsed_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
            response = f"Action blocked: {parsed.warning_message}"
            history_id = self.db.add_history(
                input_text=cleaned,
                input_mode=input_mode,
                matched_intent=parsed.intent,
                safety_level=SafetyLevel.BLOCKED.value,
                status="blocked",
                response_text=response,
                execution_ms=elapsed_ms,
            )
            result = CommandResult(
                success=False,
                status="blocked",
                intent=parsed.intent,
                input_text=cleaned,
                response_text=response,
                spoken_text=response,
                safety_level=SafetyLevel.BLOCKED.value,
                execution_ms=elapsed_ms,
                history_id=history_id,
            )
            return self._finalize_result(result, speak_response=speak_response)

        # Handle CONFIRM_REQUIRED commands when confirmation policy is active
        require_conf = self.db.get_setting("require_confirmation", "true").lower() == "true"
        if (
            parsed.safety_level == SafetyLevel.CONFIRM_REQUIRED
            and require_conf
            and not bypass_confirmation
        ):
            token = uuid.uuid4().hex[:12]
            req = ConfirmationRequest(
                token=token,
                raw_text=cleaned,
                intent=parsed.intent,
                action_description=parsed.action_description,
                warning_message=parsed.warning_message
                or "This command affects system settings and requires your confirmation.",
                input_mode=input_mode,
                params=parsed.params,
            )
            with self._confirm_lock:
                self._pending_confirmations[token] = (req, parsed)

            elapsed_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
            response = (
                f"Confirmation required: {req.action_description}. {req.warning_message}"
            )
            history_id = self.db.add_history(
                input_text=cleaned,
                input_mode=input_mode,
                matched_intent=parsed.intent,
                safety_level=SafetyLevel.CONFIRM_REQUIRED.value,
                status="pending_confirmation",
                response_text=response,
                execution_ms=elapsed_ms,
            )
            result = CommandResult(
                success=True,
                status="pending_confirmation",
                intent=parsed.intent,
                input_text=cleaned,
                response_text=response,
                spoken_text=f"Please confirm: {req.action_description}.",
                safety_level=SafetyLevel.CONFIRM_REQUIRED.value,
                execution_ms=elapsed_ms,
                requires_confirmation=True,
                confirmation_request=req,
                history_id=history_id,
            )
            self._set_state(
                AssistantState.AWAITING_CONFIRMATION,
                f"Awaiting confirmation: {req.action_description}",
            )
            self._emit("confirmation_required", {"confirmation": req.to_dict()})
            self._emit("command_result", {"result": result.to_dict()})
            if speak_response:
                self.tts.speak(result.spoken_text)
            return result

        # Execute approved task
        return self._execute_parsed(
            parsed,
            input_mode=input_mode,
            start_ns=start_ns,
            speak_response=speak_response,
        )

    def confirm_action(
        self, token: str, approved: bool, speak_response: bool = True
    ) -> CommandResult:
        """Approve or reject a pending confirmation token."""
        with self._confirm_lock:
            entry = self._pending_confirmations.pop(token, None)

        if entry is None:
            return CommandResult(
                success=False,
                status="error",
                intent="confirmation_expired",
                input_text="",
                response_text="Confirmation request was not found or has already been processed.",
            )

        req, parsed = entry
        start_ns = time.perf_counter_ns()
        if not approved:
            response = f"Cancelled: {req.action_description}."
            history_id = self.db.add_history(
                input_text=req.raw_text,
                input_mode=req.input_mode,
                matched_intent=parsed.intent,
                safety_level=parsed.safety_level.value,
                status="cancelled",
                response_text=response,
                execution_ms=0,
            )
            result = CommandResult(
                success=True,
                status="cancelled",
                intent=parsed.intent,
                input_text=req.raw_text,
                response_text=response,
                spoken_text=response,
                safety_level=parsed.safety_level.value,
                history_id=history_id,
            )
            self._emit("confirmation_resolved", {"token": token, "approved": False})
            return self._finalize_result(result, speak_response=speak_response)

        self._emit("confirmation_resolved", {"token": token, "approved": True})
        return self._execute_parsed(
            parsed,
            input_mode=req.input_mode,
            start_ns=start_ns,
            speak_response=speak_response,
        )

    def _execute_parsed(
        self,
        parsed: ParsedCommand,
        input_mode: str,
        start_ns: int,
        speak_response: bool,
    ) -> CommandResult:
        self._set_state(AssistantState.EXECUTING, parsed.action_description)
        intent = parsed.intent
        data: dict[str, Any] = {}
        success = True
        status = "success"
        spoken_text = ""

        try:
            if intent == "greeting":
                user_name = self.db.get_setting("user_name", "User")
                hour = datetime.now().hour
                part = "Good morning" if hour < 12 else ("Good afternoon" if hour < 17 else "Good evening")
                response = f"{part}, {user_name}! ORION is ready. How can I help you today?"

            elif intent == "about":
                response = (
                    "I am ORION, a Python-based voice-controlled desktop virtual assistant "
                    "developed for automating desktop tasks, opening applications and websites, "
                    "web searches, screenshots, and voice interaction."
                )

            elif intent == "help":
                response = (
                    "You can ask me to open apps like Notepad or Calculator, open websites like YouTube or GitHub, "
                    "search Google or YouTube, check the date, time, weather, or Wikipedia, take screenshots, "
                    "adjust volume/media, manage notes, calculate math, or check system status."
                )
                data["commands"] = self.command_processor.get_supported_commands()

            elif intent == "get_time":
                response, data = self.automation.get_current_time()

            elif intent == "get_date":
                response, data = self.automation.get_current_date()

            elif intent == "system_status":
                response, data = self.automation.get_system_status()

            elif intent == "open_app":
                response, data = self.automation.open_application(parsed.params["app"])

            elif intent == "open_website":
                response, data = self.automation.open_website(
                    parsed.params["name"], parsed.params["url"]
                )

            elif intent == "search_google":
                response, data = self.automation.search_google(parsed.params["query"])

            elif intent == "search_youtube":
                response, data = self.automation.search_youtube(parsed.params["query"])

            elif intent == "take_screenshot":
                response, data = self.automation.take_screenshot()

            elif intent == "open_screenshots_folder":
                response, data = self.automation.open_screenshots_folder()

            elif intent == "media_control":
                response, data = self.automation.media_control(parsed.params["action"])

            elif intent == "show_desktop":
                response, data = self.automation.minimize_all_windows()

            elif intent == "lock_screen":
                response, data = self.automation.lock_workstation()

            elif intent == "system_power":
                response, data = self.automation.system_power(parsed.params["mode"])

            elif intent == "clear_history":
                deleted = self.db.clear_history()
                response = f"Cleared {deleted} entries from command history."
                data = {"deleted_count": deleted}

            elif intent == "add_note":
                note = self.db.add_note(parsed.params["content"])
                response = f"Saved note: \"{note['content']}\"."
                data = {"note": note}

            elif intent == "list_notes":
                notes = self.db.list_notes(include_completed=False)
                if not notes:
                    response = "You have no pending notes."
                else:
                    preview = "; ".join(
                        f"{idx + 1}. {n['content']}" for idx, n in enumerate(notes[:5])
                    )
                    response = f"You have {len(notes)} open note(s): {preview}."
                data = {"notes": notes}

            elif intent == "calculate":
                response, data = self.automation.calculate_expression(
                    parsed.params["expression"]
                )

            elif intent == "wikipedia":
                info = self.info_services.fetch_wikipedia_summary(parsed.params["topic"])
                response = f"{info['title']}: {info['summary']}"
                data = info

            elif intent == "weather":
                city = parsed.params.get("city") or self.db.get_setting(
                    "default_city", self.config.default_city
                )
                weather = self.info_services.fetch_weather(city)
                response = weather["summary"]
                data = weather

            elif intent == "ai_question":
                answer = self.ai_provider.ask(parsed.params["prompt"])
                response = answer
                data = {"provider": self.ai_provider.provider_name}

            elif intent == "unknown_open_target":
                target = parsed.params.get("target", "")
                success = False
                status = "unknown"
                response = (
                    f"I don't have '{target}' registered as an app or website yet. "
                    "You can add it in the Applications & Websites Manager, or say "
                    f"'search google for {target}'."
                )

            else:
                # Optional AI fallback if explicitly configured in .env
                if self.ai_provider.is_configured:
                    try:
                        answer = self.ai_provider.ask(parsed.normalized_text)
                        response = answer
                        intent = "ai_fallback"
                        data = {"provider": self.ai_provider.provider_name}
                    except Exception as ai_exc:
                        success = False
                        status = "error"
                        response = f"AI provider error: {ai_exc}"
                else:
                    success = False
                    status = "unknown"
                    response = (
                        f"I did not recognize the command '{parsed.raw_text}'. "
                        "Say 'help' to see supported commands, or try 'search google for ...'."
                    )

        except Exception as exc:
            success = False
            status = "error"
            response = f"Could not complete '{parsed.action_description}': {exc}"

        elapsed_ms = int((time.perf_counter_ns() - start_ns) / 1_000_000)
        history_id = self.db.add_history(
            input_text=parsed.raw_text,
            input_mode=input_mode,
            matched_intent=intent,
            safety_level=parsed.safety_level.value,
            status=status,
            response_text=response,
            execution_ms=elapsed_ms,
        )
        result = CommandResult(
            success=success,
            status=status,
            intent=intent,
            input_text=parsed.raw_text,
            response_text=response,
            spoken_text=spoken_text or response,
            safety_level=parsed.safety_level.value,
            data=data,
            execution_ms=elapsed_ms,
            history_id=history_id,
        )
        return self._finalize_result(result, speak_response=speak_response)

    def set_tts_enabled(self, enabled: bool) -> bool:
        """Persist and apply voice mute/unmute preference."""
        self.update_settings({"tts_enabled": bool(enabled)})
        return self.tts.enabled

    def replay_last_response(self, text: str | None = None) -> bool:
        """Replay a specific response text or the most recent final assistant response."""
        target = (text or "").strip() or self._last_response_text or self.tts.last_spoken_text
        if not target:
            return False
        return self.tts.speak(target, force=True, interrupt=True)

    def _finalize_result(
        self, result: CommandResult, speak_response: bool = True
    ) -> CommandResult:
        self._emit("command_result", {"result": result.to_dict()})
        final_text = (result.spoken_text or result.response_text or "").strip()
        if final_text:
            self._last_response_text = final_text
        dedup_key = (
            f"hist:{result.history_id}"
            if result.history_id is not None
            else f"{result.timestamp}:{result.intent}:{final_text}"
        )
        if speak_response and final_text and dedup_key != self._last_spoken_key:
            self._last_spoken_key = dedup_key
            queued = self.tts.speak(final_text, interrupt=True)
            if not queued:
                self._set_state(AssistantState.IDLE, "Ready for voice or text command")
        else:
            self._set_state(AssistantState.IDLE, "Ready for voice or text command")
        return result

    def shutdown(self) -> None:
        self.stop_wake_word_listener()
        self.tts.shutdown()
