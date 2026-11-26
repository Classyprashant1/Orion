"""Desktop Automation Module (Synopsis Section 8).

Implements explicitly approved Windows desktop and web operations using
Python standard library (`subprocess`, `os`, `webbrowser`) alongside
`PyAutoGUI`, `Pillow`, and `psutil`.
"""

from __future__ import annotations

import ast
import ctypes
import operator
import os
import platform
import shlex
import shutil
import subprocess
import webbrowser
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import quote_plus

import psutil

from orion.config import OrionConfig
from orion.db.database import OrionDatabase

try:
    import pyautogui

    pyautogui.FAILSAFE = True
except Exception:  # pragma: no cover
    pyautogui = None

try:
    from PIL import ImageGrab
except Exception:  # pragma: no cover
    ImageGrab = None


# Safe AST binary operators for built-in voice/text arithmetic
_SAFE_BIN_OPS = {
    ast.Add: operator.add,
    ast.Sub: operator.sub,
    ast.Mult: operator.mul,
    ast.Div: operator.truediv,
    ast.FloorDiv: operator.floordiv,
    ast.Mod: operator.mod,
    ast.Pow: operator.pow,
}
_SAFE_UNARY_OPS = {
    ast.UAdd: operator.pos,
    ast.USub: operator.neg,
}

# Common Windows fallback executable locations for popular apps
_WINDOWS_COMMON_PATHS: dict[str, list[str]] = {
    "chrome": [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
    ],
    "msedge": [
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
    ],
    "code": [
        os.path.expandvars(r"%LOCALAPPDATA%\Programs\Microsoft VS Code\Code.exe"),
        r"C:\Program Files\Microsoft VS Code\Code.exe",
    ],
}


