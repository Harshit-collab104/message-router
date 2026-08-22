# RAG-Enabled Messaging Router Gateway

A high-performance, minimalist developer observability dashboard and routing gateway that acts as a middleware between incoming messages and end-user devices (simulating services like WhatsApp). It uses **ChromaDB (Vector RAG)**, **LLM classification engines (Gemini/Groq)**, and a **deterministic heuristics pipeline** to intelligently categorize and prioritize notifications into `Notify`, `Digest`, and `Quarantine (Mute)`.

---

## 🚀 Key Features

* **Zero-Memory Startup Footprint**: Large transactional data tables are lazy-loaded on-demand, reducing initial RAM consumption and enabling instant server startup.
* **Vector RAG & Cascading Fallback**: Implements a cascading search strategy (Strict Context -> User General -> Channel General -> Global Semantic Match) inside ChromaDB. It ensures historical context is always fetched, avoiding "no matches found" scenarios.
* **Metadata-Enriched Embeddings**: User reaction logs (`message_opened`, `message_replied`, `muted_after_message`, etc.) are coupled directly with the vector documents at indexing time, allowing the system to run RAG heuristics without querying Pandas dataframes.
* **Minimalist High-Contrast Console**: Custom GPU-accelerated logs viewport and device simulator styled with hardware-accelerated scrolling (`will-change`) and WhatsApp group-style bubble rendering.
* **Ingested Real-World Telemetry**: Includes an ingestion pipeline loaded with **16,000+ real conversations and transactions** from Google's Schema-Guided Dialogue (SGD) and UCI Spam corpora.
* **Production Ready**: Fully containerized with Docker and covered by unit tests using Pytest.

---

## 🛠️ Tech Stack

* **Backend**: FastAPI, Python 3.11+, SQLAlchemy (SQLite)
* **Frontend**: HTML5, Vanilla JavaScript, CSS3 (Minimalist Dark Theme)
* **Vector DB**: ChromaDB (L2 Distance Embeddings)
* **LLM Pipelines**: Google Gemini API, Groq Cloud API

---

## 📦 Running the Application

### Option A: Local Run (PowerShell)
1. **Navigate to the root directory**:
   ```powershell
   cd c:\Users\harsh\Harshit\message_router
   ```
2. **Start the FastAPI server**:
   ```powershell
   .\msg_router\.venv\Scripts\python -m uvicorn msg_router.server:app --port 8000 --host 127.0.0.1
   ```
3. **Open in browser**:
   Visit **[http://127.0.0.1:8000](http://127.0.0.1:8000)**.

### Option B: Run in Docker
1. **Build the Docker container**:
   ```bash
   docker build -t rag-router .
   ```
2. **Launch the container**:
   ```bash
   docker run -p 8000:8000 --env-file .env rag-router
   ```
3. **Open in browser**:
   Visit **[http://localhost:8000](http://localhost:8000)**.

---

## 🧪 Testing Suite (Pytest)

The test suite validates API endpoints, heuristics validation rules, and ensures that ChromaDB calls are mocked for deterministic testing.

Run all tests:
```powershell
.\msg_router\.venv\Scripts\python -m pytest msg_router/tests/test_router.py
```

Expected Output:
```text
======================== 8 passed, 4 warnings in 5.64s ========================
```
