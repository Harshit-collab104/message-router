# Missing-features matrix

**10 November 2026 implementation update:** B02 is complete: configured dataset/storage paths, safe deterministic demo bootstrap, CSV validation, offline operation, and authenticated setup status. See [DATASET_WORKFLOW.md](DATASET_WORKFLOW.md) for usage, tests, and scope. The original audit snapshot below is historical; the 9 November repairs are documented in [REPAIR_RESULTS.md](REPAIR_RESULTS.md).

As inspected on 7 November 2026. This matrix covers the current working tree, including pre-existing uncommitted webhook/digest changes. “Present” describes code and limited diagnostic evidence, not production certification. Full architecture, diagnostic limitations, and failure details are in [STATUS.md](STATUS.md); work IDs refer to [COMPLETION_BACKLOG.md](COMPLETION_BACKLOG.md).

Status vocabulary: **Present** = substantial implementation exists; **Partial** = capability exists with material omissions; **Broken** = an implemented path has a confirmed defect; **Absent** = no first-party implementation found; **Unverified** = cannot establish behavior with the authorized safe checks. Priority: P0 before external exposure; P1 for dependable end-to-end operation; P2 for quality and scale.

| Capability / intended requirement | Status | Existing evidence | Missing behavior or limitation | Priority / work |
| --- | --- | --- | --- | --- |
| Three-action routing contract | Partial | `main.py:97–428`; `server.py:161–344` | Rules exist; request/result enums and types are unvalidated; action means categorization rather than actual delivery | P1 B04, B05, B13 |
| Repeatable local dataset/bootstrap | Absent | `main.py:15–60`; active `dataset/` absent | No tracked minimal fixture or bootstrap into runtime location; readers silently return empty frames | P1 B02 |
| Profile/consent management | Partial | CSV user/group/business tables | Reads only; no user enrollment, preference update, refresh/invalidation, timezone, or authenticated identity mapping | P1 B04, B09; P2 B18 |
| Batch CSV inference | Broken | `main.py:630–715` | `messages=None` is used directly; missing template; no output contract validation | P1 B03 |
| Cold-start prompt/RAG context | Broken | `main.py:456`, `464`, `476` | Lazy tables dereferenced as if loaded; six stored prompt-error traces | P1 B03 |
| CSV conversation history API | Broken | `server.py:853`, `879` | `message_history` and `message_events` undefined in server module | P1 B03 |
| Basic scam/injection heuristic | Partial | `main.py:105–140`, `357–360` | Broad keywords create false positives; verified/admin exceptions can weaken scam checks | P1 B05 |
| Deterministic guardrails for all engines | Absent | Engine branches at `server.py:243–260` | LLM result can bypass scam, opt-out, and mute rules; prompt instructions do not provide equivalent enforcement | P0 B05 |
| Direct-mention routing override | Broken | `main.py:85–86`, `142–146` | Digits replaced before mention normalization; `@u_001` does not trigger heuristic override | P1 B05 |
| Valid OTP action/type agreement | Broken | `main.py:128–131`, `382–383`; test asserts action only | Valid verified OTP still labeled scam; code length and trust rules differ between prompt and heuristic | P1 B05 |
| DND enable/disable and timezone | Broken / Partial | `main.py:63–79`, `374`; `server.py:261–280` | Heuristic ignores gateway disable flag; naive server time; no per-user timezone or stable event time | P1 B05, B09 |
| Group mute / business opt-out | Partial | `main.py:148–160`, `365–371` | Muted group differs between prompt and heuristic; opt-out mutes even transactional content | P1 B05 |
| Semantic contextual retrieval | Partial / Unverified | `vector_store.py:102–178`; existing embeddings storage | Retrieval exists; actual stored semantic queries not run; no relevance/freshness/time contract | P1 B06; P2 B17 |
| User-isolated retrieval and evidence | Broken | Channel/global fallbacks remove user filter | Another user's text/reactions can enter prompts, logs, and decisions; message IDs not user-scoped | P0 B06 |
| Meaningful similarity control | Broken | `server.py:221–225`; classifier retrieves independently | Slider filters trace matches only; actual decisions/prompts use unfiltered matches | P1 B06 |
| Feedback-driven memory updates | Partial | Bulk CSV reaction join; live text added after routing | No live reaction endpoint or updates; new vectors omit reaction/time/media identity | P1 B12 |
| Gemini routing/media | Partial / Unverified | `main.py:569–628` | SDK path exists; prompt failure can preempt provider fallback; local manifests only; real provider untested | P1 B03, B07, B10 |
| Groq routing | Partial / Unverified | `main.py:525–566` | HTTP path exists; unvalidated JSON; no bounded retry/rate-limit strategy or fallback provenance | P1 B07 |
| Groq digest summary | Broken | `server.py:559` | Imports nonexistent `main.groq_client`; silently returns fallback summary | P1 B07 |
| Meta verification and inbound parsing | Partial | `server.py:385–482`; existing text/status tests | No POST authenticity check, recipient account mapping, event-time use, replay protection, or truthful partial failure handling | P0 B08; P1 B09 |
| Twilio inbound adapter | Partial | `server.py:485–509` | Text only, no signature/account validation, media, retry contract, or outbound client | P0 B08; P1 B09, B10 |
| Real immediate notification dispatch | Absent | Notify appears in logs/device simulation | No notify-specific push/provider dispatch; optional Meta auto-reply responds regardless of action | P1 B13 |
| Provider media download/OCR/audio | Absent / Partial local-only | Local image/voice manifests and Gemini upload | Live media IDs unresolved; audio/voice mismatch; no provider fetch or Twilio media handling | P1 B10 |
| Pending digest list / manual summary | Present with defects | `server.py:598–734` | Core manual path exists; all pending rows processed without size bounds; fallback “latest” is oldest | P1 B11 |
| Lossless digest delivery state | Broken | Mark-delivered before send at `server.py:642–656` | Preview consumes queue; failed/skipped send loses pending state; no saved digest/outbox, retry, or concurrent claim | P1 B11 |
| Scheduled digest delivery | Absent | Manual endpoints only | No scheduler, cadence, user-local delivery time, or worker lifecycle | P1 B14 |
| Outbound provider success/receipts | Partial / Unverified | `server.py:355–382`, `656` | HTTP error JSON can be called dispatched; callbacks ignored; no accepted/delivered/failed states | P1 B11, B13 |
| Idempotent inbound processing | Absent | Log ID auto-increments; message ID nonunique | Replays duplicate records/side effects; Chroma IDs can collide across users | P1 B09, B12 |
| API authentication / authorization | Absent | All routes lack auth dependencies/checks | Global logs, profiles, config writes, user digests, media and webhook are exposed | P0 B08 |
| Safe browser rendering | Partial | Text/reason escaped; ID/action/type/metadata raw HTML | Stored HTML injection through unescaped interpolation | P0 B08 |
| Persistent validated configuration | Partial | Process-global CONFIG and coercions | Invalid names/ranges accepted; no worker consistency, persistence, path configuration, example env file | P1 B04, B15 |
| Audit console and mock device | Present / Partial | All three static files; syntax check passed | Manual refresh, no health probe; empty users block sending; no digest actions or actual media preview | P2 B18 |
| Accurate observability | Partial | SQLite prompts, RAG, confidence, timing | Latency omits writes; actual fallback engine not stored; missing receipt/failure metrics, health/readiness, retention controls | P1 B07, B16 |
| Reliable migrations/session lifecycle | Partial | `create_all` and blanket-caught ALTER | No versioned schema, missing digest index in existing DB, insufficient rollback/finally cleanup | P1 B16 |
| Reproducible tests/CI | Partial | 16 tests in one module; no CI config | Normal DB/keys used, corpus dependency, broad sweep mutates user digests; major negative paths untested | P1 B01 |
| Honest quality benchmark | Broken / Absent usable inputs | `evaluate.py`; generator labels | Missing legacy inputs, synthetic reactions, no leakage-controlled split or saved results | P2 B17 |
| Reproducible safe container | Partial | Python 3.11 Dockerfile; unpinned requirements | No `.dockerignore`/lock/version matrix/health/nonroot/storage contract; build-context secret inclusion | P0 B15; P1 B16 |
| Complete submission packaging | Broken | `pack.py:6–42` | Omits `vector_store.py`; stale output path and absolute transcript path; import-time writes | P2 B19 |
| Safe, repeatable data ingestion | Partial | Three expansion/ingestion scripts | Append duplicates, synthetic feedback, forced rebuild, no provenance/checksum/license manifest; DailyDialog compatibility unverified | P2 B20 |
| Capacity/recovery controls | Absent / Partial | Single process; synchronous heavy calls; no worker | No bounded queue/backpressure, retry budget, deployment load evidence, tested backup/restore | P2 B21 |

Items inferred from the README's claimed product behavior (real notify delivery, scheduled digests, deterministic guardrails) are called out explicitly. Other operational work is recommended to make the implemented externally reachable gateway dependable; it is not represented as a separately supplied product specification.
