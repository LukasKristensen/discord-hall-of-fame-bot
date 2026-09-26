---
name: dev-environment
description: Run things locally for the Hall of Fame bot - the Python interpreter (conda env hof313, not on PATH), the unit tests, a single test, the reaction stress harness and how to read its output, and the server statistics report (synthetic or live database, and what to check when the database cannot be reached). Use when asked to "run the tests", "stress test", "generate the stats/graphs", or whenever a command needs Python.
---

# Development environment

## Python

Python is **not on PATH** (`python` opens the Microsoft Store stub). The project interpreter is the
Anaconda env `hof313` (Python 3.13, same as CI):

```bash
/c/Users/lukas/.conda/envs/hof313/python.exe
```

In PowerShell: `& "C:\Users\lukas\.conda\envs\hof313\python.exe"`. Use it directly; do not search the
disk for `python.exe`, and do not tell the user Python is missing. All conda envs are listed in
`C:\Users\lukas\.conda\environments.txt`. For scripts that print emoji, set `PYTHONIOENCODING=utf-8`,
or Windows' cp1252 console raises `UnicodeEncodeError`.

## Unit tests

From the repo root, exactly as CI runs them:

```bash
/c/Users/lukas/.conda/envs/hof313/python.exe -m unittest discover -s tests -t .
/c/Users/lukas/.conda/envs/hof313/python.exe -m unittest tests.test_commands          # one module
/c/Users/lukas/.conda/envs/hof313/python.exe -m unittest tests.test_commands.<TestClass>.<test_name>  # one test
```

- The "Setting up databases... / Creating ... table" lines are normal output, not errors. Read the
  summary line (`OK` or `FAILED (...)`).
- In PowerShell, output on stderr makes the tool report a failure even when the run passes, so trust
  the summary, not the exit status.
- Tests use fakes (`tests/fakes.py`), so no bot token or Postgres is needed. Never point a test at the
  production database or read production secrets.
- The user often pastes output from PyCharm's test runner. It is the same suite, so find the cause in
  the traceback (a missing import in a test has happened before), fix it, and confirm with the command
  above.

## Stress harness

`tests/stress/reaction_storm.py` drives the real reaction handler with hundreds of concurrent
reactions. It is not part of the unit suite; run it on purpose. `tests/stress/README.md` explains every
number.

```bash
/c/Users/lukas/.conda/envs/hof313/python.exe tests/stress/reaction_storm.py --scenario spread
/c/Users/lukas/.conda/envs/hof313/python.exe tests/stress/reaction_storm.py --scenario storm --events 2000 --concurrency 100
```

Run both `storm` (one viral post: tests the locks) and `spread` (many posts: tests the pool). A healthy
run has `dropped 0` and passes all invariants. If events are dropped, rerun with `--pool-size` well above
`--concurrency`: if the drops disappear, the pool is the bottleneck, not the locks.

## Server statistics report

Run from `src/`. It needs `matplotlib` and `numpy`, which are deliberately not in `requirements.txt`:

```bash
cd src
/c/Users/lukas/.conda/envs/hof313/python.exe server_stats.py --synthetic   # no database, seeded production-scale data
/c/Users/lukas/.conda/envs/hof313/python.exe server_stats.py               # live data
```

Output goes to `graphs/<UTC timestamp>/`, with a CSV next to each chart.

- **Which database** follows `DEV_TEST` in `.env`, like the bot: `DEV_TEST=True` reads the `*_LOCAL`
  variables. Reporting on the live fleet means running without `DEV_TEST`. Do not print or echo
  `.env` values.
- **Connection timeout** (not an authentication error) means the database host is unreachable. The
  database runs on a Raspberry Pi on the user's LAN. Check reachability before touching code:
  ```bash
  powershell -Command "Test-NetConnection <POSTGRES_HOST> -Port 5432"
  ```
  If it fails, the Pi is off or its IP changed (DHCP). Say so, and do not guess another device's IP as
  the replacement.
- **A chart that looks too uniform** (a cohort column always 100%, a flat line) is usually a
  measuring-point bug in `stats/metrics.py`, not real data. Check when each value is sampled. The maths
  lives in `stats/metrics.py` without plotting imports, so it is covered by
  `tests/test_stats_metrics.py`; fix it there with a test.
