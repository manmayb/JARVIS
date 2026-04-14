import json, sys
from datetime import datetime, timezone

class StructuredLogger:
    def __init__(self, name: str):
        self._name = name

    def _emit(self, level: str, event: str, **kwargs):
        record = {
            "ts":    datetime.now(timezone.utc).isoformat(),
            "level": level,
            "event": event,
            "name":  self._name,
            **kwargs,
        }
        print(json.dumps(record), file=sys.stdout, flush=True)

    def info   (self, event: str, **kw): self._emit("INFO",    event, **kw)
    def warning(self, event: str, **kw): self._emit("WARNING", event, **kw)
    def error  (self, event: str, **kw): self._emit("ERROR",   event, **kw)
    def debug  (self, event: str, **kw): self._emit("DEBUG",   event, **kw)

def get_logger(name: str) -> StructuredLogger:
    return StructuredLogger(name)
