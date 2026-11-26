"""Speech Recognition Module (Synopsis Section 8).

Converts recorded `sr.AudioData` into text using Google Web Speech API
(primary online recognizer per synopsis) with an optional offline PocketSphinx
fallback if installed.
"""

from __future__ import annotations

import speech_recognition as sr


class SpeechRecognitionError(RuntimeError):
    """Base error for speech-to-text failures."""


class SpeechNotUnderstoodError(SpeechRecognitionError):
    """Raised when audio could not be transcribed clearly."""


class SpeechServiceUnavailableError(SpeechRecognitionError):
    """Raised when the online speech recognition service cannot be reached."""


class SpeechRecognitionModule:
    """Transcribes audio buffers to text."""

    def __init__(
        self,
        recognizer: sr.Recognizer | None = None,
        language: str = "en-IN",
        engine: str = "google",
    ) -> None:
        self.recognizer = recognizer or sr.Recognizer()
        self.language = language
        self.engine = engine

    def configure(self, language: str | None = None, engine: str | None = None) -> None:
        if language:
            self.language = language
        if engine:
            self.engine = engine.lower().strip()

    def recognize(self, audio: sr.AudioData) -> str:
        """Convert captured AudioData into normalized text."""
        if self.engine == "sphinx":
            return self._recognize_sphinx(audio)
        return self._recognize_google(audio)

    def _recognize_google(self, audio: sr.AudioData) -> str:
        try:
            text = self.recognizer.recognize_google(audio, language=self.language)
            return str(text).strip()
        except sr.UnknownValueError as exc:
            raise SpeechNotUnderstoodError(
                "I could not understand what you said. Please speak clearly and try again."
            ) from exc
        except sr.RequestError as exc:
            raise SpeechServiceUnavailableError(
                f"Online speech recognition service is unavailable (check your internet connection): {exc}"
            ) from exc
        except Exception as exc:
            raise SpeechRecognitionError(f"Speech recognition error: {exc}") from exc

    def _recognize_sphinx(self, audio: sr.AudioData) -> str:
        try:
            text = self.recognizer.recognize_sphinx(audio)
            return str(text).strip()
        except sr.UnknownValueError as exc:
            raise SpeechNotUnderstoodError(
                "Offline recognizer could not understand the audio."
            ) from exc
        except sr.RequestError as exc:
            raise SpeechServiceUnavailableError(
                f"Offline PocketSphinx recognizer is not installed or unavailable: {exc}"
            ) from exc
        except Exception as exc:
            raise SpeechRecognitionError(f"Offline recognition error: {exc}") from exc
