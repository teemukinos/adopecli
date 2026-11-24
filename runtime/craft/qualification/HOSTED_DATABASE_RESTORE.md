# Local database backup and restore qualification

The 19 November 2026 follow-up restores the retained PostgreSQL cutover-fixture
dump into a new private cluster, creates a fresh logical backup, stops that
source cluster, and restores the new backup into a second private cluster.
The original retained dump remains unchanged. No existing service or customer
database is used.

```sh
python3 -I -B craft/tests/hosted_postgres_restore.py \
  --postgres-prefix /absolute/path/to/existing/postgresql \
  --dump /absolute/path/to/trusted-cutover-fixture.dump \
  --dump-sha256 REPLACE_WITH_VERIFIED_FIXTURE_SHA256 \
  --upgrade-migration 023_usage_quotes.sql \
  --output /absolute/path/to/new/private/qualification
```

Use only the trusted synthetic fixture described in
[native database cutover](HOSTED_DATABASE_CUTOVER.md). A PostgreSQL dump contains
executable SQL; supplying an untrusted archive is not safe. The fixture checks
the supplied SHA-256, regular-file type and custom-format header before creating
output. The output directory must be new. The command needs the existing hosted
Python dependencies and PostgreSQL tools; it never downloads or installs them.

The current writer-17 runtime requires the explicit migration argument above
when restoring the retained writer-16 fixture. The fixture applies it only to
the new disposable source cluster, verifies every retained table row and sequence
remain unchanged, and then backs up the upgraded database. The original
writer-16 qualification below remains historical evidence; it is not silently
relabelled as writer-17 qualification.

## Observed result

PostgreSQL 17.12 passes 48 checks on macOS ARM64:

- A database-only dump cannot restore its ACLs and function owners until the
  eight required roles exist. The intentionally failed `--single-transaction`
  restore leaves neither application schema. The fixture then provisions roles
  from maintained migrations and repeats the restore successfully.
- All 63 tables in `studio` and `billing_mcp` retain their exact row fingerprints.
  All five sequences retain state, definitions and ownership. Schema owners,
  table/column metadata, indexes, constraints, functions, RLS policies, triggers,
  ACLs, default privileges, role attributes and role memberships match.
- The 86-operation admission catalog and writer version 16 pass actual runtime
  startup. Runtime and function-owner roles have no superuser, RLS bypass, role
  creation, database creation or replication privileges. Only the two disposable
  runtime roles have login enabled in these fixtures.
- The owner can read the restored revision. Nonmembers cannot read it or usage;
  RLS hides all jobs. Reusing a job key returns the original job. Repeating
  settlement returns the original revision, and changed usage is refused.
  These read/replay operations change no rows or sequence state.
- A fresh queued job reserves compute, cancellation releases the reservation,
  and the restored audit sequence allocates new IDs without collision. This
  creates no additional usage event, revision or provider-delivery work.
- Before the fresh backup, a synthetic unresolved attempt records start intent
  and an expired lease. Restoration preserves its reservation and runtime
  receipt. Recovery marks it interrupted; settlement without termination
  evidence, retry, automatic reclaim and scratch cleanup are refused. Cancelling
  a separate queued job releases only that job's reservation. The unresolved
  attempt remains reserved after the final database restart.
- A real stop/start preserves the entire final fingerprint. Both clusters keep
  TCP disabled and use private Unix sockets. Both are stopped in cleanup,
  including the fixture's failure path.

Two additional command-line checks reject a wrong checksum before creating any
output and confirm that a truncated-archive failure stops its private cluster.
The failed run's logs and evidence are retained alongside the successful run.

The retained input has nineteen settled attempts, nineteen usage events,
one revision and 133 synthetic milliseconds. The fresh backup adds one unresolved
attempt with a 600,000-millisecond compute reservation. These are database test values,
not measured engine time or a customer charge. Native outputs, object metadata
and termination receipts remain synthetic. No Storage bytes or native engines
are restored or executed. Machine-local evidence is retained in
`.verify/hosted-postgres-restore-20261119/` and is not exported publicly.

## Accepted usage quotes and unresolved monetary reservations

The quote fixture has an optional restore mode. It creates its own synthetic
subscription-usage workspace and fresh database; it does not accept a customer
dump or contact a provider.

```sh
python3 -I -B craft/tests/hosted_usage_quotes.py \
  --postgres-prefix /absolute/path/to/existing/postgresql \
  --output /absolute/path/to/new/private/quote-qualification \
  --restore-check --wait-for-expiry
```

The backup contains accepted immutable quotes, settled usage, an unstarted
release, three settled retries, a held overrun and an unresolved quoted start
intent. The fixture stops the source before restoring into a fresh cluster,
bootstraps the eight roles from maintained migrations, and compares all 65 table
fingerprints, five sequences and the complete schema/role/ACL/RLS metadata.
Complete customer quote receipts and workspace usage must also match.

Read and settlement replay leave both rows and sequence state unchanged. Refused
retries preserve every table row and schema property. PostgreSQL sequence values
consumed by a rolled-back admission are not rolled back: the fixture records the
admission sequence advancing, while every other sequence remains unchanged. It
does not reset sequences or treat consumed identifiers as a second charge.

The original job key still returns the original job. Repeating settlement adds
no money record; changed usage, an exhausted customer maximum, a fourth attempt
and a held overrun remain refused. Nonmembers cannot read the quote through the
API; the API role still cannot read private quote tables directly, and job RLS
still hides nonmember rows.

After recovery, the unresolved attempt remains interrupted. Cancellation,
settlement without termination evidence, retry and cleanup cannot release its
600,000-millisecond compute reservation or 600 synthetic EUR minor units. A real
database restart preserves the complete recovered fingerprint and both reserves.
The optional expiry checks then run against the restored database, waiting for
actual five-minute quote expiry rather than changing its clock.

This extends the earlier budget-only restore proof to populated quote and money
tables. Rates, access, runtime receipts and billed quantities remain synthetic.
It proves neither actual provider acceptance nor charged amounts, Storage
recovery, Linux execution or production disaster recovery. The database clusters
use private Unix sockets with TCP disabled and are stopped in cleanup. Retained
local evidence is under `.verify/quoted-work-restore-20261119/`.

## Production recovery gates still open

This result establishes a local logical database restore, not independent-host
or Supabase disaster recovery. A deployment must separately qualify:

1. An authenticated, encrypted backup inventory with restore permissions,
   retention, recovery point and recovery time requirements. Database dumps do
   not include cluster roles, credentials, host configuration or Storage data.
2. Fencing of the original API, controllers, workers and payment senders before
   any restored service can accept work. A timeout does not prove the original
   worker or provider request stopped. Never run two restored controller-state
   identities concurrently.
3. A consistent database/Storage/controller recovery point, including object
   write fences and unresolved reservations. Never independently rewind these
   systems while controllers remain active or discard uncertainty to regain
   quota.
4. Reconciliation against actual provider acceptance, invoice and payment state
   before replaying delivery work. An old database snapshot can predate an
   irreversible provider action. Neither the budget-only fixture nor the synthetic quote fixture qualifies this.
5. Restore on the intended host and immutable worker images, with real artifact
   retrieval, native reopening, tenant isolation, recovery drills and measured
   recovery objectives. Verify roles and security-definer ownership before
   starting the service.

No remote restore, VM start, payment, deployment or publication is authorized by
this fixture. Full Local/Cloud release readiness remains incomplete.
