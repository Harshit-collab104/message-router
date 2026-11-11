import zipfile
import shutil
from pathlib import Path

from dataset_store import DATA_DIR

# Importing the packager must not create archives or copy files.
# Setup paths
WORKSPACE_DIR = Path(__file__).parent.parent
MSG_ROUTER_DIR = Path(__file__).resolve().parent
HACKERRANK_DIR = WORKSPACE_DIR / "hackerrank-orchestrate-august26"
LOG_FILE = Path("C:/Users/harsh/hackerrank_orchestrate_august26/log.txt")

def main():
    # Target submission dir
    SUBMISSION_DIR = WORKSPACE_DIR / "submission"
    SUBMISSION_DIR.mkdir(exist_ok=True)
    
    # 1. Create code.zip
    zip_path = SUBMISSION_DIR / "code.zip"
    print(f"Creating {zip_path}...")
    with zipfile.ZipFile(zip_path, 'w', zipfile.ZIP_DEFLATED) as zipf:
        # Add msg_router files
        for file_name in ["main.py", "README.md", "DATASET_WORKFLOW.md", "dataset_store.py", "demo_data.json", "vector_store.py", "evaluate.py", "requirements.txt", "server.py", "static/index.html", "static/style.css", "static/app.js"]:
            fpath = MSG_ROUTER_DIR / file_name
            if fpath.exists():
                zipf.write(fpath, arcname=f"msg_router/{file_name}")
                
        # Add README/problem_statement from hackerrank-orchestrate-august26
        for file_name in ["README.md", "problem_statement.md"]:
            fpath = HACKERRANK_DIR / file_name
            if fpath.exists():
                zipf.write(fpath, arcname=file_name)
    
    print("code.zip created successfully.")
    
    # 2. Copy output.csv
    src_output = DATA_DIR / "output.csv"
    dest_output = SUBMISSION_DIR / "output.csv"
    if src_output.exists():
        print(f"Copying {src_output} -> {dest_output}...")
        shutil.copy2(src_output, dest_output)
    else:
        print("WARNING: output.csv not found in dataset folder!")
    
    # 3. Copy log.txt
    dest_log = SUBMISSION_DIR / "log.txt"
    if LOG_FILE.exists():
        print(f"Copying {LOG_FILE} -> {dest_log}...")
        shutil.copy2(LOG_FILE, dest_log)
    else:
        print("WARNING: log.txt not found in external log path!")
    
    print("-" * 50)
    print(f"All submission files are ready in: {SUBMISSION_DIR}")
    print("Files to upload:")
    print(f"1. code.zip (code.zip)")
    print(f"2. output.csv (Predictions CSV)")
    print(f"3. log.txt (Chat transcript)")


if __name__ == "__main__":
    main()
