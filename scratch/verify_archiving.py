import os
from core.db_manager import get_file_hash, archive_prompt_file, init_db
from config import PROMPT_FILE, DATA_DIR

print(f"Checking PROMPT_FILE: {PROMPT_FILE}")
prompt_hash = get_file_hash(PROMPT_FILE)
print(f"Prompt hash: {prompt_hash}")

print("Running archive_prompt_file...")
archive_prompt_file(PROMPT_FILE, prompt_hash)

archive_dir = os.path.join(DATA_DIR, "prompts")
archive_path = os.path.join(archive_dir, f"prompt_{prompt_hash}.md")

if os.path.exists(archive_path):
    print(f"✅ Archive success: {archive_path}")
else:
    print("❌ Archive failed!")

print("Checking Database Initialization...")
init_db()
print("✅ DB Init success.")
