
import os
import sys
from pathlib import Path

# 将项目根目录添加到 sys.path
root_dir = Path(__file__).parent.parent.absolute()
if str(root_dir) not in sys.path:
    sys.path.insert(0, str(root_dir))

import time
import threading
import faulthandler
import uvicorn
import asyncio
from web.backend.app import create_app

# 启用 faulthandler
faulthandler.enable()

class Heartbeat(threading.Thread):
    def __init__(self):
        super().__init__(daemon=True)
        self.pid = os.getpid()

    def run(self):
        while True:
            time.sleep(1)
            # 这是一个非主线程的 heartbeat，确认进程没挂
            # print(f"[Heartbeat] PID {self.pid} is alive at {time.time()}", flush=True)

async def event_loop_heartbeat():
    while True:
        await asyncio.sleep(1)
        print(f"[Loop Heartbeat] Event loop is running at {time.time()}", flush=True)

class StackDumper(threading.Thread):
    def __init__(self, delay=15):
        super().__init__(daemon=True)
        self.delay = delay
        self.pid = os.getpid()

    def run(self):
        print(f"\n[Debug] StackDumper (PID: {self.pid}) started. Waiting {self.delay}s...", flush=True)
        time.sleep(self.delay)
        
        print("\n" + "="*50, flush=True)
        print(f"DEBUG: THREAD STACK DUMP (PID: {self.pid})", flush=True)
        print("="*50, flush=True)
        
        # 打印当前所有活跃线程
        print(f"\nActive Threads ({len(threading.enumerate())}):", flush=True)
        for t in threading.enumerate():
            print(f" - {t.name} (daemon={t.isDaemon()})", flush=True)
        
        print("\nStack Traces:", flush=True)
        faulthandler.dump_traceback()
        print("\n" + "="*50 + "\n", flush=True)

def main():
    # 强制设置环境
    os.environ["MOMO_USER"] = "asher"
    os.environ["MOMO_ENV"] = "development"
    
    # 启动 Dumper
    dumper = StackDumper(delay=15)
    dumper.start()
    
    Heartbeat().start()

    # 创建 App
    app = create_app()
    
    # 在 startup 时增加 loop heartbeat
    @app.on_event("startup")
    async def start_heartbeat():
        asyncio.create_task(event_loop_heartbeat())

    # 启动 uvicorn
    print(f"[Debug] Starting Uvicorn in process {os.getpid()}...", flush=True)
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=8765,
        log_level="info",
        access_log=True,
    )

if __name__ == "__main__":
    main()
