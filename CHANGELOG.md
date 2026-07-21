# FileMaker Database Auditor Tool — Project Changelog

Ye file poore project ki changes ka record hai — jab bhi koi naya feature
add ho ya kuch modify ho, is file mein naya section neeche add hota
rahega (sabse purana upar, sabse naya sab se neeche).

---

## Phase 0 — Original build (Day 1–5)

Base tool ban ke ready hua: FastAPI backend + plain HTML/CSS/JS frontend
(no React, no build step), teen tabs ke sath.

- **`backend/ddr_parser.py`** — streaming XML parser (`iterparse` use
  karta hai, taake 50MB+ DDR files pe bhi memory issue na ho). FileMaker
  ke DDR export ko ek structured dict mein convert karta hai: `tables`
  (fields ke sath), `relationships`, `layouts`, `scripts` (steps ke
  sath).
- **`backend/detection_rules.py`** — 18 static rules (missing
  validation, infinite loops, slow/unstored calculations, unindexed
  relationships, waghera).
- **`backend/script_reviewer.py`** — pasted script ka AI-powered review
  (logic issues jo static rules pakad nahi sakte).
- **`backend/sql_reviewer.py`** — pasted SQL query ka AI review + ek
  corrected/rewritten version wapis deta hai.
- **`backend/ai_client.py`** — AI provider (Claude/Gemini/Grok/Groq/
  custom) select karne aur API key set karne ka runtime layer —
  Settings panel (gear icon) se, `.env` file chuye bina.
- **`backend/main.py`** — teen endpoints: `/analyse-ddr`,
  `/review-script`, `/review-sql`. Har response hamesha valid JSON
  hota hai, kabhi raw 500 error nahi — koi bhi failure ek Info-level
  finding ban jati hai.
- **`frontend/index.html`** — 3-tab UI, findings table, HTML report
  download (client-side, koi server round-trip nahi).
- Packaging: Docker (`Dockerfile`, `docker-compose.yml`) aur Windows
  `.exe` (PyInstaller, `build_exe.bat`) dono se run ho sakta hai.

---

## Session 2026-07-20 — "Group A" features (FM Changelog se inspire)

Ek colleague ne "FM Changelog" naam ka reference/competing tool dikhaya
(multi-tenant SaaS version of the same DDR-auditing idea). Do groups of
features identify hui — **Group A** (no database chahiye, existing
upload → analyze → download flow mein fit ho jate hain) is session mein
add hui; **Group B** (snapshot history, compare, multi-tenant dashboard,
live log monitoring) database ke bina possible nahi thi, isliye deferred
hui — wahi Group B ab roadmap ban gaya (neeche dekho).

- **`backend/unused_analysis.py`** (naya) — `find_unused_fields()` aur
  `find_unused_scripts()`: koi field/script jo calculation, script step,
  relationship, ya layout mein kahin reference nahi ho raha, use flag
  karta hai. **Limitation clearly documented hai**: sirf static analysis
  hai, ek DDR export tak mehdood — button, custom menu, Server schedule,
  external API/ODBC, ya raw ExecuteSQL text mein use ho raha field/script
  is se nazar nahi aata.
- **`backend/call_chain.py`** (naya) — har script ke liye "Calls" aur
  "Called by" list banata hai. Agar koi script call-cycle mein ho (A → B
  → A), to us finding ki severity Info se **Warning** ho jati hai
  (infinite loop guard check karne ki reminder ke sath).
- **`backend/docx_report.py`** (naya) — `python-docx` se koi bhi report
  dict ko Word document mein convert karta hai, same categories mein
  grouped jaisa web UI mein hain.
- **`backend/main.py`** update — `/analyse-ddr` ab
  `run_all_rules() + run_unused_rules() + build_call_chain()` sab
  combine karke ek hi report return karta hai. Naya endpoint:
  `POST /export-docx`.
