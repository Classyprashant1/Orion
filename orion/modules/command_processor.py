"""Rule-Based Command Processing Module (Synopsis Section 8).

Matches recognized speech or typed text against a clear, extensible set of
command rules, extracts parameters, resolves custom apps/websites from SQLite,
and classifies safety risk (SAFE, CONFIRM_REQUIRED, BLOCKED) per Synopsis Sec. 6.
"""

from __future__ import annotations

import re
from typing import Any

from orion.core.models import ParsedCommand, SafetyLevel
from orion.db.database import OrionDatabase

# Explicitly restricted/dangerous patterns (Synopsis Section 6)
_BLOCKED_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (
        re.compile(
            r"\b(delete|remove|erase|wipe|format)\b.*\b(file|files|folder|directory|drive|disk|c:|system32|all)\b",
            re.I,
        ),
        "File deletion and drive formatting commands are restricted by ORION's safety policy.",
    ),
    (
        re.compile(r"\b(rm\s+-rf|del\s+/|format\s+[a-z]:|regedit|registry)\b", re.I),
        "Arbitrary destructive system or registry commands are blocked for your safety.",
    ),
]

SUPPORTED_COMMANDS_CATALOG: list[dict[str, Any]] = [
    {
        "category": "Date & Time",
        "intent": "get_time",
        "title": "Current Time",
        "examples": ["What time is it?", "Tell me the time"],
        "safety": "safe",
    },
    {
        "category": "Date & Time",
        "intent": "get_date",
        "title": "Current Date",
        "examples": ["What is today's date?", "Tell me the date"],
        "safety": "safe",
    },
    {
        "category": "Applications",
        "intent": "open_app",
        "title": "Launch Desktop Application",
        "examples": ["Open Notepad", "Open Calculator", "Launch Paint", "Open VS Code"],
        "safety": "safe",
    },
    {
        "category": "Web & Search",
        "intent": "open_website",
        "title": "Open Website / Bookmark",
        "examples": ["Open YouTube", "Open GitHub", "Go to google.com"],
        "safety": "safe",
    },
    {
        "category": "Web & Search",
        "intent": "search_google",
        "title": "Google Web Search",
        "examples": ["Search Google for Python tutorials", "Search artificial intelligence"],
        "safety": "safe",
    },
    {
        "category": "Web & Search",
        "intent": "search_youtube",
        "title": "YouTube Search",
        "examples": ["Search YouTube for lo-fi music", "Play Python course on YouTube"],
        "safety": "safe",
    },
    {
        "category": "Information",
        "intent": "wikipedia",
        "title": "Wikipedia Lookup",
        "examples": ["Wikipedia Alan Turing", "Who is Nikola Tesla"],
        "safety": "safe",
    },
    {
        "category": "Information",
        "intent": "weather",
        "title": "Live Weather Report",
        "examples": ["What is the weather in Delhi?", "Weather report"],
        "safety": "safe",
    },
    {
        "category": "Desktop Automation",
        "intent": "take_screenshot",
        "title": "Capture Screenshot",
        "examples": ["Take a screenshot", "Capture screen"],
        "safety": "safe",
    },
    {
        "category": "Desktop Automation",
        "intent": "open_screenshots_folder",
        "title": "Open Screenshots Folder",
        "examples": ["Open screenshots folder", "Show my screenshots"],
        "safety": "safe",
    },
    {
        "category": "Desktop Automation",
        "intent": "media_control",
        "title": "Volume & Media Controls",
        "examples": ["Volume up", "Volume down", "Mute volume", "Play pause", "Next track"],
        "safety": "safe",
    },
    {
        "category": "Desktop Automation",
        "intent": "show_desktop",
        "title": "Minimize Windows / Show Desktop",
        "examples": ["Show desktop", "Minimize all windows"],
        "safety": "safe",
    },
    {
        "category": "Productivity",
        "intent": "add_note",
        "title": "Create Quick Note",
        "examples": ["Take a note submit synopsis tomorrow", "Remember to review Python code"],
        "safety": "safe",
    },
    {
        "category": "Productivity",
        "intent": "list_notes",
        "title": "Read Saved Notes",
        "examples": ["Read my notes", "Show notes"],
        "safety": "safe",
    },
    {
        "category": "Utilities",
        "intent": "calculate",
        "title": "Quick Calculator",
        "examples": ["Calculate 245 * 18", "What is 120 plus 85"],
        "safety": "safe",
    },
    {
        "category": "Utilities",
        "intent": "system_status",
        "title": "System Diagnostics",
        "examples": ["System status", "Check battery and RAM"],
        "safety": "safe",
    },
    {
        "category": "Sensitive Actions (Guarded)",
        "intent": "lock_screen",
        "title": "Lock Workstation",
        "examples": ["Lock my screen", "Lock computer"],
        "safety": "confirm_required",
    },
    {
        "category": "Sensitive Actions (Guarded)",
        "intent": "system_power",
        "title": "Shutdown / Restart Computer",
        "examples": ["Shutdown computer", "Restart PC", "Cancel shutdown"],
        "safety": "confirm_required",
    },
    {
        "category": "Sensitive Actions (Guarded)",
        "intent": "clear_history",
        "title": "Clear Command History",
        "examples": ["Clear command history"],
        "safety": "confirm_required",
    },
    {
        "category": "Optional AI Extension",
        "intent": "ai_question",
        "title": "Ask AI Assistant (Requires API Key)",
        "examples": ["Ask AI explain binary search"],
        "safety": "safe",
    },
]


