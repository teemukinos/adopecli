# Comparison orchestration with an automatic handoff

The coordinator runs watch_comparison_handoffs.py outside both model contexts.
It watches only the registered current-run logs, keeps the Mac from idle sleep,
records heartbeat gaps, and exports the agent's selected result after its final
structured review. It does not author artwork, inspect images, or call a model.
It cannot prevent lid-close sleep; the laptop lid must remain open.

## CLI: combine authoring, execution and preview

Read the brief, protocol, required creative instructions, this guide and
PRODUCTION_SCENE_REFERENCE.md together. The generic scene contract replaces
unnecessary full-source reads. Author all artistic choices from the brief.

Write the scene and short production notes and launch render_production_scene.py
in the same shell command and tool call. Do not spend a separate model request
just launching a scene already written. Each complete specification uses a new
output directory and a fresh project through the existing helper.

`--output` is a checkout DIRECTORY, never the preview image. For example, use
`--output /your/private/run/attempt-01`. The preview is then exactly
`/your/private/run/attempt-01/production/exports/photograph.png`, and the run
record is `/your/private/run/attempt-01.run/run.json`. Set `previewPath` to
that full photograph.png path before launching. Never pass the output directory
to view_image. The helper also reports the exact path as `final_image`.

Use this orchestration pattern. The coordinator stays responsive while the
child's tool executes; each system wait remains bounded below 60 seconds.

```javascript
// @exec: {"yield_time_ms": 120000, "max_output_tokens": 1200}
let result = await tools.exec_command({
  cmd: authorAndRenderCommand, yield_time_ms: 1000, max_output_tokens: 1000
});
while (result.session_id) {
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

The loop uses code, not new model responses, to wait. If the outer exec yields a
cell ID, use functions.wait with up to 60 seconds; do not launch another render
or start a separate process poll. Every eventual model continuation is counted.
Inspect the returned image fully. A permitted creative correction uses the same
pattern with an authored revised scene and a new output path. Never salvage a
failed attempt or change the renderer/quality target to reduce waiting.

## Image generation: persist metadata in the generation call

Keep the same built-in image tool, fresh text-only prompt, no references, native
dimensions, and full visual review. After the image tool returns, save one JSON
metadata file inside the current run folder with these fields:

`output_hint`, `prompt_path`, `started_at`, `finished_at`, `elapsed_seconds`.

Save `output_hint` exactly as returned by the image tool. Do not parse a path
yourself: the controller extracts the PNG after the hint's `as` marker and checks
that it belongs to this fresh agent. The prompt file must be inside its folder.
Write metadata inside that same functions.exec call before returning the image
with generatedImage(result). Do not print base64 or dump full metadata into the
model context. This is ordinary bookkeeping, not a separate model task.

## Final response: reviewed selection, not another tool call

After the final preview, output one plain JSON object as the **final response**,
without Markdown fences or surrounding prose. This replaces the previous
completion-writing tool call followed by another final model response. Do not
call complete_production_run.py yourself in this registered comparison.

Both routes include string lists `visual_findings` and `limitations`, integer
`environment_failures`, `workflow_failures`, `recovery_actions`,
`troubleshooting_actions`, and boolean `earlier_assets_recipes_history_read`.
All four counters must accurately be zero and the boolean false for a clean run.

For the CLI, also include `selected_run`: the absolute path to the chosen
successful `<output>.run/run.json`. The controller reads all attempt records,
requires successful publication, and invokes the completion utility. It writes
final.png, final.blend and completion.json without a further model request.

For image generation, also include `attempt_metadata`: the list of one or two
absolute metadata JSON paths in generation order, `selected_attempt`: a one-based
index, and `reference_images_used`: false. The controller preserves originals,
copies the selected PNG, measures dimensions and writes completion.json. Provider
model identity, inference usage and billing remain unknown unless exposed.

The review is the agent's own visual judgment. Never claim that the controller
reviewed the image. Do not claim final copies already exist before the controller
has made them. Required notes can say that technical handoff is automatic; no
extra plan-update tool turn is required after visual acceptance.

On any technical failure, stop and return plain JSON with `status: "blocked"`
and an accurate `reason`. The coordinator records the failed run; the controller
does not retry or recover it. Do not read any earlier scene, recipe, image, prompt,
conversation or comparison result. No self-measurement of token history.
