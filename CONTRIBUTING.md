# Contributing

Contributions are welcome: bug fixes, features, tests and documentation alike. If you are planning
something larger than a small fix, open an issue or ask in the
[support server](https://discord.gg/r98WC5GHcn) first, so the work fits where the bot is heading.

## License terms

Hall of Fame is source-available, not open source. See [LICENSE](LICENSE) for the full terms. In short:

- You may fork the repository and run the bot on a private test server to develop and test changes.
- You may not host or operate your own instance of the bot, public or private, outside of that.
- By opening a pull request, you agree that your contribution is licensed to the project owner under
  section 4 of [LICENSE](LICENSE).

## Getting started

1. Fork the repository and clone your fork.
2. Install Python 3.13 and the dependencies:

   ```
   pip install -r requirements.txt
   ```

3. Create your own bot in the [Discord Developer Portal](https://discord.com/developers/applications),
   and a local PostgreSQL database to test against.
4. Create a `.env` file in the repository root. It is gitignored, so never commit it:

   ```
   DEV_TEST=True
   DEV_KEY=<your test bot token>
   POSTGRES_HOST_LOCAL=localhost
   POSTGRES_DB_LOCAL=<database name>
   POSTGRES_USER_LOCAL=<database user>
   POSTGRES_PASSWORD_LOCAL=<database password>
   ```

   With `DEV_TEST=True` the bot runs as the development bot and never reads production credentials.

5. Invite your test bot to a private server of your own and run it:

   ```
   python src/main.py
   ```

## Tests

The reaction counting, embed formatting and server config validation are covered by unit tests that use
lightweight stand-ins for Discord and the database, so no bot token or Postgres instance is needed.
The same command runs on every pull request through the `Tests` workflow.

`tests/integration` runs the real SQL against PostgreSQL: the reaction path, joins, the daily task,
Wrapped, data deletion and schema upgrades. It is skipped unless `HOF_TEST_DATABASE_URL` points at a
throwaway database, see [tests/integration/database.py](tests/integration/database.py). The `Tests`
workflow starts one for it.

Two guard tests protect members' privacy: `OptOutWriteGuardTests` lists every repository function that
writes a member's ID and fails on a new one until it is reviewed, and `LogPrivacyTests` fails on a log
that names a member or a server.

For behaviour under load, `tests/stress/reaction_storm.py` drives the real reaction handler with
hundreds of concurrent reactions. It is run by hand, see [tests/stress/README.md](tests/stress/README.md).
What Discord itself accepts is checked by hand on a development bot: the results are in
[tests/MANUAL_TESTS.md](tests/MANUAL_TESTS.md), and [tests/RELEASE_TEST_PLAN.md](tests/RELEASE_TEST_PLAN.md)
lists the flows to check before a release.

## Before opening a pull request

- Run the tests. They use stand-ins for Discord and the database, so no token or Postgres is needed:

  ```
  python -m unittest discover -s tests -t .
  ```

- Add or update tests for the behaviour you changed.
- Members can ask not to be featured, and from then on nothing new may be stored about them. A change
  that writes a member's user ID to the database must leave those members out in the same SQL statement,
  and be added to `OptOutWriteGuardTests` with the reason it is safe.
- Logs are kept in private developer channels, so they say what happened with the server's ID, never a
  member's or a server's name. `LogPrivacyTests` checks this.
- Keep pull requests focused on one change, and describe what it does and why.
- Never include tokens, passwords or other credentials in code, commits or pull request descriptions.

The `Tests` workflow runs on every pull request, and it must pass before anything is merged.
