"""Trusted offline construction subprocess; inherits the existing attempt group."""
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from studio_runtime.construction import execute
from studio_runtime.offline import trusted_scope
root=Path(sys.argv[1]);request=json.loads((root/'construction-call.json').read_text())
# This private entry point is launched only after sandbox-exec succeeds.
with trusted_scope():
    (root/'construction-result.json').write_text(json.dumps(execute(root,request['operation'],request['params']),allow_nan=False))
