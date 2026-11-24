"""Start an attempt with isolated Python imports, never from project contents."""
import os
from pathlib import Path
import runpy
import sys
from contextlib import nullcontext

# The child cannot execute an engine until its parent commits the process-group
# registration. Parent death closes the pipe without admitting this attempt.
if len(sys.argv) != 4:
    raise SystemExit('an execution admission pipe is required')
gate = int(sys.argv[3])
if gate < 3:
    raise SystemExit('invalid execution admission pipe')
try:
    admission = os.read(gate, 1)
finally:
    os.close(gate)
if admission not in (b'1', b'O'):
    raise SystemExit('execution was not admitted')
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from studio_runtime.offline import trusted_scope
with trusted_scope() if admission == b'O' else nullcontext():
    runpy.run_module("studio_runtime.engine_job", run_name="__main__")
