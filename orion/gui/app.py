"""Native Tkinter Desktop GUI for ORION (Synopsis Sections 8 & 9).

Thread-safe architecture: all events from OrionAssistant background threads are
pushed onto a Python Queue and drained on the Tk main thread via `root.after()`.
"""

from __future__ import annotations

import queue
import threading
import tkinter as tk
import webbrowser
from datetime import datetime
from pathlib import Path
from tkinter import filedialog, messagebox, ttk
from typing import Any

from PIL import Image, ImageTk

from orion.api.server import OrionAPIServer
from orion.core.assistant import OrionAssistant
from orion.core.models import InputMode

# Dark Cosmic ORION Palette
COLORS = {
    "bg": "#0B1020",
    "panel": "#131C33",
    "card": "#182342",
    "input": "#0E1529",
    "border": "#273761",
    "text": "#EEF3FF",
    "muted": "#93A4CC",
    "primary": "#4F8CFF",
    "primary_dark": "#3A74E5",
    "accent": "#22D3EE",
    "success": "#22C55E",
    "warning": "#F59E0B",
    "danger": "#EF4444",
}

STATE_COLORS = {
    "idle": "#4F8CFF",
    "calibrating": "#F59E0B",
    "listening": "#22D3EE",
    "recognizing": "#38BDF8",
    "processing": "#818CF8",
    "executing": "#6366F1",
    "speaking": "#22C55E",
    "awaiting_confirmation": "#F59E0B",
    "error": "#EF4444",
}


