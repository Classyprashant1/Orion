"""Voice Input Module (Synopsis Section 8).

Captures audio from a microphone via SpeechRecognition + PyAudio,
supports device enumeration and ambient noise calibration, and degrades
gracefully when no microphone hardware is attached.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import speech_recognition as sr


class VoiceInputError(RuntimeError):
    """Raised when microphone capture fails or hardware is unavailable."""


class VoiceInputTimeout(VoiceInputError):
    """Raised when no speech is detected within the listening timeout."""


@dataclass
class MicrophoneDevice:
    index: int
    name: str


class VoiceInputModule:
    """Manages microphone discovery, noise calibration, and audio capture."""

    def __init__(self, device_index: int | None = None) -> None:
        self.recognizer = sr.Recognizer()
        self.recognizer.dynamic_energy_threshold = True
        self.recognizer.pause_threshold = 0.8
        self.device_index = device_index
        self._calibrated = False

    def list_microphones(self) -> list[dict[str, Any]]:
        """Enumerate available input microphones via PyAudio."""
        try:
            names = sr.Microphone.list_microphone_names()
            return [{"index": idx, "name": name} for idx, name in enumerate(names)]
        except Exception:
            return []

    def is_microphone_available(self) -> bool:
        """Check whether PyAudio and at least one input device are accessible."""
        try:
            return len(sr.Microphone.list_microphone_names()) > 0
        except Exception:
            return False

    def set_device_index(self, device_index: int | None) -> None:
        self.device_index = device_index
        self._calibrated = False

    def calibrate(self, duration: float = 0.7) -> float:
        """Measure ambient background noise and update the energy threshold."""
        try:
            with sr.Microphone(device_index=self.device_index) as source:
                self.recognizer.adjust_for_ambient_noise(source, duration=duration)
                self._calibrated = True
                return float(self.recognizer.energy_threshold)
        except OSError as exc:
            raise VoiceInputError(
                "No accessible microphone found. Please connect a microphone or check Windows privacy settings."
            ) from exc
        except AttributeError as exc:
            raise VoiceInputError(
                "PyAudio is not available on this system. Install PyAudio to enable voice input."
            ) from exc
        except Exception as exc:
            raise VoiceInputError(f"Microphone calibration failed: {exc}") from exc

    def capture_audio(
        self,
        timeout: float = 6.0,
        phrase_time_limit: float = 10.0,
        auto_calibrate: bool = True,
    ) -> sr.AudioData:
        """Capture a single spoken utterance from the active microphone."""
        try:
            with sr.Microphone(device_index=self.device_index) as source:
                if auto_calibrate and not self._calibrated:
                    self.recognizer.adjust_for_ambient_noise(source, duration=0.5)
                    self._calibrated = True
                return self.recognizer.listen(
                    source,
                    timeout=max(1.0, float(timeout)),
                    phrase_time_limit=max(2.0, float(phrase_time_limit)),
                )
        except sr.WaitTimeoutError as exc:
            raise VoiceInputTimeout(
                "No speech was detected before the listening timeout elapsed."
            ) from exc
        except OSError as exc:
            raise VoiceInputError(
                "Microphone could not be opened. Ensure a microphone is connected and permitted."
            ) from exc
        except AttributeError as exc:
            raise VoiceInputError(
                "PyAudio backend is unavailable. Voice capture requires PyAudio."
            ) from exc
        except Exception as exc:
            raise VoiceInputError(f"Audio capture failed: {exc}") from exc
