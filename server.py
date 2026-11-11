import datetime
import base64
import hashlib
import hmac
import json
import math
import os
import sys
import time
from pathlib import Path
from urllib.parse import parse_qs

import numpy as np
import pandas as pd
import httpx
import sqlalchemy
from fastapi import Body, Depends, FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import Column, DateTime, Float, Integer, String, Text, create_engine
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.exc import IntegrityError

# Setup path to import from main.py and vector_store.py
PARENT_DIR = Path(__file__).parent
sys.path.append(str(PARENT_DIR))

from main import (
    FOLDER_DIR,
    MEDIA_DIR,
    business_accounts,
    compile_prompt,
    get_message_history,
    get_message_events,
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
    routing_flags,
    apply_routing_policy,
    validate_routing_result,
    groq_completion,
    get_routing_local_history,
)
from dataset_store import GATEWAY_DB_PATH, DATA_DIR, OFFLINE, DatasetError, inspect_dataset
from vector_store import get_client as get_chroma_client
from vector_store import retrieve_relevant_history

async def require_gateway_token(request: Request):
    """The developer console/admin API has one explicit owner credential."""
    if not request.url.path.startswith('/api/') or request.url.path in {
        '/api/webhook/whatsapp', '/api/webhook/twilio-whatsapp'}:
        return  # Provider endpoints authenticate their own signed requests.
    expected = os.environ.get('GATEWAY_API_TOKEN')
    if not expected:
        raise HTTPException(status_code=503, detail='GATEWAY_API_TOKEN is not configured')
    supplied = request.headers.get('authorization', '')
    scheme, _, token = supplied.partition(' ')
    if scheme.lower() != 'bearer' or not hmac.compare_digest(token.encode(), expected.encode()):
        raise HTTPException(status_code=401, detail='Invalid gateway credential',
                            headers={'WWW-Authenticate': 'Bearer'})


app = FastAPI(title="Message Routing Middleware Gateway", dependencies=[Depends(require_gateway_token)])

# Allow CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in os.environ.get('GATEWAY_CORS_ORIGINS', '').split(',') if origin.strip()],
    allow_credentials=False,
    allow_methods=["GET", "POST"],
    allow_headers=["Authorization", "Content-Type"],
)

# SQLite Database Setup (Self-contained in msg_router directory)
DB_PATH = GATEWAY_DB_PATH
DB_PATH.parent.mkdir(parents=True, exist_ok=True)
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
    digest_delivered = Column(Integer, default=0, index=True)


class GatewayReceipt(Base):
    """Additive receipt/claim table; no rewriting historical gateway logs."""
    __tablename__ = 'gateway_receipts'
    id = Column(String, primary_key=True)
    response = Column(Text, nullable=True)


Base.metadata.create_all(bind=engine)

# Safe migration check for existing SQLite databases
with engine.connect() as conn:
    try:
        if 'digest_delivered' not in {column['name'] for column in sqlalchemy.inspect(engine).get_columns('gateway_logs')}:
            conn.execute(sqlalchemy.text('ALTER TABLE gateway_logs ADD COLUMN digest_delivered INTEGER DEFAULT 0'))
        conn.execute(sqlalchemy.text('CREATE INDEX IF NOT EXISTS ix_gateway_logs_digest_delivered ON gateway_logs (digest_delivered)'))
        conn.commit()
    except Exception:
        conn.rollback()
        raise

# Active Gateway Configuration State
gemini_key = None if OFFLINE else os.environ.get("GEMINI_API_KEY")
groq_key = None if OFFLINE else os.environ.get("GROQ_API_KEY")