class DesktopAutomationModule:
    """Executes approved desktop, browser, screenshot, media, and utility tasks."""

    def __init__(self, config: OrionConfig, db: OrionDatabase) -> None:
        self.config = config
        self.db = db
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)

    # ------------------------------------------------------------------ #
    # Date, Time & System Info
    # ------------------------------------------------------------------ #
    def get_current_time(self) -> tuple[str, dict[str, Any]]:
        now = datetime.now()
        formatted = now.strftime("%I:%M %p").lstrip("0")
        return f"The current time is {formatted}.", {
            "time": formatted,
            "iso": now.isoformat(),
        }

    def get_current_date(self) -> tuple[str, dict[str, Any]]:
        now = datetime.now()
        formatted = now.strftime("%A, %B %d, %Y")
        return f"Today is {formatted}.", {
            "date": formatted,
            "iso": now.date().isoformat(),
        }

    def get_system_status(self) -> tuple[str, dict[str, Any]]:
        cpu = psutil.cpu_percent(interval=0.2)
        mem = psutil.virtual_memory()
        disk = psutil.disk_usage(str(Path.home().anchor or "C:\\"))
        battery = psutil.sensors_battery()
        bat_info = (
            f"{round(battery.percent)}% ({'charging' if battery.power_plugged else 'on battery'})"
            if battery
            else "Desktop AC power"
        )
        msg = (
            f"System status: CPU usage is {cpu:.0f}%, RAM usage is {mem.percent:.0f}% "
            f"({mem.used / (1024**3):.1f} of {mem.total / (1024**3):.1f} GB), "
            f"disk usage is {disk.percent:.0f}%, and power status is {bat_info}."
        )
        return msg, {
            "os": f"{platform.system()} {platform.release()}",
            "cpu_percent": cpu,
            "ram_percent": mem.percent,
            "ram_used_gb": round(mem.used / (1024**3), 2),
            "ram_total_gb": round(mem.total / (1024**3), 2),
            "disk_percent": disk.percent,
            "battery": bat_info,
        }

    # ------------------------------------------------------------------ #
    # Applications
    # ------------------------------------------------------------------ #
    def open_application(self, app_record: dict[str, Any]) -> tuple[str, dict[str, Any]]:
        exe_raw = str(app_record["executable_path"]).strip()
        display_name = str(app_record["display_name"]).strip()
        args_raw = str(app_record.get("arguments") or "").strip()

        # Windows URI protocol (e.g. ms-settings:)
        if exe_raw.endswith(":") and platform.system() == "Windows":
            os.startfile(exe_raw)  # type: ignore[attr-defined]
            return f"Opening {display_name}.", {"app": display_name, "target": exe_raw}

        resolved = self._resolve_executable(exe_raw)
        if not resolved:
            raise FileNotFoundError(
                f"Could not locate '{display_name}' ({exe_raw}) on this machine. "
                "Update its executable path in the Applications Manager."
            )

        extra_args = shlex.split(args_raw, posix=False) if args_raw else []
        creationflags = 0
        if platform.system() == "Windows":
            creationflags = getattr(subprocess, "DETACHED_PROCESS", 0) | getattr(
                subprocess, "CREATE_NEW_PROCESS_GROUP", 0
            )
            # For console apps like cmd/powershell, allow normal console window
            if Path(resolved).name.lower() in {"cmd.exe", "powershell.exe", "wt.exe"}:
                creationflags = getattr(subprocess, "CREATE_NEW_CONSOLE", 0)

        subprocess.Popen(
            [resolved, *extra_args],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=creationflags,
        )
        return f"Opening {display_name}.", {
            "app": display_name,
            "executable": resolved,
        }

    def _resolve_executable(self, exe: str) -> str | None:
        if os.path.isabs(exe) and Path(exe).exists():
            return exe
        found = shutil.which(exe)
        if found:
            return found
        key = exe.lower().removesuffix(".exe")
        for candidate in _WINDOWS_COMMON_PATHS.get(key, []):
            if Path(candidate).exists():
                return candidate
        return None

    # ------------------------------------------------------------------ #
    # Websites & Web Search
    # ------------------------------------------------------------------ #
    def open_website(self, name: str, url: str) -> tuple[str, dict[str, Any]]:
        target = url.strip()
        if not target.startswith(("http://", "https://")):
            target = f"https://{target}"
        webbrowser.open(target, new=2)
        return f"Opening {name} in your browser.", {"name": name, "url": target}

    def search_google(self, query: str) -> tuple[str, dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("Please specify what you want to search for.")
        url = f"https://www.google.com/search?q={quote_plus(cleaned)}"
        webbrowser.open(url, new=2)
        return f"Searching Google for '{cleaned}'.", {"query": cleaned, "url": url}

    def search_youtube(self, query: str) -> tuple[str, dict[str, Any]]:
        cleaned = query.strip()
        if not cleaned:
            raise ValueError("Please specify what you want to search on YouTube.")
        url = f"https://www.youtube.com/results?search_query={quote_plus(cleaned)}"
        webbrowser.open(url, new=2)
        return f"Searching YouTube for '{cleaned}'.", {"query": cleaned, "url": url}

    # ------------------------------------------------------------------ #
    # Screenshots
    # ------------------------------------------------------------------ #
    def take_screenshot(self, note: str = "") -> tuple[str, dict[str, Any]]:
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")[:-3]
        filename = f"orion_screenshot_{stamp}.png"
        filepath = self.config.screenshot_dir / filename

        img = None
        if ImageGrab is not None:
            try:
                img = ImageGrab.grab(all_screens=False)
            except Exception:
                img = None
        if img is None and pyautogui is not None:
            img = pyautogui.screenshot()
        if img is None:
            raise RuntimeError(
                "Screenshot capture failed: neither Pillow ImageGrab nor PyAutoGUI could capture the display."
            )

        img.save(str(filepath), format="PNG")
        width, height = img.size
        record = self.db.add_screenshot(
            filename=filename,
            file_path=str(filepath.resolve()),
            width=width,
            height=height,
            note=note,
        )
        return (
            f"Screenshot saved as {filename} ({width}x{height}).",
            {"screenshot": record},
        )

    def open_screenshot_file(self, file_path: str) -> tuple[str, dict[str, Any]]:
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Screenshot file not found: {file_path}")
        if platform.system() == "Windows":
            os.startfile(str(path))  # type: ignore[attr-defined]
        else:
            webbrowser.open(path.as_uri())
        return f"Opened screenshot {path.name}.", {"file_path": str(path)}

    def open_screenshots_folder(self) -> tuple[str, dict[str, Any]]:
        self.config.screenshot_dir.mkdir(parents=True, exist_ok=True)
        if platform.system() == "Windows":
            os.startfile(str(self.config.screenshot_dir))  # type: ignore[attr-defined]
        else:
            webbrowser.open(self.config.screenshot_dir.as_uri())
        return "Opened the screenshots folder.", {
            "folder": str(self.config.screenshot_dir)
        }

    # ------------------------------------------------------------------ #
    # PyAutoGUI Media, Volume & Window Automation
    # ------------------------------------------------------------------ #
    def media_control(self, action: str) -> tuple[str, dict[str, Any]]:
        if pyautogui is None:
            raise RuntimeError("PyAutoGUI is not available for keyboard/media automation.")

        key_map = {
            "volume_up": ("volumeup", 4, "Increased system volume."),
            "volume_down": ("volumedown", 4, "Decreased system volume."),
            "volume_mute": ("volumemute", 1, "Toggled system mute."),
            "play_pause": ("playpause", 1, "Toggled media play/pause."),
            "next_track": ("nexttrack", 1, "Skipped to the next track."),
            "prev_track": ("prevtrack", 1, "Went back to the previous track."),
        }
        if action not in key_map:
            raise ValueError(f"Unsupported media action: {action}")
        key_name, presses, message = key_map[action]
        pyautogui.press(key_name, presses=presses)
        return message, {"action": action, "key": key_name}

    def minimize_all_windows(self) -> tuple[str, dict[str, Any]]:
        if pyautogui is None:
            raise RuntimeError("PyAutoGUI is not available.")
        pyautogui.hotkey("win", "d")
        return "Showing desktop (minimized windows).", {"action": "show_desktop"}

    def lock_workstation(self) -> tuple[str, dict[str, Any]]:
        if platform.system() != "Windows":
            raise RuntimeError("Lock workstation is only supported on Windows.")
        ctypes.windll.user32.LockWorkStation()
        return "Locking your Windows workstation.", {"action": "lock_screen"}

    def system_power(self, mode: str) -> tuple[str, dict[str, Any]]:
        """Execute confirmed power action (shutdown or restart with 30s grace timer)."""
        if platform.system() != "Windows":
            raise RuntimeError("Power commands are only supported on Windows.")
        if mode == "shutdown":
            subprocess.Popen(["shutdown", "/s", "/t", "30"])
            return (
                "Scheduled Windows shutdown in 30 seconds. Say 'cancel shutdown' to abort.",
                {"action": "shutdown", "delay_seconds": 30},
            )
        if mode == "restart":
            subprocess.Popen(["shutdown", "/r", "/t", "30"])
            return (
                "Scheduled Windows restart in 30 seconds. Say 'cancel shutdown' to abort.",
                {"action": "restart", "delay_seconds": 30},
            )
        if mode == "cancel_shutdown":
            subprocess.Popen(["shutdown", "/a"])
            return "Cancelled any scheduled shutdown or restart.", {
                "action": "cancel_shutdown"
            }
        raise ValueError(f"Unsupported power mode: {mode}")

    # ------------------------------------------------------------------ #
    # Safe Math Evaluator
    # ------------------------------------------------------------------ #
    def calculate_expression(self, expr: str) -> tuple[str, dict[str, Any]]:
        cleaned = (
            expr.lower()
            .replace("plus", "+")
            .replace("minus", "-")
            .replace("times", "*")
            .replace("multiplied by", "*")
            .replace("into", "*")
            .replace("x", "*")
            .replace("divided by", "/")
            .replace("over", "/")
            .replace("to the power of", "**")
            .replace("^", "**")
            .strip()
        )
        if not cleaned or len(cleaned) > 80:
            raise ValueError("Please provide a valid arithmetic expression.")
        tree = ast.parse(cleaned, mode="eval")
        result = self._eval_ast(tree.body)
        if isinstance(result, float) and result.is_integer():
            display_val = str(int(result))
        elif isinstance(result, float):
            display_val = f"{result:.4f}".rstrip("0").rstrip(".")
        else:
            display_val = str(result)
        return f"The result of {cleaned} is {display_val}.", {
            "expression": cleaned,
            "result": display_val,
        }

    def _eval_ast(self, node: ast.AST) -> float:
        if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)):
            return float(node.value)
        if isinstance(node, ast.UnaryOp) and type(node.op) in _SAFE_UNARY_OPS:
            return _SAFE_UNARY_OPS[type(node.op)](self._eval_ast(node.operand))
        if isinstance(node, ast.BinOp) and type(node.op) in _SAFE_BIN_OPS:
            left = self._eval_ast(node.left)
            right = self._eval_ast(node.right)
            if isinstance(node.op, ast.Pow) and abs(right) > 100:
                raise ValueError("Exponent is too large.")
            if isinstance(node.op, (ast.Div, ast.FloorDiv, ast.Mod)) and right == 0:
                raise ZeroDivisionError("Cannot divide by zero.")
            return _SAFE_BIN_OPS[type(node.op)](left, right)
        raise ValueError("Only basic arithmetic operations (+, -, *, /, %, **) are supported.")
