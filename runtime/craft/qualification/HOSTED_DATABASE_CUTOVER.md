# Local PostgreSQL native catalog and import cutover

`craft/tests/hosted_postgres_cutover.py` exercises the real hosted Store against a
new private PostgreSQL cluster. It uses an existing PostgreSQL installation and
the hosted Python dependencies. It does not download tools, connect to an
existing database, start a VM or contact a provider.

```sh
python3 -I -B craft/tests/hosted_postgres_cutover.py \
  --postgres-prefix /absolute/path/to/existing/postgresql \
  --output /absolute/path/to/new/private/qualification
```

The output directory must not exist. The fixture persists a Unix-socket-only
configuration, rejects TCP authentication and enables login only for its two
disposable runtime roles. Those roles have no superuser or RLS-bypass rights.
It stops its own database in a `finally` block. Preserve the small evidence,
logs and dump before removing a successful qualification directory. Do not
reuse a customer cluster or change a system installation to run this fixture.

## What the database run proves

The local PostgreSQL 17.12 run passes 42 checks with all nine billing migrations
and all twenty-two hosted migrations applied from maintained source:

- Startup refuses earlier schemas and writer versions. PostgreSQL's actual
  constraint representation matches the complete 86-operation source catalog.
  All 86 operation names pass the SQL constraint; optional/unknown names fail.
- Migrations 021 and 022 preserve the complete historical job row. A transaction
  opened before migration 022 cannot write with writer version 15 afterward.
  The old API writer also cannot change an asset owned by its authenticated user.
- All seventeen typed import families and two legacy requests are admitted
  idempotently. Changing Inspect authorization under an existing key is refused.
- Concurrent claims select only the image's declared family. A family-specific
  worker skips incompatible earlier jobs. Image-only and vector-only workers
  cannot claim a legacy import; a worker supporting both can claim it.
- Actual API/coordinator logins enforce membership and RLS. A nonmember cannot
  enumerate jobs, read workspace usage or fetch the published revision. A viewer
  cannot create projects; an administrator cannot masquerade as the runtime.
- Publication refuses a different request digest, incomplete native validation,
  a different family or a different engine without settling the job. Explicit
  retry and repeated settlement preserve the intended request and one revision.
- Nineteen attempts produce exactly nineteen usage events, one revision and
  no active reservations. All attempts are settled and scratch-cleaned. A real
  database stop/start preserves the published revision and 133 fixture
  milliseconds without reopening a TCP listener.

## Explicit evidence boundaries

Native metadata, artifact rows and termination receipts in this fixture are
synthetic. They are identified as such in the source and evidence. The fixture
does not run an engine, verify storage bytes or measure real compute. Its 133
milliseconds are fixed test values, not a benchmark, invoice or cost claim.
The separate real-engine portable import fixture checks native replay.

The fixture uses an explicit `budget_only` policy and confirms no provider usage
is queued. This does not qualify subscription charging, monetary reconciliation,
Stripe delivery or payment. At this cutover checkpoint the retained dump was
evidence, not proof of a tested backup restore or independent-host disaster
recovery. The subsequent [local restore qualification](HOSTED_DATABASE_RESTORE.md)
restores that exact dump and a fresh logical backup into disposable clusters.
Its database-only scope does not qualify independent-host, Storage or provider
recovery.

These are macOS-local PostgreSQL transactions. Linux worker images, Inspect
cross-platform report migration, Video/Motion decoders, container resource and
isolation behavior, live credentials and deployment-specific cutover/recovery
still need their own execution evidence. No production readiness follows from
this database check alone.