class CommandProcessorModule:
    """Deterministic rule-based command parser with safety classification."""

    def __init__(self, db: OrionDatabase) -> None:
        self.db = db

    def get_supported_commands(self) -> list[dict[str, Any]]:
        return list(SUPPORTED_COMMANDS_CATALOG)

    def parse(self, raw_text: str) -> ParsedCommand:
        cleaned = (raw_text or "").strip()
        # Strip optional leading wake word ("hey orion, open notepad" -> "open notepad")
        norm = re.sub(
            r"^(?:hey\s+|ok\s+|okay\s+|hello\s+)?orion[\s,:\-]*",
            "",
            cleaned,
            flags=re.I,
        ).strip()
        if not norm:
            # User literally just said "Hey Orion" / "Orion"
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text="hello",
                intent="greeting",
                action_description="Greet user",
                safety_level=SafetyLevel.SAFE,
            )

        lower = norm.lower().rstrip("?.!")

        # 1. Blocked safety checks FIRST (Synopsis Sec. 6)
        for pattern, warning in _BLOCKED_PATTERNS:
            if pattern.search(lower):
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="blocked_command",
                    action_description="Blocked restricted command",
                    safety_level=SafetyLevel.BLOCKED,
                    warning_message=warning,
                )

        # 2. Greetings / Identity / Help
        if re.fullmatch(r"(hi|hello|hey|good morning|good afternoon|good evening)", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="greeting",
                action_description="Respond to greeting",
            )

        if re.search(r"\b(who are you|what is your name|introduce yourself|about orion)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="about",
                action_description="Introduce ORION",
            )

        if re.fullmatch(r"(help|commands|what can you do|list commands|show commands)", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="help",
                action_description="List supported commands",
            )

        # 3. Date & Time
        if (
            re.search(
                r"\b(what\s+time\s+is\s+it|what(?:'s| is)?\s+the\s+time|current\s+time|tell\s+me\s+the\s+time|time\s+now)\b",
                lower,
            )
            or lower == "time"
        ):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="get_time",
                action_description="Report current time",
            )

        if (
            re.search(
                r"\b(what(?:'s| is)?\s+(?:today'?s\s+|the\s+)?date|current\s+date|tell\s+me\s+(?:the\s+|today'?s\s+)?date|today'?s\s+date|what\s+day\s+is\s+(?:it|today))\b",
                lower,
            )
            or lower == "date"
        ):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="get_date",
                action_description="Report current date",
            )

        # 4. Screenshots
        if re.search(r"\b(open|show)\s+(?:my\s+)?screenshots?(?:\s+folder)?\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="open_screenshots_folder",
                action_description="Open screenshots folder",
            )

        if re.search(r"\b(take|capture|grab|snap)\s+(?:a\s+)?(?:screen\s*shot|screen)\b", lower) or lower == "screenshot":
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="take_screenshot",
                action_description="Capture desktop screenshot",
            )

        # 5. Sensitive System Controls (Confirmation Required)
        if re.search(r"\bcancel\s+(?:shutdown|restart)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="system_power",
                action_description="Cancel scheduled shutdown/restart",
                params={"mode": "cancel_shutdown"},
                safety_level=SafetyLevel.SAFE,
            )

        if re.search(r"\b(lock\s+(?:my\s+|the\s+)?(?:screen|computer|pc|workstation|windows))\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="lock_screen",
                action_description="Lock Windows workstation",
                safety_level=SafetyLevel.CONFIRM_REQUIRED,
                warning_message="This will immediately lock your Windows session.",
            )

        if re.search(r"\b(shut\s*down|power\s*off)\s*(?:computer|pc|system|laptop|windows)?\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="system_power",
                action_description="Shut down Windows (30s timer)",
                params={"mode": "shutdown"},
                safety_level=SafetyLevel.CONFIRM_REQUIRED,
                warning_message="This will schedule a Windows shutdown in 30 seconds.",
            )

        if re.search(r"\b(restart|reboot)\s*(?:computer|pc|system|laptop|windows)?\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="system_power",
                action_description="Restart Windows (30s timer)",
                params={"mode": "restart"},
                safety_level=SafetyLevel.CONFIRM_REQUIRED,
                warning_message="This will schedule a Windows restart in 30 seconds.",
            )

        if re.search(r"\bclear\s+(?:command\s+)?history\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="clear_history",
                action_description="Clear saved command history",
                safety_level=SafetyLevel.CONFIRM_REQUIRED,
                warning_message="This will permanently delete all saved command history entries.",
            )

        # 6. Volume / Media / Desktop Window Controls
        if re.search(r"\b(volume\s+up|increase\s+volume|turn\s+up\s+(?:the\s+)?volume|louder)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="media_control",
                action_description="Increase volume",
                params={"action": "volume_up"},
            )
        if re.search(r"\b(volume\s+down|decrease\s+volume|lower\s+(?:the\s+)?volume|turn\s+down\s+(?:the\s+)?volume|quieter)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="media_control",
                action_description="Decrease volume",
                params={"action": "volume_down"},
            )
        if re.search(r"\b(mute|unmute)(?:\s+(?:the\s+)?(?:volume|audio|sound))?\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="media_control",
                action_description="Toggle mute",
                params={"action": "volume_mute"},
            )
        if re.search(r"\b(play\s*pause|pause\s+music|resume\s+music|pause\s+media|play\s+media)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="media_control",
                action_description="Toggle media play/pause",
                params={"action": "play_pause"},
            )
        if re.search(r"\b(next\s+track|next\s+song|skip\s+track|skip\s+song)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="media_control",
                action_description="Next media track",
                params={"action": "next_track"},
            )
        if re.search(r"\b(previous\s+track|previous\s+song|prev\s+track)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="media_control",
                action_description="Previous media track",
                params={"action": "prev_track"},
            )
        if re.search(r"\b(show\s+desktop|minimize\s+all(?:\s+windows)?)\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="show_desktop",
                action_description="Minimize all windows / show desktop",
            )

        # 7. System Status / Diagnostics
        if re.search(
            r"\b(system\s+status|system\s+info|battery\s+status|check\s+battery|cpu\s+usage|ram\s+usage|memory\s+usage)\b",
            lower,
        ):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="system_status",
                action_description="Report system CPU, RAM, disk, and battery",
            )

        # 8. Notes & Reminders
        note_match = re.match(
            r"^(?:take\s+a\s+note|add\s+(?:a\s+)?note|create\s+(?:a\s+)?note|note\s+down|remember\s+(?:to|that))\s+(.+)$",
            norm,
            re.I,
        )
        if note_match:
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="add_note",
                action_description="Save quick note",
                params={"content": note_match.group(1).strip()},
            )

        if re.search(r"\b(read|show|list|view)\s+(?:my\s+)?notes\b", lower):
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="list_notes",
                action_description="Read saved notes",
            )

        # 9. Weather
        weather_match = re.search(
            r"\bweather(?:\s+(?:in|for|at)\s+([a-zA-Z\s\-]+))?\b", lower
        )
        if weather_match:
            city = (weather_match.group(1) or "").strip()
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="weather",
                action_description=f"Check weather{f' in {city}' if city else ''}",
                params={"city": city},
            )

        # 10. Wikipedia Lookup
        wiki_match = re.match(
            r"^(?:wikipedia|wiki|tell\s+me\s+about|who\s+is|what\s+is)\s+(.+)$",
            norm,
            re.I,
        )
        if wiki_match:
            topic = wiki_match.group(1).strip().rstrip("?.!")
            # Avoid hijacking arithmetic ("what is 12 + 5")
            if not re.fullmatch(r"[\d\s\+\-\*/\.\(\)\^%a-z]*(?:plus|minus|times|divided|[\+\-\*/])[\d\s\+\-\*/\.\(\)\^%a-z]*", topic, re.I):
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="wikipedia",
                    action_description=f"Look up '{topic}' on Wikipedia",
                    params={"topic": topic},
                )

        # 11. Arithmetic Calculator
        calc_match = re.match(
            r"^(?:calculate|compute|evaluate|solve|what\s+is)\s+([\d\s\+\-\*/\.\(\)\^%]+|.*\b(?:plus|minus|times|multiplied by|divided by|over)\b.*)$",
            norm,
            re.I,
        )
        if calc_match:
            expr = calc_match.group(1).strip().rstrip("?.!")
            if re.search(r"\d", expr):
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="calculate",
                    action_description=f"Calculate {expr}",
                    params={"expression": expr},
                )

        # 12. Explicit AI Question Hook
        ai_match = re.match(r"^(?:ask\s+ai|ask\s+orion|ai)\s+(.+)$", norm, re.I)
        if ai_match:
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="ai_question",
                action_description="Query AI assistant",
                params={"prompt": ai_match.group(1).strip()},
            )

        # 13. YouTube Search
        yt_match = re.match(
            r"^(?:search\s+youtube\s+(?:for\s+)?|youtube\s+search\s+(?:for\s+)?|play\s+(.+?)\s+on\s+youtube)(.*)$",
            norm,
            re.I,
        )
        if yt_match:
            query = (yt_match.group(1) or yt_match.group(2) or "").strip()
            if query:
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="search_youtube",
                    action_description=f"Search YouTube for '{query}'",
                    params={"query": query},
                )

        # 14. Google / Web Search
        search_match = re.match(
            r"^(?:search\s+(?:google\s+for\s+|the\s+web\s+for\s+|for\s+)?|google\s+)(.+)$",
            norm,
            re.I,
        )
        if search_match:
            query = search_match.group(1).strip()
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="search_google",
                action_description=f"Search Google for '{query}'",
                params={"query": query},
            )

        # 15. Open Application / Website / URL (dynamic lookup against SQLite!)
        open_match = re.match(
            r"^(?:open|launch|start|run|go\s+to|visit)\s+(.+)$", norm, re.I
        )
        if open_match:
            target = open_match.group(1).strip().rstrip(".")
            target_clean = re.sub(r"^(?:the\s+)?", "", target, flags=re.I).strip()

            # Check custom/built-in applications first
            app_row = self.db.get_app_by_alias(target_clean)
            if app_row:
                req_conf = bool(app_row.get("requires_confirmation"))
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="open_app",
                    action_description=f"Open {app_row['display_name']}",
                    params={"app": app_row},
                    safety_level=(
                        SafetyLevel.CONFIRM_REQUIRED if req_conf else SafetyLevel.SAFE
                    ),
                    warning_message=(
                        f"{app_row['display_name']} is marked as a restricted application and requires confirmation."
                        if req_conf
                        else ""
                    ),
                )

            # Check custom/built-in websites
            site_row = self.db.get_website_by_alias(target_clean)
            if site_row:
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="open_website",
                    action_description=f"Open {site_row['display_name']}",
                    params={"name": site_row["display_name"], "url": site_row["url"]},
                )

            # Direct domain/URL check (e.g. "open python.org" or "go to https://docs.python.org")
            if re.match(
                r"^(?:https?://)?[a-zA-Z0-9\-]+(?:\.[a-zA-Z0-9\-]+)+(?:/\S*)?$",
                target_clean,
            ):
                return ParsedCommand(
                    raw_text=cleaned,
                    normalized_text=norm,
                    intent="open_website",
                    action_description=f"Open {target_clean}",
                    params={"name": target_clean, "url": target_clean},
                )

            # Unknown open target -> offer helpful feedback
            return ParsedCommand(
                raw_text=cleaned,
                normalized_text=norm,
                intent="unknown_open_target",
                action_description=f"Unregistered target '{target_clean}'",
                params={"target": target_clean},
                confidence=0.3,
            )

        # 16. Fallback / Unrecognized
        return ParsedCommand(
            raw_text=cleaned,
            normalized_text=norm,
            intent="unknown",
            action_description="Unrecognized command",
            confidence=0.0,
        )
