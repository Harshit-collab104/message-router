# Configurable offline dataset workflow

Implemented 10 November 2026 (Asia/Calcutta): backlog **B02**, the highest-priority missing prerequisite after the verified defect repairs. This is one cohesive feature: initialize inputs, validate them, route/evaluate offline, and expose setup status through the existing console.

## Existing functionality reused

Inspection found CSV loading in `main.py`, bulk indexing/retrieval in `vector_store.py`, a seeded large generator in `generate_data.py`, evaluation in `evaluate.py`, three ingestion/expansion scripts, and submission packaging in `pack.py`. No second router, vector store, or generator was added.

The new `dataset_store.py` centralizes local paths, CSV contracts, readiness, and publishing. The existing generator exports through that publisher; existing ingestion scripts inherit the configured root through `main.FOLDER_DIR`. The small bundled `demo_data.json` provides original synthetic examples rather than downloading a corpus or inventing real engagement telemetry.

## Run the isolated demo

From the repository root in PowerShell, using the existing environment:

```powershell
# Relative paths resolve against this repository, independent of the shell's directory.
$env:MESSAGE_ROUTER_DATA_DIR = 'demo_runtime/data'
$env:MESSAGE_ROUTER_GATEWAY_DB = 'demo_runtime/gateway.db'
$env:MESSAGE_ROUTER_OFFLINE = 'true'

.\.venv\Scripts\python.exe -B dataset_store.py bootstrap
.\.venv\Scripts\python.exe -B dataset_store.py validate
.\.venv\Scripts\python.exe -B main.py --offline
.\.venv\Scripts\python.exe -B evaluate.py --offline
```

The bootstrap creates a previously nonexistent input directory, including 2 profiles, a group, 2 businesses, consent records, 3 historical messages/reactions, 5 incoming messages, optional empty media manifests, ground-truth labels, an output template, and `dataset_manifest.json`. The inputs cover all three actions. The five expected actions are `notify`, `digest`, `mute`, `notify`, `mute`; the toy evaluation is 5/5 for actions and types. These are deterministic regression examples, not evidence of real-world accuracy.

Running the same bootstrap again reports `unchanged` if its managed inputs still match the bundled demo. It preserves derived `output.csv`. An existing unrelated directory, edited input, changed requested corpus, or malformed manifest is rejected without replacing data. The command validates a temporary sibling directory before publishing; failed publication leaves no partial dataset.

To use the console after initialization:

```powershell
$env:GATEWAY_API_TOKEN = '<your-secret-local-admin-token>'
.\.venv\Scripts\python.exe -B -m uvicorn server:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000`, enter the token, and connect. The console now reports missing/invalid data and provides setup instructions. With the isolated demo, the recipient, contacts, and incoming queue are populated. Routing the five inputs yields 2 inbox, 1 pending digest, and 2 quarantine entries in an initially empty gateway database. Restart after changing CSV input files or environment settings: metadata and lazy caches retain the existing process-local architecture.

Offline mode skips provider initialization/calls, vector reads/writes, indexing, and outbound sends, including when provider credentials exist. A digest preview remains pending; attempting outbound digest dispatch reports `skipped` and retains the pending work. Authentication and shared routing safety rules still apply.

The commands above create local demo inputs/predictions. Starting the app creates the configured SQLite file; neither bootstrap nor batch/evaluation opens it. No sample data is seeded on application import.

## Configuration

Settings are loaded in `dataset_store.py` from the repository's `.env` without overriding process environment values. [.env.example](.env.example) documents them. Restart the application after changing settings.

| Setting | Default / behavior |
| --- | --- |
| `MESSAGE_ROUTER_DATA_DIR` | `<repo>/dataset`; CSV metadata, history/events, incoming messages, `media/`, labels, and predictions. |
| `MESSAGE_ROUTER_OFFLINE` | `false`; accepts `true`/`false` or `1`/`0`. Invalid values fail explicitly. `main.py --offline` and `evaluate.py --offline` provide one-command local-only execution too. |
| `MESSAGE_ROUTER_GATEWAY_DB` | `<repo>/msg_router_gateway.db`; optional SQLite path override. Its parent directory is created on application startup. |
| `MESSAGE_ROUTER_CHROMA_DIR` | `<repo>/chroma_db` for the original default input root; `<custom-data-root>/chroma_db` for a custom root, so changing input roots does not silently reuse the old vector corpus. An explicit path can override this. Offline mode never opens it. |

