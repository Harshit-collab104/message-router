# Message Router regression tests

The 23 cases in this directory originally characterized verified defects. They now assert the repaired behavior. The historical causes and observations remain in [FAILURE_REPRODUCTIONS.md](../../FAILURE_REPRODUCTIONS.md); current changes and limits are in [REPAIR_RESULTS.md](../../REPAIR_RESULTS.md).

From the repository root:

```powershell
$env:PYTEST_DISABLE_PLUGIN_AUTOLOAD = '1'
.\.venv\Scripts\python.exe -B -m pytest tests -q -p no:cacheprovider
node --check static/app.js
node --test tests/frontend.test.cjs
```

Use `tests/characterization` instead of `tests` to run just these 23 regressions. `tests/test_repairs.py` adds policy, authentication/signature, input validation, retry, receipt, migration, and batch-output checks. The original 16 endpoint/rule tests are preserved in `tests/test_router.py` with isolated fixtures and updated preview semantics.

Shared fixtures live in `tests/conftest.py`. Each case copies the router modules and dataset helper unchanged into a fresh temporary directory, disables dotenv loading, removes provider settings, blocks network connection/DNS attempts, supplies synthetic vector records/distances, and uses temporary SQLite. The shared client supplies synthetic owner credentials/provider signatures for positive smoke tests; negative tests make raw unsigned/unauthenticated requests. No real credentials, corpus, SDK initialization, Chroma index, or live database is needed.

The small ASGI request helper runs actual FastAPI routing, request parsing, middleware, and endpoint bodies without a listening server or Windows TestClient socketpair. It fails if a coroutine needs asynchronous IO. These are unit-level routing/storage checks, not lifespan, real transport, multi-worker, semantic embedding quality, or external-provider integration tests. Node tests use a minimal DOM stub to check escaping and token headers.

On this restricted chat host, the saved writable folders still refer to C:. If pytest cannot restore D: as its working directory, start it in an allowed scratch directory and pass absolute D: interpreter/test paths, as shown in REPAIR_RESULTS.md. No change to Git metadata or production directories is needed to run the tests.

The dataset workflow adds its synthetic fixture and companion CLI modules to this isolated workspace. See [dataset workflow tests](../test_dataset_workflow.py) and [setup instructions](../../DATASET_WORKFLOW.md).