class OrionDesktopApp:
    """Complete multi-tab Tkinter desktop application for ORION."""

    def __init__(
        self,
        assistant: OrionAssistant,
        api_server: OrionAPIServer | None = None,
    ) -> None:
        self.assistant = assistant
        self.api_server = api_server
        self._event_queue: queue.Queue[dict[str, Any]] = queue.Queue()
        self._current_state = "idle"
        self._pulse_phase = 0
        self._active_confirm_token: str | None = None
        self._preview_photo: ImageTk.PhotoImage | None = None
        self._mic_map: dict[str, str] = {}
        self._voice_map: dict[str, str] = {}

        self.root = tk.Tk()
        self.root.title("ORION — Voice-Controlled Desktop Virtual Assistant")
        self.root.geometry("1180x760")
        self.root.minsize(960, 640)
        self.root.configure(bg=COLORS["bg"])
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

        self._configure_styles()
        self._build_header()
        self._build_notebook()
        self._build_statusbar()

        # Subscribe to assistant events
        self.assistant.subscribe(self._enqueue_event)

        # Populate initial data
        self._refresh_apps_table()
        self._refresh_websites_table()
        self._refresh_history_table()
        self._refresh_screenshots_list()
        self._refresh_notes_list()
        self._load_settings_form()
        self._load_recent_feed()

        # Start UI event polling & orb animation loop
        self._poll_events()
        self._animate_orb()

    # ------------------------------------------------------------------ #
    # Styling
    # ------------------------------------------------------------------ #
    def _configure_styles(self) -> None:
        style = ttk.Style(self.root)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass

        style.configure("TFrame", background=COLORS["bg"])
        style.configure("Card.TFrame", background=COLORS["card"])
        style.configure("Panel.TFrame", background=COLORS["panel"])
        style.configure(
            "TLabel",
            background=COLORS["bg"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Card.TLabel",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Segoe UI", 10),
        )
        style.configure(
            "Muted.TLabel",
            background=COLORS["card"],
            foreground=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        style.configure(
            "Heading.TLabel",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Segoe UI", 11, "bold"),
        )

        # Notebook tabs
        style.configure(
            "TNotebook",
            background=COLORS["bg"],
            borderwidth=0,
            tabmargins=[6, 6, 6, 0],
        )
        style.configure(
            "TNotebook.Tab",
            background=COLORS["panel"],
            foreground=COLORS["muted"],
            padding=[16, 9],
            font=("Segoe UI", 10, "bold"),
            borderwidth=0,
        )
        style.map(
            "TNotebook.Tab",
            background=[("selected", COLORS["primary"])],
            foreground=[("selected", "#FFFFFF")],
        )

        # Buttons
        style.configure(
            "Primary.TButton",
            background=COLORS["primary"],
            foreground="#FFFFFF",
            font=("Segoe UI", 10, "bold"),
            padding=[14, 7],
            borderwidth=0,
        )
        style.map(
            "Primary.TButton",
            background=[("active", COLORS["primary_dark"]), ("disabled", "#334155")],
        )
        style.configure(
            "Secondary.TButton",
            background=COLORS["panel"],
            foreground=COLORS["text"],
            font=("Segoe UI", 9, "bold"),
            padding=[11, 6],
            borderwidth=1,
        )
        style.map("Secondary.TButton", background=[("active", "#223158")])

        style.configure(
            "Danger.TButton",
            background="#7F1D1D",
            foreground="#FEE2E2",
            font=("Segoe UI", 9, "bold"),
            padding=[11, 6],
            borderwidth=0,
        )
        style.map("Danger.TButton", background=[("active", COLORS["danger"])])

        # Treeview
        style.configure(
            "Treeview",
            background=COLORS["input"],
            foreground=COLORS["text"],
            fieldbackground=COLORS["input"],
            rowheight=28,
            font=("Segoe UI", 9),
            borderwidth=0,
        )
        style.configure(
            "Treeview.Heading",
            background=COLORS["panel"],
            foreground=COLORS["accent"],
            font=("Segoe UI", 9, "bold"),
            borderwidth=0,
        )
        style.map(
            "Treeview",
            background=[("selected", COLORS["primary_dark"])],
            foreground=[("selected", "#FFFFFF")],
        )

        style.configure(
            "TEntry",
            fieldbackground=COLORS["input"],
            foreground=COLORS["text"],
            insertcolor=COLORS["text"],
        )
        style.configure(
            "TCombobox",
            fieldbackground=COLORS["input"],
            background=COLORS["panel"],
            foreground=COLORS["text"],
        )
        style.configure(
            "Card.TCheckbutton",
            background=COLORS["card"],
            foreground=COLORS["text"],
            font=("Segoe UI", 9),
        )

    # ------------------------------------------------------------------ #
    # Header & Status Bar
    # ------------------------------------------------------------------ #
    def _build_header(self) -> None:
        header = tk.Frame(self.root, bg=COLORS["panel"], height=64)
        header.pack(fill="x", side="top")
        header.pack_propagate(False)

        left = tk.Frame(header, bg=COLORS["panel"])
        left.pack(side="left", padx=18, pady=10)

        tk.Label(
            left,
            text="✦ ORION",
            bg=COLORS["panel"],
            fg=COLORS["accent"],
            font=("Segoe UI", 16, "bold"),
        ).pack(side="left")

        tk.Label(
            left,
            text="  Voice-Controlled Desktop Virtual Assistant",
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("Segoe UI", 10),
        ).pack(side="left", padx=(4, 0))

        right = tk.Frame(header, bg=COLORS["panel"])
        right.pack(side="right", padx=18)

        self.state_badge = tk.Label(
            right,
            text="IDLE",
            bg="#1E293B",
            fg=COLORS["accent"],
            font=("Segoe UI", 9, "bold"),
            padx=12,
            pady=4,
        )
        self.state_badge.pack(side="left", padx=(0, 10))

        self.wake_btn = ttk.Button(
            right,
            text="Wake Word: OFF",
            style="Secondary.TButton",
            command=self._toggle_wake_word,
        )
        self.wake_btn.pack(side="left", padx=4)

        self.mute_btn = ttk.Button(
            right,
            text="Voice: ON" if self.assistant.tts.enabled else "Voice: Muted",
            style="Secondary.TButton",
            command=self._toggle_tts_mute,
        )
        self.mute_btn.pack(side="left", padx=4)

        ttk.Button(
            right,
            text="Replay",
            style="Secondary.TButton",
            command=self._replay_last_speech,
        ).pack(side="left", padx=4)

        ttk.Button(
            right,
            text="Stop Speech",
            style="Secondary.TButton",
            command=self._stop_speech,
        ).pack(side="left", padx=4)

        if self.api_server is not None:
            ttk.Button(
                right,
                text="Open Web Dashboard",
                style="Primary.TButton",
                command=lambda: webbrowser.open(self.api_server.url),
            ).pack(side="left", padx=(6, 0))

    def _build_statusbar(self) -> None:
        bar = tk.Frame(self.root, bg=COLORS["panel"], height=28)
        bar.pack(fill="x", side="bottom")
        bar.pack_propagate(False)

        self.status_var = tk.StringVar(value="Ready for voice or text command.")
        tk.Label(
            bar,
            textvariable=self.status_var,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="w",
        ).pack(side="left", padx=14)

        mic_ok = self.assistant.voice_input.is_microphone_available()
        tts_ok = self.assistant.tts.is_available
        api_text = f"  |  API: {self.api_server.url}" if self.api_server else ""
        hw_text = f"Mic: {'OK' if mic_ok else 'None'}  |  TTS: {'OK' if tts_ok else 'Off'}{api_text}"
        tk.Label(
            bar,
            text=hw_text,
            bg=COLORS["panel"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
            anchor="e",
        ).pack(side="right", padx=14)

    # ------------------------------------------------------------------ #
    # Main Tabbed Notebook
    # ------------------------------------------------------------------ #
    def _build_notebook(self) -> None:
        self.notebook = ttk.Notebook(self.root)
        self.notebook.pack(fill="both", expand=True, padx=14, pady=(10, 8))

        self.tab_console = ttk.Frame(self.notebook)
        self.tab_shortcuts = ttk.Frame(self.notebook)
        self.tab_history = ttk.Frame(self.notebook)
        self.tab_notes = ttk.Frame(self.notebook)
        self.tab_settings = ttk.Frame(self.notebook)

        self.notebook.add(self.tab_console, text="  Assistant Console  ")
        self.notebook.add(self.tab_shortcuts, text="  Apps & Websites  ")
        self.notebook.add(self.tab_history, text="  History & Screenshots  ")
        self.notebook.add(self.tab_notes, text="  Notes  ")
        self.notebook.add(self.tab_settings, text="  Settings & Commands  ")

        self._build_console_tab()
        self._build_shortcuts_tab()
        self._build_history_tab()
        self._build_notes_tab()
        self._build_settings_tab()

    # ------------------------------------------------------------------ #
    # TAB 1: Assistant Console
    # ------------------------------------------------------------------ #
    def _build_console_tab(self) -> None:
        container = tk.Frame(self.tab_console, bg=COLORS["bg"])
        container.pack(fill="both", expand=True, pady=6)
        container.columnconfigure(1, weight=1)
        container.rowconfigure(0, weight=1)

        # Left Panel: Voice Orb + Quick Actions
        left_card = tk.Frame(
            container, bg=COLORS["card"], width=320, highlightbackground=COLORS["border"], highlightthickness=1
        )
        left_card.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        left_card.grid_propagate(False)

        tk.Label(
            left_card,
            text="VOICE CONTROL",
            bg=COLORS["card"],
            fg=COLORS["accent"],
            font=("Segoe UI", 9, "bold"),
        ).pack(pady=(16, 4))

        self.orb_canvas = tk.Canvas(
            left_card,
            width=180,
            height=180,
            bg=COLORS["card"],
            highlightthickness=0,
            cursor="hand2",
        )
        self.orb_canvas.pack(pady=6)
        self.orb_outer = self.orb_canvas.create_oval(
            18, 18, 162, 162, outline=COLORS["accent"], width=2
        )
        self.orb_inner = self.orb_canvas.create_oval(
            34, 34, 146, 146, fill=COLORS["primary"], outline=""
        )
        self.orb_icon = self.orb_canvas.create_text(
            90, 90, text="🎙", fill="#FFFFFF", font=("Segoe UI Emoji", 30)
        )
        self.orb_canvas.bind("<Button-1>", lambda _e: self._start_voice_capture())

        self.orb_label_var = tk.StringVar(value="Click Orb to Speak")
        tk.Label(
            left_card,
            textvariable=self.orb_label_var,
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(pady=(2, 8))

        self.listen_btn = ttk.Button(
            left_card,
            text="Listen for Voice Command",
            style="Primary.TButton",
            command=self._start_voice_capture,
        )
        self.listen_btn.pack(fill="x", padx=20, pady=(0, 14))

        tk.Frame(left_card, bg=COLORS["border"], height=1).pack(fill="x", padx=16, pady=6)

        tk.Label(
            left_card,
            text="QUICK ACTIONS",
            bg=COLORS["card"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9, "bold"),
        ).pack(anchor="w", padx=18, pady=(8, 8))

        qa_frame = tk.Frame(left_card, bg=COLORS["card"])
        qa_frame.pack(fill="both", expand=True, padx=16)
        qa_frame.columnconfigure(0, weight=1)
        qa_frame.columnconfigure(1, weight=1)

        quick_commands = [
            ("Current Time", "What time is it?"),
            ("Today's Date", "What is today's date?"),
            ("Screenshot", "Take a screenshot"),
            ("System Info", "System status"),
            ("Open Notepad", "Open Notepad"),
            ("Calculator", "Open Calculator"),
            ("Open YouTube", "Open YouTube"),
            ("Weather", "What is the weather?"),
            ("Read Notes", "Read my notes"),
            ("Lock Screen", "Lock my screen"),
        ]
        for idx, (label, cmd) in enumerate(quick_commands):
            btn = ttk.Button(
                qa_frame,
                text=label,
                style="Secondary.TButton",
                command=lambda c=cmd: self._run_command_async(c, InputMode.QUICK_ACTION.value),
            )
            btn.grid(row=idx // 2, column=idx % 2, sticky="ew", padx=4, pady=4)

        # Right Panel: Transcript Feed + Command Entry
        right_card = tk.Frame(
            container, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1
        )
        right_card.grid(row=0, column=1, sticky="nsew")
        right_card.rowconfigure(1, weight=1)
        right_card.columnconfigure(0, weight=1)

        top_row = tk.Frame(right_card, bg=COLORS["card"])
        top_row.grid(row=0, column=0, sticky="ew", padx=16, pady=(14, 8))
        tk.Label(
            top_row,
            text="Command & Response Transcript",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(side="left")
        ttk.Button(
            top_row,
            text="Clear Feed",
            style="Secondary.TButton",
            command=self._clear_feed_widget,
        ).pack(side="right")

        feed_frame = tk.Frame(right_card, bg=COLORS["input"])
        feed_frame.grid(row=1, column=0, sticky="nsew", padx=16, pady=(0, 12))
        feed_frame.rowconfigure(0, weight=1)
        feed_frame.columnconfigure(0, weight=1)

        self.feed_text = tk.Text(
            feed_frame,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=("Segoe UI", 10),
            wrap="word",
            relief="flat",
            padx=14,
            pady=12,
            state="disabled",
        )
        feed_scroll = ttk.Scrollbar(feed_frame, orient="vertical", command=self.feed_text.yview)
        self.feed_text.configure(yscrollcommand=feed_scroll.set)
        self.feed_text.grid(row=0, column=0, sticky="nsew")
        feed_scroll.grid(row=0, column=1, sticky="ns")

        # Text tags for clean formatting
        self.feed_text.tag_configure("user", foreground="#93C5FD", font=("Segoe UI", 10, "bold"))
        self.feed_text.tag_configure("orion", foreground="#EEF3FF", font=("Segoe UI", 10))
        self.feed_text.tag_configure("meta", foreground=COLORS["muted"], font=("Segoe UI", 8))
        self.feed_text.tag_configure("error", foreground="#FCA5A5", font=("Segoe UI", 10))
        self.feed_text.tag_configure("warn", foreground="#FDE68A", font=("Segoe UI", 10, "bold"))
        self.feed_text.tag_configure("system", foreground=COLORS["accent"], font=("Segoe UI", 9, "italic"))

        self._append_system_note(
            "ORION ready. Speak a command using the microphone orb or type below "
            "(e.g., 'What time is it?', 'Open Notepad', 'Search Google for Python', 'Take a screenshot')."
        )

        # Command Entry Bar
        input_bar = tk.Frame(right_card, bg=COLORS["card"])
        input_bar.grid(row=2, column=0, sticky="ew", padx=16, pady=(0, 16))
        input_bar.columnconfigure(0, weight=1)

        self.cmd_entry_var = tk.StringVar()
        self.cmd_entry = tk.Entry(
            input_bar,
            textvariable=self.cmd_entry_var,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            font=("Segoe UI", 11),
            relief="flat",
            highlightbackground=COLORS["border"],
            highlightcolor=COLORS["primary"],
            highlightthickness=1,
        )
        self.cmd_entry.grid(row=0, column=0, sticky="ew", ipady=8, padx=(0, 8))
        self.cmd_entry.bind("<Return>", lambda _e: self._submit_text_command())

        self.speak_reply_var = tk.BooleanVar(value=self.assistant.tts.enabled)
        ttk.Checkbutton(
            input_bar,
            text="Speak",
            variable=self.speak_reply_var,
            command=self._on_speak_checkbox_toggle,
            style="Card.TCheckbutton",
        ).grid(row=0, column=1, padx=(0, 8))

        ttk.Button(
            input_bar,
            text="Run Command",
            style="Primary.TButton",
            command=self._submit_text_command,
        ).grid(row=0, column=2)

    # ------------------------------------------------------------------ #
    # TAB 2: Applications & Websites CRUD
    # ------------------------------------------------------------------ #
    def _build_shortcuts_tab(self) -> None:
        pane = ttk.PanedWindow(self.tab_shortcuts, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=6)

        # --- Left: Applications ---
        apps_card = tk.Frame(pane, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        pane.add(apps_card, weight=1)

        tk.Label(
            apps_card, text="Registered Applications (Voice: 'Open <alias>')",
            bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=14, pady=(12, 8))

        app_form = tk.Frame(apps_card, bg=COLORS["card"])
        app_form.pack(fill="x", padx=14, pady=(0, 10))
        app_form.columnconfigure(1, weight=1)

        self.app_alias_var = tk.StringVar()
        self.app_name_var = tk.StringVar()
        self.app_exe_var = tk.StringVar()
        self.app_confirm_var = tk.BooleanVar(value=False)

        self._form_entry(app_form, 0, "Alias:", self.app_alias_var)
        self._form_entry(app_form, 1, "Display Name:", self.app_name_var)

        tk.Label(app_form, text="Executable:", bg=COLORS["card"], fg=COLORS["muted"]).grid(
            row=2, column=0, sticky="w", pady=3, padx=(0, 8)
        )
        exe_row = tk.Frame(app_form, bg=COLORS["card"])
        exe_row.grid(row=2, column=1, sticky="ew", pady=3)
        exe_row.columnconfigure(0, weight=1)
        tk.Entry(
            exe_row, textvariable=self.app_exe_var, bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat"
        ).grid(row=0, column=0, sticky="ew", ipady=4)
        ttk.Button(exe_row, text="Browse", style="Secondary.TButton", command=self._browse_exe).grid(
            row=0, column=1, padx=(6, 0)
        )

        ttk.Checkbutton(
            app_form, text="Require confirmation before launch",
            variable=self.app_confirm_var, style="Card.TCheckbutton"
        ).grid(row=3, column=0, columnspan=2, sticky="w", pady=4)

        btn_row = tk.Frame(app_form, bg=COLORS["card"])
        btn_row.grid(row=4, column=0, columnspan=2, sticky="ew", pady=(4, 0))
        ttk.Button(btn_row, text="Save App", style="Primary.TButton", command=self._save_app).pack(side="left")
        ttk.Button(btn_row, text="Launch Selected", style="Secondary.TButton", command=self._launch_selected_app).pack(side="left", padx=6)
        ttk.Button(btn_row, text="Delete Selected", style="Danger.TButton", command=self._delete_selected_app).pack(side="right")

        self.apps_tree = ttk.Treeview(
            apps_card, columns=("alias", "name", "exe", "guard"), show="headings"
        )
        self.apps_tree.heading("alias", text="Alias")
        self.apps_tree.heading("name", text="Name")
        self.apps_tree.heading("exe", text="Executable")
        self.apps_tree.heading("guard", text="Safety")
        self.apps_tree.column("alias", width=110)
        self.apps_tree.column("name", width=130)
        self.apps_tree.column("exe", width=150)
        self.apps_tree.column("guard", width=75)
        self.apps_tree.pack(fill="both", expand=True, padx=14, pady=(0, 14))

        # --- Right: Websites ---
        sites_card = tk.Frame(pane, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        pane.add(sites_card, weight=1)

        tk.Label(
            sites_card, text="Registered Websites (Voice: 'Open <alias>')",
            bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 10, "bold")
        ).pack(anchor="w", padx=14, pady=(12, 8))

        site_form = tk.Frame(sites_card, bg=COLORS["card"])
        site_form.pack(fill="x", padx=14, pady=(0, 10))
        site_form.columnconfigure(1, weight=1)

        self.site_alias_var = tk.StringVar()
        self.site_name_var = tk.StringVar()
        self.site_url_var = tk.StringVar()
        self._form_entry(site_form, 0, "Alias:", self.site_alias_var)
        self._form_entry(site_form, 1, "Display Name:", self.site_name_var)
        self._form_entry(site_form, 2, "URL:", self.site_url_var)

        sbtn_row = tk.Frame(site_form, bg=COLORS["card"])
        sbtn_row.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(8, 0))
        ttk.Button(sbtn_row, text="Save Website", style="Primary.TButton", command=self._save_website).pack(side="left")
        ttk.Button(sbtn_row, text="Open Selected", style="Secondary.TButton", command=self._open_selected_website).pack(side="left", padx=6)
        ttk.Button(sbtn_row, text="Delete Selected", style="Danger.TButton", command=self._delete_selected_website).pack(side="right")

        self.sites_tree = ttk.Treeview(
            sites_card, columns=("alias", "name", "url"), show="headings"
        )
        self.sites_tree.heading("alias", text="Alias")
        self.sites_tree.heading("name", text="Display Name")
        self.sites_tree.heading("url", text="URL")
        self.sites_tree.column("alias", width=110)
        self.sites_tree.column("name", width=130)
        self.sites_tree.column("url", width=210)
        self.sites_tree.pack(fill="both", expand=True, padx=14, pady=(0, 14))

    # ------------------------------------------------------------------ #
    # TAB 3: History & Screenshots
    # ------------------------------------------------------------------ #
    def _build_history_tab(self) -> None:
        pane = ttk.PanedWindow(self.tab_history, orient="vertical")
        pane.pack(fill="both", expand=True, pady=6)

        # Top: Command History
        hist_card = tk.Frame(pane, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        pane.add(hist_card, weight=3)

        toolbar = tk.Frame(hist_card, bg=COLORS["card"])
        toolbar.pack(fill="x", padx=14, pady=(12, 8))
        tk.Label(
            toolbar, text="Command History Log", bg=COLORS["card"], fg=COLORS["text"],
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")

        self.hist_search_var = tk.StringVar()
        self.hist_search_var.trace_add("write", lambda *_: self._refresh_history_table())
        tk.Entry(
            toolbar, textvariable=self.hist_search_var, bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat", width=28
        ).pack(side="left", padx=12, ipady=4)

        ttk.Button(toolbar, text="Re-run Selected", style="Primary.TButton", command=self._rerun_selected_history).pack(side="right", padx=4)
        ttk.Button(toolbar, text="Clear All", style="Danger.TButton", command=self._clear_all_history).pack(side="right", padx=4)
        ttk.Button(toolbar, text="Refresh", style="Secondary.TButton", command=self._refresh_history_table).pack(side="right", padx=4)

        self.hist_tree = ttk.Treeview(
            hist_card, columns=("time", "mode", "command", "intent", "status", "response"), show="headings"
        )
        for col, title, width in [
            ("time", "Time", 85),
            ("mode", "Mode", 75),
            ("command", "Command", 210),
            ("intent", "Intent", 120),
            ("status", "Status", 95),
            ("response", "Response", 380),
        ]:
            self.hist_tree.heading(col, text=title)
            self.hist_tree.column(col, width=width)
        self.hist_tree.pack(fill="both", expand=True, padx=14, pady=(0, 12))

        # Bottom: Screenshots
        shot_card = tk.Frame(pane, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        pane.add(shot_card, weight=2)

        shot_top = tk.Frame(shot_card, bg=COLORS["card"])
        shot_top.pack(fill="x", padx=14, pady=(10, 6))
        tk.Label(
            shot_top, text="Captured Screenshots", bg=COLORS["card"], fg=COLORS["text"],
            font=("Segoe UI", 10, "bold")
        ).pack(side="left")
        ttk.Button(
            shot_top, text="Capture Now", style="Primary.TButton",
            command=lambda: self._run_command_async("Take a screenshot", InputMode.QUICK_ACTION.value)
        ).pack(side="right", padx=4)
        ttk.Button(shot_top, text="Open Folder", style="Secondary.TButton", command=self._open_shots_folder).pack(side="right", padx=4)
        ttk.Button(shot_top, text="Open File", style="Secondary.TButton", command=self._open_selected_shot).pack(side="right", padx=4)
        ttk.Button(shot_top, text="Delete", style="Danger.TButton", command=self._delete_selected_shot).pack(side="right", padx=4)

        shot_body = tk.Frame(shot_card, bg=COLORS["card"])
        shot_body.pack(fill="both", expand=True, padx=14, pady=(0, 12))
        shot_body.columnconfigure(0, weight=2)
        shot_body.columnconfigure(1, weight=1)
        shot_body.rowconfigure(0, weight=1)

        self.shots_tree = ttk.Treeview(
            shot_body, columns=("file", "dims", "captured"), show="headings"
        )
        self.shots_tree.heading("file", text="Filename")
        self.shots_tree.heading("dims", text="Dimensions")
        self.shots_tree.heading("captured", text="Captured At")
        self.shots_tree.column("file", width=260)
        self.shots_tree.column("dims", width=100)
        self.shots_tree.column("captured", width=150)
        self.shots_tree.grid(row=0, column=0, sticky="nsew", padx=(0, 12))
        self.shots_tree.bind("<<TreeviewSelect>>", self._on_select_screenshot)

        self.shot_preview_label = tk.Label(
            shot_body,
            text="Select a screenshot to preview",
            bg=COLORS["input"],
            fg=COLORS["muted"],
            font=("Segoe UI", 9),
        )
        self.shot_preview_label.grid(row=0, column=1, sticky="nsew")

    # ------------------------------------------------------------------ #
    # TAB 4: Notes
    # ------------------------------------------------------------------ #
    def _build_notes_tab(self) -> None:
        card = tk.Frame(self.tab_notes, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        card.pack(fill="both", expand=True, pady=6)

        tk.Label(
            card,
            text="Quick Notes & Reminders (Voice: 'Take a note ...' / 'Read my notes')",
            bg=COLORS["card"],
            fg=COLORS["text"],
            font=("Segoe UI", 11, "bold"),
        ).pack(anchor="w", padx=16, pady=(14, 10))

        bar = tk.Frame(card, bg=COLORS["card"])
        bar.pack(fill="x", padx=16, pady=(0, 12))
        self.note_entry_var = tk.StringVar()
        note_entry = tk.Entry(
            bar, textvariable=self.note_entry_var, bg=COLORS["input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], font=("Segoe UI", 10), relief="flat"
        )
        note_entry.pack(side="left", fill="x", expand=True, ipady=6, padx=(0, 8))
        note_entry.bind("<Return>", lambda _e: self._add_note())

        ttk.Button(bar, text="Add Note", style="Primary.TButton", command=self._add_note).pack(side="left", padx=4)
        ttk.Button(bar, text="Toggle Done", style="Secondary.TButton", command=self._toggle_selected_note).pack(side="left", padx=4)
        ttk.Button(bar, text="Delete", style="Danger.TButton", command=self._delete_selected_note).pack(side="left", padx=4)

        self.notes_tree = ttk.Treeview(card, columns=("status", "content", "created"), show="headings")
        self.notes_tree.heading("status", text="Status")
        self.notes_tree.heading("content", text="Note Content")
        self.notes_tree.heading("created", text="Created At")
        self.notes_tree.column("status", width=100)
        self.notes_tree.column("content", width=640)
        self.notes_tree.column("created", width=180)
        self.notes_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))

    # ------------------------------------------------------------------ #
    # TAB 5: Settings & Supported Commands Reference
    # ------------------------------------------------------------------ #
    def _build_settings_tab(self) -> None:
        pane = ttk.PanedWindow(self.tab_settings, orient="horizontal")
        pane.pack(fill="both", expand=True, pady=6)

        # Left: Settings Form
        set_card = tk.Frame(pane, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        pane.add(set_card, weight=1)

        tk.Label(
            set_card, text="Audio, Speech & Safety Settings", bg=COLORS["card"],
            fg=COLORS["text"], font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", padx=16, pady=(14, 10))

        form = tk.Frame(set_card, bg=COLORS["card"])
        form.pack(fill="x", padx=16)
        form.columnconfigure(1, weight=1)

        self.set_user_var = tk.StringVar()
        self.set_city_var = tk.StringVar()
        self.set_lang_var = tk.StringVar()
        self.set_engine_var = tk.StringVar()
        self.set_mic_var = tk.StringVar()
        self.set_voice_var = tk.StringVar()
        self.set_rate_var = tk.IntVar(value=175)
        self.set_vol_var = tk.DoubleVar(value=0.95)
        self.set_tts_enabled_var = tk.BooleanVar(value=True)
        self.set_confirm_var = tk.BooleanVar(value=True)

        self._form_entry(form, 0, "Your Name:", self.set_user_var)
        self._form_entry(form, 1, "Default Weather City:", self.set_city_var)

        tk.Label(form, text="STT Language:", bg=COLORS["card"], fg=COLORS["muted"]).grid(row=2, column=0, sticky="w", pady=5)
        ttk.Combobox(
            form, textvariable=self.set_lang_var, values=["en-IN", "en-US", "en-GB"], state="readonly"
        ).grid(row=2, column=1, sticky="ew", pady=5)

        tk.Label(form, text="STT Engine:", bg=COLORS["card"], fg=COLORS["muted"]).grid(row=3, column=0, sticky="w", pady=5)
        ttk.Combobox(
            form, textvariable=self.set_engine_var, values=["google", "sphinx"], state="readonly"
        ).grid(row=3, column=1, sticky="ew", pady=5)

        tk.Label(form, text="Microphone:", bg=COLORS["card"], fg=COLORS["muted"]).grid(row=4, column=0, sticky="w", pady=5)
        self.mic_combo = ttk.Combobox(form, textvariable=self.set_mic_var, state="readonly")
        self.mic_combo.grid(row=4, column=1, sticky="ew", pady=5)

        tk.Label(form, text="TTS Voice:", bg=COLORS["card"], fg=COLORS["muted"]).grid(row=5, column=0, sticky="w", pady=5)
        self.voice_combo = ttk.Combobox(form, textvariable=self.set_voice_var, state="readonly")
        self.voice_combo.grid(row=5, column=1, sticky="ew", pady=5)

        tk.Label(form, text="Speech Rate (WPM):", bg=COLORS["card"], fg=COLORS["muted"]).grid(row=6, column=0, sticky="w", pady=5)
        tk.Scale(
            form, from_=100, to=280, orient="horizontal", variable=self.set_rate_var,
            bg=COLORS["card"], fg=COLORS["text"], highlightthickness=0, troughcolor=COLORS["input"]
        ).grid(row=6, column=1, sticky="ew", pady=2)

        tk.Label(form, text="Speech Volume:", bg=COLORS["card"], fg=COLORS["muted"]).grid(row=7, column=0, sticky="w", pady=5)
        tk.Scale(
            form, from_=0.0, to=1.0, resolution=0.05, orient="horizontal", variable=self.set_vol_var,
            bg=COLORS["card"], fg=COLORS["text"], highlightthickness=0, troughcolor=COLORS["input"]
        ).grid(row=7, column=1, sticky="ew", pady=2)

        ttk.Checkbutton(
            form, text="Enable Text-to-Speech responses (pyttsx3)",
            variable=self.set_tts_enabled_var, style="Card.TCheckbutton"
        ).grid(row=8, column=0, columnspan=2, sticky="w", pady=(8, 4))

        ttk.Checkbutton(
            form, text="Require user confirmation for sensitive/system commands",
            variable=self.set_confirm_var, style="Card.TCheckbutton"
        ).grid(row=9, column=0, columnspan=2, sticky="w", pady=4)

        action_bar = tk.Frame(set_card, bg=COLORS["card"])
        action_bar.pack(fill="x", padx=16, pady=14)
        ttk.Button(action_bar, text="Save Settings", style="Primary.TButton", command=self._save_settings).pack(side="left")
        ttk.Button(action_bar, text="Calibrate Mic", style="Secondary.TButton", command=self._calibrate_mic).pack(side="left", padx=6)
        ttk.Button(action_bar, text="Test Voice", style="Secondary.TButton", command=self._test_voice).pack(side="left", padx=4)

        # Right: Built-in Commands Reference (double-click to run!)
        cmd_card = tk.Frame(pane, bg=COLORS["card"], highlightbackground=COLORS["border"], highlightthickness=1)
        pane.add(cmd_card, weight=1)

        tk.Label(
            cmd_card, text="Supported Commands Catalog (Double-click to Run)",
            bg=COLORS["card"], fg=COLORS["text"], font=("Segoe UI", 11, "bold")
        ).pack(anchor="w", padx=16, pady=(14, 10))

        self.cmd_tree = ttk.Treeview(
            cmd_card, columns=("cat", "title", "example", "safety"), show="headings"
        )
        self.cmd_tree.heading("cat", text="Category")
        self.cmd_tree.heading("title", text="Command")
        self.cmd_tree.heading("example", text="Example Phrase")
        self.cmd_tree.heading("safety", text="Safety")
        self.cmd_tree.column("cat", width=110)
        self.cmd_tree.column("title", width=140)
        self.cmd_tree.column("example", width=210)
        self.cmd_tree.column("safety", width=85)
        self.cmd_tree.pack(fill="both", expand=True, padx=16, pady=(0, 16))

        for item in self.assistant.command_processor.get_supported_commands():
            self.cmd_tree.insert(
                "",
                "end",
                values=(
                    item["category"],
                    item["title"],
                    item["examples"][0] if item["examples"] else "",
                    item["safety"],
                ),
            )
        self.cmd_tree.bind("<Double-1>", self._on_catalog_double_click)

    # ------------------------------------------------------------------ #
    # Helpers
    # ------------------------------------------------------------------ #
    def _form_entry(self, parent: tk.Widget, row: int, label: str, var: tk.StringVar) -> None:
        tk.Label(parent, text=label, bg=COLORS["card"], fg=COLORS["muted"]).grid(
            row=row, column=0, sticky="w", pady=4, padx=(0, 8)
        )
        tk.Entry(
            parent,
            textvariable=var,
            bg=COLORS["input"],
            fg=COLORS["text"],
            insertbackground=COLORS["text"],
            relief="flat",
        ).grid(row=row, column=1, sticky="ew", pady=4, ipady=4)

    # ------------------------------------------------------------------ #
    # Event Polling & Orb Animation (Main Thread Safe)
    # ------------------------------------------------------------------ #
    def _enqueue_event(self, event: dict[str, Any]) -> None:
        self._event_queue.put(event)

    def _poll_events(self) -> None:
        while not self._event_queue.empty():
            try:
                ev = self._event_queue.get_nowait()
                self._handle_event(ev)
            except queue.Empty:
                break
        self.root.after(80, self._poll_events)

    def _handle_event(self, event: dict[str, Any]) -> None:
        etype = event.get("type")
        if etype == "state_changed":
            self._current_state = event.get("state", "idle")
            detail = event.get("detail", "")
            color = STATE_COLORS.get(self._current_state, COLORS["primary"])
            self.state_badge.configure(
                text=self._current_state.replace("_", " ").upper(), fg=color
            )
            self.status_var.set(detail)
            self.orb_canvas.itemconfig(self.orb_inner, fill=color)
            self.orb_canvas.itemconfig(self.orb_outer, outline=color)
            if self._current_state == "listening":
                self.orb_label_var.set("Listening...")
            elif self._current_state == "recognizing":
                self.orb_label_var.set("Recognizing Speech...")
            elif self._current_state == "speaking":
                self.orb_label_var.set("Speaking...")
            elif self._current_state in {"processing", "executing"}:
                self.orb_label_var.set("Executing...")
            else:
                self.orb_label_var.set("Click Orb to Speak")

        elif etype == "command_result":
            res = event.get("result") or {}
            self._append_result_to_feed(res)
            self._refresh_history_table()
            if res.get("intent") == "take_screenshot":
                self._refresh_screenshots_list()
            if res.get("intent") in {"add_note", "list_notes"}:
                self._refresh_notes_list()

        elif etype == "confirmation_required":
            req = event.get("confirmation") or {}
            token = req.get("token")
            if token and token != self._active_confirm_token:
                self._active_confirm_token = token
                self._show_confirmation_dialog(req)

        elif etype == "wake_word_status":
            active = bool(event.get("active"))
            self.wake_btn.configure(text=f"Wake Word: {'ON' if active else 'OFF'}")

        elif etype == "settings_updated":
            s = event.get("settings") or {}
            enabled = str(s.get("tts_enabled", "true")).lower() == "true"
            self.speak_reply_var.set(enabled)
            self.mute_btn.configure(text="Voice: ON" if enabled else "Voice: Muted")

    def _animate_orb(self) -> None:
        self._pulse_phase = (self._pulse_phase + 1) % 20
        if self._current_state in {"listening", "speaking", "recognizing"}:
            delta = abs(10 - self._pulse_phase)
            pad = 10 + delta
            self.orb_canvas.coords(self.orb_outer, pad, pad, 180 - pad, 180 - pad)
        else:
            self.orb_canvas.coords(self.orb_outer, 18, 18, 162, 162)
        self.root.after(90, self._animate_orb)

    # ------------------------------------------------------------------ #
    # Assistant Actions
    # ------------------------------------------------------------------ #
    def _start_voice_capture(self) -> None:
        self.listen_btn.state(["disabled"])

        def _worker() -> None:
            try:
                self.assistant.listen_and_execute()
            finally:
                self.root.after(0, lambda: self.listen_btn.state(["!disabled"]))

        threading.Thread(target=_worker, daemon=True).start()

    def _submit_text_command(self) -> None:
        text = self.cmd_entry_var.get().strip()
        if not text:
            return
        self.cmd_entry_var.set("")
        self._run_command_async(text, InputMode.TEXT.value)

    def _run_command_async(self, text: str, mode: str) -> None:
        speak = self.speak_reply_var.get()
        threading.Thread(
            target=self.assistant.process_command,
            args=(text, mode, False, speak),
            daemon=True,
        ).start()

    def _show_confirmation_dialog(self, req: dict[str, Any]) -> None:
        token = req["token"]
        approved = messagebox.askyesno(
            "ORION Safety Confirmation",
            f"Action: {req.get('action_description')}\n\n"
            f"{req.get('warning_message')}\n\n"
            "Do you approve executing this command?",
            icon="warning",
            parent=self.root,
        )
        self._active_confirm_token = None
        threading.Thread(
            target=self.assistant.confirm_action,
            args=(token, approved, self.speak_reply_var.get()),
            daemon=True,
        ).start()

    def _toggle_wake_word(self) -> None:
        if self.assistant.is_wake_word_running():
            self.assistant.stop_wake_word_listener()
            self.wake_btn.configure(text="Wake Word: OFF")
        else:
            ok = self.assistant.start_wake_word_listener()
            if not ok:
                messagebox.showwarning(
                    "Microphone Unavailable",
                    "No microphone was detected. Connect a microphone to use Wake-Word mode.",
                    parent=self.root,
                )
            else:
                self.wake_btn.configure(text="Wake Word: ON")

    def _stop_speech(self) -> None:
        self.assistant.tts.stop()

    def _replay_last_speech(self) -> None:
        if not self.assistant.replay_last_response():
            self.status_var.set("No response available to replay yet.")

    def _toggle_tts_mute(self) -> None:
        new_state = not self.assistant.tts.enabled
        self.assistant.set_tts_enabled(new_state)
        self.speak_reply_var.set(new_state)
        self.mute_btn.configure(text="Voice: ON" if new_state else "Voice: Muted")
        self.status_var.set("Voice output unmuted." if new_state else "Voice output muted.")

    def _on_speak_checkbox_toggle(self) -> None:
        enabled = bool(self.speak_reply_var.get())
        self.assistant.set_tts_enabled(enabled)
        self.mute_btn.configure(text="Voice: ON" if enabled else "Voice: Muted")

    # ------------------------------------------------------------------ #
    # Feed Rendering
    # ------------------------------------------------------------------ #
    def _clear_feed_widget(self) -> None:
        self.feed_text.configure(state="normal")
        self.feed_text.delete("1.0", "end")
        self.feed_text.configure(state="disabled")

    def _append_system_note(self, text: str) -> None:
        self.feed_text.configure(state="normal")
        self.feed_text.insert("end", f"{text}\n\n", "system")
        self.feed_text.see("end")
        self.feed_text.configure(state="disabled")

    def _append_result_to_feed(self, res: dict[str, Any]) -> None:
        ts = datetime.now().strftime("%H:%M:%S")
        inp = res.get("input_text") or "(voice)"
        resp = res.get("response_text") or ""
        status = res.get("status", "success")
        intent = res.get("intent", "unknown")
        ms = res.get("execution_ms", 0)

        tag = "orion"
        if status in {"error", "blocked"}:
            tag = "error"
        elif status in {"pending_confirmation", "cancelled"}:
            tag = "warn"

        self.feed_text.configure(state="normal")
        self.feed_text.insert("end", f"[{ts}] You: {inp}\n", "user")
        self.feed_text.insert("end", f"ORION: {resp}\n", tag)
        self.feed_text.insert("end", f"   intent={intent}  •  status={status}  •  {ms} ms\n\n", "meta")
        self.feed_text.see("end")
        self.feed_text.configure(state="disabled")

    def _load_recent_feed(self) -> None:
        recent = self.assistant.db.get_history(limit=5)
        for item in reversed(recent):
            self._append_result_to_feed(
                {
                    "input_text": item["input_text"],
                    "response_text": item["response_text"],
                    "status": item["status"],
                    "intent": item["matched_intent"],
                    "execution_ms": item["execution_ms"],
                }
            )

    # ------------------------------------------------------------------ #
    # CRUD Handlers (Apps, Websites, History, Screenshots, Notes, Settings)
    # ------------------------------------------------------------------ #
    def _browse_exe(self) -> None:
        path = filedialog.askopenfilename(
            title="Select Application Executable",
            filetypes=[("Executables", "*.exe;*.bat;*.cmd;*.lnk"), ("All Files", "*.*")],
        )
        if path:
            self.app_exe_var.set(path)

    def _refresh_apps_table(self) -> None:
        self.apps_tree.delete(*self.apps_tree.get_children())
        for app in self.assistant.db.list_apps():
            self.apps_tree.insert(
                "",
                "end",
                iid=str(app["id"]),
                values=(
                    app["alias"],
                    app["display_name"],
                    app["executable_path"],
                    "Confirm" if app["requires_confirmation"] else "Safe",
                ),
            )

    def _save_app(self) -> None:
        try:
            self.assistant.db.upsert_app(
                alias=self.app_alias_var.get(),
                display_name=self.app_name_var.get(),
                executable_path=self.app_exe_var.get(),
                requires_confirmation=self.app_confirm_var.get(),
            )
            self.app_alias_var.set("")
            self.app_name_var.set("")
            self.app_exe_var.set("")
            self.app_confirm_var.set(False)
            self._refresh_apps_table()
            self.status_var.set("Application registered successfully.")
        except ValueError as exc:
            messagebox.showwarning("Validation Error", str(exc), parent=self.root)

    def _launch_selected_app(self) -> None:
        sel = self.apps_tree.selection()
        if not sel:
            return
        alias = self.apps_tree.item(sel[0], "values")[0]
        self._run_command_async(f"open {alias}", InputMode.QUICK_ACTION.value)

    def _delete_selected_app(self) -> None:
        sel = self.apps_tree.selection()
        if not sel:
            return
        self.assistant.db.delete_app(int(sel[0]))
        self._refresh_apps_table()

    def _refresh_websites_table(self) -> None:
        self.sites_tree.delete(*self.sites_tree.get_children())
        for site in self.assistant.db.list_websites():
            self.sites_tree.insert(
                "",
                "end",
                iid=str(site["id"]),
                values=(site["alias"], site["display_name"], site["url"]),
            )

    def _save_website(self) -> None:
        try:
            self.assistant.db.upsert_website(
                alias=self.site_alias_var.get(),
                display_name=self.site_name_var.get(),
                url=self.site_url_var.get(),
            )
            self.site_alias_var.set("")
            self.site_name_var.set("")
            self.site_url_var.set("")
            self._refresh_websites_table()
            self.status_var.set("Website bookmark saved.")
        except ValueError as exc:
            messagebox.showwarning("Validation Error", str(exc), parent=self.root)

    def _open_selected_website(self) -> None:
        sel = self.sites_tree.selection()
        if not sel:
            return
        alias = self.sites_tree.item(sel[0], "values")[0]
        self._run_command_async(f"open {alias}", InputMode.QUICK_ACTION.value)

    def _delete_selected_website(self) -> None:
        sel = self.sites_tree.selection()
        if not sel:
            return
        self.assistant.db.delete_website(int(sel[0]))
        self._refresh_websites_table()

    def _refresh_history_table(self) -> None:
        self.hist_tree.delete(*self.hist_tree.get_children())
        search = self.hist_search_var.get().strip() if hasattr(self, "hist_search_var") else ""
        for item in self.assistant.db.get_history(limit=150, search=search):
            ts = str(item["created_at"])[11:19]
            self.hist_tree.insert(
                "",
                "end",
                iid=str(item["id"]),
                values=(
                    ts,
                    item["input_mode"],
                    item["input_text"],
                    item["matched_intent"],
                    item["status"],
                    item["response_text"],
                ),
            )

    def _rerun_selected_history(self) -> None:
        sel = self.hist_tree.selection()
        if not sel:
            return
        cmd = self.hist_tree.item(sel[0], "values")[2]
        self.notebook.select(self.tab_console)
        self._run_command_async(cmd, InputMode.QUICK_ACTION.value)

    def _clear_all_history(self) -> None:
        if messagebox.askyesno("Confirm Clear", "Delete all command history entries?", parent=self.root):
            self.assistant.db.clear_history()
            self._refresh_history_table()

    def _refresh_screenshots_list(self) -> None:
        self.shots_tree.delete(*self.shots_tree.get_children())
        for s in self.assistant.db.list_screenshots(limit=50):
            self.shots_tree.insert(
                "",
                "end",
                iid=str(s["id"]),
                values=(s["filename"], f"{s['width']}x{s['height']}", str(s["captured_at"])[:19].replace("T", " ")),
            )

    def _on_select_screenshot(self, _event: Any) -> None:
        sel = self.shots_tree.selection()
        if not sel:
            return
        rec = self.assistant.db.get_screenshot(int(sel[0]))
        if not rec or not Path(rec["file_path"]).exists():
            self.shot_preview_label.configure(image="", text="Image file missing on disk")
            return
        try:
            img = Image.open(rec["file_path"])
            img.thumbnail((320, 190))
            self._preview_photo = ImageTk.PhotoImage(img)
            self.shot_preview_label.configure(image=self._preview_photo, text="")
        except Exception as exc:
            self.shot_preview_label.configure(image="", text=f"Preview error: {exc}")

    def _open_selected_shot(self) -> None:
        sel = self.shots_tree.selection()
        if not sel:
            return
        rec = self.assistant.db.get_screenshot(int(sel[0]))
        if rec:
            try:
                self.assistant.automation.open_screenshot_file(rec["file_path"])
            except Exception as exc:
                messagebox.showerror("Error", str(exc), parent=self.root)

    def _open_shots_folder(self) -> None:
        self.assistant.automation.open_screenshots_folder()

    def _delete_selected_shot(self) -> None:
        sel = self.shots_tree.selection()
        if not sel:
            return
        rec = self.assistant.db.delete_screenshot(int(sel[0]))
        if rec and Path(rec["file_path"]).exists():
            try:
                Path(rec["file_path"]).unlink()
            except OSError:
                pass
        self.shot_preview_label.configure(image="", text="Select a screenshot to preview")
        self._refresh_screenshots_list()

    def _refresh_notes_list(self) -> None:
        self.notes_tree.delete(*self.notes_tree.get_children())
        for n in self.assistant.db.list_notes(include_completed=True):
            self.notes_tree.insert(
                "",
                "end",
                iid=str(n["id"]),
                values=(
                    "Done" if n["is_completed"] else "Open",
                    n["content"],
                    str(n["created_at"])[:19].replace("T", " "),
                ),
            )

    def _add_note(self) -> None:
        content = self.note_entry_var.get().strip()
        if not content:
            return
        self.assistant.db.add_note(content)
        self.note_entry_var.set("")
        self._refresh_notes_list()

    def _toggle_selected_note(self) -> None:
        sel = self.notes_tree.selection()
        if not sel:
            return
        self.assistant.db.toggle_note(int(sel[0]))
        self._refresh_notes_list()

    def _delete_selected_note(self) -> None:
        sel = self.notes_tree.selection()
        if not sel:
            return
        self.assistant.db.delete_note(int(sel[0]))
        self._refresh_notes_list()

    def _load_settings_form(self) -> None:
        s = self.assistant.get_settings()
        self.set_user_var.set(s.get("user_name", "User"))
        self.set_city_var.set(s.get("default_city", "Delhi"))
        self.set_lang_var.set(s.get("stt_language", "en-IN"))
        self.set_engine_var.set(s.get("stt_engine", "google"))
        self.set_rate_var.set(int(float(s.get("tts_rate", "175") or 175)))
        self.set_vol_var.set(float(s.get("tts_volume", "0.95") or 0.95))
        self.set_tts_enabled_var.set(s.get("tts_enabled", "true").lower() == "true")
        self.set_confirm_var.set(s.get("require_confirmation", "true").lower() == "true")

        # Microphones
        mics = self.assistant.voice_input.list_microphones()
        self._mic_map = {"System Default": ""}
        mic_labels = ["System Default"]
        selected_mic_label = "System Default"
        for m in mics:
            lbl = f"[{m['index']}] {m['name']}"
            self._mic_map[lbl] = str(m["index"])
            mic_labels.append(lbl)
            if str(m["index"]) == s.get("stt_mic_index", ""):
                selected_mic_label = lbl
        self.mic_combo["values"] = mic_labels
        self.set_mic_var.set(selected_mic_label)

        # TTS Voices
        voices = self.assistant.tts.list_voices()
        self._voice_map = {"System Default": ""}
        voice_labels = ["System Default"]
        selected_voice_label = "System Default"
        for v in voices:
            lbl = v["name"]
            self._voice_map[lbl] = v["id"]
            voice_labels.append(lbl)
            if v["id"] == s.get("tts_voice_id", ""):
                selected_voice_label = lbl
        self.voice_combo["values"] = voice_labels
        self.set_voice_var.set(selected_voice_label)

    def _save_settings(self) -> None:
        self.assistant.update_settings(
            {
                "user_name": self.set_user_var.get().strip() or "User",
                "default_city": self.set_city_var.get().strip() or "Delhi",
                "stt_language": self.set_lang_var.get() or "en-IN",
                "stt_engine": self.set_engine_var.get() or "google",
                "stt_mic_index": self._mic_map.get(self.set_mic_var.get(), ""),
                "tts_voice_id": self._voice_map.get(self.set_voice_var.get(), ""),
                "tts_rate": self.set_rate_var.get(),
                "tts_volume": round(self.set_vol_var.get(), 2),
                "tts_enabled": self.set_tts_enabled_var.get(),
                "require_confirmation": self.set_confirm_var.get(),
            }
        )
        messagebox.showinfo("Settings Saved", "ORION settings were saved and applied.", parent=self.root)

    def _calibrate_mic(self) -> None:
        def _worker() -> None:
            res = self.assistant.calibrate_microphone()
            if res.get("success"):
                self.root.after(
                    0,
                    lambda: messagebox.showinfo(
                        "Calibration Complete",
                        f"Ambient noise calibrated (energy threshold: {res['energy_threshold']}).",
                        parent=self.root,
                    ),
                )
            else:
                self.root.after(
                    0,
                    lambda: messagebox.showwarning(
                        "Calibration Failed", str(res.get("error")), parent=self.root
                    ),
                )

        threading.Thread(target=_worker, daemon=True).start()

    def _test_voice(self) -> None:
        self._save_settings()
        queued = self.assistant.tts.speak(
            "Hello! ORION text to speech is working properly.", force=True
        )
        if not queued:
            messagebox.showwarning("TTS Unavailable", "pyttsx3 voice engine is not available.", parent=self.root)

    def _on_catalog_double_click(self, _event: Any) -> None:
        sel = self.cmd_tree.selection()
        if not sel:
            return
        example = self.cmd_tree.item(sel[0], "values")[2]
        if example:
            self.notebook.select(self.tab_console)
            self._run_command_async(example, InputMode.QUICK_ACTION.value)

    # ------------------------------------------------------------------ #
    # Lifecycle
    # ------------------------------------------------------------------ #
    def run(self) -> None:
        self.root.mainloop()

    def _on_close(self) -> None:
        self.assistant.unsubscribe(self._enqueue_event)
        if self.api_server is not None:
            self.api_server.stop()
        self.assistant.shutdown()
        self.root.destroy()
