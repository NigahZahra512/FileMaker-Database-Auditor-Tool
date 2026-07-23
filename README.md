# FileMaker Database Auditor Tool

A tool that audits a FileMaker database for common design problems, using
both static rules and AI-powered review.

- **DDR Analysis** — parses a FileMaker Design Data Report (DDR) export and
  runs 18 static checks (missing validation, infinite loops, slow
  calculations, unindexed relationships, and more).
- **Script Review** — pastes a script and gets an AI review for logic
  issues that static rules can't catch.
- **SQL Review** — pastes a SQL statement and gets both a list of issues
  (injection risk, missing WHERE clause, etc.) **and** a corrected,
  rewritten version of the query.

---

## 1. How to export a DDR from FileMaker

The DDR (Design Data Report) is an XML export of your entire database
schema — tables, fields, relationships, layouts, and scripts. This is
the file the DDR Analysis tab needs.

1. Open your database in **FileMaker Pro**.
2. Go to **Tools > Database Design Report...**, select all options, and
   save — **or** use **File > Save/Send Records As > XML** with the DDR
   stylesheet, or **Tools > Save a Copy As > Compacted copy** for a
   smaller file.
3. FileMaker will generate the report. This can take a few minutes for a
   large database.

That `.xml` file is what you upload in the DDR Analysis tab.

---

## 2. Running the tool with Docker (recommended)

This is the "no manual setup" way to run everything.