CONFIG = {
    "offline_mode": OFFLINE,
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
    candidate = dict(CONFIG)
    if 'active_model' in new_config:
        model = new_config['active_model']
        if OFFLINE and model != 'heuristic':
            raise HTTPException(400, 'LLM engines are disabled in offline mode')
        if model not in {'heuristic', 'gemini', 'groq'}:
            raise HTTPException(400, 'Unknown active_model')
        if model == 'gemini' and not gemini_client:
            raise HTTPException(400, 'GEMINI_API_KEY is not configured')
        if model == 'groq' and not groq_key:
            raise HTTPException(400, 'GROQ_API_KEY is not configured')
        candidate['active_model'] = model
    if 'l2_distance_threshold' in new_config:
        value = new_config['l2_distance_threshold']
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or not 0 <= value <= 2:
            raise HTTPException(400, 'l2_distance_threshold must be a finite number between 0 and 2')
        candidate['l2_distance_threshold'] = float(value)
    if 'dnd_enabled' in new_config:
        if not isinstance(new_config['dnd_enabled'], bool):
            raise HTTPException(400, 'dnd_enabled must be a boolean')
        candidate['dnd_enabled'] = new_config['dnd_enabled']
    CONFIG.update(candidate)
    return CONFIG


def claim_receipt(key):
    try:
        with SessionLocal.begin() as db:
            db.add(GatewayReceipt(id=key))
            db.flush()
    except IntegrityError:
        with SessionLocal() as db:
            receipt = db.get(GatewayReceipt, key)
            if receipt is not None and receipt.response is not None:
                response = json.loads(receipt.response)
                response['duplicate'] = True
                return response
        raise HTTPException(409, 'An operation with this identifier is already in progress')
    return None


def release_receipt(key):
    with SessionLocal.begin() as db:
        db.query(GatewayReceipt).filter_by(id=key).delete()


def validate_message(payload):
    for field in ('message_id', 'user_id', 'conversation_type'):
        if not isinstance(payload.get(field), str) or not payload[field].strip():
            raise HTTPException(400, f'Missing or invalid {field}')
    if payload['conversation_type'] not in {'personal', 'group', 'business'}:
        raise HTTPException(400, 'Unknown conversation_type')
    if not isinstance(payload.get('message_text', ''), str):
        raise HTTPException(400, 'message_text must be a string')
    count = payload.get('forwarded_count', 0)
    if isinstance(count, bool) or not isinstance(count, int) or count < 0:
        raise HTTPException(400, 'forwarded_count must be a non-negative integer')
    for field in ('sender_user_id', 'group_id', 'business_id', 'media_type', 'media_id'):
        if payload.get(field) is not None and not isinstance(payload[field], str):
            raise HTTPException(400, f'{field} must be a string or null')


async def route_incoming_message(payload: dict, *, source: str = 'internal') -> dict:
    validate_message(payload)
    key = json.dumps(['message', source, payload['user_id'], payload['message_id']], separators=(',', ':'))
    cached = claim_receipt(key)
    if cached is not None:
        return cached
    try:
        return await _route_new_message(payload, receipt_key=key, source=source)
    except Exception:
        with SessionLocal() as db:
            receipt = db.get(GatewayReceipt, key)
            completed = receipt is not None and receipt.response is not None
        if not completed:
            release_receipt(key)
        raise


async def _route_new_message(payload: dict, *, receipt_key=None, source='internal') -> dict:
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
    if not OFFLINE and message_text and message_text.strip() != "":
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

    row_dict['_excluded_history_ids'] = {str(item['message_id']) for item in retrieved if item['distance'] > CONFIG['l2_distance_threshold']}
    row_dict['_retrieved_history'] = filtered_retrieved
    row_dict['_dnd_enabled'] = CONFIG['dnd_enabled']
    row_series = pd.Series(row_dict)

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
        if routing_flags(row_series)['is_scam']:
            action, message_type_pred, reason, confidence, evidence = apply_routing_policy(
                ('digest', 'unknown', '', 0.75, 'none'), row_series)
            model_used = 'policy'
        elif model_used == "gemini" and gemini_client:
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
        action, message_type_pred, reason, confidence, evidence = validate_routing_result(
            (action, message_type_pred, reason, confidence, evidence))
        model_used = row_series.get('_model_used', model_used)
    except Exception as pipe_err:
        print(
            f"Error executing {model_used} pipeline: {pipe_err}. Falling back to heuristics."
        )
        action, message_type_pred, reason, confidence, evidence = predict_heuristic(
            row_series
        )
        model_used = "heuristic (fallback)"

    action, message_type_pred, reason, confidence, evidence = apply_routing_policy(
        (action, message_type_pred, reason, confidence, evidence), row_series)
    allowed_ids = {str(item['message_id']) for item in filtered_retrieved}
    local_history = get_routing_local_history(row_series)
    allowed_ids.update(local_history.loc[local_history['user_id'] == user_id, 'message_id'].astype(str))
    evidence = ';'.join(identifier for identifier in evidence.split(';') if identifier in allowed_ids) or 'none'

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
        digest_delivered=0,
    )
    try:
        db.add(log_entry)
        db.flush()
        response = {
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
        response['duplicate'] = False
        if receipt_key is not None:
            db.get(GatewayReceipt, receipt_key).response = json.dumps(response)
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()

    # 5. Index new message text in ChromaDB for immediate memory updates
    if not OFFLINE and message_text and message_text.strip() != "":
        try:
            chroma_client = get_chroma_client()
            collection = chroma_client.get_or_create_collection(name="message_history")
            collection.add(
                ids=[json.dumps([source, str(user_id), str(message_id)], separators=(',', ':'))],
                documents=[message_text],
                metadatas=[
                    {
                        "source": source,
                        "message_id": str(message_id),
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

    return response


@app.post("/api/gateway/webhook")
async def receive_webhook_message(payload: dict = Body(...)):
    return await route_incoming_message(payload)


# ----------------- WHATSAPP CLOUD API & TWILIO WEBHOOKS -----------------


async def send_whatsapp_message(recipient_phone: str, text: str) -> dict:
    """Dispatches outbound text message to a WhatsApp user using Meta Cloud API."""
    if OFFLINE:
        return {'status': 'skipped', 'reason': 'Outbound delivery is disabled in offline mode'}
    token = os.environ.get("WHATSAPP_TOKEN")
    phone_id = os.environ.get("WHATSAPP_PHONE_NUMBER_ID")

    if not token or not phone_id:
        return {
            "status": "skipped",
            "reason": "WHATSAPP_TOKEN or WHATSAPP_PHONE_NUMBER_ID not configured",
        }

    url = f"https://graph.facebook.com/v20.0/{phone_id}/messages"
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }
    payload = {
        "messaging_product": "whatsapp",
        "to": recipient_phone,
        "type": "text",
        "text": {"body": text},
    }
    try:
        async with httpx.AsyncClient() as client:
            resp = await client.post(url, json=payload, headers=headers, timeout=10.0)
            if not 200 <= resp.status_code < 300:
                return {'status': 'error', 'detail': f'WhatsApp HTTP {resp.status_code}'}
            data = resp.json()
            if not isinstance(data, dict) or not data.get('messages') or not data['messages'][0].get('id'):
                return {'status': 'error', 'detail': 'WhatsApp did not acknowledge a message'}
            return {**data, 'status': 'dispatched'}
    except Exception as err:
        return {"status": "error", "detail": str(err)}


@app.get("/api/webhook/whatsapp")
async def verify_whatsapp_webhook(request: Request):
    """Meta WhatsApp Webhook verification handshake."""
    params = request.query_params
    mode = params.get("hub.mode")
    token = params.get("hub.verify_token")
    challenge = params.get("hub.challenge")

    verify_token = os.environ.get("WHATSAPP_VERIFY_TOKEN")
    if not verify_token:
        raise HTTPException(503, 'WHATSAPP_VERIFY_TOKEN is not configured')

    if mode == "subscribe" and token and hmac.compare_digest(token.encode(), verify_token.encode()):
        return Response(content=challenge or "", media_type="text/plain", status_code=200)
    return Response(content="Verification failed", status_code=403)


@app.post("/api/webhook/whatsapp")
async def receive_whatsapp_message(request: Request):
    """Handles incoming Meta WhatsApp events, parses messages, and routes through gateway."""
    secret = os.environ.get('WHATSAPP_APP_SECRET')
    if not secret:
        raise HTTPException(503, 'WHATSAPP_APP_SECRET is not configured')
    raw = await request.body()
    expected = 'sha256=' + hmac.new(secret.encode(), raw, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get('x-hub-signature-256', '').encode(), expected.encode()):
        raise HTTPException(403, 'Invalid Meta signature')
    try:
        body = json.loads(raw)
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Invalid JSON payload"})

    if not isinstance(body, dict) or not isinstance(body.get('entry', []), list):
        raise HTTPException(400, 'Invalid Meta event structure')
    entries = body.get("entry", [])
    routed_messages = []
    errors = []

    for entry in entries:
        for change in entry.get("changes", []):
            val = change.get("value", {})

            # Status updates (sent, delivered, read) - acknowledge and skip
            if "statuses" in val and "messages" not in val:
                continue

            messages = val.get("messages", [])
            for msg in messages:
                from_phone = msg.get("from", "unknown")
                msg_id = msg.get("id", f"wa_{int(time.time() * 1000)}")
                msg_type = msg.get("type", "text")

                media_type = None
                media_id = None
                message_text = ""

                if msg_type == "text":
                    message_text = msg.get("text", {}).get("body", "")
                elif msg_type == "image":
                    message_text = msg.get("image", {}).get("caption", "[Image Attachment]")
                    media_type = "image"
                    media_id = msg.get("image", {}).get("id")
                elif msg_type in ("audio", "voice"):
                    message_text = "[Voice Note / Audio Attachment]"
                    media_type = "audio"
                    media_id = msg.get(msg_type, {}).get("id")
                elif msg_type == "document":
                    message_text = (
                        msg.get("document", {}).get("caption")
                        or msg.get("document", {}).get("filename", "[Document Attachment]")
                    )
                    media_type = "document"
                    media_id = msg.get("document", {}).get("id")
                elif msg_type == "interactive":
                    interactive = msg.get("interactive", {})
                    itype = interactive.get("type")
                    if itype == "button_reply":
                        message_text = interactive.get("button_reply", {}).get("title", "[Button Reply]")
                    elif itype == "list_reply":
                        message_text = interactive.get("list_reply", {}).get("title", "[List Reply]")
                    else:
                        message_text = "[Interactive Response]"
                else:
                    message_text = f"[{msg_type} message]"

                router_payload = {
                    "message_id": msg_id,
                    "user_id": from_phone,
                    "conversation_type": "business",
                    "sender_user_id": from_phone,
                    "group_id": "none",
                    "business_id": "whatsapp_gateway",
                    "message_text": message_text,
                    "media_type": media_type,
                    "media_id": media_id,
                    "forwarded_count": 0,
                }

                try:
                    result = await route_incoming_message(router_payload, source='meta')
                    routed_messages.append(result)

                    # Optional auto-reply when enabled
                    if os.environ.get("WHATSAPP_AUTO_REPLY", "false").lower() == "true" and result["action"] == "notify" and not result["duplicate"]:
                        reply_text = f"Gateway: [{result['action'].upper()}] - {result['reason']}"
                        await send_whatsapp_message(from_phone, reply_text)
                except Exception as route_err:
                    errors.append({"message_id": msg_id, "error": "Routing failed; retry this event"})

    response = {'status': 'partial_failure' if errors else 'success',
                'processed_count': len(routed_messages), 'results': routed_messages}
    if errors:
        return JSONResponse(status_code=503, content={**response, 'errors': errors})
    return response


@app.post("/api/webhook/twilio-whatsapp")
async def receive_twilio_whatsapp(request: Request):
    """Handles incoming Twilio WhatsApp sandbox/production webhook."""
    raw_body = (await request.body()).decode("utf-8")
    parsed = parse_qs(raw_body, keep_blank_values=True)
    token = os.environ.get('TWILIO_AUTH_TOKEN')
    if not token:
        raise HTTPException(503, 'TWILIO_AUTH_TOKEN is not configured')
    url = os.environ.get('TWILIO_WEBHOOK_URL') or str(request.url)
    signed = url + ''.join(key + value for key in sorted(parsed) for value in sorted(set(parsed[key])))
    expected = base64.b64encode(hmac.new(token.encode(), signed.encode(), hashlib.sha1).digest()).decode()
    if not hmac.compare_digest(request.headers.get('x-twilio-signature', '').encode(), expected.encode()):
        raise HTTPException(403, 'Invalid Twilio signature')
    from_number = parsed.get("From", [""])[0]
    body = parsed.get("Body", [""])[0]
    msg_id = parsed.get("MessageSid", [f"tw_{int(time.time() * 1000)}"])[0]
    sender = from_number.replace("whatsapp:", "") if from_number else "unknown"

    router_payload = {
        "message_id": msg_id,
        "user_id": sender,
        "conversation_type": "business",
        "sender_user_id": sender,
        "group_id": "none",
        "business_id": "twilio_whatsapp",
        "message_text": body,
        "media_type": None,
        "media_id": None,
        "forwarded_count": 0,
    }

    result = await route_incoming_message(router_payload, source='twilio')
    return Response(content="<Response></Response>", media_type="application/xml")


# ----------------- DIGEST SUMMARIZER & DELIVERY -----------------


def generate_digest_summary_text(messages_data: list) -> str:
    """Generates a 2-3 bullet point executive summary from a list of message dictionaries.

    Uses Gemini or Groq if configured, otherwise falls back to a structured rule-based digest.
    """
    if not messages_data:
        return "No pending messages in your digest."

    bullet_items = []
    for m in messages_data:
        sender = (
            m.get("sender_user_id")
            or m.get("business_id")
            or m.get("group_id")
            or "Unknown"
        )
        text = (m.get("message_text") or "").strip()
        bullet_items.append(f"- From [{sender}]: {text}")

    messages_block = "\n".join(bullet_items)

    prompt = (
        "You are an intelligent notification assistant. The user has received the following "
        "low-priority or quiet-hour notifications while away:\n\n"
        f"{messages_block}\n\n"
        "Provide a concise, 2-3 bullet point summary highlighting what happened. "
        "Do not include preamble. Format strictly as short, readable bullet points."
    )

    # 1. Try Gemini
    if gemini_client and CONFIG["active_model"] == "gemini":
        try:
            response = gemini_client.models.generate_content(
                model=CONFIG.get("gemini_model", "gemini-2.5-flash"),
                contents=prompt,
            )
            if response and response.text:
                return response.text.strip()
        except Exception as e:
            print(f"Gemini digest generation failed: {e}")

    if groq_key and CONFIG['active_model'] in {'gemini', 'groq'}:
        try:
            return groq_completion(prompt, model_name=CONFIG['groq_model'], json_mode=False)
        except Exception as error:
            print(f'Groq digest generation failed: {error}')

    # 3. Rule-based structured fallback (Zero external dependencies)
    total_count = len(messages_data)
    senders = list(
        set(
            [
                m.get("sender_user_id") or m.get("business_id") or "various senders"
                for m in messages_data
            ]
        )
    )
    categories = list(
        set([m.get("message_type_pred") or "general" for m in messages_data])
    )

    preview_lines = [f"• Received {total_count} updates from {', '.join(senders[:3])}."]
    preview_lines.append(f"• Categories include: {', '.join(categories[:3])}.")
    if len(messages_data) > 0:
        first_preview = (messages_data[-1].get("message_text") or "")[:60]
        preview_lines.append(f'• Latest: "{first_preview}..."')
    return "\n".join(preview_lines)


async def process_user_digest(user_id: str, auto_send: bool = False) -> dict:
    """Preview without consuming; mark accepted only after successful dispatch."""
    key = json.dumps(['digest', user_id])
    if auto_send:
        claim_receipt(key)
    try:
        with SessionLocal() as db:
            pending = db.query(GatewayLog).filter(
                GatewayLog.user_id == user_id, GatewayLog.action == 'digest',
                GatewayLog.digest_delivered == 0).order_by(GatewayLog.id.asc()).all()
            messages_data = [{
                'id': log.id, 'message_id': log.message_id, 'sender_user_id': log.sender_user_id,
                'business_id': log.business_id, 'group_id': log.group_id,
                'message_text': log.message_text, 'message_type_pred': log.message_type_pred,
            } for log in pending]
        if not messages_data:
            return {'status': 'empty', 'user_id': user_id, 'message_count': 0, 'summary': 'No pending digest items.'}
        summary = generate_digest_summary_text(messages_data)
        dispatch = 'skipped'
        if auto_send:
            try:
                response = await send_whatsapp_message(user_id, f'Your Notification Digest:\n\n{summary}')
                dispatch = response.get('status', 'error')
            except Exception:
                dispatch = 'error'
            if dispatch == 'dispatched':
                with SessionLocal.begin() as db:
                    db.query(GatewayLog).filter(GatewayLog.id.in_([item['id'] for item in messages_data])).update(
                        {'digest_delivered': 1}, synchronize_session=False)
        return {'status': 'success' if not auto_send or dispatch == 'dispatched' else dispatch,
                'user_id': user_id, 'message_count': len(messages_data), 'summary': summary,
                'message_ids': [item['message_id'] for item in messages_data], 'dispatch': dispatch}
    finally:
        if auto_send:
            release_receipt(key)


@app.get("/api/digest/pending/{user_id}")
async def get_pending_digest(user_id: str):
    """Returns list of pending, un-dispatched digest messages for a user."""
    db = SessionLocal()
    pending = (
        db.query(GatewayLog)
        .filter(
            GatewayLog.user_id == user_id,
            GatewayLog.action == "digest",
            GatewayLog.digest_delivered == 0,
        )
        .order_by(GatewayLog.id.asc())
        .all()
    )
    db.close()

    results = [
        {
            "id": l.id,
            "message_id": l.message_id,
            "sender": l.sender_user_id or l.business_id or l.group_id or "unknown",
            "text": l.message_text,
            "type": l.message_type_pred,
            "reason": l.reason,
            "timestamp": l.timestamp.strftime("%Y-%m-%d %H:%M:%S")
            if l.timestamp
            else "",
        }
        for l in pending
    ]
    return {"user_id": user_id, "pending_count": len(results), "messages": results}


@app.post("/api/digest/generate/{user_id}")
async def generate_user_digest(user_id: str, auto_send: bool = False):
    """Preview a digest, or dispatch it and mark provider-accepted messages."""
    result = await process_user_digest(user_id=user_id, auto_send=auto_send)
    return result


@app.post("/api/digest/dispatch-all")
async def dispatch_all_pending_digests(auto_send: bool = False):
    """Finds all distinct users with pending digest notifications and processes them in batch."""
    db = SessionLocal()
    user_rows = (
        db.query(GatewayLog.user_id)
        .filter(
            GatewayLog.action == "digest",
            GatewayLog.digest_delivered == 0,
        )
        .distinct()
        .all()
    )
    db.close()

    user_ids = [r[0] for r in user_rows if r[0]]
    dispatched = []

    for uid in user_ids:
        res = await process_user_digest(user_id=uid, auto_send=auto_send)
        dispatched.append(res)

    return {
        "status": "success" if all(item["status"] in {"success", "empty"} for item in dispatched) else "partial_failure",
        "users_processed_count": len(dispatched),
        "results": dispatched,
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


@app.exception_handler(DatasetError)
async def dataset_error_handler(request: Request, error: DatasetError):
    return JSONResponse(status_code=503, content={'code': 'dataset_invalid', 'detail': str(error)})


@app.get('/api/dataset/status')
async def get_dataset_status():
    return inspect_dataset(DATA_DIR)


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
    history = get_message_history()
    user_hist = history[history["user_id"] == user_id]
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
    events = get_message_events()
    events_subset = events[events["user_id"] == user_id]
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
