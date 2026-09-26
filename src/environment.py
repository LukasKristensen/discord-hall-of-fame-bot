"""Which environment the bot is running in, and which secrets belong to it.

The bot token and the database credentials have always been chosen per environment, so a
development run connects to a local database with a development token. The listing site keys were
not: they were read into module level variables the moment the module was imported, in every
environment. Nothing outside production has any use for them, and a process that never needs a live
credential should not be holding one.

This module is the single place that decides what counts as production, so that the answer cannot
drift between the bot and the services it reports to.
"""

import os
from dotenv import load_dotenv

load_dotenv()

DEVELOPMENT_FLAG = "DEV_TEST"


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