### Requirements
- [Docker Desktop](https://www.docker.com/products/docker-desktop/) installed and running

### Steps
1. Copy `.env.example` to `.env`:
   ```
   cp .env.example .env
   ```
   (on Windows PowerShell: `copy .env.example .env`)

   This step is **optional** -- `docker compose up` will run fine even
   without a `.env` file. If you skip it, just paste your API key into
   the app's Settings panel in the browser once it's running instead.

2. Open `.env` and fill in your API key. You only need **one** provider:
   ```
   AI_PROVIDER=gemini
   GEMINI_API_KEY=your_actual_key_here
   ```

3. From the project root folder, run:
   ```
   docker compose up
   ```

4. Open your browser to:
   ```
   http://localhost:8000
   ```

That's it — no `pip install`, no manually running Python scripts. Docker
builds the image and starts the server automatically.

To stop it, press `Ctrl+C`, or run `docker compose down` from another
terminal.

---

## 3. Running without Docker (for development/testing)

If you want to run it directly with Python instead:

```
pip install -r requirements.txt
cd backend
python main.py
```

Then open `http://127.0.0.1:8000` in your browser.

---

## 3.5 Building a standalone .exe (to send someone without Python/Docker)

If you want to send this to someone who doesn't have Python or Docker
installed, you can package it into a single Windows `.exe` with
PyInstaller. **This must be built ON Windows** (PyInstaller can't
cross-build a Windows exe from Linux/Mac).

1. Make sure `python` and `pip` work in your terminal (Python 3.11+).
2. From the project root, run:
   ```
   build_exe.bat
   ```
3. Wait for it to finish (a couple of minutes the first time). Your
   file is at `dist\FileMakerAuditor.exe`.
4. Send that single `.exe` file to whoever needs it. Double-clicking it:
   - Opens a console window (keep it open -- that's the server running)
   - Automatically opens the app in their default browser
   - They can paste an API key into the Settings panel in-browser --
     no `.env` file needed at all

To close the app, just close the console window.

**Note:** the brief's actual Day 5 deliverable is the Docker Compose
setup (section 2 above) -- that's what's graded against the "Full
stack runs with `docker compose up` and no manual setup steps" success
criterion. The `.exe` is a convenience extra for sending to someone
without Docker, not a replacement for it.

---



## 4. Using the tool

**Signing in**: a master account is created automatically the first
time the tool ever runs (email `sohaibkhan2030@gmail.com`, password
`qwerty123` — change this from the **Password** button in the header
after your first sign-in). Only the master account can add or remove
sub-accounts, from the **Users** button in the header (sub-accounts
don't see that button at all). Any signed-in account — master or
sub — can sign in, use the whole tool, and change its own password.

**DDR Analysis**: upload a DDR `.xml` file (see section 1) and click
**Run Analysis**. You get a colour-coded findings table (red =
Critical, amber = Warning, green = Info). Tick "Save as snapshot for
client" first to also store this analysis under a client name — that
unlocks every feature below, which all work from saved snapshots
rather than a fresh upload each time.

**Snapshot History**: pick a client to see every DDR they've had
analysed, reload any past one, or tick exactly two and hit **Compare
Selected** to see what changed between them (fields/scripts/layouts/
relationships added, removed, or modified).

**Dashboard**: every client as a card — total snapshots, the latest
upload's Critical/Warning/Info counts, and whether Critical findings
are trending up or down since the previous upload. Rename or delete a
client from here too.

**Timeline**: a client's saved snapshots as a chronological release
history, each one showing its C/W/I delta from the release before it.

**Table Audit**: pick a saved snapshot, then click into any table to
see every field (type, calculation, storage, validation, unused
flag), what it's related to, which layouts use it, and which scripts
touch it.

**Script Audit**: a searchable inventory of every script in a saved
snapshot — step counts, Calls/Called-by relationships, and risk flags
(missing error handling, loops without an exit, call cycles,
destructive steps, long uncommented scripts).

**ExecuteSQL Audit**: every Execute SQL step found inside a saved
snapshot's scripts, with static checks (SELECT *, missing WHERE,
concatenated SQL, write queries without WHERE) — no query is ever
actually run.

**Quick Script Check** / **Quick SQL Check**: the original paste-based
flows, for reviewing a script or SQL statement on its own without a
DDR file — paste, click **Review**, get AI findings (and, for SQL, a
suggested rewrite too).

**Download Report** / **Download DOCX**: available on every results
screen — a standalone `.html` file (no external dependencies, opens in
any browser) or a Word document, both built from whatever's currently
on screen.

---


## Project structure

```
.
├── backend/
│   ├── main.py                 # FastAPI app -- all endpoints + serves the frontend
│   ├── ddr_parser.py            # Parses the DDR XML into tables/scripts/relationships/layouts
│   ├── detection_rules.py       # 18 static rules (missing validation, infinite loops, etc.)
│   ├── ai_client.py              # Safe AI wrapper (Claude/Gemini/Grok/Groq/Custom)
│   ├── script_reviewer.py        # AI review of a pasted script (Quick Script Check)
│   ├── sql_reviewer.py           # AI review + rewrite of a pasted SQL statement (Quick SQL Check)
│   ├── unused_analysis.py        # Unused Fields / Unused Scripts detection
│   ├── call_chain.py             # Script Calls / Called-by relationships, cycle detection
│   ├── docx_report.py            # Word (.docx) export of any report
│   ├── database.py               # SQLite persistence: clients, snapshots, dashboard, timeline, users/sessions
│   ├── compare_snapshots.py      # Diffs two saved snapshots (added/removed/changed)
│   ├── table_audit.py            # Deep per-table breakdown from a saved snapshot
│   ├── script_audit.py           # Script inventory + risk flags from a saved snapshot
│   ├── sql_audit.py              # ExecuteSQL step discovery + static checks from a saved snapshot
│   ├── combine_reports.py        # CLI helper: merges standalone JSON outputs
│   ├── explore_ddr_structure.py  # CLI helper: inspect a DDR file's raw XML structure
│   └── auditor.db                # SQLite database file (created automatically on first run)
├── frontend/
│   └── index.html               # Full web UI -- sidebar nav, all tabs (vanilla HTML/CSS/JS)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
├── CHANGELOG.md                 # Full history of every feature/session, in order
└── README.md
```

See `CHANGELOG.md` for what each file does in more depth and the order
features were added in.

## Notes

- Both `script_reviewer.py` and `sql_reviewer.py` are built so that a
  failed or malformed AI response never crashes the app — you'll always
  get a valid JSON response back, even if the AI call itself fails.
- Only one AI provider key is required at a time, controlled by
  `AI_PROVIDER` in `.env` (`gemini`, `claude`, or `grok`).
