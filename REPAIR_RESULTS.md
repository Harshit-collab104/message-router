# Message Router repair results

9 November 2026 (Asia/Calcutta). Repository: `D:\Harshit\message_router\msg_router`.

The verified implementation was repaired in place within its existing FastAPI, pandas, SQLAlchemy/SQLite, Chroma, Gemini/Groq, and vanilla JavaScript architecture. The pre-existing user changes were the starting point; no checkout/reset, service deployment, package install, corpus rebuild, or live provider call was performed.

## Repairs and observable behavior

| Audit IDs | Change |
| --- | --- |
| F01–F03 | Prompt and client-history paths use lazy-table accessors; both empty and CSV/vector history work. Batch loads messages, reports missing input explicitly, and writes predictions in input order without requiring an existing output template. |
| F04, F08 | Retrieval retains recipient ownership through strict and user-only fallback, with an ownership postcheck. One authorized, cutoff-filtered vector snapshot is reused by prompt/classifier/trace. Rejected vector IDs cannot re-enter through CSV fallback or cited evidence. New vector IDs include source, recipient, and message ID; original message IDs remain the public evidence IDs. |
| F05–F08 | A shared policy enforces injection/scam checks across gateway and direct provider/batch paths. Mentions work with recipient-ID boundaries; verified numeric OTPs are not automatically typed scam; ordinary leak alerts are not credential-theft scams; opt-out applies to promotional content. The DND toggle reaches every engine. Muted groups retain the existing heuristic digest policy, with mentions and security rules taking precedence. Model result enums, confidence, and evidence types are checked. |
| F09, F13 | Default digest generation is a non-consuming preview. Failed/skipped/rejected sends remain pending; provider acceptance is required before marking rows accepted through the existing `digest_delivered` column. Overlapping dispatches receive 409 while one is in progress. New arrivals during a send remain pending. Batch dispatch reports partial failures instead of unconditional success. |
| F10, F18 tracing subset | Digest uses the actual Groq Requests transport with text mode, rather than a nonexistent SDK client. Routing validates provider JSON and reports the engine used after Gemini fallback. Heuristic digest mode does not invoke providers. |
| F11 | Private APIs require a configured owner/admin bearer credential. Meta POST uses raw-body HMAC verification; Twilio validates its form signature against the exact callback URL. Missing secrets fail closed; the predictable Meta verification-token default is removed. CORS has no wildcard origin by default. |
| F12 | An additive SQLite receipt table claims `(source, recipient, message_id)`, returns cached results on replay, and rejects work already in progress. Routing decisions and cached replay responses commit atomically. New indexing avoids cross-recipient/source ID collisions. Historical logs are preserved. |
| F15 packaging subset, F17 | Docker context exclusions protect local secrets/environments/databases; HTTPX is explicitly declared. The console supports a tab-scoped bearer credential and escapes previously raw sender/action/type/RAG-metadata HTML. |

The 23 characterization cases now assert corrected outcomes. The older 16 tests are isolated from live imports/storage and use signed/authenticated synthetic requests. Forty-five additional backend cases cover positive/negative boundaries, fallbacks, retries, overlapping claims, atomic rollback, additive migration, and CSV output. Three Node tests cover console credentials and escaped rendering.

## Necessary interface/configuration changes

All existing endpoint URLs and routing tuple shapes are retained. The following behavior changes are intentional repairs:

- Private `/api/...` requests need `Authorization: Bearer <GATEWAY_API_TOKEN>`. The credential is a privileged single-owner/admin boundary, not a new multi-user account system. Missing server configuration returns 503; missing/invalid credentials return 401. Public static assets remain accessible so the console can show its Connect form.
- Configure `WHATSAPP_APP_SECRET` and `WHATSAPP_VERIFY_TOKEN` for Meta, and `TWILIO_AUTH_TOKEN` for Twilio. Unsigned/incorrectly signed POSTs return 403 when configured; absent signing secrets return 503. Meta verification GET still returns the plain challenge with a valid configured token.
- Set `TWILIO_WEBHOOK_URL` to the exact externally configured URL, including query string, behind a reverse proxy. The implemented Twilio mode is legacy Auth Token/HMAC-SHA1 form callbacks, not SharedKey or JSON-body signing. A published [Twilio SDK test vector](https://github.com/twilio/twilio-python/blob/main/tests/unit/test_request_validator.py) is exercised independently of the signing fixture; the URL/parameter rules follow [Twilio request validation](https://www.twilio.com/docs/usage/security#validating-requests-are-coming-from-twilio).
- The console's access-token input stores the credential in `sessionStorage` for the tab and attaches it to API requests. Real `.env` contents were not changed. See [.env.example](.env.example); no secrets are supplied in that file.
- `auto_send=false` keeps digest items pending. For `auto_send=true`, response `status`/`dispatch` exposes error/skipped/accepted outcomes; a successful HTTP error-body response is no longer called dispatched. Provider acceptance is distinct from a final delivery/read receipt.
- Routing responses have an additive `duplicate` boolean. In-progress duplicate routing/dispatch returns HTTP 409. The optional debug WhatsApp reply runs only for a new notify decision, not muted/digest/replayed traffic.
- Invalid model names, malformed message fields, nonboolean DND flags, and invalid thresholds now return client errors. Config changes validate as a whole before updating the existing process-local CONFIG.

On the next application import/startup, SQLAlchemy creates `gateway_receipts` if absent and adds the existing digest flag/index if needed. The migration regression preserves synthetic duplicate historical logs and verifies the missing index is restored. No startup/migration was run on the user's actual SQLite file during this task.

## Exact files changed

Twenty files: fourteen modified and six added, relative to the task-start working files (not the older Git HEAD).

| File | Change |
| --- | --- |
| `main.py` | Modified: shared policy, lazy access, context reuse, provider validation/transport/fallback identity, batch output. |
| `server.py` | Modified: authentication/signatures, validated config/payloads, receipts and atomic decision storage, shared routing context/policy, truthful digest dispatch, history handler. |
| `vector_store.py` | Modified: recipient-only fallback/postcheck, source/recipient-scoped index IDs, source-relative store path. |
| `requirements.txt` | Modified: declare HTTPX directly. |
| `.gitignore` | Modified: allow the sanitized `.env.example`. |
| `.dockerignore` | Added: exclude credentials, environments, Git data, caches, SQLite files/sidecars, and Chroma storage. |
| `.env.example` | Added: document required owner/provider secrets and optional settings with no usable credentials. |
| `static/app.js` | Modified: token headers/connection status and HTML escaping. |
| `static/index.html` | Modified: access-token controls and actual HTTP connection status. |
| `static/style.css` | Modified: style the password field consistently with the existing form. |
| `tests/conftest.py` | Added: shared isolated offline fixtures and authenticated/signed smoke client. |
| `tests/test_router.py` | Modified: preserve 16 original cases using isolated fixtures, owned RAG seed, and non-consuming preview expectation. |
| `tests/characterization/conftest.py` | Modified: defer to shared parent fixtures. |
| `tests/characterization/test_failures.py` | Modified: convert 23 observed-bad cases into repair regressions. |
| `tests/characterization/README.md` | Modified: current commands, fixture safety, scope and host workaround. |
| `tests/test_repairs.py` | Added: 45 additional backend cases. |
| `tests/frontend.test.cjs` | Added: 3 Node tests using a small DOM stub. |
| `STATUS.md` | Modified: dated update linking current repair results while retaining the original audit. |
| `FAILURE_REPRODUCTIONS.md` | Modified: distinguish the historical characterization baseline from current regressions. |
| `REPAIR_RESULTS.md` | Added: this report. |

The real `.env`, live gateway/Chroma databases, old data/evaluation/ingestion/packaging scripts, Dockerfile, historical feature matrix/backlog, and Git metadata were not changed.

## Commands and observed checks

Staged implementation checks, after the repairs and identity-key changes:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'D:\Harshit\message_router\msg_router\.venv\Scripts\python.exe' -B -m pytest tests -q -p no:cacheprovider --tb=short --junitxml=repair-results.xml
node --check static/app.js
node --test tests/frontend.test.cjs
```

- Full staged Python suite: **84 passed, 39 warnings in 15.79 seconds**, exit 0. Warnings are the existing SQLAlchemy/default `datetime.utcnow()` deprecation.
- Targeted receipt/identity/atomicity check: **4 passed, 41 deselected, 6 warnings**, exit 0, after adding source-scoped identities. The subsequent full staged run includes the latest bulk-index source normalization.
- Node tests: **3 passed, 0 failed, 0 skipped**, exit 0.
- `node --check static/app.js`: exit 0.
- AST parsing of changed Python modules/tests: passed without writing bytecode.

Because the chat's configured writable folders still point to C:, verification uses allowed scratch space as the process working directory. The installed suite can be targeted without changing that directory:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
& 'D:\Harshit\message_router\msg_router\.venv\Scripts\python.exe' -B -m pytest 'D:\Harshit\message_router\msg_router\tests' -q -p no:cacheprovider --tb=short
node --check 'D:\Harshit\message_router\msg_router\static\app.js'
node --test 'D:\Harshit\message_router\msg_router\tests\frontend.test.cjs'
```

Fixtures resolve the implementation from their own installed location, copy it into per-test temporary workspaces, disable dotenv/provider credentials, and block network connections/DNS. SQLite is real temporary SQLite; vectors/embeddings and providers are synthetic. Actual FastAPI request parsing, dependencies, CORS, handler bodies, routing, receipt transactions, and digest state run in process. The synchronous-completing ASGI helper avoids this host's Windows TestClient/socketpair issue; it is not a real HTTP transport or concurrency/load test. No xfails or skipped backend tests are used.

### Final installed-copy verification

The absolute-path commands above were executed from permitted scratch space against the installed `D:` files. Pytest also wrote its JUnit result to scratch space (`--junitxml=installed-repair-results.xml`).

| Check | Observed result |
| --- | --- |
| Installed Python suite | **84 passed, 39 warnings in 34.49 seconds**, exit 0. JUnit: 84 tests, 0 failures, 0 errors, 0 skipped. |
| Installed frontend Node tests | **3 passed, 0 failed, 0 skipped**, exit 0. |
| Installed `static/app.js` syntax | `node --check`: exit 0. |
| Copy integrity | All 20 installed additions/modifications matched staged SHA-256 values before this report-only results update. All remaining recorded files matched task-start values. |
| Gateway SQLite integrity | Unchanged: `7dab6f4b36b97282cf2291ba22ef2b435de655735013d824c4410c1db3714850`. |
| Chroma SQLite integrity | Unchanged: `bdc7d93b40ac6e6dd6ce4c13021592e1106d6835e509fb07e01ffc481b448386`. |

No real `.env` credentials were used or changed. No live schema migration, Chroma query/rebuild, provider send, package install, or deployment occurred. The installed fixture resolves its implementation root on `D:`, so these results are not merely a rerun of the earlier staged source copies.

## Remaining limits

- This is not a complete production hardening pass. Missing demo/evaluation data, provider identity mapping, per-user timezones, real media downloads/feedback learning, scheduled delivery, package locks/CI, retention/health, and load behavior remain in the historical backlog. Unknown first-contact urgency keeps the conservative existing digest default.
- Receipts protect processing after this upgrade; historical log rows are not retroactively assigned provider receipt identities. A crash can leave an in-progress claim with no response; it intentionally returns 409 until an operator reconciles that attempt rather than automatically expiring it and risking a duplicate. Provider send/acknowledgement and the final SQLite digest update cannot provide exactly-once delivery across crashes or ambiguous network timeouts. No automatic retry worker was introduced.
- Existing Chroma data is read-compatible through original-ID fallback metadata, but no rebuild/backfill or real semantic query was performed. Historical index omissions are not recreated by source changes. Vector insertion remains best effort after the durable routing transaction.
- The private API credential grants owner/admin access to all console users/logs; it is not recipient-scoped end-user authentication. Twilio proxy URL, provider secrets, actual callbacks, SDK availability, and real delivery must be checked in the intended deployment. Meta HMAC cases use generated synthetic fixtures; live-provider validation was not performed.
- The gateway still does synchronous work in async endpoints, uses process-local configuration, and records its existing pre-persistence routing timer. Full versioned migrations and external delivery receipts remain separate work.

Exact changed paths and unchanged live stores are checked against task-start SHA-256 values before and after installation; no Git reset, commit, or metadata repair is part of these changes.
