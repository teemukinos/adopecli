# Contributing

Set up a checkout with `scripts/setup`, then make changes in the shared runtime under
`runtime/craft/runtime/`. Keep its durable job, revision and recovery behaviour.

Before you open a pull request:

- Run the checks for the part you changed: the runtime tools in
  `runtime/craft/runtime/tools/test_*.py` and the operation checks in
  `runtime/craft/tests/`.
- If you changed an operation, regenerate the capability matrix and include both
  generated files.
- If you changed an engine patch or lock, run `scripts/setup --only FAMILY` and the
  family's checks.

Use synthetic fixtures only. Do not include customer assets, private paths, account
identifiers, secrets or local state.
