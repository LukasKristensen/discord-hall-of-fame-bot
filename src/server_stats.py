"""Export the server statistics report.

Run from the ``src`` directory:

    python server_stats.py                  # read Postgres, export to ../graphs/<timestamp>
    python server_stats.py --synthetic      # no database, generated data at production scale
    python server_stats.py --out ./somewhere

The figures themselves live in ``stats/``; this file only decides where the data
comes from and where the export goes.

Rendering needs ``matplotlib`` and ``numpy``. They are deliberately not in
``requirements.txt``: the bot never plots anything, and this is a developer tool
run by hand, so the deployment does not carry a plotting stack. Install them into
the working environment before running the report::

    pip install matplotlib numpy

``stats.metrics``, which holds every calculation the figures rest on, imports
neither, so the unit tests cover the maths without them.
"""

import argparse
import os
import sys

from dotenv import load_dotenv

# Make the export location independent of the current working directory.
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
PROJECT_ROOT = os.path.abspath(os.path.join(SCRIPT_DIR, os.pardir))
DEFAULT_GRAPH_ROOT = os.path.join(PROJECT_ROOT, "graphs")


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Generate the report from seeded synthetic data instead of Postgres.",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=20260908,
        help="Seed for --synthetic, so a run can be reproduced exactly.",
    )
    parser.add_argument(
        "--out",
        default=DEFAULT_GRAPH_ROOT,
        help="Root folder for exports. A timestamped subfolder is created inside it.",
    )
    return parser.parse_args(argv)


def database_settings():
    """The connection settings for the environment the report runs in.

    Chosen the same way the bot chooses them: a development run (``DEV_TEST=True``)
    reads the local database through the ``*_LOCAL`` variables and never loads the
    production credentials. Reporting on the live fleet means running it with the
    production environment.
    """
    load_dotenv(os.path.join(PROJECT_ROOT, ".env"))
    import environment

    prefix = "_LOCAL" if environment.is_development() else ""
    return {
        "host": os.getenv(f"POSTGRES_HOST{prefix}"),
        "database": os.getenv(f"POSTGRES_DB{prefix}"),
        "user": os.getenv(f"POSTGRES_USER{prefix}"),
        "password": os.getenv(f"POSTGRES_PASSWORD{prefix}"),
    }


def connect():
    """Open the Postgres connection the report reads from."""
    import psycopg2

    return psycopg2.connect(**database_settings())


def load_dataset(args):
    """Either the live fleet or a seeded stand-in for it."""
    if args.synthetic:
        from stats import synthetic

        print("Building synthetic dataset (no database connection)")
        return synthetic.build_dataset(seed=args.seed)

    from stats import queries

    connection = connect()
    try:
        print("Loading dataset from Postgres")
        return queries.load_dataset(connection)
    finally:
        connection.close()


def main(argv=None):
    # Imported here rather than at the top, as it needs matplotlib: this keeps the rest of the
    # module, the database settings included, importable and testable without the plotting stack
    from stats import report

    args = parse_args(argv)
    dataset = load_dataset(args)

    if not dataset.servers:
        print("No servers found; nothing to export.")
        return 1

    out_dir = report.create_output_dir(args.out)
    print(f"Exporting {len(dataset.servers):,} servers to {out_dir}")
    outputs = report.render(dataset, out_dir)
    print(f"Done: {len(outputs)} figures plus {report.INDEX_FILENAME}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
