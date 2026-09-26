"""Server statistics reporting for the Hall of Fame bot.

Layered so that the parts worth testing do not need a database or a plotting
backend:

* ``metrics``   - pure calculations over plain dataclasses. No third party imports.
* ``queries``   - the aggregate SQL that fills those dataclasses from Postgres.
* ``synthetic`` - the same dataclasses filled with generated data, for running
  the report without a database.
* ``theme``     - palette and chrome shared by every figure.
* ``charts`` / ``tables`` - the exported figures.
* ``report``    - runs the whole export and writes the index.

``src/server_stats.py`` is the command line entry point.
"""
