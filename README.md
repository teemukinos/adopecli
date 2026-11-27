# A dope CLI

A creative studio for agents. Your agent creates and revises editable files
(vector art, images, photos, video, motion, audio, PDF, layouts, interfaces,
animation, textures, materials, documents, slides, CAD, spreadsheets) through
one MCP connection or CLI. Jobs are durable, every result is an immutable
revision, and the native project files stay yours.

Everything runs on your Mac. Engines run with network access denied.

## Requirements

- macOS on Apple Silicon
- Python 3.12 or later (`brew install python`)
- Git and the Xcode command line tools (`xcode-select --install`)
- rustup (`brew install rustup`); setup installs the pinned Rust version itself
- About 20 GB of free disk space for the first build. The built engines take 1 GB;
  `scripts/setup --clean` removes the 15 GB build cache afterwards.

## Set up

```sh
git clone https://github.com/teemukinos/adopecli.git a-dope-cli
cd a-dope-cli
scripts/setup
bin/dope doctor
.venv/bin/python -B runtime/craft/tests/checkout_examples_check.py
```

The last command runs one example job for every engine you built.

`scripts/setup` builds the seventeen engines on your Mac from pinned public source
commits plus the patches in `runtime/craft/engines/`. Nothing prebuilt is
downloaded. The first full run took about 40 minutes on an M5 Pro Mac (15 cores,
24 GB); the first engine takes longest because later engines reuse its build
cache. Running setup again only builds what is missing or out of date. To start
small, build one engine first:

```sh
scripts/setup --only vector
```

## Connect your agent

Use the absolute path to `bin/dope` in your clone.

Claude Code:

```sh
claude mcp add --scope user dope -- "$PWD/bin/dope" mcp
```

Codex:

```sh
codex mcp add dope -- "$PWD/bin/dope" mcp
```

Claude desktop: add this entry under `mcpServers` in
`~/Library/Application Support/Claude/claude_desktop_config.json`:

```json
"dope": { "command": "/absolute/path/to/a-dope-cli/bin/dope", "args": ["mcp"] }
```

Restart the agent. Ask it to run `dope_capabilities`. The tools start with `dope_`.

## Use the CLI

Run these from the clone, one at a time:

```sh
bin/dope create-project "First project"
bin/dope describe vector.create
bin/dope submit PROJECT_ID vector.create --parameters examples/vector.json --key first
bin/dope job JOB_ID
bin/dope checkout REVISION_ID ./out
```

Each command prints JSON. Replace the placeholders with values from earlier output:

- `PROJECT_ID` is the `id` that `create-project` prints.
- `JOB_ID` is the `id` that `submit` prints.
- `REVISION_ID` is the `result_revision` that `job` prints once the job's `state`
  is `succeeded`. Until then, run `bin/dope job JOB_ID` again every few seconds.

`checkout` writes the revision's files to a new folder, here `./out`; the folder
must not exist yet. `bin/dope describe` shows each operation's parameters and an
example, and `examples/` has a parameter file for every engine.

`bin/dope help` lists the commands and `bin/dope rules` lists the editing rules.
Submitting a job starts a background worker if none is running, so jobs finish even
when the agent disconnects. The worker stops after 15 minutes without work. Its log
is `~/.local/share/a-dope-cli/state.worker.log`.

Projects live in `~/.local/share/a-dope-cli/state`. Set `DOPE_STATE_DIR` to use
another folder. Use the same folder for the agent and the CLI.

## Update

```sh
git pull
scripts/setup
```

Then restart your agent.

## Troubleshooting

**A command exits with code 78.** Either setup has not run yet (the message says
to run `scripts/setup`), or the command is running inside another sandbox, such as
an agent's shell sandbox. `bin/dope` applies its own network-deny sandbox and macOS
cannot nest them. Run the command with the agent's sandbox off, or connect the
agent through `bin/dope mcp`, which the agent starts outside its shell sandbox.

**An engine fails to build.** Setup prints the last lines of the compiler output
and the log's path under `.build/`. Fix the cause it names, then retry that engine
alone, for example `scripts/setup --only audio`. Engines that already built are kept.

**Something else looks wrong.** `bin/dope doctor` checks that every engine is
built, that the state folder is writable and that jobs cannot reach the network,
and says what to fix.

**Where your work is.** Projects and their revisions live in the state folder:
`~/.local/share/a-dope-cli/state`, or `DOPE_STATE_DIR` if you set it.

**Disconnect or remove.** Run `claude mcp remove --scope user dope` and
`codex mcp remove dope`, and delete the entry from the Claude desktop config if you
added one. Then delete the clone. The state folder stays until you delete it.

## What is in this repository

- `bin/dope`: the CLI and MCP entry point
- `scripts/setup`: builds the engines and the Python environment
- `runtime/craft/runtime/`: the durable runtime, MCP server and engine adapters
- `runtime/craft/engines/`: pinned source locks and maintained engine patches
- `runtime/craft/tests/`, `runtime/craft/runtime/tools/`: checks

Generated folders stay out of Git: `.venv/`, `.engines/` and `.build/`.

## License

Original software is under the [MIT license](LICENSE). The engines are built from
their upstream projects under their own licenses; see
[third-party material](THIRD_PARTY.md). Read [security scope](SECURITY.md) and
[contributing](CONTRIBUTING.md).

This is an early open-source release. It is not a signed binary release, and there
is no hosted service.
