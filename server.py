import datetime
import json
import os
import sys
import time
from pathlib import Path

import numpy as np
import pandas as pd
import sqlalchemy
from dotenv import load_dotenv
from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

# Load .env file
load_dotenv()

# Setup path to import from main.py and vector_store.py
PARENT_DIR = Path(__file__).parent
sys.path.append(str(PARENT_DIR))

from main import (
    FOLDER_DIR,
    MEDIA_DIR,
    business_accounts,
    compile_prompt,
    get_message_history,
    get_messages,
    group_members,
    groups,
    images,
    predict_heuristic,
    process_message_with_gemini,
    process_message_with_groq,
    user_business_history,
    users,
    voice_notes,
)
from vector_store import get_client as get_chroma_client
from vector_store import retrieve_relevant_history

# Initialize FastAPI App
app = FastAPI(title="Message Routing Middleware Gateway")

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# SQLite Database Setup (Self-contained in msg_router directory)
DB_PATH = Path(__file__).parent / "msg_router_gateway.db"
DATABASE_URL = f"sqlite:///{DB_PATH}"
engine = create_engine(DATABASE_URL, connect_args={"check_same_thread": False})
SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)
Base = sqlalchemy.orm.declarative_base()


class GatewayLog(Base):
    __tablename__ = "gateway_logs"
    id = Column(Integer, primary_key=True, index=True)
    message_id = Column(String, index=True)
    user_id = Column(String, index=True)
    conversation_type = Column(String)
    sender_user_id = Column(String, nullable=True)
    group_id = Column(String, nullable=True)
    business_id = Column(String, nullable=True)
    message_text = Column(Text, nullable=True)
    media_type = Column(String, nullable=True)
    media_id = Column(String, nullable=True)
    action = Column(String)
    message_type_pred = Column(String)
    reason = Column(Text)
    confidence = Column(Float)
    evidence_message_ids = Column(String)
    latency_ms = Column(Float)
    timestamp = Column(DateTime, default=datetime.datetime.utcnow)
    retrieved_rag = Column(Text)  # JSON-stringified vector matches
    prompt_compiled = Column(Text)


Base.metadata.create_all(bind=engine)

# Active Gateway Configuration State
gemini_key = os.environ.get("GEMINI_API_KEY")
groq_key = os.environ.get("GROQ_API_KEY")

CONFIG = {
    "active_model": "gemini" if gemini_key else ("groq" if groq_key else "heuristic"),
    "l2_distance_threshold": 1.5,
    "dnd_enabled": True,
    "gemini_model": os.environ.get("GEMINI_MODEL", "gemini-2.5-flash"),
    "groq_model": os.environ.get("GROQ_MODEL", "llama-3.3-70b-versatile"),
}

# Initialize Gemini Client if key available
gemini_client = None
if gemini_key:
    try:
        from google import genai

        gemini_client = genai.Client(api_key=gemini_key)
        print("Gemini API client successfully initialized in middleware gateway.")
    except Exception as ex:
        print(f"Error creating Gemini client: {ex}")

# ----------------- GATEWAY API ENDPOINTS -----------------


@app.get("/api/gateway/config")
async def get_gateway_config():
    return CONFIG


@app.post("/api/gateway/config")
async def update_gateway_config(new_config: dict = Body(...)):
    global CONFIG
    if "active_model" in new_config:
        model = new_config["active_model"]
        if model == "gemini" and not gemini_client:
            raise HTTPException(
                status_code=400,
                detail="Gemini API Client is not configured. Add GEMINI_API_KEY to environment.",
            )
        if model == "groq" and not groq_key:
            raise HTTPException(
                status_code=400,
                detail="Groq API key is not configured. Add GROQ_API_KEY to environment.",
            )
        CONFIG["active_model"] = model
    if "l2_distance_threshold" in new_config:
        CONFIG["l2_distance_threshold"] = float(new_config["l2_distance_threshold"])
    if "dnd_enabled" in new_config:
        CONFIG["dnd_enabled"] = bool(new_config["dnd_enabled"])
    return CONFIG


