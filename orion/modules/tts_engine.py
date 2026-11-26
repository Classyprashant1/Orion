
"""Text-to-Speech Module (Synopsis Section 8).

Runs speech synthesis inside a dedicated single-owner worker thread so COM/SAPI5
never blocks Tkinter or FastAPI threads.

On Windows, uses SAPI5 (`SAPI.SpVoice` via `win32com`, with `pyttsx3` fallback)
with an interruptible `WaitUntilDone` loop to avoid the known `pyttsx3` 2.99
SAPI5 bug where subsequent `runAndWait()` calls silently return without audio.
"""

from __future__ import annotations

import logging
import math
import platform
import queue
import threading
from typing import Any, Callable

try:
    import pyttsx3
except Exception:  # pragma: no cover
    pyttsx3 = None

logger = logging.getLogger(__name__)

# SAPI5 SpeechVoiceSpeakFlags
_SVSF_ASYNC = 1
_SVSF_PURGE_BEFORE_SPEAK = 2


class TextToSpeechModule:
    """Thread-safe offline Text-to-Speech engine (Windows SAPI5 + pyttsx3)."""

    def __init__(
        self,
        enabled: bool = True,
        rate: int = 175,
        volume: float = 0.95,
        voice_id: str = "",
        on_speaking_change: Callable[[bool], None] | None = None,
    ) -> None:
        self.enabled = enabled
        self.rate = max(80, min(320, int(rate)))
        self.volume = max(0.0, min(1.0, float(volume)))
        self.voice_id = voice_id
        self._on_speaking_change = on_speaking_change

        self._queue: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._voices_cache: list[dict[str, str]] = []
        self._available = False
        self._backend = "none"
        self._ready_event = threading.Event()
        self._stop_event = threading.Event()
        self._cancel_current = threading.Event()
        self._speaking = False
        self._last_spoken_text = ""
        self._seq_lock = threading.Lock()
        self._speech_seq = 0

        self._worker = threading.Thread(
            target=self._run_loop, name="OrionTTSWorker", daemon=True
        )
        self._worker.start()
        self._ready_event.wait(timeout=8.0)

    @property
    def is_available(self) -> bool:
        return self._available

    @property
    def is_speaking(self) -> bool:
        return self._speaking

    @property
    def backend_name(self) -> str:
        return self._backend

    @property
    def last_spoken_text(self) -> str:
        return self._last_spoken_text

    def list_voices(self) -> list[dict[str, str]]:
        return list(self._voices_cache)

    def configure(
        self,
        enabled: bool | None = None,
        rate: int | None = None,
        volume: float | None = None,
        voice_id: str | None = None,
    ) -> None:
        if enabled is not None:
            self.enabled = bool(enabled)
            if not self.enabled:
                self.stop()
        if rate is not None:
            self.rate = max(80, min(320, int(rate)))
        if volume is not None:
            self.volume = max(0.0, min(1.0, float(volume)))
        if voice_id is not None:
            self.voice_id = str(voice_id)
        self._queue.put(("config", None))

    def _drain_pending_speech(self) -> None:
        preserved: list[tuple[str, Any]] = []
        while not self._queue.empty():
            try:
                item = self._queue.get_nowait()
                if item[0] == "config":
                    preserved.append(item)
            except queue.Empty:
                break
        for item in preserved:
            self._queue.put(item)

    def speak(self, text: str, force: bool = False, interrupt: bool = True) -> bool:
        """Queue text to be spoken asynchronously.

        When `interrupt=True` (default), safely cancels any active/queued speech
        so the newest response is spoken immediately without overlap.
        """
        cleaned = (text or "").strip()
        if not cleaned:
            return False
        self._last_spoken_text = cleaned
        if (not self.enabled and not force) or not self._available:
            return False
        with self._seq_lock:
            self._speech_seq += 1
            seq = self._speech_seq
            if interrupt:
                self._cancel_current.set()
                self._drain_pending_speech()
            self._queue.put(("speak", (seq, cleaned)))
        return True

    def replay_last(self, force: bool = True) -> bool:
        """Replay the most recent spoken response text."""
        if not self._last_spoken_text:
            return False
        return self.speak(self._last_spoken_text, force=force, interrupt=True)

    def stop(self) -> None:
        """Interrupt active speech and clear any queued utterances."""
        with self._seq_lock:
            self._speech_seq += 1
            self._cancel_current.set()
            self._drain_pending_speech()
            self._queue.put(("stop", None))

    def shutdown(self) -> None:
        """Gracefully terminate the background TTS worker."""
        self._cancel_current.set()
        self._stop_event.set()
        self._queue.put(("shutdown", None))
        self._worker.join(timeout=3.0)

    def _notify(self, speaking: bool) -> None:
        self._speaking = speaking
        if self._on_speaking_change:
            try:
                self._on_speaking_change(speaking)
            except Exception:
                pass

    # ------------------------------------------------------------------ #
    # Windows SAPI5 Helpers (Reliable multi-utterance playback + stop)
    # ------------------------------------------------------------------ #
    @staticmethod
    def _wpm_to_sapi_rate(wpm: int) -> int:
        # SAPI5 Rate ranges from -10 to +10, with 0 roughly ~175 WPM
        rate_val = int(round(math.log(max(80, wpm) / 175.0, 1.12)))
        return max(-10, min(10, rate_val))

    def _apply_sapi_settings(self, sp_voice: Any) -> None:
        try:
            sp_voice.Rate = self._wpm_to_sapi_rate(self.rate)
            sp_voice.Volume = max(0, min(100, int(round(self.volume * 100))))
            if self.voice_id:
                tokens = sp_voice.GetVoices()
                for idx in range(tokens.Count):
                    tok = tokens.Item(idx)
                    if tok.Id == self.voice_id:
                        sp_voice.Voice = tok
                        break
        except Exception as exc:
            logger.debug("Failed applying SAPI5 settings: %s", exc)

    def _init_sapi5(self) -> Any | None:
        if platform.system() != "Windows":
            return None
        try:
            import win32com.client

            sp_voice = win32com.client.Dispatch("SAPI.SpVoice")
            tokens = sp_voice.GetVoices()
            voices: list[dict[str, str]] = []
            for idx in range(tokens.Count):
                tok = tokens.Item(idx)
                voices.append(
                    {
                        "id": str(tok.Id),
                        "name": str(tok.GetDescription()),
                        "languages": "",
                    }
                )
            if not voices:
                return None
            self._voices_cache = voices
            self._apply_sapi_settings(sp_voice)
            return sp_voice
        except Exception as exc:
            logger.debug("Direct SAPI5 init unavailable: %s", exc)
            return None

    # ------------------------------------------------------------------ #
    # pyttsx3 Fallback Helpers (Cross-platform)
    # ------------------------------------------------------------------ #
    def _init_pyttsx3_voices(self) -> bool:
        if pyttsx3 is None:
            return False
        try:
            engine = pyttsx3.init()
            voices = engine.getProperty("voices") or []
            self._voices_cache = [
                {
                    "id": str(getattr(v, "id", "")),
                    "name": str(getattr(v, "name", "System Voice")),
                    "languages": "",
                }
                for v in voices
            ]
            try:
                engine.stop()
            except Exception:
                pass
            return True
        except Exception as exc:
            logger.debug("pyttsx3 init unavailable: %s", exc)
            return False

    def _speak_pyttsx3_fresh(self, text: str) -> None:
        """Create a clean pyttsx3 engine instance per utterance to avoid runAndWait lockups."""
        if pyttsx3 is None:
            return
        # Clear pyttsx3's cached engine reference so a fresh driver is created cleanly
        try:
            if hasattr(pyttsx3, "_activeEngines"):
                pyttsx3._activeEngines.clear()
        except Exception:
            pass
        engine = pyttsx3.init()
        engine.setProperty("rate", self.rate)
        engine.setProperty("volume", self.volume)
        if self.voice_id:
            try:
                engine.setProperty("voice", self.voice_id)
            except Exception:
                pass
        engine.say(text)
        engine.runAndWait()
        try:
            engine.stop()
        except Exception:
            pass

    # ------------------------------------------------------------------ #
    # Worker Loop
    # ------------------------------------------------------------------ #
    def _run_loop(self) -> None:
        com_initialized = False
        sp_voice = None
        try:
            if platform.system() == "Windows":
                try:
                    import pythoncom

                    pythoncom.CoInitialize()
                    com_initialized = True
                except Exception:
                    pass

            sp_voice = self._init_sapi5()
            if sp_voice is not None:
                self._backend = "sapi5"
                self._available = True
            elif self._init_pyttsx3_voices():
                self._backend = "pyttsx3"
                self._available = True
            else:
                self._backend = "none"
                self._available = False
        finally:
            self._ready_event.set()

        if not self._available:
            if com_initialized:
                try:
                    import pythoncom

                    pythoncom.CoUninitialize()
                except Exception:
                    pass
            return

        while not self._stop_event.is_set():
            try:
                action, payload = self._queue.get(timeout=0.3)
            except queue.Empty:
                continue

            if action == "shutdown":
                if sp_voice is not None:
                    try:
                        sp_voice.Speak("", _SVSF_ASYNC | _SVSF_PURGE_BEFORE_SPEAK)
                    except Exception:
                        pass
                break

            elif action == "config":
                if sp_voice is not None:
                    self._apply_sapi_settings(sp_voice)

            elif action == "stop":
                self._cancel_current.clear()
                if sp_voice is not None:
                    try:
                        sp_voice.Speak("", _SVSF_ASYNC | _SVSF_PURGE_BEFORE_SPEAK)
                    except Exception:
                        pass

            elif action == "speak" and payload:
                seq, text_to_speak = payload
                with self._seq_lock:
                    if seq != self._speech_seq:
                        continue
                    self._cancel_current.clear()
                self._notify(True)
                try:
                    if sp_voice is not None:
                        self._apply_sapi_settings(sp_voice)
                        # Speak asynchronously & poll WaitUntilDone so stop() interrupts immediately
                        sp_voice.Speak(
                            str(text_to_speak),
                            _SVSF_ASYNC | _SVSF_PURGE_BEFORE_SPEAK,
                        )
                        while not sp_voice.WaitUntilDone(80):
                            if self._cancel_current.is_set() or self._stop_event.is_set():
                                sp_voice.Speak("", _SVSF_ASYNC | _SVSF_PURGE_BEFORE_SPEAK)
                                break
                    else:
                        self._speak_pyttsx3_fresh(str(text_to_speak))
                except Exception as exc:
                    logger.warning("TTS playback error: %s", exc)
                finally:
                    self._notify(False)

        if com_initialized:
            try:
                import pythoncom

                pythoncom.CoUninitialize()
            except Exception:
                pass
