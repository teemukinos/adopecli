# Compact production assignment and validated file handling

The coordinator loads the Studio and image-generation instructions, checks the
local environment and provides each fresh production agent only its applicable
rules, the unchanged brief, the route contract and the invocation interface.
The agent receives no earlier artistic content. This removes a separate startup
reading request and repeated multi-app documentation. The full production token
measurement still starts with the agent's first response, not after preparation.

`comparison_attempt.py` accepts `--root`, `--operation`, `--attempt` (1 or 2),
and `--payload` (JSON). The coordinator creates a private `run-config.json` with
route, Python, render-helper, CLI and current session ID. It contains software
paths only, never scene or prompt defaults.

- `render`: payload has the complete authored `document` and authored `notes`.
  The helper saves inputs, creates a new project via the existing render helper,
  requires publication, validates the PNG and returns `preview_path` and
  `run_record`. The agent passes the returned preview path directly to
  `view_image`. It never constructs or guesses a file path.
- `prepare-image`: payload has authored `prompt` and `notes`. It saves both to
  exclusive attempt files before generation.
- `record-image`: payload has the unchanged tool `output_hint`, `started_at`
  and `finished_at`. The helper resolves the original file, verifies current
  session ownership and PNG integrity, and preserves its exact bytes and metadata.
  The agent must not parse the tool hint or choose its own output paths.

Run authoring, execution, bounded waits and preview in one tool call. Encode
payloads with JSON.stringify and use proper POSIX single-quote escaping, never
JSON.stringify alone as shell escaping. Each process wait stays under 60 seconds.
For a delegated CLI agent, give the outer execution a 600-second yield budget
while the coordinator stays responsive; each nested process wait remains at most
50 seconds. Keep the image tool at its required 120-second outer yield budget.
If either execution yields early, use exactly 60 seconds for its continuation,
not short polling. Every continuation remains counted. A known route has no
exploratory file reads.

Both agents end with a structured visual review containing `selected_attempt`,
`visual_findings`, `limitations`, four accurate failure/recovery counters and
`earlier_assets_recipes_history_read:false`. Image generation also reports
`reference_images_used:false`. The watcher derives attempt paths itself and
exports the reviewed selection without another model request.

`production_file_io.py` validates PNG structure and checksums, rejects path
escapes, validates all delivery contents before installation, and stages files
before exclusive installation. Existing files and dangling symlinks are never
overwritten. An installation failure removes only that invocation's newly
installed files. This file-level cleanup is not a render retry or recovery.
Any production failure still invalidates the clean run and stops that agent.

Keep full visual review and the same one-correction allowance. Do not reduce
renderer quality, reuse older artwork, change model settings or substitute an
image provider. Scoped power protection cannot prevent lid-close sleep.
