# Explicit local project erasure

This implements the owner-approved contract in the product's
`docs/LOCAL_ERASURE_REQUIREMENTS.md`. The synthetic source fixture passes 63
checks on 19 November 2026. Installed-artifact qualification remains pending.
The earlier private package does not contain this action.

`erase-project PROJECT` and `studio_erase_project` preview by default. Applying
requires an explicit flag, the stopped worker, settled jobs and current proof
that every recorded attempt stopped or was never admitted. Neither an elapsed
lease nor a cancellation request supplies that proof. Legacy or external
execution without sufficient local proof remains refused.

Local schema 6 adds one minimal erasure table. Its key hashes the workspace and
random project identifier; it stores only fixed phases, timestamps and aggregate
counts. No names, submitted text, paths, errors, original request bodies or
arbitrary evidence enter this table. Missing jobs, assets and revisions cannot
be inspected, exported or retried after deletion. The tombstone also rejects
reinsertion of the erased project identity.

A short-lived connection receives deletion authority for one pending erasure.
Normal connections cannot modify erasure records or delete immutable execution
and reconciliation records. Schema-5 writers remain fenced. Pending erasure
fences ordinary database writes until cleanup finishes; other projects remain
readable and their logical rows and retained file bytes are preserved. This is
an application authority boundary, not protection against a user who directly
modifies their own database or runtime code.

The operation holds the worker and artifact locks. It inventories all ten
existing tables, selected attempt folders and blob references. Unsafe paths,
symlinks, hard links, unknown ownership and unassigned staging content are
refused. It commits intent before removing files. Retries derive ownership and
shared references again from current rows, never from an old preview. Shared
blobs remain while another project references them. After file removal, one
transaction removes the selected rows, including events and reconciliation
content, and advances the durable phase.

Database cleanup enables SQLite secure deletion, checks free space, compacts
the database and checkpoints the WAL. Open readers, lock contention, low space
or filesystem failures return an unfinished result and retain the durable
intent. Cleanup does not report completion until managed database cleanup
succeeds. It does not guarantee physical erasure from storage media, process
memory, backups or filesystem snapshots.

Original imports, external exports, assistant transcripts, hosted records and
device backups remain separate. Completion contains only the hash, fixed phase,
aggregate counts and these exclusions. It must not copy erased content into an
event, log or response. Source checks precede qualification of a newly built,
exactly identified installed artifact; the earlier private package does not
contain this action.

## Bounded source evidence

`tools/local_erasure_acceptance.py` uses disposable synthetic state. It covers all
ten content-bearing tables, CLI/MCP preview and apply, actual open SQLite
readers, a held worker lock, pending-writer refusal, schema-5 migration and stale
writers, immutable evidence, scoped authority, unknown paths, symlinks and hard
links, shared blobs, unchanged other-project rows and external files, and
consistent refusal of erased identifiers. It also scans the completed active
store and WAL for the selected fixture secret and checks SQLite integrity.
Unlink interruption and low-space cases use explicitly marked fault injection;
they do not establish behavior during an actual device failure. No native
engine executes and no owner data is used by this fixture.