All relative paths use the repository/module directory rather than current working directory. Existing default SQLite/Chroma locations remain compatible. `dataset/` and the documented `demo_runtime/` are excluded from Git/Docker contexts; the versioned synthetic source is JSON. Custom directories should be managed as local input/runtime data rather than committed credentials or personal-message corpora.

## Validation and errors

`dataset_store.py validate` prints JSON and exits 0 only for a usable dataset; missing files, empty recipients/incoming messages, malformed CSVs, invalid flags/counts/times/conversation contexts, duplicate keys, unknown recipient references, or dangling reactions produce readiness errors and exit 2. Required tables are users, groups, group membership, business accounts, business consent, incoming messages, message history, and reactions. A header-only group/business/history table is valid when that feature has no rows. Media manifests, labels, and predictions are optional for runtime readiness, but existing files are validated.

Readers preserve string IDs, including leading zeros, and normalize the existing `brand_name` alias. Missing optional files are empty; existing corrupt files are no longer silently converted into empty dataframes. Invalid metadata fails startup explicitly; use the standalone validate command to diagnose it. A malformed lazy-loaded transaction table returns HTTP 503 with `code: dataset_invalid` and a file/column-specific detail. Errors do not echo message text or credentials.

Authenticated `GET /api/dataset/status` returns `ready`, `data_dir`, `offline_mode`, per-table row counts, `missing`, and `errors`. Missing setup returns HTTP 200 with `ready: false`; the endpoint describes file readiness, not provider health or hot-reloaded cache state. Unauthenticated access retains the owner-token boundary.

Bootstrap/generation refuses replacement rather than adding a force-delete path. Filesystem failures have a clear nonzero CLI exit. Indexing validates CSV inputs before opening/deleting a collection; a bad input cannot destroy the existing index merely because `force_rebuild=True`. Online embedding/index failures after validation still need the separate recoverable-rebuild work in B20.

## Other workflows now use the same root

- `generate_data.py` retains the existing seeded large synthetic generator, now guarded against import-time writes. `--history-rows` and `--target-rows` control its size; default values remain 10,000 and 1,000. It publishes into a new configured root and refuses replacement. Its labels remain synthetic heuristics and do not constitute a calibrated benchmark.
- `evaluate.py` reads the configured `messages.csv` and `ground_truth.csv`, requires matching IDs, and retains action/type accuracy output. Missing/mismatched labels fail explicitly.
- `vector_store.py` indexes the configured history path and rejects offline indexing with exit 2. Online indexing can require embedding assets; bootstrap does not index or download them.
- Existing ingestion scripts still import `main.FOLDER_DIR`, so their input/output CSV paths now follow the same configuration. Their download/rebuild/idempotency limitations remain separate backlog work.
- `pack.py` reads configured predictions and includes the new helper/demo/docs plus the existing vector module in the archive. Importing it no longer creates output. Legacy submission/transcript assumptions beyond dataset paths remain B19 work.

## Automated verification and limits

