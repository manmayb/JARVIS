import uvicorn
import argparse
import sys
from core.logging import get_logger

log = get_logger("JARVIS.launcher")

def start_api():
    """Start the main JARVIS FastAPI server."""
    log.info("launch.api", host="0.0.0.0", port=8000)
    uvicorn.run("api.app:app", host="0.0.0.0", port=8000, reload=True)

def start_worker(worker_type: str):
    """Placeholder for separate worker processes if decoupled from API lifespan."""
    log.info("launch.worker", type=worker_type)
    # Background tasks are currently handled by apscheduler inside the API lifespan.
    # If the project scales to separate workers, logic goes here.
    if worker_type == "autonomy":
        from autonomy.scheduler import scheduler
        from autonomy.event_watcher import event_watcher
        import asyncio
        
        async def run_autonomy():
            await scheduler.start()
            await event_watcher.start()
            while True: await asyncio.sleep(3600)
            
        asyncio.run(run_autonomy())
    else:
        print(f"Unknown worker type: {worker_type}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="JARVIS V4 Bootloader")
    parser.add_argument("--mode", choices=["api", "worker"], default="api", help="Mode to run the system in")
    parser.add_argument("--type", help="Worker type when mode is 'worker'")
    
    args = parser.parse_args()
    
    if args.mode == "api":
        start_api()
    elif args.mode == "worker":
        start_worker(args.type or "autonomy")
