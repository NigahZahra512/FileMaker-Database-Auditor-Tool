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



1. **DDR tab**: upload a DDR `.xml` file (see section 1) and click
   **Run Analysis**. You should see a colour-coded table of findings
   (red = Critical, amber = Warning, green = Info) and a summary count
   at the top.

2. **Script tab**: paste a script's steps as text (step name + any
   condition/value) and click **Review**. The AI will return any logic
   issues it finds, or an empty result if the script looks fine.

3. **SQL tab**: paste a raw SQL statement (e.g. copied out of an
   "Execute SQL" script step) and click **Review**. You'll get both:
   - A findings table (injection risk, missing WHERE, etc.)
   - A **suggested rewrite** box showing a corrected version of the query

4. On any tab, click **Download Report** to save a standalone `.html`
   file with the current findings — this file has no external
   dependencies and can be opened directly in a browser or emailed to
   someone else.

---

## 5. Recording a demo

A demo should show all three flows in one short recording:

1. Start the tool (`docker compose up`), open `http://localhost:8000`
2. **DDR tab** — upload a DDR file, click Run Analysis, show the
   findings table populate with colour-coded results
3. **Script tab** — paste a sample script, click Review, show the AI
   findings appear
4. **SQL tab** — paste a sample SQL statement (ideally one with an
   obvious issue, e.g. `SELECT * FROM Employees WHERE ID = " & $id & "`),
   click Review, show both the findings **and** the rewritten SQL box
5. Click **Download Report** once to show the standalone HTML file
   being saved

Any free screen recorder works (Windows: Xbox Game Bar with `Win+G`,
or OBS Studio for more control).

---

## Project structure

```
.
├── backend/
│   ├── main.py                 # FastAPI app (3 endpoints + serves the frontend)
│   ├── ddr_parser.py            # Day 1: parses the DDR XML
│   ├── detection_rules.py       # Day 2: 18 static rules
│   ├── ai_client.py              # Day 3: safe AI wrapper (Claude/Gemini)
│   ├── script_reviewer.py        # Day 3: AI script review
│   ├── sql_reviewer.py           # Day 3/5: AI SQL review + rewrite
│   ├── combine_reports.py        # Day 4: merges the 3 JSON outputs (CLI use)
│   └── explore_ddr_structure.py  # Day 1: DDR structure exploration helper
├── frontend/
│   └── index.html               # Day 4: 3-tab web UI (vanilla HTML/CSS/JS)
├── Dockerfile
├── docker-compose.yml
├── requirements.txt
├── .env.example
└── README.md
```

## Notes

- Both `script_reviewer.py` and `sql_reviewer.py` are built so that a
  failed or malformed AI response never crashes the app — you'll always
  get a valid JSON response back, even if the AI call itself fails.
- Only one AI provider key is required at a time, controlled by
  `AI_PROVIDER` in `.env` (`gemini`, `claude`, or `grok`).