@app.post("/api/gateway/webhook")
async def receive_webhook_message(payload: dict = Body(...)):
    start_time = time.time()

    message_id = payload.get("message_id")
    user_id = payload.get("user_id")
    conversation_type = payload.get("conversation_type")
    sender_user_id = payload.get("sender_user_id")
    group_id = payload.get("group_id")
    business_id = payload.get("business_id")
    message_text = payload.get("message_text", "")
    media_type = payload.get("media_type")
    media_id = payload.get("media_id")
    forwarded_count = payload.get("forwarded_count", 0)

    if not message_id or not user_id or not conversation_type:
        raise HTTPException(
            status_code=400,
            detail="Missing required payload fields: 'message_id', 'user_id', 'conversation_type'",
        )

    # Build dynamic Series for pandas model calculations
    row_dict = {
        "message_id": message_id,
        "user_id": user_id,
        "conversation_type": conversation_type,
        "sender_user_id": sender_user_id or "none",
        "group_id": group_id or "none",
        "business_id": business_id or "none",
        "message_text": message_text,
        "media_type": media_type if media_type else np.nan,
        "media_id": media_id if media_id else np.nan,
        "forwarded_count": forwarded_count,
        "created_at": datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
    }

    row_series = pd.Series(row_dict)

    # 1. RAG Vector Store Search
    retrieved = []
    if message_text and message_text.strip() != "":
        try:
            retrieved = retrieve_relevant_history(
                user_id=user_id,
                conv_type=conversation_type,
                group_id=group_id,
                business_id=business_id,
                sender_user_id=sender_user_id,
                message_text=message_text,
                limit=5,
            )
        except Exception as ve_err:
            print(f"RAG ChromaDB retrieval failed: {ve_err}")

    # Apply configured L2 similarity threshold filtering
    filtered_retrieved = []
    for r in retrieved:
        if r["distance"] <= CONFIG["l2_distance_threshold"]:
            filtered_retrieved.append(r)

    # 2. Compile dynamic LLM context prompt
    prompt = ""
    try:
        prompt = compile_prompt(row_series)
    except Exception as pr_err:
        prompt = f"Prompt compilation failed: {pr_err}"

    # 3. Route decision pipeline
    action, message_type_pred, reason, confidence, evidence = (
        "digest",
        "unknown",
        "Fallback heuristics.",
        0.5,
        "none",
    )
    model_used = CONFIG["active_model"]

    try:
        if model_used == "gemini" and gemini_client:
            action, message_type_pred, reason, confidence, evidence = (
                process_message_with_gemini(
                    gemini_client, row_series, CONFIG["gemini_model"]
                )
            )
        elif model_used == "groq" and groq_key:
            action, message_type_pred, reason, confidence, evidence = (
                process_message_with_groq(row_series, prompt)
            )
        else:
            action, message_type_pred, reason, confidence, evidence = predict_heuristic(
                row_series
            )
            model_used = "heuristic"
    except Exception as pipe_err:
        print(
            f"Error executing {model_used} pipeline: {pipe_err}. Falling back to heuristics."
        )
        action, message_type_pred, reason, confidence, evidence = predict_heuristic(
            row_series
        )
        model_used = "heuristic (fallback)"

    # 4. Check Do Not Disturb settings (DND)
    if CONFIG["dnd_enabled"]:
        user_rows = users[users["user_id"] == user_id]
        if len(user_rows) > 0:
            dnd_window = user_rows.iloc[0]["do_not_disturb_window"]
            from main import is_in_dnd

            in_dnd = (
                is_in_dnd(row_dict["created_at"], dnd_window) if dnd_window else False
            )

            # Direct mention check overrides DND
            has_mention = False
            if message_text and f"@{user_id}" in message_text:
                has_mention = True

            if action == "notify" and in_dnd and not has_mention:
                action = "digest"
                reason += " (Delivered to digest due to user Do Not Disturb hours)"

    latency_ms = (time.time() - start_time) * 1000

    # Save trace log to SQLite
    db = SessionLocal()
    log_entry = GatewayLog(
        message_id=message_id,
        user_id=user_id,
        conversation_type=conversation_type,
        sender_user_id=sender_user_id,
        group_id=group_id,
        business_id=business_id,
        message_text=message_text,
        media_type=media_type,
        media_id=media_id,
        action=action,
        message_type_pred=message_type_pred,
        reason=reason,
        confidence=float(confidence),
        evidence_message_ids=evidence,
        latency_ms=latency_ms,
        retrieved_rag=json.dumps(filtered_retrieved),
        prompt_compiled=prompt,
    )
    db.add(log_entry)
    db.commit()
    db.refresh(log_entry)
    db.close()

    # 5. Index new message text in ChromaDB for immediate memory updates
    if message_text and message_text.strip() != "":
        try:
            chroma_client = get_chroma_client()
            collection = chroma_client.get_or_create_collection(name="message_history")
            collection.add(
                ids=[message_id],
                documents=[message_text],
                metadatas=[
                    {
                        "user_id": str(user_id),
                        "conversation_type": str(conversation_type),
                        "group_id": str(group_id or "none"),
                        "business_id": str(business_id or "none"),
                        "sender_user_id": str(sender_user_id or "none"),
                        "media_type": str(media_type or "none"),
                    }
                ],
            )
        except Exception as add_err:
            print(f"Error indexing new message into ChromaDB: {add_err}")

    return {
        "message_id": message_id,
        "action": action,
        "message_type": message_type_pred,
        "reason": reason,
        "confidence": confidence,
        "evidence_message_ids": evidence,
        "latency_ms": latency_ms,
        "model_used": model_used,
        "rag_matches": filtered_retrieved,
        "timestamp": log_entry.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
    }


