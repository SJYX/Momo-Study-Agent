import os
import logging
from core.logger import setup_logger, get_logger

def test_logger_dynamic_switching():
    log_dir = "logs"
    os.makedirs(log_dir, exist_ok=True)
    
    user1_log = os.path.join(log_dir, "user1.log")
    user2_log = os.path.join(log_dir, "user2.log")
    
    # Cleanup old logs if they exist
    for p in [user1_log, user2_log]:
        if os.path.exists(p):
            os.remove(p)
            
    # 1. Setup for user1
    logger1 = setup_logger("user1")
    logger1.info("This belongs to user1")
    
    # 2. Setup for user2 (this should trigger switching)
    logger2 = setup_logger("user2")
    logger2.info("This belongs to user2")
    
    # Verify user1.log contains only its message
    with open(user1_log, "r", encoding="utf-8") as f:
        content1 = f.read()
        assert "This belongs to user1" in content1
        assert "This belongs to user2" not in content1
        
    # Verify user2.log contains only its message
    with open(user2_log, "r", encoding="utf-8") as f:
        content2 = f.read()
        assert "This belongs to user2" in content2
        assert "This belongs to user1" not in content2

    print("✅ Logger dynamic switching test passed!")

if __name__ == "__main__":
    # Reset logger handlers for clean test
    root = logging.getLogger()
    for h in root.handlers[:]:
        root.removeHandler(h)
        
    try:
        test_logger_dynamic_switching()
    except Exception as e:
        print(f"❌ Test failed: {e}")
        import traceback
        traceback.print_exc()
