# Photographic-production result boundary

This local fixture exercises the `product-scene-v1` CPU profile through the public sealed CLI. It creates an owned 256 × 256 synthetic scene, verifies its original pixels, changes one material while preserving native geometry and camera, and renders that revision again. It then imports a copy of the original with one altered delivered pixel and correctly rebound ordinary file receipts. Native verification must refuse that copy without publishing a revision or advancing its project head.

```sh
PACKAGE/lib/dobe/python/bin/python3 -I -B production_result_acceptance.py PACKAGE NEW_OUTPUT
```

Use the maintained fixture at `craft/runtime/tools/production_result_acceptance.py`; the output directory must not exist. The fixture uses separate local state, never changes immutable stored artifacts or database rows, retains actual durable results and checks that all recorded native process groups stop. Originals remain unchanged. It runs five native attempts (four successes and one expected failure) and one separate storage import. Guard verification must agree before and after the jobs.

The original private.2 reproduction accepted an altered PNG after Blender reported `AssertionError: Reopened render pixels differ`. Blender's default Python-error exit behavior and a retained `engine-result.json` allowed stale success to be published. The repair requests a nonzero Python-error exit, removes the previous result before each invocation, validates the current result mode and requires explicit pixel reproduction for verification. The final validation records the separately observed cold reopen rather than a creation-phase flag.

This is a result-publication and bounded 3D-profile fixture. It does not establish broad photographic fidelity, every native property or dependency, synthesis inference, owner creative approval, GPU/Linux execution, actual billed cost, publisher identity, clean-host installation or a complete release. A passing source fixture is not acceptance of an older sealed package. Bind each executed package and fixture to exact source and output receipts.
