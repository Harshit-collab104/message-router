import pandas as pd
from pathlib import Path
from main import predict_heuristic

def main():
    LARGE_DIR = Path(__file__).parent.parent / "hackerrank-orchestrate-august26" / "dataset_large"
    DEFAULT_DIR = Path(__file__).parent.parent / "hackerrank-orchestrate-august26" / "dataset"
    
    if (LARGE_DIR / "messages.csv").exists():
        messages_path = LARGE_DIR / "messages.csv"
        gt_path = LARGE_DIR / "ground_truth.csv"
        is_large = True
        print("Evaluating on LARGE synthetic dataset (1,000 messages)...")
    else:
        messages_path = DEFAULT_DIR / "sample_messages.csv"
        gt_path = DEFAULT_DIR / "sample_messages.csv"
        is_large = False
        print("Evaluating on BASELINE sample messages (30 messages)...")
        
    messages = pd.read_csv(messages_path)
    gt = pd.read_csv(gt_path)
    
    gt_map = gt.set_index('message_id').to_dict(orient='index')
    
    correct_action = 0
    correct_type = 0
    total = len(messages)
    
    print("-" * 80)
    for idx, row in messages.iterrows():
        m_id = row['message_id']
        pred_act, pred_type, reason, conf, evidence = predict_heuristic(row)
        
        true_label = gt_map.get(m_id, {})
        true_act = true_label.get('action', None)
        true_type = true_label.get('message_type', None)
        
        act_ok = (pred_act == true_act)
        type_ok = (pred_type == true_type)
        
        if act_ok: correct_action += 1
        if type_ok: correct_type += 1
        
        # Output progress details: all for baseline, every 100th for large dataset
        if not is_large or (idx + 1) % 100 == 0 or idx == 0:
            status = "OK" if (act_ok and type_ok) else "FAIL"
            print(f"[{idx+1}/{total}] ID: {m_id} | Status: {status}")
            print(f"      True Act: {true_act} -> Pred: {pred_act} ({'OK' if act_ok else 'FAIL'})")
            print(f"      True Type: {true_type} -> Pred: {pred_type} ({'OK' if type_ok else 'FAIL'})")
            print(f"      Evidence: {evidence}")
            print("-" * 60)
            
    print(f"\nFinal Results ({'Large Dataset' if is_large else 'Baseline'}):")
    print(f"Action Accuracy: {correct_action} / {total} ({correct_action/total*100:.2f}%)")
    print(f"Type Accuracy: {correct_type} / {total} ({correct_type/total*100:.2f}%)")

if __name__ == "__main__":
    main()