@app.get("/api/gateway/logs")
async def get_gateway_logs(limit: int = 50):
    db = SessionLocal()
    logs = db.query(GatewayLog).order_by(GatewayLog.id.desc()).limit(limit).all()
    res = []
    for l in logs:
        res.append(
            {
                "id": l.id,
                "message_id": l.message_id,
                "user_id": l.user_id,
                "conversation_type": l.conversation_type,
                "sender_user_id": l.sender_user_id,
                "group_id": l.group_id,
                "business_id": l.business_id,
                "message_text": l.message_text,
                "media_type": l.media_type,
                "media_id": l.media_id,
                "action": l.action,
                "message_type_pred": l.message_type_pred,
                "reason": l.reason,
                "confidence": l.confidence,
                "evidence_message_ids": l.evidence_message_ids,
                "latency_ms": l.latency_ms,
                "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "rag_matches": json.loads(l.retrieved_rag) if l.retrieved_rag else [],
                "prompt_compiled": l.prompt_compiled,
            }
        )
    db.close()
    return res


# ----------------- CLIENT SIMULATION API ENDPOINTS -----------------


@app.get("/api/users")
async def get_all_users():
    records = users.replace({np.nan: None}).to_dict(orient="records")
    return records


@app.get("/api/contacts/{user_id}")
async def get_user_contacts(user_id: str):
    hist_df = get_message_history()
    user_hist = hist_df[hist_df["user_id"] == user_id]
    if len(user_hist) == 0:
        msg_df = get_messages()
        user_hist = msg_df[msg_df["user_id"] == user_id]

    contacts = {}

    for _, r in user_hist.iterrows():
        conv_type = r["conversation_type"]

        if conv_type == "group" and pd.notna(r["group_id"]):
            g_id = r["group_id"]
            if g_id not in contacts:
                g_row = groups[groups["group_id"] == g_id]
                g_name = (
                    g_row.iloc[0]["group_name"] if len(g_row) > 0 else f"Group ({g_id})"
                )
                g_type = g_row.iloc[0]["group_type"] if len(g_row) > 0 else "unknown"
                contacts[g_id] = {
                    "id": g_id,
                    "name": g_name,
                    "type": "group",
                    "detail": f"Group Type: {g_type.title()}",
                }
        elif conv_type == "business" and pd.notna(r["business_id"]):
            b_id = r["business_id"]
            if b_id not in contacts:
                b_row = business_accounts[business_accounts["business_id"] == b_id]
                b_name = f"Business ({b_id})"
                if len(b_row) > 0:
                    if "business_name" in b_row.columns:
                        b_name = b_row.iloc[0]["business_name"]
                    elif "brand_name" in b_row.columns:
                        b_name = b_row.iloc[0]["brand_name"]
                b_cat = b_row.iloc[0]["category"] if len(b_row) > 0 else "unknown"
                is_verified = (
                    b_row.iloc[0]["verified"] == 1 if len(b_row) > 0 else False
                )
                contacts[b_id] = {
                    "id": b_id,
                    "name": b_name,
                    "type": "business",
                    "detail": f"{b_cat.replace('_', ' ').title()}{' ✓' if is_verified else ''}",
                }
        elif conv_type == "personal" and pd.notna(r["sender_user_id"]):
            s_id = r["sender_user_id"]
            if s_id not in contacts:
                u_row = users[users["user_id"] == s_id]
                u_name = (
                    u_row.iloc[0]["user_name"] if len(u_row) > 0 else f"User ({s_id})"
                )
                contacts[s_id] = {
                    "id": s_id,
                    "name": u_name,
                    "type": "personal",
                    "detail": f"User ID: {s_id}",
                }

    if not contacts:
        contacts["u_sandbox"] = {
            "id": "u_sandbox",
            "name": "Sandbox Sender",
            "type": "personal",
            "detail": "Test Chat Channel",
        }

    return list(contacts.values())


