"""Which environment the bot is running in, and which secrets belong to it.

The bot token and the database credentials have always been chosen per environment, so a
development run connects to a local database with a development token. The listing site keys were
not: they were read into module level variables the moment the module was imported, in every
environment. Nothing outside production has any use for them, and a process that never needs a live
credential should not be holding one.

This module is the single place that decides what counts as production, so that the answer cannot
drift between the bot and the services it reports to. It is also the only Python code that reads the
.env file, because gating the readers is not enough: loading the whole file would still put every
live credential into the process environment of a development run.

The Pi's deployment scripts, src/run.sh and src/pg_backup.sh, export the whole .env themselves before
starting the bot or a backup. That is intended: they only ever run in production, where every value
is needed. A development run goes through this module and never through them.
"""

import os
from dotenv import dotenv_values

DEVELOPMENT_FLAG = "DEV_TEST"

# Variables only the live bot has any use for. A development run never loads them from .env: it has
# its own token (DEV_KEY) and its own database (the *_LOCAL variables)
PRODUCTION_ONLY_VARIABLES = frozenset({
    "KEY",
    "TOPGG_API_KEY",
    "DISCORD_BOT_LIST_API_KEY",
    "MONGODB_URI",
    # The name the migrations read the same production Mongo database under
    "MONGO_URI",
    "POSTGRES_HOST",
    "POSTGRES_DB",
    "POSTGRES_USER",
    "POSTGRES_PASSWORD",
})


def load_environment(values: dict = None):
    """
    Copy the .env file into the process environment, leaving out the production-only variables when
    the run is a development one.

    Like python-dotenv's own loader, a variable already set in the environment is left alone, and
    the file is found the same way, by searching upward from this module's folder.
    :param values: The variables to load, read from the .env file when not supplied
    """
    values = dotenv_values() if values is None else values
    development = os.environ.get(DEVELOPMENT_FLAG, values.get(DEVELOPMENT_FLAG)) == "True"
    for name, value in values.items():
        if value is None or name in os.environ:
            continue
        if development and name in PRODUCTION_ONLY_VARIABLES:
            continue
        os.environ[name] = value


load_environment()


def is_development() -> bool:
    """
    :return: True when the bot is running as the development bot
    """
    return os.getenv(DEVELOPMENT_FLAG) == "True"


def is_production() -> bool:
    """
    :return: True when the bot is running as the live bot
    """
    return not is_development()


def production_secret(name: str):
    """
    Read a credential that only the live bot has any use for.

    Outside production this returns None without reading the variable, so that a development run
    cannot end up holding a live credential and cannot accidentally authenticate as the real bot.
    :param name: The environment variable holding the credential
    :return: The credential in production, otherwise None
    """
    if is_development():
        return None
    return os.getenv(name)


def database_settings() -> dict:
    """
    The PostgreSQL connection settings for this environment: the local database in development and
    the production one otherwise. Everything that connects goes through this, so that no part of a
    development run can reach the production database.
    :return: Keyword arguments for psycopg2.connect or a psycopg2 pool
    """
    prefix = "_LOCAL" if is_development() else ""
    return {
        "host": os.getenv(f"POSTGRES_HOST{prefix}"),
        "database": os.getenv(f"POSTGRES_DB{prefix}"),
        "user": os.getenv(f"POSTGRES_USER{prefix}"),
        "password": os.getenv(f"POSTGRES_PASSWORD{prefix}"),
    }
