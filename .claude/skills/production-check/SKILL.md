---
name: production-check
description: Review a Hall of Fame branch or pull request for anything that could break the live bot once it is merged and deployed - schema changes, dependencies, environment and secrets, connection pool and event loop behaviour, message templates, and behaviour changes existing servers will notice. Use when asked to "double check the PR", "make sure nothing breaks in production", "is this ready to deploy", or before the user merges a large branch.
---

# Production readiness check

The live bot runs on a Raspberry Pi (Compute Module 5) with PostgreSQL, serving 600+ servers and
260k+ members. It restarts through `src/run.sh` and a crash-restart loop in `main.py`. A mistake here
reaches every server at once, so this check looks for what unit tests do not catch.

This is a review. Report findings first and fix only what the user agrees to, as uncommitted edits.

## Steps

1. **Scope.** Diff the branch against `origin/main`, and find its PR and check status.
2. **Tests.** Run the full suite with the `hof313` interpreter (see `dev-environment`). CI has three
   checks: Unit Tests, Validation Checks (invalid imports) and CodeQL. Say which you ran yourself and
   which you are taking from CI.
3. **Go through the areas below** and read the diff for each. Skip areas the branch does not touch.
4. **Report** in two groups:
   - **Would break or degrade production:** file:line, the failure scenario, and the fix.
   - **Intended but visible behaviour changes:** what server admins or members will notice after
     deploy, and which servers it affects (for example only servers that use one counting method).
   End with what you could not verify.

## Areas

**Database schema**
- New columns need `ALTER TABLE ... ADD COLUMN IF NOT EXISTS ... DEFAULT ...` next to the
  `CREATE TABLE IF NOT EXISTS` in the repository, because production tables already exist.
- New columns must also be in `ALLOWED_COLUMNS` in `server_config_repo.py`, in every SELECT that
  builds a `ServerClass` (row indexes shift), and in `db_backup.py`.
- One-off data changes go in `src/migrations/`. Check that they are idempotent and say whether the user
  has to run one by hand before or after deploy.
- Upserts need the matching primary key or unique constraint to exist in production, not only in the
  test fakes.

**Dependencies and environment**
- Every third-party import under `src/` that the bot loads must be in `requirements.txt`. Compare
  against `main` before calling one missing a regression: `matplotlib` and `numpy` are for the stats
  report only and are deliberately left out.
- Development versus production is decided by `DEV_TEST == "True"` in `environment.py`. Production-only
  secrets (the bot token, Top.gg and other list-site keys, production database credentials) must only be
  read in production. A new secret needs the same gating.
- The Python version is pinned at 3.13 in CI; watch for syntax or library use that needs something
  newer.

**Concurrency and the database pool**
- psycopg2 calls block the event loop. Look for new database work on the reaction path, and for loops
  over all guilds that do not go through `concurrency.run_in_batches` with a timeout.
- Connections come from `get_db_connection` (a semaphore in front of the pool). Check that every new
  path returns its connection, and that a failed statement is rolled back before the connection is
  reused. An aborted transaction on a shared connection fails everything after it.
- Anything created at import time and bound to an event loop (semaphores, locks) must be recreated when
  the crash-restart loop starts a new loop.
- If the pool size changed, check that Postgres `max_connections` still covers the bot plus the other
  scripts that connect (`hof_wrapped`, `db_backup`, the monthly snapshot).

**Discord behaviour**
- Required permissions: a new API call may need a permission servers never granted. Commands should say
  what is missing instead of failing.
- Rate limits: count edits and sends per guild in daily jobs. Prefer one edit over several.
- Command changes: a new or renamed command needs a `command_refs.py` constant (the ID only exists
  after the global sync, so ask the user for it), and changed option names or types change how the
  command appears to every server after `tree.sync()`.
- Message templates: every `messages.X.format(...)` call must pass exactly the placeholders the
  template uses, and every `messages.X` and `command_refs.X` referenced must exist. Check all call
  sites, including multi-line ones.

**Behaviour existing servers will notice**
- Changes to reaction counting, thresholds, defaults, whitelist matching or post layout apply to every
  server on deploy. Work out who is affected and whether posts already on the board will change the next
  time they update. A correct fix can still surprise admins, so list it for the release notes.

**Tools that run outside the bot**
- `server_stats.py` and the `stats` package must stay importable without a display (headless
  matplotlib) and must keep their public entry points.
