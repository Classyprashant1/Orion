"""Core domain data models for ORION."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any


class AssistantState(str, Enum):
    """Lifecycle states of the ORION assistant pipeline."""

    IDLE = "idle"
    CALIBRATING = "calibrating"
    LISTENING = "listening"
    RECOGNIZING = "recognizing"
    PROCESSING = "processing"
    AWAITING_CONFIRMATION = "awaiting_confirmation"
    EXECUTING = "executing"
    SPEAKING = "speaking"
    ERROR = "error"


class SafetyLevel(str, Enum):
    """Safety classification for desktop and system operations (Synopsis Sec. 6)."""

    SAFE = "safe"
    CONFIRM_REQUIRED = "confirm_required"
    BLOCKED = "blocked"


class InputMode(str, Enum):
    """How a user command entered ORION."""

    VOICE = "voice"
    TEXT = "text"
    QUICK_ACTION = "quick_action"
    API = "api"
    WAKE_WORD = "wake_word"


@dataclass
class ParsedCommand:
    """Result of rule-based command matching."""

    raw_text: str
    normalized_text: str
    intent: str
    action_description: str
    params: dict[str, Any] = field(default_factory=dict)
    safety_level: SafetyLevel = SafetyLevel.SAFE
    warning_message: str = ""
    confidence: float = 1.0


@dataclass
class ConfirmationRequest:
    """Pending confirmation token for a restricted desktop/system command."""

    token: str
    raw_text: str
    intent: str
    action_description: str
    warning_message: str
    input_mode: str
    params: dict[str, Any] = field(default_factory=dict)
    created_at: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class CommandResult:
    """Structured result returned after processing and executing a command."""

    success: bool
    status: str  # success | error | blocked | pending_confirmation | cancelled | unknown
    intent: str
    input_text: str
    response_text: str
    spoken_text: str = ""
    safety_level: str = SafetyLevel.SAFE.value
    data: dict[str, Any] = field(default_factory=dict)
    execution_ms: int = 0
    requires_confirmation: bool = False
    confirmation_request: ConfirmationRequest | None = None
    history_id: int | None = None
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        if self.confirmation_request is not None:
            payload["confirmation_request"] = self.confirmation_request.to_dict()
        return payload
