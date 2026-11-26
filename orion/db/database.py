"""Thread-safe SQLite database repository for ORION."""

from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any

SCHEMA_FILE = Path(__file__).resolve().parent / "schema.sql"

DEFAULT_APPS: list[tuple[str, str, str, str, int, int]] = [
    # (alias, display_name, executable_path, arguments, is_builtin, requires_confirmation)
    ("notepad", "Notepad", "notepad.exe", "", 1, 0),
    ("calculator", "Calculator", "calc.exe", "", 1, 0),
    ("calc", "Calculator", "calc.exe", "", 1, 0),
    ("paint", "Microsoft Paint", "mspaint.exe", "", 1, 0),
    ("file explorer", "File Explorer", "explorer.exe", "", 1, 0),
    ("explorer", "File Explorer", "explorer.exe", "", 1, 0),
    ("command prompt", "Command Prompt", "cmd.exe", "", 1, 1),
    ("cmd", "Command Prompt", "cmd.exe", "", 1, 1),
    ("powershell", "Windows PowerShell", "powershell.exe", "", 1, 1),
    ("terminal", "Windows Terminal", "wt.exe", "", 1, 0),
    ("task manager", "Task Manager", "taskmgr.exe", "", 1, 0),
    ("settings", "Windows Settings", "ms-settings:", "", 1, 0),
    ("snipping tool", "Snipping Tool", "snippingtool.exe", "", 1, 0),
    ("vs code", "Visual Studio Code", "code", "", 1, 0),
    ("vscode", "Visual Studio Code", "code", "", 1, 0),
    ("chrome", "Google Chrome", "chrome", "", 1, 0),
    ("google chrome", "Google Chrome", "chrome", "", 1, 0),
    ("edge", "Microsoft Edge", "msedge", "", 1, 0),
    ("microsoft edge", "Microsoft Edge", "msedge", "", 1, 0),
    ("wordpad", "WordPad", "write.exe", "", 1, 0),
]

DEFAULT_WEBSITES: list[tuple[str, str, str, int]] = [
    # (alias, display_name, url, is_builtin)
    ("google", "Google", "https://www.google.com", 1),
    ("youtube", "YouTube", "https://www.youtube.com", 1),
    ("github", "GitHub", "https://github.com", 1),
    ("wikipedia", "Wikipedia", "https://www.wikipedia.org", 1),
    ("gmail", "Gmail", "https://mail.google.com", 1),
    ("stack overflow", "Stack Overflow", "https://stackoverflow.com", 1),
    ("stackoverflow", "Stack Overflow", "https://stackoverflow.com", 1),
    ("linkedin", "LinkedIn", "https://www.linkedin.com", 1),
    ("chatgpt", "ChatGPT", "https://chatgpt.com", 1),
    ("gemini", "Google Gemini", "https://gemini.google.com", 1),
    ("google drive", "Google Drive", "https://drive.google.com", 1),
    ("google maps", "Google Maps", "https://maps.google.com", 1),
    ("reddit", "Reddit", "https://www.reddit.com", 1),
]

DEFAULT_SETTINGS: dict[str, str] = {
    "tts_enabled": "true",
    "tts_rate": "175",
    "tts_volume": "0.95",
    "tts_voice_id": "",
    "stt_language": "en-IN",
    "stt_timeout": "6",
    "stt_phrase_limit": "10",
    "stt_mic_index": "",
    "stt_engine": "google",
    "wake_word_enabled": "false",
    "wake_word_phrase": "orion",
    "require_confirmation": "true",
    "default_city": "Delhi",
    "user_name": "User",
}


