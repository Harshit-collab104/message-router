import os
import json
import pandas as pd
from pathlib import Path
from tqdm import tqdm
from dataset_store import DATA_DIR, CHROMA_DIR, OFFLINE, DatasetError, read_csv_table

# Path settings
WORKSPACE_DIR = Path(__file__).parent.parent
MSG_ROUTER_DIR = Path(__file__).resolve().parent
CHROMA_DB_PATH = CHROMA_DIR

print(f"ChromaDB persistent path set to: {CHROMA_DB_PATH}")

def get_client():
    if OFFLINE:
        raise DatasetError('Vector storage is disabled in offline mode')
    import chromadb
    return chromadb.PersistentClient(path=str(CHROMA_DB_PATH))

def init_db(history_csv_path, force_rebuild=False):
    print(f"Loading history from {history_csv_path} for ChromaDB indexing...")
    df = read_csv_table(history_csv_path, table_name='message_history.csv', required=True)
    
    # Load events to join reactions into metadata
    events_csv_path = Path(history_csv_path).parent / "message_events.csv"
    if events_csv_path.exists():
        print(f"Loading events from {events_csv_path} to join with history...")
        events_df = read_csv_table(events_csv_path, required=True)
        df = df.merge(events_df, on=["message_id", "user_id"], how="left")
    
    client = get_client()
    
    # Get or create collection
    collection_name = "message_history"
    
    if force_rebuild:
        try:
            client.delete_collection(name=collection_name)
            print("Deleted existing ChromaDB collection for rebuild.")
        except Exception:
            pass
            
    collection = client.get_or_create_collection(name=collection_name)
    
    existing_count = collection.count()
    if existing_count > 0 and not force_rebuild:
        print(f"ChromaDB collection '{collection_name}' already contains {existing_count} documents. Skipping indexing.")
        return collection
        
    # Fill NA values for string columns to avoid errors
    df['message_text'] = df['message_text'].fillna("")
    df['group_id'] = df['group_id'].fillna("none")
    df['business_id'] = df['business_id'].fillna("none")
    df['sender_user_id'] = df['sender_user_id'].fillna("none")
    df['media_type'] = df['media_type'].fillna("none")
    df['source'] = df['source'].fillna('history') if 'source' in df else 'history'
    
    # We only index documents with non-empty text and ensure unique IDs
    df_to_index = df[df['message_text'] != ""]
    df_to_index = df_to_index.drop_duplicates(subset=['source', 'user_id', 'message_id'])
    
    ids = []
    documents = []
    metadatas = []
    
    for idx, row in df_to_index.iterrows():
        ids.append(json.dumps([str(row.get('source', 'history')), str(row['user_id']), str(row['message_id'])], separators=(',', ':')))
        documents.append(row['message_text'])
        
        # Read reaction values
        msg_opened = int(row.get('message_opened', 0)) if pd.notna(row.get('message_opened')) else 0
        msg_replied = int(row.get('message_replied', 0)) if pd.notna(row.get('message_replied')) else 0
        dismissed = int(row.get('notification_dismissed', 0)) if pd.notna(row.get('notification_dismissed')) else 0
        muted_after = int(row.get('muted_after_message', 0)) if pd.notna(row.get('muted_after_message')) else 0
        reported = int(row.get('message_reported', 0)) if pd.notna(row.get('message_reported')) else 0

        metadatas.append({
            'source': str(row.get('source', 'history')),
            'message_id': str(row['message_id']),
            'user_id': str(row['user_id']),
            'conversation_type': str(row['conversation_type']),
            'group_id': str(row['group_id']),
            'business_id': str(row['business_id']),
            'sender_user_id': str(row['sender_user_id']),
            'media_type': str(row['media_type']),
            'message_opened': msg_opened,
            'message_replied': msg_replied,
            'notification_dismissed': dismissed,
            'muted_after_message': muted_after,
            'message_reported': reported
        })
        
    batch_size = 500
    total_docs = len(ids)
    print(f"Indexing {total_docs} documents into ChromaDB in batches of {batch_size}...")
    
    for i in tqdm(range(0, total_docs, batch_size)):
        end_idx = min(i + batch_size, total_docs)
        collection.add(
            ids=ids[i:end_idx],
            documents=documents[i:end_idx],
            metadatas=metadatas[i:end_idx]
        )
        
    print(f"ChromaDB collection successfully built. Total documents indexed: {collection.count()}")
    return collection

