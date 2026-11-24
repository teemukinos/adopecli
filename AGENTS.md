# For agents

Two jobs bring an agent here.

## The user asked you to set up A dope CLI

1. Check the Mac: `uname -sm` prints `Darwin arm64`; Python 3.12 or later, `git`,
   `rustup` and the Xcode command line tools are present. Ask the user before you
   install anything with Homebrew.
2. Run `scripts/setup` from the repository root. It took about 40 minutes for all
   seventeen engines on an M5 Pro Mac; `scripts/setup --only vector` is a quick first check. It needs
   network access to fetch the pinned sources and Rust packages, so run it outside
   your sandbox or ask the user to run it.
3. Run `bin/dope doctor`. Every engine you built shows `true`, and
   `network_denied` is `true`. Then run
   `.venv/bin/python -B runtime/craft/tests/checkout_examples_check.py`; it runs one
   example job per built engine and must end with `"failed": []`.
4. Add the MCP server with the absolute path to `bin/dope`:
   `claude mcp add --scope user dope -- "$PWD/bin/dope" mcp` or
   `codex mcp add dope -- "$PWD/bin/dope" mcp`.
5. Tell the user to restart the agent, then call `dope_capabilities`.

`bin/dope` applies its own network-deny sandbox, so it refuses to run inside
another sandbox (exit 78). Connect through MCP, or run the command with your
sandbox off.

## You are changing this repository

- The runtime is `runtime/craft/runtime/studio_runtime/`. Keep one job queue and
  one runtime; extend what exists.
- Engine changes go in the maintained patches and locks in `runtime/craft/engines/`.
  A lock change makes `scripts/setup` rebuild that engine.
- After changing operations, regenerate the matrix with
  `.venv/bin/python -B runtime/craft/capability_inventory.py`.
- Use synthetic fixtures. Never commit credentials, client files, project state,
  `.venv/`, `.engines/` or `.build/`.
