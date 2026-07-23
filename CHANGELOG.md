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
7. **Users / Login** — ✅ done (2026-07-22 session, cont'd 4) — live
   end-to-end server test still pending, see bottom of file
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

---

## Session 2026-07-22 — Full backend review + config fixes + end-to-end test

Poori backend `.py` files (16 files: `main.py`, `database.py`,
`ddr_parser.py`, `detection_rules.py`, `ai_client.py`, `call_chain.py`,
`compare_snapshots.py`, `docx_report.py`, `script_audit.py`,
`sql_audit.py`, `table_audit.py`, `unused_analysis.py`,
`script_reviewer.py`, `sql_reviewer.py`, `combine_reports.py`,
`explore_ddr_structure.py`) padhi aur review ki — pehli baar poora
backend logic verify hua (pehle sirf config/docs files upload hui
thin).

**Review nateeja:** koi backend logic bug nahi mila. `main.py`'s saare
endpoints sahi wired hain; `table_audit.py` `unused_analysis.py`'s
`_collect_field_references()` reuse karta hai (taake "unused" ka
matlab poore tool mein consistent rahe) — ye achi design choice hai.

**2 config bugs jo pehle flag hue thay, dobara mile (kyunke original
files dobara upload hui thin, fixed wali nahi) — dobara fix kiye:**

- `FileMakerAuditor.spec` — `sqlalchemy` add kiya `hiddenimports` mein.
- `build_exe.bat` — `--hidden-import=sqlalchemy` add kiya.
- `docker-compose.yml` — `database.py`'s actual `_db_path()` padh kar
  confirm kiya (non-frozen case: `backend/auditor.db`), phir
  persistent bind mount add kiya: `./data/auditor.db:/app/backend/auditor.db`.

**README.md update:**
- "Project structure" — ab saari 17 backend files list hoti hain
  (pehle sirf purani 8).
- "Using the tool" section poora rewrite kiya — pehle sirf 3 original
  tabs describe karta tha, ab Snapshot History, Dashboard, Timeline,
  Table Audit, Script Audit, ExecuteSQL Audit sab cover karta hai.

**End-to-end testing (real FastAPI server ke sath):**
- `python3 -m py_compile` saari 16 backend files pe — clean.
- Do sample DDR files (ek extra field ke sath) bana kar test kiya:
  `/analyse-ddr` (bina aur sath snapshot save ke), `/api/dashboard`,
  `/api/timeline`, `/api/compare-snapshots` (naya field sahi detect
  hua), `/api/snapshots/{id}/table-audit`,
  `/api/snapshots/{id}/script-audit`, `/api/snapshots/{id}/sql-audit`,
  `/export-docx` (valid Word file), aur frontend serving — sab pass.
- `docker-compose.yml` YAML syntax verify kiya.

**Agli session ke liye:** roadmap ka agla real step -- Users/Login
(Step 7) -- ya Dashboard hierarchy refinement / AI Config test-button
(dono low priority, FM Changelog se) mein se koi ek chunna hai.

---

## Session 2026-07-22 (cont'd) — AI Config: Test Connection button

**Wajah:** Settings panel mein ab tak sirf "Save" tha -- galat key,
galat model name, ya galat custom base URL daalne pe koi turant error
nahi milta tha. `ai_client.py`'s andar `_call_claude()` / `_call_gemini()`
/ waghera saare functions jaan-boojh kar failure sirf server console pe
print karte hain aur `None` return karte hain (taake ek AI call fail
hone se poora audit crash na ho) -- lekin isi wajah se galat config ka
result sirf "kuch nahi dikh raha" / "details show nahi ho rahin" jaisa
lagta hai, bina kisi wajah ke. Test Connection button ye wajah turant
saamne la deta hai, upload/paste karne se pehle hi.

- **`backend/ai_client.py`** update — naya `test_connection(provider,
  api_key, custom_base_url=None, custom_model=None)`:
  - Provider ko ek chhota real API call karta hai (`max_tokens=10`,
    "Say OK") -- Settings form mein abhi jo bhi type kiya hua hai
    wahi key/base-url/model use karta hai, saved runtime key nahi
    (taake Save dabane se pehle hi test ho sake).
  - Exception ko silently print/None nahi karta -- `_friendly_connection_
    error()` se ek readable reason wapis deta hai: galat key (401/
    authentication), galat model name (404), rate-limit/quota (429),
    ya network/base-URL issue (connection/timeout) -- har case alag
    pehchana jata hai.
- **`backend/main.py`** — naya endpoint
  `POST /api/settings/test-connection` (same `SettingsRequest` body jo
  `/api/settings` already use karta hai) -- kuch save nahi karta, sirf
  test karta hai.
- **`frontend/index.html`** — Settings modal mein "Test Connection"
  button (Save ke bagal mein), result ek inline banner mein (green =
  success, red = failure ke sath reason). Modal khulte waqt ya provider
  badalne pe purana result clear ho jata hai.

**Testing (is session mein)**: `py_compile` clean, FastAPI server real
chala kar `POST /api/settings/test-connection` ko live test kiya --
empty key ("Enter an API key first"), invalid Claude key (real call
`api.anthropic.com` ko gaya, 401 wapis aaya, friendly message ban gaya),
unknown provider name, custom provider bina base-url/model ke, aur
confirm kiya ke existing `POST /api/settings` (Save) bilkul waisa hi
kaam kar raha hai jaisa pehle karta tha.

---

## Session 2026-07-22 (cont'd, 3) — Client → Solution → Snapshot hierarchy

**Wajah:** Idiosol ke clients ke paas aksar ek se zyada FileMaker
solutions hote hain (e.g. ek client ki "Inventory System" alag aur
"CRM System" alag). Pehle sab snapshots ek hi client ke neeche flat mix
ho rahe thay -- sirf filename se pata chalta tha kaunsi kis solution ki
hai, aur Compare Snapshots galti se 2 alag solutions compare kar sakta
tha (jo bilkul galat/meaningless diff deta). Naya "Solution" layer ye
gap band karta hai. Isi kaam ne "Dashboard hierarchy refinement" ka
scope bhi clear kar diya -- neeche dekhein.

- **`backend/database.py`** update:
  - Naya table `solutions` -- id, `client_id` (FK), naam
    (`UNIQUE(client_id, name)` -- do alag clients ka same-naam solution
    ho sakta hai, ek client ke andar duplicate naam nahi), created_at.
  - `snapshots.solution_id` naya column, **nullable** -- purana koi bhi
    saved snapshot bina migration ke valid rehta hai, bas dashboard/
    filters mein "No solution" bucket mein dikhta hai.
  - Naye helpers: `get_or_create_solution()`, `list_solutions(client_id)`,
    `rename_solution()`, `delete_solution()` (cascade -- solution delete
    hone par uski saari snapshots bhi delete hoti hain, doosri solutions/
    client untouched rehte hain).
  - `create_snapshot()` / `list_snapshots()` ab optional `solution_id`
    accept/filter karte hain.
  - `dashboard_summary()` refine hua -- ab har client ke andar
    `solutions: [...]` list hoti hai, har solution ka apna
    `snapshot_count` / `latest_snapshot` / `critical_trend` (ek doosre se
    independent), plus legacy no-solution snapshots ke liye synthetic
    "No solution" row. Client-level totals bhi wahi rehte hain (sab
    solutions + no-solution combined) taake purana bina-solution client
    bilkul pehle jaisa dikhta rahe.
- **`backend/main.py`** update:
  - Naye endpoints: `GET/POST /api/clients/{client_id}/solutions`,
    `PUT/DELETE /api/solutions/{solution_id}`.
  - `/analyse-ddr` ab optional `solution_name` form field leta hai --
    diya jaye to get-or-create solution (scoped to that client), phir
    snapshot usi solution_id ke sath save hoti hai. Solution na diya
    jaye to bilkul pehle jaisa "client only" save hota hai.
  - `GET /api/snapshots` ab optional `solution_id` filter bhi leta hai.
  - `POST /api/compare-snapshots` mein **naya safety check**: agar dono
    snapshots ki solution alag-alag ho (dono non-null), request 400 ke
    sath clearly bata deta hai ke "ye 2 alag solutions hain, compare
    karna meaningless hoga" -- ab galti se cross-solution diff nahi ban
    sakta. Ek ya dono snapshots "No solution" (legacy) hon to allow hai.
- **`frontend/index.html`** update:
  - DDR upload form -- client name ke sath ek optional "Solution"
    input + datalist (us client ki existing solutions suggest hoti hain
    jaise hi client field se focus hatta hai).
  - Snapshot History tab -- client filter ke bagal mein naya solution
    filter select (client choose karne par uski solutions + "No
    solution" option automatically populate hoti hain).
  - Dashboard cards -- har client card ab apni solutions ki mini-list
    dikhata hai (naam, snapshot count, apna Critical trend badge alag
    se). "View history" click karne par history ab **Client → Solution
    → Snapshots** grouped dikhti hai, har solution group ke apne
    rename/delete (✎/🗑) icons ke sath.
  - **Dashboard hierarchy refinement (jo pehle "scope clear karni hai"
    tha) is se resolve ho gaya**: hierarchy = Client → Solution →
    Snapshot, jo upar implement ho chuki hai.

**Testing (is session mein)**: `database.py` ke naye helpers ek direct
Python script se test kiye (client → 2 solutions → snapshots → filter →
dashboard shape) -- Inventory System ka apna trend ("down") CRM System
se (0 snapshots) aur legacy no-solution snapshot se sahi separate
dikha. Poore backend + extracted frontend `<script>` block ka syntax
check (`py_compile` / `node --check`) clean.

---

## Session 2026-07-22 (cont'd, 4) — Users / Login (Step 7)

**Wajah:** Roadmap ka sabse bara pending item. Ab tak tool bina kisi
login ke koi bhi khol kar use kar sakta tha -- kisi bhi client ke
snapshots, uski analysis, sab kuch bina authentication ke accessible
tha. Ye step ek basic access-gate add karta hai: sirf koi account
rakhne wala hi tool use kar sakta hai.

**Design choices:**
- Deliberately minimal -- **no roles, no email, no password-reset
  flow**. Har account bilkul same cheezein kar sakta hai (add/remove
  teammates included). Ye ek internal-team access gate hai, permissions
  system nahi.
- Session cookie-based rakha (Authorization header nahi) -- taake
  frontend ki existing 25+ `fetch()` calls mein se **ek bhi na badalni
  pare**. Same-origin `fetch()` already cookie automatically bhej deta
  hai.
- Password hashing stdlib-only (`hashlib.pbkdf2_hmac` + per-user random
  salt) -- bcrypt/passlib jaisi nayi dependency `requirements.txt` mein
  add nahi karni pari.
- Sessions database mein store hoti hain (server memory mein nahi,
  ai_client ke runtime config ke unlike) -- taake server/.exe restart
  hone par log out na ho jaye.

- **`backend/database.py`** update:
  - Naye tables: `users` (id, unique username, password_hash,
    created_at), `sessions` (token PK, user_id FK, created_at).
  - Naye helpers: `count_users()`, `create_user()`, `verify_user()`
    (galat username aur galat password dono same generic failure
    return karta hai -- kisi ko pata nahi chalta ke koi username
    exist karta hai ya nahi), `create_session()`,
    `get_user_by_session()`, `delete_session()`, `list_users()`,
    `delete_user()` (**last remaining account delete nahi hone deta**
    -- warna tool permanently unreachable ho jata, kisi login screen
    ke bina wapis andar aane ka koi rasta nahi bachta).
- **`backend/main.py`** update:
  - Naya single `@app.middleware("http")` -- har request pe check
    karta hai (har individual endpoint mein `Depends(...)` add karne
    ke bajaye). Sirf ye paths bina login ke kaam karte hain: `/`
    (frontend shell), `/api/auth/status`, `/api/auth/login`,
    `/api/auth/bootstrap`, `/api/auth/logout`. Baaki **har** endpoint
    (analyse-ddr, review-script, review-sql, export-docx, saare
    `/api/clients`, `/api/solutions`, `/api/snapshots`,
    `/api/compare-snapshots`, `/api/dashboard`, `/api/timeline`,
    `/api/settings*`) ab login maangte hain.
  - Naye endpoints: `GET /api/auth/status` (has_users/logged_in/
    username -- frontend ye pehle call karta hai ye decide karne ke
    liye ke login form dikhana hai ya bootstrap form ya seedha app),
    `POST /api/auth/bootstrap` (**sirf ek dafa kaam karta hai** -- agar
    koi bhi user already exist karta ho to refuse kar deta hai, taake
    self-registration hamesha ke liye open na rahe), `POST
    /api/auth/login`, `POST /api/auth/logout`, `GET/POST
    /api/auth/users`, `DELETE /api/auth/users/{id}`.
- **`frontend/index.html`** update:
  - Naya full-page auth overlay (login form ya, sirf jab database mein
    zero users hon, "create the first account" form) -- page load pe
    hamesha sabse pehle dikhta hai, jab tak `/api/auth/status` confirm
    na kar de ke koi already logged in hai.
  - Header mein naya "Users" button (Manage Users modal -- list +
    add/remove) aur "Log out" button, plus "Signed in as ..." badge.
  - Login/bootstrap successful hone ke baad, existing 7 top-level
    init functions (`loadSettingsStatus`, `loadClients`, waghera, jo
    page load pe already call ho rahi thin) **dobara call** hoti hain
    -- taake pehli baar jo unauthenticated call hui thi (jo 401 leke
    aayi thi) ke baad real data load ho jaye.
  - **Koi bhi existing fetch() call nahi badla** -- cookie-based
    session hone ki wajah se sab automatically kaam kar gaye.

**Testing (is session mein):** `py_compile` dono updated backend files
pe clean, extracted `<script>` block ka `node --check` clean. Password
hashing logic (pbkdf2 + salt) ek standalone script se test kiya --
correct password verify hoti hai, galat password reject hoti hai,
corrupt/malformed stored-hash gracefully `False` return karta hai.
**Note:** is session ke sandbox mein network access nahi tha, isliye
`fastapi`/`sqlalchemy` install karke poora live server end-to-end test
(jaisa pichli sessions mein hota tha) nahi kiya ja saka -- agli session
mein real server ke sath bootstrap → login → add teammate → logout →
re-login → last-user-delete-guard poora flow verify karna baaki hai.

**README.md update:** "Using the tool" mein naya sign-in
paragraph add hua; "Project structure" mein `database.py` ki line
update hui (users/sessions tables mention).

---

## Abhi baaki (roadmap ke agle steps)

- **Live server end-to-end test** (is Users/Login session ka baaki
  hissa): real FastAPI server chala kar poora bootstrap → login → add
  teammate → logout → re-login → last-user-guard flow verify karna.
- **Live Log Monitoring**: FileMaker Server logs live tail karna
  (background service/websocket chahiye — sab se mushkil, isliye sab
  se aakhir mein).
- **Optional follow-up polish (low priority)**: Table Audit / Script
  Audit / ExecuteSQL Audit tabs abhi bhi client-only filter use karte
  hain (solution filter nahi) -- wo teeno tabs seedha ek specific
  snapshot pick karte hain, isliye solution filter "nice to have" hai,
  zaroori nahi. Agar chahiye to add ho sakta hai.

---

## Session 2026-07-22 (cont'd, 5) — Explore page (Group A: unified Tables/Fields/Scripts/Layouts/Relationships) + Global Search

**Wajah:** Ek colleague ke "FM Changelog" reference tool ne ek unified
"Explore" page dikhaya tha — ek hi page pe Tables/Fields/Scripts/
Layouts/Relationships tabs, click karke drill-down detail. Isko is
tool mein add karna tha.

- **`backend/explore.py`** (naya) — koi naya parsing/analysis logic
  nahi likha; jo already tha usay flatten/reuse kiya:
  - `build_fields_list()` — har table ke fields ko ek flat list mein
    (is_unused flag `unused_analysis._collect_field_references()` se).
  - `build_layouts_list()`, `build_relationships_list()` — layout/
    relationship ka poora field/portal/predicate detail inline (taake
    click karne pe dusra server round-trip na lagay).
  - `build_explore_stats()` — summary strip ke counts (`call_chain.
    _build_call_graph()` se script-calls count).
  - `build_explore()` — sab combine karke ek hi response.
- **`backend/main.py`** — naya `GET /api/snapshots/{id}/explore`
  endpoint, jo upar wala combine karta hai. Table aur Script row detail
  **existing** `/table-audit/{name}` aur `/script-audit/{name}`
  endpoints hi reuse karte hain (koi duplicate detail-endpoint nahi
  likha).
- **`frontend/index.html`** — naya "Explore" tab:
  - Client/snapshot picker (Table Audit tab jaisa hi pattern).
  - Stats strip: Tables, Fields, Scripts, Layouts, Relationships,
    Script Calls, Unused Fields, Unused Scripts, Always-Eval, Unstored
    Calcs.
  - 5 sub-tabs (pills, counts ke sath — "Tables (97)" jaisa).
  - **Global search** (top search bar) — Tables/Fields/Scripts/
    Layouts/Relationships **sab ek sath** search karta hai jab query
    non-empty ho (grouped sections, har category max 15 results, "+N
    more — narrow your search" note). Query empty ho to normal
    per-tab browsing wapis aa jati hai.
  - Row click: Table/Script → full existing detail endpoint se detail
    khulta hai; Field/Layout/Relationship → inline expand (data
    already loaded hai, extra fetch nahi lagta).
  - Visual polish pass: full-width search apni alag card mein, stats
    strip flat/borderless row (per-metric box ki jagah sirf thin
    divider lines), reference screenshot se match karne ke liye.

**Bug fixes (isi session mein):**
- Explore ka snapshot dropdown login ke baad reload nahi ho raha tha
  (`reloadAppDataAfterLogin()` mein naya loader add karna bhool gaya
  tha) — fix ho gaya.
- Fields/Layouts/Relationships list ko search se filter karne ke baad
  row click karne pe **galat item** ka detail khul jata tha (filtered-
  array ka index, poore-array ke against use ho raha tha). Fix: har
  row apna original index (`_i`) carry karta hai ab, filter se pehle.

---

## Session 2026-07-22 (cont'd, 6) — Master/Sub-Account Hierarchy + Change Password + Light/Dark Theme

**Wajah:** Purana Users/Login system (Step 7) mein sab accounts barabar
the — koi bhi account dusre accounts add/remove kar sakta tha, aur
pehla visitor hi "first account" bana leta tha. User ne bataya ke sirf
**ek master account** hona chahiye (fixed email/password se seed), jo
hi sub-accounts create kar sake.

- **`backend/database.py`** update:
  - `User` model mein naye columns: `role` ("master" ya "sub"),
    `created_by_id`.
  - **`seed_master_account()`** — app pehli dafa start hone par
    (users table bilkul khali ho tab) automatically ek master account
    ban jata hai: email `sohaibkhan2030@gmail.com`, password
    `qwerty123`. Purana "jo pehle aaye wo master" wala bootstrap flow
    hata diya.
  - **`_migrate_user_columns()`** — safe migration jo **existing DB ko
    delete kiye bina** naye columns add kar deti hai (SQLite
    `PRAGMA table_info` se check karke `ALTER TABLE ... ADD COLUMN`),
    aur agar koi purana account already tha (is feature se pehle
    banaya hua), usay automatically master bana deti hai — taake
    kisi ke paas zero master wala DB na bache.
  - `create_user()` ab `role` + `created_by_id` accept karta hai.
  - Naya `change_password(user_id, current_password, new_password)` —
    current password verify karke naya set karta hai.
  - `list_users()` role bhi return karta hai; `delete_user()` ab
    **master account delete hone se refuse** karta hai (last-account
    guard ke ilawa).
- **`backend/main.py`** update:
  - `/api/auth/bootstrap` retire kiya (PUBLIC_PATHS se bhi hata diya)
    — ab kabhi zaroorat nahi padti, master hamesha seed ho chuka hota
    hai.
  - `/api/auth/status` ab `role` bhi return karta hai.
  - `GET/POST /api/auth/users` aur `DELETE /api/auth/users/{id}` ab
    **sirf master** kar sakta hai (naya `_require_master()` guard, 403
    return karta hai warna).
  - Naya `POST /api/auth/change-password` — koi bhi logged-in account
    (master ya sub) apna khud ka password change kar sakta hai.
- **`frontend/index.html`** update:
  - Login form ab "Email" field dikhata hai; "create the first
    account" (bootstrap) form poori tarah hata diya — login hamesha
    seedha normal sign-in form hi hota hai ab.
  - Header mein naye buttons: **theme toggle** (sun/moon icon,
    light/dark) aur **Password** (change-password modal).
  - "Users" header button ab **sirf master ko dikhta hai**
    (`hideAuthOverlay()` mein role check se).
  - Users modal: har row pe "Master"/"Sub-account" badge; master ki
    apni row pe "Remove" button nahi dikhta.
  - **Light/Dark theme**: poori stylesheet CSS variables pe based thi
    already, isliye sirf ek `html[data-theme="light"]` override block
    add kiya — koi component CSS badalna nahi para. `<head>` mein ek
    chhota inline script (page paint se pehle) saved theme
    `localStorage` se apply karta hai, taake reload pe flash na ho.

**Testing (is session mein):** `py_compile` dono backend files pe
clean. Migration + seeding logic ek standalone script se **stdlib-only
`sqlite3`** ke through verify kiya (SQLAlchemy is sandbox mein install
nahi ho saka, network access nahi tha) — purani-schema wali table pe
`ALTER TABLE ADD COLUMN` chalaya, purane account ko master banaya,
named-placeholder (`:id`) syntax bhi confirm kiya ke stdlib sqlite3
driver ke sath kaam karta hai (jo `exec_driver_sql()` internally use
karta hai). Extracted dono `<script>` blocks `node --check` se clean.
**Note:** pichli session ki tarah is session mein bhi live FastAPI
server chala kar poora end-to-end flow (login as master → sub-account
banana → us se login → password change → master delete refuse) test
nahi ho saka (sandbox mein network/sqlalchemy nahi tha) — ye agli
session mein baaki hai.

---

## Abhi baaki (roadmap ke agle steps, latest)

- **Live server end-to-end test** (Explore + Master/Sub-Account dono
  sessions ka baaki hissa): real FastAPI server chala kar poora flow
  verify karna — login as seeded master → sub-account create → uss
  se login → password change → master delete refuse → Explore
  snapshot select → sab 5 tabs + global search + row detail.
- **Explore page ke baaki sub-features**: Field Usage (reverse lookup —
  ye field kin layouts/scripts mein use hota hai), dedicated Unused
  tab, Patterns tab (detection_rules.py ke findings), Call Chain tab,
  $$Variables tab, ERD (visual diagram), aur Explore ke andar ek AI
  button.
- **Deep Audit / Table Audit ko richer banana**: Auto-Enter Total,
  Dynamic Access, Globals, Likely Typos jaise naye flags (reference
  tool ke "Deep Audit" page jaisa).
- **Download DOCX / Markdown** — har Explore detail page (Table/
  Script) ke liye.
- **Multi-tenant Dashboard + Servers + Live Logs**: clients/solutions
  card view, server register karna, live log tail karna. Sab se bara
  aur mushkil pending item — background service/websocket chahiye,
  isliye roadmap mein sab se aakhir mein.
- **Solution-level page**: DDR/SAX snapshot history table ek solution
  ke andar, "Daily Audit"/"Live Connect"/"Monitor" buttons.
- **Releases & Test Packs**: snapshot ko "release" tag karna, test
  packs generate karna.

---

## Session 2026-07-22 (cont'd, 7) — Bug fix: snapshot dropdowns not refreshing after save/rename/delete

**Bug report:** Master login/theme/password sab sahi kaam kar rahe the,
lekin ek naya DDR upload snapshot ke saath save karne ke baad bhi
Explore tab ke dropdown mein "No snapshots saved yet" hi dikh raha
tha — jab tak page reload (re-login) na ho.

**Root cause:** `/analyse-ddr` submit handler snapshot save hone ke
baad sirf `refreshSnapshots()`, `loadScriptAuditSnapshotOptions()`
call karta tha — **Explore aur Table Audit dropdown is list mein kabhi
add hi nahi hue the** jab wo dono tabs bane the. Wahi gap client/
solution rename aur client/solution/snapshot delete handlers mein bhi
tha (sirf `refreshSnapshots()` + kabhi kabhi `loadScriptAuditSnapshot
Options()`/`loadTimeline()` call hoti thi, Explore/Table Audit kabhi
nahi).

**Fix:** Ek naya shared helper `refreshAllSnapshotDependentLists()`
banaya jo sabhi 6 jagah ek sath refresh karta hai (`refreshSnapshots`,
`loadScriptAuditSnapshotOptions`, `loadTableAuditSnapshotOptions`,
`loadExploreSnapshotOptions`, `loadTimeline`, `loadDashboard`) — aur
in 6 jagah use kiya: naya snapshot save hone ke baad, client rename,
client delete, solution rename, solution delete, snapshot delete, aur
login ke baad ka reload bhi. Ab jahan bhi koi naya "snapshot list
dikhane wala tab" future mein add ho, sirf isi ek helper function mein
add karna hoga — har jagah alag se yaad rakhne ki zaroorat nahi.

**Data-shape review (isi session mein):** User ne poocha ke Tables/
Fields/Scripts/Layouts/Relationships ka data sahi fetch ho raha hai ya
nahi — `explore.py`, `table_audit.py`, `script_audit.py`,
`call_chain.py`, aur `ddr_parser.py` ke beech har field-name
line-by-line cross-check kiya (jaise `field_objects` ke `table`/`field`
keys, predicates ke `left_field`/`right_field` shape, script issues ke
`severity`/`label`/`detail`). Koi mismatch nahi mila — asal masla sirf
upar wala dropdown-refresh bug tha.
