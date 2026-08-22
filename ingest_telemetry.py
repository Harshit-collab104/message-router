import os
import sys
import zipfile
import urllib.request
import pandas as pd
import numpy as np
from pathlib import Path

# Setup paths to import from main.py and vector_store.py
PARENT_DIR = Path(__file__).parent
sys.path.append(str(PARENT_DIR))

from main import FOLDER_DIR
from vector_store import init_db

def download_and_ingest():
    print(f"Active dataset directory detected: {FOLDER_DIR}")
    
    # 1. Download UCI SMS Spam Collection
    url = "https://archive.ics.uci.edu/ml/machine-learning-databases/00228/smsspamcollection.zip"
    zip_path = PARENT_DIR / "smsspamcollection.zip"
    extracted_path = PARENT_DIR / "smsspamcollection"
    
    print(f"Downloading UCI SMS Spam Collection from {url}...")
    try:
        urllib.request.urlretrieve(url, zip_path)
        print("Download complete. Extracting file...")
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extracted_path)
        print("Extraction complete.")
    except Exception as e:
        print(f"Error downloading or extracting dataset: {e}")
        return False
        
    raw_file = extracted_path / "SMSSpamCollection"
    if not raw_file.exists():
        print(f"Error: Raw dataset file not found at {raw_file}")
        return False
        
    # 2. Parse the tab-separated file
    print("Parsing messages...")
    messages_data = []
    with open(raw_file, 'r', encoding='utf-8') as f:
        for line in f:
            parts = line.strip().split('\t')
            if len(parts) == 2:
                messages_data.append({
                    "label": parts[0], # 'spam' or 'ham'
                    "text": parts[1]
                })
                
    print(f"Parsed {len(messages_data)} messages from UCI dataset.")
    
    # Load existing telemetry files to append
    history_csv = FOLDER_DIR / "message_history.csv"
    events_csv = FOLDER_DIR / "message_events.csv"
    users_csv = FOLDER_DIR / "users.csv"
    
    if not history_csv.exists() or not events_csv.exists() or not users_csv.exists():
        print("Error: Target database CSV files do not exist.")
        return False
        
    history_df = pd.read_csv(history_csv)
    events_df = pd.read_csv(events_csv)
    users_df = pd.read_csv(users_csv)
    
    user_ids = users_df['user_id'].tolist()
    if not user_ids:
        user_ids = ['u_001']
        
    print(f"Existing history has {len(history_df)} messages.")
    print(f"Existing events has {len(events_df)} rows.")
    
    new_history = []
    new_events = []
    
    # Keep track of generated spammers and businesses
    spam_senders = [f"spammer_{i:03d}" for i in range(1, 50)]
    ham_senders = [f"u_{i:03d}" for i in range(100, 200)]
    biz_senders = [f"biz_{i:03d}" for i in range(100, 150)]
    
    print("Mapping UCI messages to RAG router format...")
    for idx, msg in enumerate(messages_data):
        msg_id = f"msg_uci_{idx:05d}"
        target_user = user_ids[idx % len(user_ids)] # Distribute messages across target sandbox users
        
        if msg["label"] == "spam":
            # Map spam to business alerts or personal chats from spammers
            is_biz = (idx % 2 == 0)
            conv_type = "business" if is_biz else "personal"
            biz_id = biz_senders[idx % len(biz_senders)] if is_biz else "none"
            sender_id = "none" if is_biz else spam_senders[idx % len(spam_senders)]
            
            new_history.append({
                "message_id": msg_id,
                "user_id": target_user,
                "conversation_type": conv_type,
                "group_id": "none",
                "business_id": biz_id,
                "sender_user_id": sender_id,
                "created_at": "2026-08-01 10:00:00",
                "message_text": msg["text"],
                "media_type": "none",
                "media_id": "none",
                "forwarded_count": int(np.random.choice([0, 1, 3, 6, 12]))
            })
            
            new_events.append({
                "message_id": msg_id,
                "user_id": target_user,
                "message_opened": 0,
                "message_replied": 0,
                "notification_dismissed": int(np.random.choice([0, 1])),
                "muted_after_message": 1,
                "message_reported": 1 # Spam is reported by user
            })
        else:
            # Map ham to casual personal or group chats
            is_group = (idx % 3 == 0)
            conv_type = "group" if is_group else "personal"
            group_id = f"group_{idx % 10:03d}" if is_group else "none"
            sender_id = ham_senders[idx % len(ham_senders)]
            
            new_history.append({
                "message_id": msg_id,
                "user_id": target_user,
                "conversation_type": conv_type,
                "group_id": group_id,
                "business_id": "none",
                "sender_user_id": sender_id,
                "created_at": "2026-08-01 10:00:00",
                "message_text": msg["text"],
                "media_type": "none",
                "media_id": "none",
                "forwarded_count": 0
            })
            
            new_events.append({
                "message_id": msg_id,
                "user_id": target_user,
                "message_opened": 1,
                "message_replied": int(np.random.choice([0, 1])),
                "notification_dismissed": 0,
                "muted_after_message": 0,
                "message_reported": 0 # Legitimate chats are not reported
            })
            
    # Convert to DataFrames and append
    new_history_df = pd.DataFrame(new_history)
    new_events_df = pd.DataFrame(new_events)
    
    updated_history_df = pd.concat([history_df, new_history_df], ignore_index=True)
    updated_events_df = pd.concat([events_df, new_events_df], ignore_index=True)
    
    # Write back to CSVs
    print(f"Writing {len(updated_history_df)} total records back to {history_csv}...")
    updated_history_df.to_csv(history_csv, index=False)
    updated_events_df.to_csv(events_csv, index=False)
    print("Files written successfully.")
    
    # Clean up zip files
    try:
        if zip_path.exists():
            os.remove(zip_path)
        import shutil
        if extracted_path.exists():
            shutil.rmtree(extracted_path)
        print("Cleaned up temporary download folders.")
    except Exception as cleanup_err:
        print(f"Warning: Cleanup failed: {cleanup_err}")
        
    # 3. Rebuild ChromaDB persistent database with the full dataset
    print("Rebuilding ChromaDB index with the newly ingested telemetry data...")
    init_db(history_csv, force_rebuild=True)
    print("Telemetry ingestion and database re-indexing complete!")
    return True

if __name__ == "__main__":
    download_and_ingest()