- **`frontend/index.html`** update:
  - "Unused Fields", "Unused Scripts", "Call Chain" category order mein
    add hui.
  - "Download DOCX" button add hua (har results tab pe).
  - **Bug fix**: category-grouping `f.module || f.category` check kar
    rahi thi, aur har DDR finding ka `module` hamesha `"ddr"` hota hai —
    isliye sab findings ek hi unlabeled group mein collapse ho rahi
    thin. Fix: `f.category || f.module`.
  - **UI change**: DDR results ab clickable category-boxes ka grid hain
    (naam + count), collapsed by default. Box click karne se uski
    findings table neeche expand hoti hai; doosra box click karne se
    pehla band ho jata hai (accordion-style) — taake 7-category,
    100+ finding wali report ek lambi scrolling page na bane.
- **`requirements.txt`** — `python-docx==1.1.2` add hui.

---

## Session 2026-07-21 — Roadmap decide hua + Step 1 & Step 3

Ek 8-step roadmap decide hua (FM Changelog se hi inspire, lekin apne
architecture mein):

1. **Database Foundation** (SQLite) — ✅ done (ye session)
2. **Snapshot History** (view/list) — ✅ done (ye session)
3. **Compare Snapshots** — ✅ done (ye session)
4. **Multi-Client Dashboard** — ✅ done (2026-07-21 session, cont'd)
5. Users / Login — abhi baaki
6. Deep Per-Table Audit — abhi baaki
7. Timeline / Releases — abhi baaki
8. Live Log Monitoring — abhi baaki (sab se mushkil, isliye sab se aakhir)

### Step 1 — Database Foundation

- **`backend/database.py`** (naya) — SQLite + SQLAlchemy. Do tables:
  - `clients` — id, unique naam, created_at
  - `snapshots` — id, client_id (FK), filename, created_at, poora
    `parsed_data` + `report` JSON columns mein store, plus
    critical/warning/info counts (fast listing ke liye denormalized)
  - `.db` file (`auditor.db`) `backend/` folder mein banti hai (frozen
    `.exe` ke case mein `.exe` ke sath, taake persist rahe — temp
    PyInstaller unpack folder mein nahi).
- **`backend/main.py`** update:
  - Startup pe `init_db()` call hota hai (tables khud ban jate hain
    agar exist nahi karte).
  - `/analyse-ddr` ab optional form fields leta hai: `client_name`,
    `save_snapshot`. Agar dono diye jayein, analysis ke sath-sath
    snapshot bhi save ho jata hai — get-or-create client by name, phir
    snapshot row create.
  - Naye endpoints: `GET/POST /api/clients`, `GET /api/snapshots`
    (optional `client_id` filter), `GET /api/snapshots/{id}`.
- **`frontend/index.html`** update:
  - DDR tab mein "Save as snapshot for client" checkbox + client-name
    input (existing clients autocomplete/datalist).
  - Naya "Snapshot History" panel — client filter dropdown, saari
    snapshots ki list (client, filename, date, C/W/I counts), aur
    "View" button jo purani snapshot ka poora report wapis load kar
    deta hai bina re-upload kiye.
- **`requirements.txt`** — `SQLAlchemy==2.0.35` add hui.

### Step 3 — Compare Snapshots

(Step 2 ka "list dikhana" hissa Step 1 ke sath hi frontend mein ban gaya
tha, isliye seedha Step 3 pe gaye.)

- **`backend/compare_snapshots.py`** (naya) — `compare_snapshots(data_a,
  data_b)`: do parsed DDR dicts ko diff karta hai — tables, fields
  (per table), scripts, relationships, layouts sab check hote hain ke
  kya add hua, kya remove hua, kya change hua.
  - **Design choice**: output wahi finding shape use karta hai jo
    `detection_rules.py` / `unused_analysis.py` / `call_chain.py`
    already use kar rahe hain (`module`, `category`, `severity`,
    `location`, `description`, `suggestion`). Is se frontend ka existing
    category-box grid + findings table bina kisi naye UI component ke
    diff bhi render kar leta hai.
  - Severity convention: **Added → Info**, **Removed → Warning**,
    **Changed → Warning** (kyunke removal/change dono behaviour badal
    sakte hain).
- **`backend/main.py`** — naya endpoint `POST /api/compare-snapshots`
  (body: `snapshot_id_a`, `snapshot_id_b`). Dono snapshots database se
  load karta hai, `created_at` ke hisaab se automatically decide karta
  hai kaunsa "purana" aur kaunsa "naya" hai (taake diff hamesha
  old → new direction mein padhi jaye, chahe user ne ids kisi bhi order
  mein bheji hon). Same-id ya not-found cases ke liye proper 400/404.
- **`frontend/index.html`** update:
  - Snapshot History list mein har row ke sath ek checkbox add hua.
  - "Compare Selected" button — exactly do snapshots select karne pe
    active hota hai, backend se diff mangwata hai, aur usay wahi
    `renderDDRReport()` function se render karta hai jo normal analysis
    dikhata hai (koi naya rendering code likhna nahi para).

**Testing (dono steps, is session mein)**: real FastAPI server chalaya,
do alag DDR files upload ki (same client, jaan-boojh kar ek field aur
ek script change karke), snapshots correctly save huin, `/api/clients`
duplicate name pe nayi row nahi banata (get-or-create verified),
`/api/snapshots/{id}` se poori purani report reload hoti hai,
`/api/compare-snapshots` ne sahi tarah field-removed, field-added,
script-removed, script-added detect kiya, aur same-id (400) /
not-found (404) error cases bhi sahi kaam kar rahe hain.

---

## Session 2026-07-21 (cont'd) — Step 4: Multi-Client Dashboard

Roadmap ka agla step: ek dedicated 4th tab jo saare clients ko ek
glance mein dikhata hai, bina kisi client ko manually select kiye
snapshot list scroll karne ki zaroorat ke.

- **`backend/database.py`** update — naye helpers:
  - `dashboard_summary()` — har client ke liye: `snapshot_count`,
    `latest_snapshot` (filename/date/C-W-I), aur `critical_trend`
    (`"up"` / `"down"` / `"flat"` / `null`) — latest snapshot ka
    Critical count us se pehli snapshot se compare karke, taake dashboard
    khud bata de ke client ki situation better ho rahi hai ya worse,
    bina Compare Snapshots tab khole.
  - `rename_client()` — duplicate-name clash 400 error ke sath guard
    kiya hua.
  - `delete_client()` — ORM-level delete taake `cascade="all,
    delete-orphan"` (Step 1 se already defined) us client ki saari
    snapshots bhi khud delete kar de.
  - `delete_snapshot()` — single snapshot delete, client aur baaki
    snapshots untouched.
- **`backend/main.py`** update — naye endpoints: `GET /api/dashboard`,
  `PUT /api/clients/{id}` (rename), `DELETE /api/clients/{id}`,
  `DELETE /api/snapshots/{id}`.
- **`frontend/index.html`** update:
  - Naya 4th tab: **Dashboard**. Client cards ka grid — naam, total
    snapshot count, latest upload ka C/W/I, aur trend badge (▲ Critical
    up / ▼ Critical down / — No change).
  - Har card pe rename (✎) aur delete (🗑) icon-buttons, dono confirm/
    prompt ke sath.
  - "View history" click karne se card ke neeche us client ki poori
    snapshot list expand hoti hai (view + per-snapshot delete ✕ ke
    sath); "View" click karne se DDR tab pe switch ho ke wahi purana
    `loadSnapshotDetail()` reuse hota hai — koi naya render/download
    code path nahi likhna para.
  - Client rename/delete ke baad DDR tab ka client dropdown/datalist +
    snapshot list bhi khud refresh ho jate hain, taake dono jagah data
    sync rahe.

**Testing (is session mein)**: FastAPI `TestClient` se rename (success
+ duplicate-name 400 clash), delete-client (cascade snapshots ke sath),
delete-missing-snapshot (404), aur dashboard empty/non-empty states
verify kiye.

---

## Session 2026-07-21 (cont'd, 2) — Professional UI pass + roadmap reorder

Feedback after seeing the Dashboard tab live: it read as everything
squeezed onto one page, one leftover Hinglish line was visible inside
the tool itself (should only ever appear in code comments, never in
what the user actually sees), and Snapshot History was buried inside
the DDR tab instead of being its own place.

- **Left sidebar navigation** replaces the old horizontal tab strip.
  Same `.tab-btn` / `.tab-panel` mechanism as before (so none of the
  existing JS logic had to change) — just re-skinned into a vertical,
  icon-labelled nav column (`.sidebar` / `.app-layout` / `.main-content`
  CSS), which reads as a proper application shell instead of a stacked
  single page.
- **Snapshot History is now its own page** (`tab-snapshots`), separate
  from DDR Analysis. DDR Analysis tab is now upload + results only.
  `loadSnapshotDetail()` now switches to the DDR Analysis tab itself
  before rendering a reloaded snapshot, so "View" works correctly
  whether it's clicked from Snapshot History or from a Dashboard card.
- **All user-facing text is English-only.** Hinglish stays exactly
  where it always was — code comments for whoever reads this codebase
  next — but nothing in Hinglish is shown inside the tool's UI itself.

### Roadmap reorder (decided this session)

Original order was Users/Login (5) before Deep Per-Table Audit (6) and
Timeline/Releases (7). Reordered: **6 and 7 now come before 5** — both
extend analysis/snapshot features that already exist, whereas
Users/Login is closer to infrastructure and easier to bolt on once the
feature set it needs to protect is more complete.

1. Database Foundation — ✅ done
2. Snapshot History (view/list) — ✅ done
3. Compare Snapshots — ✅ done
4. Multi-Client Dashboard — ✅ done
5. **Deep Per-Table Audit** — abhi baaki (moved up, was Step 6)
6. **Timeline / Releases** — ✅ done (2026-07-21 session, cont'd)
7. Users / Login — abhi baaki (moved down, was Step 5)
8. Live Log Monitoring — abhi baaki (hardest, still last)

---

## Session 2026-07-21 (cont'd, 3) — Step 5: Deep Per-Table Audit

- **`backend/table_audit.py`** (naya) — `build_table_summary(data)`
  (lightweight per-table counts for the picker list: record count,
  field count, unstored-calc count, always-evaluate count, unused-field
  count, validated-field count) and `build_table_detail(data,
  table_name)` (full breakdown for one table: every field with its
  type/calc/storage/validation/unused flags, every relationship
  touching the table, every layout that places one of its fields, and
  every script step that references one of its fields).
  - Reuses `unused_analysis._collect_field_references()` instead of
    re-scanning calc text / step text / relationships / layouts a
    second time, so "unused" always means the same thing across the
    whole tool.
  - **Same design constraint as Compare Snapshots**: works off a saved
    snapshot's `parsed_data`, not a fresh unsaved upload — the full
    parsed DDR dict only exists for the length of one `/analyse-ddr`
    request otherwise.
- **`backend/main.py`** — two new endpoints:
  `GET /api/snapshots/{id}/table-audit` (the picker list) and
  `GET /api/snapshots/{id}/table-audit/{table_name}` (one table's full
  detail, 404 if the table name doesn't exist in that snapshot).
- **`frontend/index.html`** — new sidebar page, **Table Audit**:
  - Client + snapshot pickers (same pattern as Snapshot History) select
    which saved snapshot to audit.
  - Table cards grid — name, record/field counts, and flag badges
    (unstored calc / always-eval / unused / validated) so the tables
    that need attention stand out before you even click in.
  - Clicking a card expands a full detail panel below: a fields table
    (name/type/kind/flags), Related Tables, Layouts Using This Table,
    and Scripts Touching This Table — each pulled straight from
    `table_audit.py`'s output, no extra client-side computation.

**Testing (is session mein)**: FastAPI `TestClient` ke sath ek synthetic
parsed-DDR snapshot bana ke dono naye endpoints check kiye — summary
list ke counts sahi (unstored/always-eval/unused/validated), full
detail mein fields/relationships/layouts/scripts sab sahi shape mein,
aur missing-table case 404 sahi deta hai.

---

## Abhi baaki (roadmap ke agle steps, reordered — see note above)

- **Users / Login**: basic authentication.
- **Live Log Monitoring**: FileMaker Server logs live tail karna
  (background service/websocket chahiye — sab se mushkil, isliye sab
  se aakhir mein).
- Settings panel improvements (AI provider + key) — pehle se hai,
  koi naya kaam mentioned nahi.

---

## Session 2026-07-21 (cont'd, 4) — Step 6: Timeline / Releases

- **`backend/database.py`** update — naya `timeline_summary()` helper.
  Har client ke saved snapshots ko chronological release events mein
  return karta hai. Har event ke sath Critical / Warning / Info summary
  aur us client ke immediately previous saved release se C/W/I delta bhi
  aata hai. Existing snapshots table hi use hoti hai, isliye koi database
  migration nahi chahiye.
- **`backend/main.py`** — naya `GET /api/timeline` endpoint, optional
  `client_id` filter ke sath.
- **`frontend/index.html`** update — sidebar mein naya **Timeline** page:
  - all-clients ya individual-client filter
  - client-wise chronological release stream
  - har release par filename, timestamp, C/W/I counts, aur prior release
    se deltas
  - Critical aur Warning kam hone par green, barhne par red indication;
    Info deltas neutral rehte hain
  - har release se existing snapshot viewer khulta hai
  - snapshot/client delete ya rename, aur naya snapshot save hone ke baad
    timeline refresh ho jati hai

**Testing (is session mein)**: `python -m compileall -q backend`, direct
`timeline_summary()` shape check current SQLite data ke against, aur
FastAPI `TestClient` se `/api/timeline` plus `client_id` filter verify
kiye gaye.

---

## Session 2026-07-21 (cont'd, 5) — Script Audit from saved DDR snapshots

- **`backend/script_audit.py`** (naya) — saved DDR ke parsed script data se
  searchable script inventory aur per-script detail banata hai. Har script
  ke steps, Calls / Called by relationships, aur static risk flags milte hain.
  Checks: missing error handling around failure-prone steps, loops without
  explicit exit, direct/indirect call cycles, destructive data steps, aur
  long uncommented scripts.
- **`backend/main.py`** — naye endpoints:
  `GET /api/snapshots/{id}/script-audit` aur
  `GET /api/snapshots/{id}/script-audit/{script_name}`.
- **`frontend/index.html`** — naya sidebar **Script Audit** page, client +
  snapshot picker, search, risk-flagged script table, aur click-to-open
  full parsed step detail. Purana paste-based tab ab **Quick Script Check**
  hai, taake clear ho ke complete professional audit DDR se hota hai.

**Testing:** backend compile, synthetic scripts par risk/cycle checks,
FastAPI endpoint, aur frontend JavaScript syntax verify kiye gaye.

---

## Session 2026-07-21 (cont'd, 6) — Script Audit loop accuracy

- **False-positive fix:** Script Audit aur existing DDR rule dono ab
  `Go to Record/Request/Page [Next; Exit after last]` ko valid FileMaker
  loop exit samajhte hain. Is common record-walking pattern ko ab
  "Loop without explicit exit" warning nahi milegi.
- **Performance insight:** jin scripts mein `Show All Records` paanch ya
  zyada dafa repeat hota ho, Script Audit ab **Repeated record scans**
  Info flag deta hai. Suggestion: har field ke liye records dobara loop
  karne ke bajaye, ek record-walking loop mein poori HTML/report row
  build karein.

**Testing:** safe `Next; Exit after last` loop, unsafe no-exit loop,
repeated-scan detection, aur current saved `Data HTML` snapshot verify
kiya gaya.