From the repository root:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider --tb=short
node --check static/app.js
node --test tests/frontend.test.cjs
```

Shared fixtures copy the implementation and bundled demo to per-test temporary directories, clear configuration/provider settings, and use temporary SQLite. The offline CLI subprocess tests additionally install a Python audit hook that blocks DNS/socket connections and fails even if application code catches a blocked request. Provider keys are deliberately present in the offline end-to-end case to verify that they are not used.

New coverage includes deterministic/idempotent publication, edited/unrelated-data protection, malformed manifests, publication failure cleanup, schema and cross-file errors, explicit configuration, leading-zero/alias compatibility, authenticated readiness, lazy HTTP errors, offline routing/digest behavior, CLI setup/batch/evaluation, large-generator reuse, import safety, and archive bootstrap compatibility. The previous 84 backend regression tests remain part of the full run. Frontend tests cover setup messages, escaped errors, and authenticated status requests in addition to the previous security cases.

This feature does not implement a delivery worker/outbox, real provider enrollment, live feedback learning, media downloads, a scheduler, hot reload, production migrations, or a new database architecture. B11/B09 delivery persistence/identity work remains a prerequisite for scheduling and dependable real delivery. Data remains CSV plus the existing SQLite and Chroma stores.

### Observed staged verification

- Full Python suite: **115 passed, 44 warnings in 84.92 seconds**, exit 0, using `-B -m pytest tests -q -p no:cacheprovider --tb=short --junitxml=dataset-feature-results.xml` with plugin autoload disabled. This includes 31 new backend cases plus all 84 prior tests; no skips or xfails. Warnings are the existing SQLAlchemy/default `datetime.utcnow()` deprecation.
- Frontend: **6 passed, 0 failed, 0 skipped**, exit 0, using `node --test tests/frontend.test.cjs`.
- `node --check static/app.js`: exit 0.
- Python AST checks and local documentation links: passed.
- CLI and archive smoke cases bootstrap, route and evaluate all five examples in isolated directories. Their network audit hooks recorded no attempted connections.

No live database or real `.env` is needed to exercise the feature in tests.

### Observed installed-copy verification

- Installed Python suite: **115 passed, 0 failures, 0 errors, 0 skipped**, JUnit duration **51.970 seconds**. Executed the installed `D:/Harshit/message_router/msg_router/tests` with the repository virtual environment, `-B -m pytest`, plugin autoload disabled, `-q -p no:cacheprovider --tb=short --junitxml=installed-dataset-feature-results.xml`. The command ran from the permitted scratch directory because the desktop session's configured writable root still names the old C: checkout.
- Installed frontend suite: **6 passed, 0 failed, 0 skipped**, exit 0; installed `static/app.js` syntax check: exit 0.
- Read-only installed `dataset_store.py validate`: native exit **2**, as expected for the current default data directory with eight required CSVs absent. No runtime dataset was seeded. Run the documented explicit bootstrap before using the demo.
- Integrity check: all 22 installed feature files matched their reviewed staged hashes. Other recorded source files and both existing SQLite/Chroma database files retained their pre-feature hashes. No real `.env` was changed and no external provider was contacted by these checks.

## Exact changed files

Changes are measured against the current repaired repository at the start of this feature, preserving its existing edits.

| File | Purpose |
| --- | --- |
| `dataset_store.py` (new) | Configuration, CSV contracts, readiness, validated publishing, bootstrap and validation CLI. |
| `demo_data.json` (new) | Versioned original synthetic demo inputs and labels. |
| `main.py` | Reuse validated readers/domain constants, configured paths, and offline routing/CLI behavior. |
| `server.py` | Configured SQLite path, offline provider/vector/send controls, authenticated dataset status and structured CSV errors. |
| `vector_store.py` | Configured paths, lazy client initialization, offline controls, and input validation before index mutation. |
| `evaluate.py` | Evaluate configured messages/labels with explicit errors and offline mode. |
| `generate_data.py` | Reuse the existing seeded generator with configured publishing and an import guard. |
| `pack.py` | Read configured predictions; include bootstrap dependencies/demo/docs; prevent import-time archive creation. |
| `static/app.js` | Fetch and render authenticated setup/validation status using text-safe messages. |
| `static/index.html` | Setup-status area and configured-queue label. |
| `.env.example` | Document input/storage paths and offline mode. |
| `.gitignore`, `.dockerignore` | Exclude generated default/demo runtime data. |
| `tests/conftest.py` | Isolate the new module/configuration and support seeded demo cases. |
| `tests/test_dataset_workflow.py` (new) | Bootstrap, schema/configuration/error, offline workflow, CLI and archive regression coverage. |
| `tests/frontend.test.cjs` | Add three setup/status rendering tests. |
| `tests/characterization/README.md` | Document the expanded shared fixture. |
| `README.md` (new) | Repository-local entry point to accurate setup and current evidence. |
| `DATASET_WORKFLOW.md` (new) | This feature's configuration, usage, scope and observed checks. |
| `STATUS.md`, `MISSING_FEATURES.md`, `COMPLETION_BACKLOG.md` | Record the completed B02 checkpoint and distinguish original audit findings from current behavior. |

Total: 22 files, 5 added and 17 modified. Existing `.env`, live SQLite/Chroma data, requirements, the remaining implementation modules, and Git metadata are preserved. Demo inputs are initialized only by an explicit bootstrap/generation command; the feature installation does not seed the user's real runtime directory.
