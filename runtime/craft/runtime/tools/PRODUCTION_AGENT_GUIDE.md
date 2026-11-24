# Efficient agent workflow

Read this guide and PRODUCTION_SCENE_REFERENCE.md together with the brief and
required creative instructions in one call. The reference describes all allowed
fields and the renderer's relevant conventions. Reading the complete schema and
renderer again is unnecessary unless a specific question remains unresolved.

Author every artistic parameter from the brief. This workflow supplies no scene,
camera, lighting, material palette or artistic template. Keep required direction
and plan notes short and write them with the initial scene, not in separate turns.

## Render and inspect in one tool roundtrip

Run render_production_scene.py with `--cli`, `--state`, `--spec` and `--output`.
Each output and its `.run` directory must be new. Every call creates a fresh
project, renders with the durable worker, requires publication and checks out the
revision. Use private state without another worker or queued jobs. Do not replace
this with ad hoc CLI orchestration or recover artifacts from a failed attempt.

Avoid one-second polling and nested short waits. In functions.exec, use an outer
60-second yield and one bounded internal wait. For example, with `command` and
`previewPath` authored for this run:

```javascript
// @exec: {"yield_time_ms": 60000, "max_output_tokens": 1200}
let result = await tools.exec_command({
  cmd: command, yield_time_ms: 1000, max_output_tokens: 1000
});
if (result.session_id) {
  result = await tools.write_stdin({
    session_id: result.session_id, chars: "",
    yield_time_ms: 50000, max_output_tokens: 1000
  });
}
text(result);
if (result.exit_code === 0) {
  image((await tools.view_image({path: previewPath})).image_url);
}
```

If still running, resume that same process with a single 50-second write_stdin
wait in the next 60-second exec cell and show the image in that call on success.
Do not start another render while a process is running. If the outer exec itself
yields a cell ID, use functions.wait with a meaningful bounded wait, not repeated
one-second waits. All waits remain under 60 seconds.

The preview path is `<output>/production/exports/photograph.png`. Show it as soon
as rendering succeeds, so visual inspection does not need another request just
to fetch the image. Technical metadata already lives in `<output>.run/run.json`
and `<output>/production/metrics.json`; do not dump it into context repeatedly.
Inspect the image fully before deciding whether any creative correction is needed.

## Deliver without transcribing technical metadata

After visual review, write a short review JSON containing string lists
`visual_findings` and `limitations`, the explicit counters `environment_failures`,
`workflow_failures`, `recovery_actions`, `troubleshooting_actions`, and boolean
`earlier_assets_recipes_history_read`. These are the agent's observations and
must be accurate. The clean completion tool accepts only zero counters and false
for prior-artwork/history use.

Run in the same call that writes the review and updates the short plan:

```sh
PYTHON complete_production_run.py --root /absolute/private/job \
  --selected /absolute/private/job/attempt-02.run/run.json \
  --review /absolute/private/job/review.json
```

Select whichever successful attempt is final. The tool assembles exact project,
revision, timing and dimension metadata from successful run records, copies the
published PNG and native scene, and writes completion.json. It refuses failed
attempts and existing final files. It neither performs visual review nor replaces
the agent's findings. Do not manually transcribe IDs or duplicate engine metrics.

The supplied PYTHON must support Python 3.9+; the prepared Python includes Pillow
if additional image inspection is necessary. Preserve full logs and both attempts.
Finish with a short delivery message. Do not measure the agent's own token history;
the comparison coordinator reads native telemetry after the final response.