class OrionDatabase:
    """Thread-safe SQLite persistence layer for ORION."""

    def __init__(self, db_path: Path | str) -> None:
        self.db_path = Path(db_path)
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=15.0)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON;")
        return conn

    def _init_db(self) -> None:
        schema_sql = SCHEMA_FILE.read_text(encoding="utf-8")
        with self._lock, self._connect() as conn:
            conn.executescript(schema_sql)
            self._seed_defaults(conn)

    def _seed_defaults(self, conn: sqlite3.Connection) -> None:
        for alias, display_name, exe_path, args, is_builtin, req_conf in DEFAULT_APPS:
            conn.execute(
                """
                INSERT OR IGNORE INTO custom_apps
                    (alias, display_name, executable_path, arguments, is_builtin, requires_confirmation)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (alias, display_name, exe_path, args, is_builtin, req_conf),
            )
        for alias, display_name, url, is_builtin in DEFAULT_WEBSITES:
            conn.execute(
                """
                INSERT OR IGNORE INTO custom_websites
                    (alias, display_name, url, is_builtin)
                VALUES (?, ?, ?, ?)
                """,
                (alias, display_name, url, is_builtin),
            )
        for key, value in DEFAULT_SETTINGS.items():
            conn.execute(
                "INSERT OR IGNORE INTO settings (key, value) VALUES (?, ?)",
                (key, value),
            )

    # ------------------------------------------------------------------ #
    # Settings
    # ------------------------------------------------------------------ #
    def get_all_settings(self) -> dict[str, str]:
        with self._lock, self._connect() as conn:
            rows = conn.execute("SELECT key, value FROM settings").fetchall()
            merged = dict(DEFAULT_SETTINGS)
            for row in rows:
                merged[row["key"]] = row["value"]
            return merged

    def get_setting(self, key: str, default: str = "") -> str:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT value FROM settings WHERE key = ?", (key,)
            ).fetchone()
            if row is not None:
                return str(row["value"])
            return DEFAULT_SETTINGS.get(key, default)

    def set_setting(self, key: str, value: Any) -> None:
        str_val = str(value).lower() if isinstance(value, bool) else str(value)
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO settings (key, value, updated_at)
                VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str_val),
            )

    def update_settings(self, updates: dict[str, Any]) -> dict[str, str]:
        with self._lock, self._connect() as conn:
            for key, value in updates.items():
                str_val = str(value).lower() if isinstance(value, bool) else str(value)
                conn.execute(
                    """
                    INSERT INTO settings (key, value, updated_at)
                    VALUES (?, ?, strftime('%Y-%m-%dT%H:%M:%fZ', 'now'))
                    ON CONFLICT(key) DO UPDATE SET
                        value = excluded.value,
                        updated_at = excluded.updated_at
                    """,
                    (key, str_val),
                )
        return self.get_all_settings()

    # ------------------------------------------------------------------ #
    # Command History
    # ------------------------------------------------------------------ #
    def add_history(
        self,
        input_text: str,
        input_mode: str,
        matched_intent: str,
        safety_level: str,
        status: str,
        response_text: str,
        execution_ms: int = 0,
    ) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO command_history
                    (input_text, input_mode, matched_intent, safety_level, status, response_text, execution_ms)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    input_text,
                    input_mode,
                    matched_intent,
                    safety_level,
                    status,
                    response_text,
                    int(execution_ms),
                ),
            )
            return int(cur.lastrowid)

    def get_history(
        self,
        limit: int = 100,
        search: str = "",
        status: str = "",
    ) -> list[dict[str, Any]]:
        query = "SELECT * FROM command_history WHERE 1=1"
        params: list[Any] = []
        if search.strip():
            pattern = f"%{search.strip()}%"
            query += " AND (input_text LIKE ? OR response_text LIKE ? OR matched_intent LIKE ?)"
            params.extend([pattern, pattern, pattern])
        if status.strip():
            query += " AND status = ?"
            params.append(status.strip())
        query += " ORDER BY id DESC LIMIT ?"
        params.append(max(1, min(int(limit), 1000)))
        with self._lock, self._connect() as conn:
            rows = conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def delete_history_item(self, history_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM command_history WHERE id = ?", (history_id,)
            )
            return cur.rowcount > 0

    def clear_history(self) -> int:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM command_history")
            return cur.rowcount

    def get_stats(self) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            total_commands = conn.execute(
                "SELECT COUNT(*) FROM command_history"
            ).fetchone()[0]
            successful_commands = conn.execute(
                "SELECT COUNT(*) FROM command_history WHERE status = 'success'"
            ).fetchone()[0]
            voice_commands = conn.execute(
                "SELECT COUNT(*) FROM command_history WHERE input_mode IN ('voice', 'wake_word')"
            ).fetchone()[0]
            apps_count = conn.execute("SELECT COUNT(*) FROM custom_apps").fetchone()[0]
            websites_count = conn.execute(
                "SELECT COUNT(*) FROM custom_websites"
            ).fetchone()[0]
            screenshots_count = conn.execute(
                "SELECT COUNT(*) FROM screenshots"
            ).fetchone()[0]
            open_notes_count = conn.execute(
                "SELECT COUNT(*) FROM notes WHERE is_completed = 0"
            ).fetchone()[0]
            top_intents = [
                dict(r)
                for r in conn.execute(
                    """
                    SELECT matched_intent AS intent, COUNT(*) AS count
                    FROM command_history
                    GROUP BY matched_intent
                    ORDER BY count DESC
                    LIMIT 6
                    """
                ).fetchall()
            ]
            return {
                "total_commands": total_commands,
                "successful_commands": successful_commands,
                "voice_commands": voice_commands,
                "apps_count": apps_count,
                "websites_count": websites_count,
                "screenshots_count": screenshots_count,
                "open_notes_count": open_notes_count,
                "top_intents": top_intents,
            }

    # ------------------------------------------------------------------ #
    # Custom & Built-in Applications
    # ------------------------------------------------------------------ #
    def list_apps(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_apps ORDER BY is_builtin ASC, display_name ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_app_by_alias(self, alias: str) -> dict[str, Any] | None:
        cleaned = alias.strip().lower()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM custom_apps WHERE LOWER(alias) = ? OR LOWER(display_name) = ?",
                (cleaned, cleaned),
            ).fetchone()
            return dict(row) if row else None

    def upsert_app(
        self,
        alias: str,
        display_name: str,
        executable_path: str,
        arguments: str = "",
        requires_confirmation: bool = False,
    ) -> dict[str, Any]:
        norm_alias = alias.strip().lower()
        norm_name = display_name.strip()
        norm_exe = executable_path.strip()
        if not norm_alias or not norm_name or not norm_exe:
            raise ValueError("Alias, display name, and executable path are required.")
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO custom_apps
                    (alias, display_name, executable_path, arguments, is_builtin, requires_confirmation)
                VALUES (?, ?, ?, ?, 0, ?)
                ON CONFLICT(alias) DO UPDATE SET
                    display_name = excluded.display_name,
                    executable_path = excluded.executable_path,
                    arguments = excluded.arguments,
                    requires_confirmation = excluded.requires_confirmation
                """,
                (norm_alias, norm_name, norm_exe, arguments.strip(), int(requires_confirmation)),
            )
            row = conn.execute(
                "SELECT * FROM custom_apps WHERE LOWER(alias) = ?", (norm_alias,)
            ).fetchone()
            return dict(row)

    def delete_app(self, app_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM custom_apps WHERE id = ?", (app_id,))
            return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # Custom & Built-in Websites
    # ------------------------------------------------------------------ #
    def list_websites(self) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM custom_websites ORDER BY is_builtin ASC, display_name ASC"
            ).fetchall()
            return [dict(r) for r in rows]

    def get_website_by_alias(self, alias: str) -> dict[str, Any] | None:
        cleaned = alias.strip().lower()
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM custom_websites WHERE LOWER(alias) = ? OR LOWER(display_name) = ?",
                (cleaned, cleaned),
            ).fetchone()
            return dict(row) if row else None

    def upsert_website(
        self, alias: str, display_name: str, url: str
    ) -> dict[str, Any]:
        norm_alias = alias.strip().lower()
        norm_name = display_name.strip()
        norm_url = url.strip()
        if not norm_alias or not norm_name or not norm_url:
            raise ValueError("Alias, display name, and URL are required.")
        if not norm_url.startswith(("http://", "https://")):
            norm_url = f"https://{norm_url}"
        with self._lock, self._connect() as conn:
            conn.execute(
                """
                INSERT INTO custom_websites (alias, display_name, url, is_builtin)
                VALUES (?, ?, ?, 0)
                ON CONFLICT(alias) DO UPDATE SET
                    display_name = excluded.display_name,
                    url = excluded.url
                """,
                (norm_alias, norm_name, norm_url),
            )
            row = conn.execute(
                "SELECT * FROM custom_websites WHERE LOWER(alias) = ?", (norm_alias,)
            ).fetchone()
            return dict(row)

    def delete_website(self, website_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                "DELETE FROM custom_websites WHERE id = ?", (website_id,)
            )
            return cur.rowcount > 0

    # ------------------------------------------------------------------ #
    # Screenshots
    # ------------------------------------------------------------------ #
    def add_screenshot(
        self,
        filename: str,
        file_path: str,
        width: int = 0,
        height: int = 0,
        note: str = "",
    ) -> dict[str, Any]:
        with self._lock, self._connect() as conn:
            cur = conn.execute(
                """
                INSERT INTO screenshots (filename, file_path, width, height, note)
                VALUES (?, ?, ?, ?, ?)
                """,
                (filename, file_path, width, height, note),
            )
            row = conn.execute(
                "SELECT * FROM screenshots WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_screenshots(self, limit: int = 50) -> list[dict[str, Any]]:
        with self._lock, self._connect() as conn:
            rows = conn.execute(
                "SELECT * FROM screenshots ORDER BY id DESC LIMIT ?",
                (max(1, min(int(limit), 200)),),
            ).fetchall()
            return [dict(r) for r in rows]

    def get_screenshot(self, screenshot_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM screenshots WHERE id = ?", (screenshot_id,)
            ).fetchone()
            return dict(row) if row else None

    def delete_screenshot(self, screenshot_id: int) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute(
                "SELECT * FROM screenshots WHERE id = ?", (screenshot_id,)
            ).fetchone()
            if not row:
                return None
            conn.execute("DELETE FROM screenshots WHERE id = ?", (screenshot_id,))
            return dict(row)

    # ------------------------------------------------------------------ #
    # Notes & Reminders
    # ------------------------------------------------------------------ #
    def add_note(self, content: str) -> dict[str, Any]:
        cleaned = content.strip()
        if not cleaned:
            raise ValueError("Note content cannot be empty.")
        with self._lock, self._connect() as conn:
            cur = conn.execute("INSERT INTO notes (content) VALUES (?)", (cleaned,))
            row = conn.execute(
                "SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)
            ).fetchone()
            return dict(row)

    def list_notes(self, include_completed: bool = True) -> list[dict[str, Any]]:
        sql = "SELECT * FROM notes"
        if not include_completed:
            sql += " WHERE is_completed = 0"
        sql += " ORDER BY is_completed ASC, id DESC"
        with self._lock, self._connect() as conn:
            rows = conn.execute(sql).fetchall()
            return [dict(r) for r in rows]

    def toggle_note(self, note_id: int, is_completed: bool | None = None) -> dict[str, Any] | None:
        with self._lock, self._connect() as conn:
            row = conn.execute("SELECT * FROM notes WHERE id = ?", (note_id,)).fetchone()
            if not row:
                return None
            new_state = (
                int(is_completed)
                if is_completed is not None
                else (0 if row["is_completed"] else 1)
            )
            conn.execute(
                "UPDATE notes SET is_completed = ? WHERE id = ?",
                (new_state, note_id),
            )
            updated = conn.execute(
                "SELECT * FROM notes WHERE id = ?", (note_id,)
            ).fetchone()
            return dict(updated)

    def delete_note(self, note_id: int) -> bool:
        with self._lock, self._connect() as conn:
            cur = conn.execute("DELETE FROM notes WHERE id = ?", (note_id,))
            return cur.rowcount > 0
