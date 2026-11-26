"""ORION — Python-Based Voice-Controlled Desktop Virtual Assistant.

Entry point supporting three launch modes:
  1. Default (`python main.py`): Launches the Native Tkinter Desktop GUI
     alongside the Companion Web Control Center API (http://127.0.0.1:8765).
  2. Web-Only (`python main.py --web-only`): Runs only the FastAPI + WebSocket
     backend and responsive Web Dashboard.
  3. Interactive CLI (`python main.py --cli`): Terminal mode with voice/text support.
"""

from __future__ import annotations

import argparse
import sys
import webbrowser

import uvicorn

from orion.api.server import OrionAPIServer, create_app
from orion.config import OrionConfig
from orion.core.assistant import OrionAssistant
from orion.core.models import InputMode


def run_cli(assistant: OrionAssistant) -> None:
    print("============================================================")
    print("  ORION — Voice-Controlled Desktop Virtual Assistant (CLI)")
    print("  Type any command, ':voice' to speak, or 'exit' to quit.")
    print("============================================================")
    try:
        while True:
            try:
                user_input = input("\nYou > ").strip()
            except (EOFError, KeyboardInterrupt):
                break
            if not user_input:
                continue
            if user_input.lower() in {"exit", "quit", ":quit"}:
                break
            if user_input.lower() in {":voice", ":v"}:
                result = assistant.listen_and_execute()
            else:
                result = assistant.process_command(user_input, InputMode.TEXT.value)

            print(f"ORION [{result.intent} | {result.status}]: {result.response_text}")

            if result.requires_confirmation and result.confirmation_request:
                req = result.confirmation_request
                ans = input(f"Approve '{req.action_description}'? (y/N): ").strip().lower()
                final = assistant.confirm_action(req.token, approved=(ans in {"y", "yes"}))
                print(f"ORION [{final.status}]: {final.response_text}")
    finally:
        assistant.shutdown()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="ORION — Python-Based Voice-Controlled Desktop Virtual Assistant"
    )
    parser.add_argument(
        "--web-only",
        action="store_true",
        help="Run only the FastAPI backend & Web Dashboard without Tkinter GUI.",
    )
    parser.add_argument(
        "--no-web",
        action="store_true",
        help="Run only the Tkinter Desktop GUI without starting the local companion API server.",
    )
    parser.add_argument(
        "--cli",
        action="store_true",
        help="Run in interactive terminal (CLI) mode.",
    )
    parser.add_argument(
        "--open-browser",
        action="store_true",
        help="Automatically open the Companion Web Dashboard in your browser (with --web-only).",
    )
    parser.add_argument("--host", default=None, help="Override API host (default from .env).")
    parser.add_argument("--port", type=int, default=None, help="Override API port (default from .env).")
    args = parser.parse_args(argv)

    config = OrionConfig.load()
    host = args.host or config.api_host
    port = args.port or config.api_port
    assistant = OrionAssistant(config=config)

    if args.cli:
        run_cli(assistant)
        return 0

    if args.web_only:
        app = create_app(assistant)
        url = f"http://{host}:{port}"
        print(f"ORION Companion Web Control Center running at {url}")
        if args.open_browser:
            webbrowser.open(url)
        try:
            uvicorn.run(app, host=host, port=port, log_level="info")
        finally:
            assistant.shutdown()
        return 0

    # Default: Native Tkinter Desktop GUI (+ optional Companion API Server)
    api_server: OrionAPIServer | None = None
    if config.auto_start_api and not args.no_web:
        api_server = OrionAPIServer(assistant, host=host, port=port)
        api_server.start()

    from orion.gui.app import OrionDesktopApp

    desktop_app = OrionDesktopApp(assistant=assistant, api_server=api_server)
    desktop_app.run()
    return 0


if __name__ == "__main__":
    sys.exit(main())