@app.get("/api/client/messages/{user_id}/{contact_id}")
async def get_client_messages(user_id: str, contact_id: str):
    user_hist = message_history[message_history["user_id"] == user_id]
    context_hist = pd.DataFrame()

    is_group = (
        contact_id.startswith("group_")
        or len(groups[groups["group_id"] == contact_id]) > 0
    )
    is_biz = (
        contact_id.startswith("biz_")
        or len(business_accounts[business_accounts["business_id"] == contact_id]) > 0
    )

    conv_type = "personal"
    if is_group:
        conv_type = "group"
        context_hist = user_hist[user_hist["group_id"] == contact_id]
    elif is_biz:
        conv_type = "business"
        context_hist = user_hist[user_hist["business_id"] == contact_id]
    else:
        conv_type = "personal"
        context_hist = user_hist[user_hist["sender_user_id"] == contact_id]

    msg_list = []

    # Event mapping
    events_subset = message_events[message_events["user_id"] == user_id]
    events_map = events_subset.set_index("message_id").to_dict(orient="index")

    if len(context_hist) > 0:
        context_hist = context_hist.sort_values(by="created_at", ascending=True)
        for _, r in context_hist.iterrows():
            m_id = r["message_id"]
            ev = events_map.get(m_id, {})

            media_path = None
            if pd.notna(r["media_type"]) and pd.notna(r["media_id"]):
                if r["media_type"] == "image":
                    media_path = f"/api/media/image/{r['media_id']}"
                elif r["media_type"] == "voice":
                    media_path = f"/api/media/voice/{r['media_id']}"

            msg_list.append(
                {
                    "message_id": m_id,
                    "created_at": str(r["created_at"]),
                    "message_text": r["message_text"]
                    if pd.notna(r["message_text"])
                    else "",
                    "media_type": r["media_type"]
                    if pd.notna(r["media_type"])
                    else None,
                    "media_path": media_path,
                    "forwarded_count": int(r["forwarded_count"])
                    if pd.notna(r["forwarded_count"])
                    else 0,
                    "direction": "incoming",
                    "reaction": {
                        "opened": int(ev.get("message_opened", 0)),
                        "replied": int(ev.get("message_replied", 0)),
                        "dismissed": int(ev.get("notification_dismissed", 0)),
                        "muted": int(ev.get("muted_after_message", 0)),
                        "reported": int(ev.get("message_reported", 0)),
                    },
                }
            )

    # Include matching web traffic webhook logs
    db = SessionLocal()
    if conv_type == "group":
        db_msgs = (
            db.query(GatewayLog)
            .filter(GatewayLog.user_id == user_id, GatewayLog.group_id == contact_id)
            .all()
        )
    elif conv_type == "business":
        db_msgs = (
            db.query(GatewayLog)
            .filter(GatewayLog.user_id == user_id, GatewayLog.business_id == contact_id)
            .all()
        )
    else:
        db_msgs = (
            db.query(GatewayLog)
            .filter(
                GatewayLog.user_id == user_id, GatewayLog.sender_user_id == contact_id
            )
            .all()
        )

    for m in db_msgs:
        media_path = None
        if m.media_type and m.media_id:
            media_path = f"/api/media/{m.media_type}/{m.media_id}"

        msg_list.append(
            {
                "message_id": m.message_id,
                "created_at": m.timestamp.strftime("%Y-%m-%d %H:%M:%S"),
                "message_text": m.message_text,
                "media_type": m.media_type,
                "media_path": media_path,
                "forwarded_count": 0,
                "direction": "incoming",
                "action": m.action,
                "message_type_pred": m.message_type_pred,
                "reason": m.reason,
                "confidence": m.confidence,
                "is_routed": True,
            }
        )
    db.close()

    msg_list.sort(key=lambda x: x["created_at"])
    return msg_list


