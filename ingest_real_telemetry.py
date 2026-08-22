import os
import sys
import zipfile
import json
import urllib.request
import pandas as pd
import numpy as np
from pathlib import Path

# Setup paths to import from main.py and vector_store.py
PARENT_DIR = Path(__file__).parent
sys.path.append(str(PARENT_DIR))

from main import FOLDER_DIR
from vector_store import init_db

def download_file(url, target_path):
    print(f"Downloading {url} to {target_path}...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req) as response, open(target_path, 'wb') as out_file:
        out_file.write(response.read())
    print("Download finished.")

def parse_dailydialog(extracted_dir):
    """
    Parses DailyDialog dialogues_text.txt file where turns are split by __eou__.
    """
    dialogues_file = extracted_dir / "ijcnlp_dailydialog" / "dialogues_text.txt"
    if not dialogues_file.exists():
        # Search recursively for dialogues_text.txt if directory structure varies
        found = list(extracted_dir.glob("**/dialogues_text.txt"))
        if found:
            dialogues_file = found[0]
        else:
            print("Warning: dialogues_text.txt not found in extracted zip.")
            return []
            
    print(f"Parsing DailyDialog conversations from {dialogues_file}...")
    dialogues = []
    with open(dialogues_file, 'r', encoding='utf-8') as f:
        for line in f:
            turns = [t.strip() for t in line.strip().split("__eou__") if t.strip()]
            if turns:
                dialogues.append(turns)
    return dialogues

def parse_sgd_json(json_path):
    """
    Parses Google's Schema-Guided Dialogue JSON structure to extract messages and user interactions.
    """
    print(f"Parsing Schema-Guided Dialogue transactional updates from {json_path}...")
    with open(json_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
        
    dialogues = []
    for item in data:
        turns = []
        for turn in item.get("turns", []):
            utterance = turn.get("utterance", "").strip()
            speaker = turn.get("speaker", "").lower() # 'user' or 'system'
            if utterance:
                turns.append((speaker, utterance))
        if turns:
            dialogues.append(turns)
    return dialogues

def ingest_real_telemetry():
    print(f"Active dataset directory detected: {FOLDER_DIR}")
    
    # 1. Download DailyDialog ZIP (Personal/Group Conversations)
    dd_url = "http://yanran.li/files/ijcnlp_dailydialog.zip"
    dd_zip_path = PARENT_DIR / "dailydialog.zip"
    dd_extracted_dir = PARENT_DIR / "dailydialog_extracted"
    
    try:
        download_file(dd_url, dd_zip_path)
        print("Extracting DailyDialog zip...")
        with zipfile.ZipFile(dd_zip_path, 'r') as zip_ref:
            zip_ref.extractall(dd_extracted_dir)
        dd_conversations = parse_dailydialog(dd_extracted_dir)
        print(f"Successfully loaded {len(dd_conversations)} DailyDialog chats.")
    except Exception as e:
        print(f"Error downloading/parsing DailyDialog: {e}. Falling back to default list.")
        dd_conversations = []

    # 2. Download Schema-Guided Dialogue (SGD) transactional logs
    sgd_url = "https://raw.githubusercontent.com/google-research-datasets/dstc8-schema-guided-dialogue/master/train/dialogues_001.json"
    sgd_json_path = PARENT_DIR / "sgd_dialogues_001.json"
    
    try:
        download_file(sgd_url, sgd_json_path)
        sgd_conversations = parse_sgd_json(sgd_json_path)
        print(f"Successfully loaded {len(sgd_conversations)} Schema-Guided Dialogue transactions.")
    except Exception as e:
        print(f"Error downloading/parsing SGD: {e}.")
        sgd_conversations = []
        
    # Read existing target datasets
    history_csv = FOLDER_DIR / "message_history.csv"
    events_csv = FOLDER_DIR / "message_events.csv"
    users_csv = FOLDER_DIR / "users.csv"
    
    history_df = pd.read_csv(history_csv)
    events_df = pd.read_csv(events_csv)
    users_df = pd.read_csv(users_csv)
    user_ids = users_df['user_id'].tolist()
    if not user_ids:
        user_ids = ['u_001']
        
    new_history = []
    new_events = []
    
    # Map DailyDialog (Personal & Group Chats)
    print("Mapping DailyDialog personal/group dialogues to RAG formats...")
    # Limit to 800 conversations to keep index size balanced
    for idx, turns in enumerate(dd_conversations[:800]):
        target_user = user_ids[idx % len(user_ids)]
        for turn_idx, text in enumerate(turns[:6]):
            msg_id = f"msg_dd_real_{idx:04d}_{turn_idx:02d}"
            conv_type = "personal" if turn_idx % 2 == 0 else "group"
            group_id = f"group_{(idx % 8) + 1:03d}" if conv_type == "group" else "none"
            sender_id = f"u_{(idx % 30) + 10:03d}"
            
            new_history.append({
                "message_id": msg_id, "user_id": target_user, "conversation_type": conv_type,
                "group_id": group_id, "business_id": "none", "sender_user_id": sender_id,
                "created_at": "2026-08-01 12:00:00", "message_text": text,
                "media_type": "none", "media_id": "none", "forwarded_count": 0
            })
            # Safe conversation events
            new_events.append({
                "message_id": msg_id, "user_id": target_user,
                "message_opened": 1, "message_replied": int(np.random.choice([0, 1])),
                "notification_dismissed": 0, "muted_after_message": 0, "message_reported": 0
            })
            
    # Map SGD (Business Transactional Updates)
    print("Mapping SGD business transactions to RAG formats...")
    for idx, turns in enumerate(sgd_conversations[:800]):
        target_user = user_ids[idx % len(user_ids)]
        biz_id = f"biz_{(idx % 25) + 1:03d}"
        for turn_idx, (speaker, text) in enumerate(turns[:4]):
            msg_id = f"msg_sgd_real_{idx:04d}_{turn_idx:02d}"
            conv_type = "business"
            
            # Map system messages to transactional logs (Airtel, Uber, bank-like notifications)
            new_history.append({
                "message_id": msg_id, "user_id": target_user, "conversation_type": conv_type,
                "group_id": "none", "business_id": biz_id, "sender_user_id": "none",
                "created_at": "2026-08-01 14:00:00", "message_text": text,
                "media_type": "none", "media_id": "none", "forwarded_count": 0
            })
            
            # Transaction notifications are usually opened but rarely replied to
            new_events.append({
                "message_id": msg_id, "user_id": target_user,
                "message_opened": 1, "message_replied": 0,
                "notification_dismissed": int(np.random.choice([0, 1])),
                "muted_after_message": 0, "message_reported": 0
            })
            
    if new_history:
        new_hist_df = pd.DataFrame(new_history)
        new_event_df = pd.DataFrame(new_events)
        
        # Concat and update csv files
        updated_hist = pd.concat([history_df, new_hist_df], ignore_index=True)
        updated_events = pd.concat([events_df, new_event_df], ignore_index=True)
        
        print(f"Writing updated history ({len(updated_hist)} rows) and events to CSV files...")
        updated_hist.to_csv(history_csv, index=False)
        updated_events.to_csv(events_csv, index=False)
        
    # Clean up downloads
    for p in [dd_zip_path, sgd_json_path]:
        try:
            if p.exists():
                os.remove(p)
        except Exception:
            pass
    import shutil
    try:
        if dd_extracted_dir.exists():
            shutil.rmtree(dd_extracted_dir)
    except Exception:
        pass
        
    # 3. Rebuild ChromaDB persistent database with the full dataset and merged reactions metadata
    print("Rebuilding ChromaDB index with the newly ingested telemetry data and reaction variables...")
    init_db(history_csv, force_rebuild=True)
    print("Telemetry ingestion and database re-indexing complete!")

if __name__ == "__main__":
    ingest_real_telemetry()
