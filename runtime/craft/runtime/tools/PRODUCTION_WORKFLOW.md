# Rendering independent scene specifications

`production.create` starts a new project with no source revision. Do not submit a
second creation to a project that already has a head revision: it cannot publish
over that head. A corrected full scene specification needs a new project.
Supported material/light revisions instead use `production.edit` with the current
explicit source revision and its exact recipe preconditions.

For complete scene specifications, use the orchestration helper:

```sh
python3 render_production_scene.py \
  --cli /absolute/path/to/dobe-source \
  --state /absolute/path/to/private-state \
  --spec /absolute/path/to/new-scene.json \
  --output /absolute/path/to/new-delivery
```

The helper validates the caller's scene, creates a fresh project on every call,
submits the existing `production.create` operation, runs the durable worker,
requires successful revision publication, and checks out the published artifacts.
A corrected scene can use the same private state with a different output path;
the helper creates another project without modifying the earlier project.

The helper contains no scene template or artistic defaults. It does not change
renderer behavior, relax publication checks, recover failed attempts, or retry
automatically. A failure exits nonzero and preserves logs in `<output>.run`.
`--output` names a directory, not an image. Preview `<output>/production/exports/photograph.png`;
the exact path is also returned as `final_image`. Read `<output>.run/run.json`
for the publication record. Do not pass the checkout directory to an image viewer.

The output directory and its `.run` directory must both be new. Use private state
without other queued jobs or another worker, because `worker --once` processes
the next queued job in that state. CLI limits are set for this private state.

This is a local source utility. It does not update an installed package or service.

For agent use, read [the compact scene contract](PRODUCTION_SCENE_REFERENCE.md)
and [the efficient workflow](PRODUCTION_AGENT_GUIDE.md). The workflow batches
render waiting with image inspection and uses `complete_production_run.py` to
assemble verified technical metadata after the agent supplies its visual review.

Controlled comparisons may use [automatic handoff orchestration](COMPARISON_AGENT_GUIDE.md).
The local controller finalizes a structured visual review without another model
roundtrip and records sleep/stall evidence. Its temporary idle-sleep protection
does not override laptop lid-close sleep or change global power settings.

For compact measured assignments, use [the validated attempt interface](COMPACT_COMPARISON.md). It returns actual preview paths and handles generation metadata without agent path parsing.
