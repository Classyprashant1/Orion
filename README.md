# ORION — Python-Based Voice-Controlled Desktop Virtual Assistant

**ORION** is a modular, production-ready Python desktop virtual assistant built according to the **ORION Project Synopsis** (*Lingaya's Vidyapeeth — B.Tech Fifth Semester Minor Project, 2026–2027*, by **Prasant Sharma (24CS45)**, **Nitesh Bhati (24CS50)**, and **Hariom Dwivedi (24CS30)** under the guidance of **Mr. Saurabh**).

ORION captures voice commands through a microphone (or typed commands via text entry), converts speech to text, matches commands using a deterministic rule-based engine with safety controls, executes desktop and web automation tasks, persists history and shortcuts in SQLite, and responds both visually and via offline Text-to-Speech.

---

## Key Features & Synopsis Alignment

| Synopsis Module | Implementation File | Capabilities |
|---|---|---|
| **Voice Input Module** | `orion/modules/voice_input.py` | PyAudio microphone enumeration, ambient noise calibration, non-blocking speech capture, graceful hardware fallback |
| **Speech Recognition Module** | `orion/modules/speech_recognition_engine.py` | Online Google Speech Recognition (`SpeechRecognition`) with configurable language (`en-IN`, `en-US`, `en-GB`) + optional offline PocketSphinx hook |
| **Command Processing Module** | `orion/modules/command_processor.py` | Rule-based intent & entity parser, wake-word stripping, dynamic SQLite custom app/website resolution, and **3-tier safety guard** (`SAFE`, `CONFIRM_REQUIRED`, `BLOCKED`) |
| **Desktop Automation Module** | `orion/modules/desktop_automation.py` | Launch desktop apps (`subprocess`/`os`), open websites & run Google/YouTube searches (`webbrowser`), report date/time/system diagnostics (`psutil`), capture PNG screenshots (`PyAutoGUI`/`Pillow`), media/volume/window automation, safe AST calculator |
| **Text-to-Speech Module** | `orion/modules/tts_engine.py` | Dedicated thread-safe `pyttsx3` (Windows SAPI5) worker queue with voice selection, rate/volume controls, and instant interrupt |
| **Graphical User Interface** | `orion/gui/app.py` | Native 5-tab **Tkinter** dark-themed desktop UI with animated status orb, transcript feed, confirmation modal, custom app/website CRUD, history log, screenshot previewer, notes, and audio settings |
| **Companion Web & API Layer** | `orion/api/server.py` + `orion/web/` | Local **FastAPI** REST + **WebSocket** server and responsive Web Control Center synchronized in real time with the desktop assistant |
| **Persistence Layer** | `orion/db/database.py` + `schema.sql` | Zero-config SQLite database (`data/orion.db`) storing command history, built-in & custom apps, website bookmarks, screenshot metadata, notes, and preferences |
| **Future Scope Hooks** | `orion/modules/info_services.py`, `orion/modules/ai_provider.py` | Live Wikipedia summaries, Weather lookup (OpenWeatherMap API or `wttr.in` fallback), continuous wake-word mode (`"Orion"`), and optional Gemini/OpenAI LLM Q&A via `.env` |

---

## Project Structure

```text
Orion Proj/
├── main.py                              # Application entry point (Tkinter GUI, --web-only, --cli)
├── pyproject.toml                       # Project configuration & uv dependencies
├── requirements.txt                     # Portable pip requirements
├── .env.example                         # Optional environment & API key configuration
├── orion/
│   ├── config.py                        # Environment loader & directory paths
│   ├── core/
│   │   ├── models.py                    # Enums & dataclasses (AssistantState, SafetyLevel, CommandResult)
│   │   └── assistant.py                 # 5-step pipeline orchestrator, confirmation engine & wake-word loop
│   ├── db/
│   │   ├── schema.sql                   # SQLite relational schema
│   │   └── database.py                  # Thread-safe repository & built-in seed data
│   ├── modules/
│   │   ├── voice_input.py               # PyAudio mic listing, calibration & audio capture
│   │   ├── speech_recognition_engine.py # Speech-to-text processing
│   │   ├── command_processor.py         # Rule-based intent matcher & safety policy
│   │   ├── desktop_automation.py        # Apps, browser, search, screenshots, media & system controls
│   │   ├── tts_engine.py                # Thread-safe pyttsx3 speech queue
│   │   ├── info_services.py             # Wikipedia & Weather integrations
│   │   └── ai_provider.py               # Optional Gemini / OpenAI LLM integration
│   ├── api/
│   │   └── server.py                    # FastAPI REST & WebSocket backend
│   ├── web/                             # Responsive Companion Web Control Center (HTML/CSS/JS)
│   └── gui/
│       └── app.py                       # Native Tkinter Desktop GUI
└── tests/                               # Automated unit & integration tests (pytest)
```

---

## Prerequisites

- **Operating System**: Windows 10 / 11 (primary target per synopsis; core engine runs cross-platform)
- **Python**: Python 3.11 or 3.12 (recommended for prebuilt Windows `PyAudio` wheels)
- **Hardware**: Microphone for voice commands, speakers/headphones for TTS feedback, and internet connection for online speech recognition & web queries

---

## Installation & Setup

### Option A: Using `uv` (Recommended — fastest & reproducible)

```powershell
# 1. Sync virtual environment and install all dependencies (uses Python 3.12)
uv sync --python 3.12

# 2. (Optional) Copy environment template if you want Weather/AI API keys
Copy-Item .env.example .env
```

### Option B: Using standard `venv` + `pip`

```powershell
# 1. Create and activate a virtual environment
py -3.12 -m venv .venv
.\.venv\Scripts\Activate.ps1

# 2. Install dependencies
pip install -r requirements.txt

# 3. (Optional) Copy environment template
Copy-Item .env.example .env
```

---

## Running ORION

### 1. Native Desktop GUI + Companion Web Dashboard (Default)
Launches the native **Tkinter Desktop GUI** and starts the local Companion Web Control Center at `http://127.0.0.1:8765`:

```powershell
.\.venv\Scripts\python.exe main.py
```

### 2. Native Desktop GUI Only (No local HTTP server)

```powershell
.\.venv\Scripts\python.exe main.py --no-web
```

### 3. Companion Web Control Center Only (Browser UI + REST/WebSocket API)

```powershell
.\.venv\Scripts\python.exe main.py --web-only --open-browser
```

### 4. Interactive Terminal (CLI) Mode

```powershell
.\.venv\Scripts\python.exe main.py --cli
```
*(In CLI mode, type any command directly or type `:voice` to capture from your microphone.)*

---

## Supported Voice & Text Commands

| Category | Example Voice / Text Commands | Safety Tier |
|---|---|---|
| **Date & Time** | `"What time is it?"`, `"What is today's date?"` | Safe |
| **Desktop Applications** | `"Open Notepad"`, `"Open Calculator"`, `"Launch Paint"`, `"Open VS Code"`, `"Open Chrome"`, `"Open File Explorer"`, `"Open <custom alias>"` | Safe (`cmd`/`powershell` require confirmation) |
| **Websites & Bookmarks** | `"Open YouTube"`, `"Open GitHub"`, `"Open Google"`, `"Go to python.org"`, `"Open <custom bookmark>"` | Safe |
| **Web Search** | `"Search Google for Python tutorials"`, `"Search YouTube for lo-fi beats"` | Safe |
| **Information** | `"Wikipedia Alan Turing"`, `"Who is Nikola Tesla?"`, `"What is the weather in Delhi?"` | Safe |
| **Screenshots** | `"Take a screenshot"`, `"Open screenshots folder"` | Safe |
| **Volume & Media** | `"Volume up"`, `"Volume down"`, `"Mute volume"`, `"Play pause"`, `"Next track"`, `"Show desktop"` | Safe |
| **Notes & Utilities** | `"Take a note submit project report"`, `"Read my notes"`, `"Calculate 245 * 18"`, `"System status"` | Safe |
| **Guarded System Actions** | `"Lock my screen"`, `"Shutdown computer"`, `"Restart PC"`, `"Clear command history"` | **Requires Confirmation** |
| **Restricted / Destructive** | `"Delete all files on C: drive"`, `"rm -rf"` | **Blocked** |
| **Optional AI Q&A** | `"Ask AI explain binary search"` *(requires `.env` AI key)* | Safe |

---

## Optional External API Configuration (`.env`)

All core synopsis features work out of the box with **zero API keys**. To enable optional extensions, copy `.env.example` to `.env` and configure:

| Variable | Purpose | Required? |
|---|---|---|
| `ORION_API_HOST` / `ORION_API_PORT` | Host/port for Companion Web UI & REST API (default `127.0.0.1:8765`) | Optional |
| `OPENWEATHER_API_KEY` | Live weather via OpenWeatherMap (falls back to `wttr.in` if omitted) | Optional |
| `ORION_AI_PROVIDER` | Set to `gemini` or `openai` to enable AI Q&A (default `none`) | Optional |
| `GEMINI_API_KEY` / `OPENAI_API_KEY` | API key for the selected AI provider | Optional |

---

## REST & WebSocket API Reference

When running in Default or `--web-only` mode, interactive OpenAPI docs are available at `http://127.0.0.1:8765/docs`:

- `GET /api/health` — Service health check
- `GET /api/status` — Live state, hardware availability, pending confirmations & usage stats
- `POST /api/commands/execute` — Execute a text/API command through the 5-step pipeline
- `POST /api/commands/listen` — Trigger microphone capture + speech recognition + execution
- `POST /api/commands/confirm` — Approve or cancel a pending safety confirmation token
- `GET /api/commands/supported` — List all supported commands and example phrases
- `GET/DELETE /api/history` — Query, search, filter, or clear command history
- `GET/POST/DELETE /api/apps` — Manage built-in & custom desktop application aliases
- `GET/POST/DELETE /api/websites` — Manage built-in & custom website bookmarks
- `GET/POST/DELETE /api/screenshots` — Capture, preview, open, and manage screenshots
- `GET/POST/PATCH/DELETE /api/notes` — Manage voice/text notes
- `GET/PUT /api/settings` — Read/update audio, speech, and safety settings
- `GET /api/devices/microphones`, `POST /api/devices/calibrate`, `GET /api/devices/voices`, `POST /api/tts/test`
- `WS /ws/events` — Real-time event stream (`state_changed`, `transcript`, `command_result`, `confirmation_required`)

---

## Running Automated Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -v
```
