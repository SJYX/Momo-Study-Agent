import os
import sys
import time

# MUST set before importing project modules
os.environ["MOMO_USER"] = "test_user"

# Add root to sys.path
sys.path.append('.')

from core.db_manager import init_db, log_progress_snapshots, get_latest_progress, get_file_hash, archive_prompt_file
from config import PROMPT_FILE, SCORE_PROMPT_FILE, REFINE_PROMPT_FILE, DATA_DIR

def test_archiving():
    print("--- Testing Archiving ---")
    prompts = [(PROMPT_FILE, "main"), (SCORE_PROMPT_FILE, "score"), (REFINE_PROMPT_FILE, "refine")]
    for path, ptype in prompts:
        h = get_file_hash(path)
        archive_prompt_file(path, h, ptype)
        archive_path = os.path.join(DATA_DIR, "prompts", f"prompt_{ptype}_{h}.md")
        if os.path.exists(archive_path):
            print(f"✅ {ptype} archived: {archive_path}")
        else:
            print(f"❌ {ptype} archive FAILED")

def test_incremental_tracking():
    print("\n--- Testing Incremental Tracking ---")
    db_test = "data/test_tracking.db"
    if os.path.exists(db_test): os.remove(db_test)
    init_db(db_test)
    
    word_list = [
        {"voc_id": 1, "voc_spelling": "apple", "short_term_familiarity": 1.0, "review_count": 5},
        {"voc_id": 2, "voc_spelling": "banana", "short_term_familiarity": 2.0, "review_count": 10}
    ]
    
    print("First snapshot...")
    log_progress_snapshots(word_list, db_path=db_test)
    
    print("Second snapshot (NO CHANGE)...")
    count = log_progress_snapshots(word_list, db_path=db_test)
    print(f"Snapshots logged: {count} (Expected: 0)")
    
    print("Third snapshot (CHANGE Familiarity of apple)...")
    word_list[0]["short_term_familiarity"] = 1.5
    count = log_progress_snapshots(word_list, db_path=db_test)
    print(f"Snapshots logged: {count} (Expected: 1)")
    
    print("Fourth snapshot (CHANGE review_count of banana)...")
    word_list[1]["review_count"] = 11
    count = log_progress_snapshots(word_list, db_path=db_test)
    print(f"Snapshots logged: {count} (Expected: 1)")

if __name__ == "__main__":
    os.environ["MOMO_USER"] = "test_user"
    test_archiving()
    test_incremental_tracking()
