# Message Router

A FastAPI notification-routing prototype that classifies personal, group, and business messages into `notify`, `digest`, or `mute`. It uses CSV profiles/history, SQLite audit/digest/receipt storage, optional Chroma retrieval, optional Gemini/Groq reasoning, and a browser developer console.

Start with the [offline dataset workflow](DATASET_WORKFLOW.md). It includes a deterministic synthetic demo, configuration, validation, CLI evaluation, and console setup without provider calls. Initialize explicitly with `python dataset_store.py bootstrap`; existing or edited data is never replaced.

The console/API requires `GATEWAY_API_TOKEN`. Provider webhooks require their signing secrets. See [.env.example](.env.example).

Current evidence and work:

- [Dataset feature and verification](DATASET_WORKFLOW.md)
- [Verified defect repairs](REPAIR_RESULTS.md)
- [Historical repository audit](STATUS.md)
- [Completion backlog](COMPLETION_BACKLOG.md)

This is a prototype with remaining delivery, feedback, media, scheduling, and operational work. `notify` is still a routing outcome/device simulation rather than a general-purpose push service.
