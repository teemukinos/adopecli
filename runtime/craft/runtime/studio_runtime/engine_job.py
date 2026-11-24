"""One bounded engine attempt; launched in its own process group by the worker."""
import json
import os
from pathlib import Path
import signal
import sys
import threading
import time
from . import capabilities
from . import limits
from .animate_process import attempt_group


def main():
    root = Path(sys.argv[1]).resolve()
    parent = int(sys.argv[2])
    if os.getppid() != parent:
        os.killpg(os.getpgrp(), signal.SIGKILL)
    def watch_parent():
        while True:
            time.sleep(0.5)
            if os.getppid() != parent:
                # The worker died. Stop this attempt and its engine children together.
                os.killpg(os.getpgrp(), signal.SIGKILL)
    threading.Thread(target=watch_parent, daemon=True).start()
    request = json.loads((root / "request.json").read_text())
    try:
        limits.apply_process_limits(limits.validate(request.get("limits", {})))
        with attempt_group():
            result = capabilities.adapter(request["operation"]).execute(root, request["operation"], request["parameters"])
        (root / "result.json").write_text(json.dumps(result) + "\n")
    except Exception as e:
        (root / "error.json").write_text(json.dumps({"code": "engine_failure", "message": str(e)[:2000]}) + "\n")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
