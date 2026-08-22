import os
import sys
import pandas as pd
from pathlib import Path

# Setup paths
PARENT_DIR = Path(__file__).parent
sys.path.append(str(PARENT_DIR))

from main import FOLDER_DIR
from vector_store import init_db

def load_daily_dialog_via_api():
    """
    Example of pulling personal/group chat conversations using the HuggingFace datasets API.
    Requirements: pip install datasets
    """
    try:
        from datasets import load_dataset
        print("Fetching DailyDialog dataset from HuggingFace...")
        # Split can be 'train', 'validation', or 'test'
        dataset = load_dataset("daily_dialog", split="train", trust_remote_code=True)
        print(f"Downloaded DailyDialog. Found {len(dataset)} conversation logs.")
        
        mapped_logs = []
        # Take a subset of 1000 conversations for indexing
        for idx in range(min(1000, len(dataset))):
            dialog = dataset[idx]["dialog"]
            target_user = f"u_{(idx % 10) + 1:03d}"
            
            for turn_idx, text in enumerate(dialog):
                msg_id = f"msg_dd_{idx:04d}_{turn_idx:02d}"
                conv_type = "personal" if turn_idx % 2 == 0 else "group"
                group_id = f"group_{(idx % 5) + 1:03d}" if conv_type == "group" else "none"
                sender_id = f"u_{(idx % 20) + 5:03d}"
                
                mapped_logs.append({
                    "message_id": msg_id,
                    "user_id": target_user,
                    "conversation_type": conv_type,
                    "group_id": group_id,
                    "business_id": "none",
                    "sender_user_id": sender_id,
                    "created_at": "2026-08-01 12:00:00",
                    "message_text": text,
                    "media_type": "none",
                    "media_id": "none",
                    "forwarded_count": 0,
                    # Event mappings
                    "message_opened": 1,
                    "message_replied": 1 if turn_idx % 2 == 0 else 0,
                    "notification_dismissed": 0,
                    "muted_after_message": 0,
                    "message_reported": 0
                })
        return mapped_logs
    except Exception as e:
        print(f"HuggingFace datasets library not available or error occurred: {e}")
        print("Falling back to local simulation...")
        return None

def generate_synthetic_business_updates():
    """
    Generates high-fidelity transactional business updates when raw data is not provided.
    """
    templates = [
        "Your order #{num} has been shipped via DHL. Track here: http://dhl.com/track/{num}",
        "Flight {num} to Delhi is delayed by 45 minutes. Boarding begins at Gate B{num}.",
        "A debit of $55.00 occurred on your card ending {num} at StarBucks.",
        "Airtel recharge successful. Account credit: $10.00. Plan active till next month.",
        "Your table reservation for 4 at Olive Bistro is confirmed for tonight at 8 PM."
    ]
    
    mapped_logs = []
    print("Generating synthetic transactional updates...")
    for idx in range(500):
        template = templates[idx % len(templates)]
        num_var = idx * 17
        text = template.replace("{num}", str(num_var))
        target_user = f"u_{(idx % 10) + 1:03d}"
        biz_id = f"biz_{(idx % 15) + 1:03d}"
        msg_id = f"msg_biz_synth_{idx:04d}"
        
        mapped_logs.append({
            "message_id": msg_id,
            "user_id": target_user,
            "conversation_type": "business",
            "group_id": "none",
            "business_id": biz_id,
            "sender_user_id": "none",
            "created_at": "2026-08-01 14:00:00",
            "message_text": text,
            "media_type": "none",
            "media_id": "none",
            "forwarded_count": 0,
            # Transactional alerts are opened, but rarely replied to by the user
            "message_opened": 1,
            "message_replied": 0,
            "notification_dismissed": 0,
            "muted_after_message": 0,
            "message_reported": 0
        })
    return mapped_logs

def run_expansion():
    # 1. Try fetching DailyDialog (Casual Chats)
    dd_logs = load_daily_dialog_via_api()
    
    # 2. Generate Transactional Business updates
    biz_logs = generate_synthetic_business_updates()
    
    all_new_logs = []
    if dd_logs:
        all_new_logs.extend(dd_logs)
    all_new_logs.extend(biz_logs)
    
    if not all_new_logs:
        print("No new logs gathered. Expansion aborted.")
        return
        
    # Append to existing database
    history_csv = FOLDER_DIR / "message_history.csv"
    events_csv = FOLDER_DIR / "message_events.csv"
    
    history_df = pd.read_csv(history_csv)
    events_df = pd.read_csv(events_csv)
    
    new_hist_rows = []
    new_event_rows = []
    
    for log in all_new_logs:
        new_hist_rows.append({
            "message_id": log["message_id"],
            "user_id": log["user_id"],
            "conversation_type": log["conversation_type"],
            "group_id": log["group_id"],
            "business_id": log["business_id"],
            "sender_user_id": log["sender_user_id"],
            "created_at": log["created_at"],
            "message_text": log["message_text"],
            "media_type": log["media_type"],
            "media_id": log["media_id"],
            "forwarded_count": log["forwarded_count"]
        })
        new_event_rows.append({
            "message_id": log["message_id"],
            "user_id": log["user_id"],
            "message_opened": log["message_opened"],
            "message_replied": log["message_replied"],
            "notification_dismissed": log["notification_dismissed"],
            "muted_after_message": log["muted_after_message"],
            "message_reported": log["message_reported"]
        })
        
    new_hist_df = pd.DataFrame(new_hist_rows)
    new_event_df = pd.DataFrame(new_event_rows)
    
    updated_hist = pd.concat([history_df, new_hist_df], ignore_index=True)
    updated_events = pd.concat([events_df, new_event_df], ignore_index=True)
    
    print(f"Saving updated database. Total message history size: {len(updated_hist)} rows.")
    updated_hist.to_csv(history_csv, index=False)
    updated_events.to_csv(events_csv, index=False)
    
    # Re-index ChromaDB
    init_db(history_csv, force_rebuild=True)
    print("Database expanded and ChromaDB re-indexed successfully!")

if __name__ == "__main__":
    run_expansion()