@app.get("/api/client/device/{user_id}")
async def get_device_channels(user_id: str):
    db = SessionLocal()
    logs = db.query(GatewayLog).filter(GatewayLog.user_id == user_id).all()
    db.close()

    inbox = []
    digest = []
    quarantine = []

    seen_ids = set()

    for l in logs:
        seen_ids.add(l.message_id)
        msg_obj = {
            "message_id": l.message_id,
            "sender": l.sender_user_id or l.group_id or l.business_id,
            "conversation_type": l.conversation_type,
            "sender_user_id": l.sender_user_id,
            "group_id": l.group_id,
            "text": l.message_text,
            "media_type": l.media_type,
            "action": l.action,
            "type": l.message_type_pred,
            "reason": l.reason,
            "timestamp": l.timestamp.strftime("%H:%M"),
        }
        if l.action == "notify":
            inbox.append(msg_obj)
        elif l.action == "digest":
            digest.append(msg_obj)
        else:
            quarantine.append(msg_obj)

    inbox.sort(key=lambda x: x["message_id"], reverse=True)
    digest.sort(key=lambda x: x["message_id"], reverse=True)
    quarantine.sort(key=lambda x: x["message_id"], reverse=True)

    return {"inbox": inbox, "digest": digest, "quarantine": quarantine}


@app.get("/api/incoming/{user_id}")
async def get_incoming_queue(user_id: str):
    messages_df = get_messages()
    user_incoming = messages_df[messages_df["user_id"] == user_id]
    records = user_incoming.replace({np.nan: None}).to_dict(orient="records")
    return records


# ----------------- MEDIA ROUTING ENDPOINTS -----------------


@app.get("/api/media/image/{media_id}")
async def get_media_image(media_id: str):
    img_row = images[images["image_id"] == media_id]
    if len(img_row) == 0:
        raise HTTPException(status_code=404, detail="Image ID not found in dataset")
    file_name = Path(img_row.iloc[0]["file_path"]).name
    file_path = MEDIA_DIR / "images" / file_name
    if not file_path.exists():
        file_path = FOLDER_DIR / "media" / "images" / file_name
        if not file_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Image file not found: {file_name}"
            )
    return FileResponse(file_path)


@app.get("/api/media/voice/{media_id}")
async def get_media_voice(media_id: str):
    vn_row = voice_notes[voice_notes["voice_note_id"] == media_id]
    if len(vn_row) == 0:
        raise HTTPException(
            status_code=404, detail="Voice note ID not found in dataset"
        )
    file_name = Path(vn_row.iloc[0]["file_path"]).name
    file_path = MEDIA_DIR / "audio" / file_name
    if not file_path.exists():
        file_path = FOLDER_DIR / "media" / "audio" / file_name
        if not file_path.exists():
            raise HTTPException(
                status_code=404, detail=f"Audio file not found: {file_name}"
            )
    return FileResponse(file_path)


# Static files routing redirection
@app.get("/")
async def redirect_to_index():
    return RedirectResponse(url="/static/index.html")


# Create static directory if not exists, and mount StaticFiles
STATIC_DIR = PARENT_DIR / "static"
STATIC_DIR.mkdir(exist_ok=True)
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host="127.0.0.1", port=8000)
