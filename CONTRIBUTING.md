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

## Before opening a pull request

- Run the tests. They use stand-ins for Discord and the database, so no token or Postgres is needed:

  ```
  python -m unittest discover -s tests -t .
  ```

- Add or update tests for the behaviour you changed.
- Keep pull requests focused on one change, and describe what it does and why.
- Never include tokens, passwords or other credentials in code, commits or pull request descriptions.

The `Tests` workflow runs on every pull request, and it must pass before anything is merged.