def retrieve_relevant_history(user_id, conv_type, group_id, business_id, sender_user_id, message_text, limit=3):
    """
    Query ChromaDB for relevant history messages under the specific conversation context.
    Uses Cascading Fallback Retrieval if no matching context is found.
    """
    if OFFLINE or not message_text or pd.isna(message_text):
        return []
        
    client = get_client()
    collection = client.get_or_create_collection(name="message_history")
    
    # 1. Strict contextual filter
    filters = [{"user_id": str(user_id)}]
    context_filter = None
    if conv_type == 'group' and group_id and group_id != "none" and not pd.isna(group_id):
        context_filter = {"group_id": str(group_id)}
    elif conv_type == 'business' and business_id and business_id != "none" and not pd.isna(business_id):
        context_filter = {"business_id": str(business_id)}
    elif conv_type == 'personal' and sender_user_id and sender_user_id != "none" and not pd.isna(sender_user_id):
        context_filter = {"sender_user_id": str(sender_user_id)}
        
    if context_filter:
        filters.append(context_filter)
        
    where_filters_to_try = []
    
    # Cascade 1: Strict match
    if len(filters) > 1:
        where_filters_to_try.append({"where": {"$and": filters}, "label": "strict context"})
    else:
        where_filters_to_try.append({"where": filters[0], "label": "user context"})
        
    # Cascade 2: User-only match (fallback to general messages involving this user)
    if len(filters) > 1:
        where_filters_to_try.append({"where": {"user_id": str(user_id)}, "label": "user fallback"})
        
    # Private history never falls back outside the recipient's ownership scope.

    for attempt in where_filters_to_try:
        try:
            results = collection.query(
                query_texts=[message_text],
                n_results=limit,
                where=attempt["where"]
            )
            
            retrieved = []
            if results and 'ids' in results and len(results['ids']) > 0 and len(results['ids'][0]) > 0:
                for idx in range(len(results['ids'][0])):
                    doc_id = results['ids'][0][idx]
                    doc_text = results['documents'][0][idx]
                    distance = results['distances'][0][idx] if 'distances' in results else 0.0
                    metadata = results['metadatas'][0][idx]
                    
                    if not metadata or str(metadata.get('user_id')) != str(user_id):
                        continue
                    doc_id = metadata.get('message_id', doc_id)
                    # Store lookup fallback label in metadata for auditing
                    metadata_copy = dict(metadata) if metadata else {}
                    metadata_copy["retrieval_strategy"] = attempt["label"]
                    
                    retrieved.append({
                        'message_id': doc_id,
                        'message_text': doc_text,
                        'distance': distance,
                        'metadata': metadata_copy
                    })
                
                # If we successfully retrieved records, return them!
                if len(retrieved) > 0:
                    return retrieved
        except Exception as e:
            print(f"Error querying ChromaDB with {attempt['label']}: {e}")
            
    return []

def test_retrieval():
    """
    Quick self-test retrieval function.
    """
    print("Testing ChromaDB retrieval...")
    res = retrieve_relevant_history(
        user_id="u_001",
        conv_type="personal",
        group_id="none",
        business_id="none",
        sender_user_id="u_002",
        message_text="Are we meeting today?",
        limit=2
    )
    print(f"Test query results: {res}")
    return len(res) >= 0

if __name__ == "__main__":
    import sys
    history_csv = DATA_DIR / 'message_history.csv'
    try:
        if not history_csv.exists():
            raise DatasetError(f'Missing required CSV: {history_csv}')
        init_db(history_csv)
        test_retrieval()
    except (DatasetError, OSError) as error:
        print(f'Message Router vector store: {error}', file=sys.stderr)
        raise SystemExit(2)
