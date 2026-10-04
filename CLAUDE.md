# Hall of Fame bot

A Discord bot that reposts messages to a Hall of Fame channel once they pass a reaction threshold, and
recognises the members who land there with leaderboards, profiles and a yearly Wrapped. It runs on a
Raspberry Pi with PostgreSQL for 600+ servers and 260k+ members. Repo:
`LukasKristensen/discord-hall-of-fame-bot`.

## Running things

Python is not on PATH. Use the conda env `hof313` (Python 3.13, same as CI):

```bash
/c/Users/lukas/.conda/envs/hof313/python.exe -m unittest discover -s tests -t .
```

Tests use fakes, so they need no token or database. The stress harness, the stats report and database
troubleshooting are in the `dev-environment` skill.

## Where things live

| Path | What |
|---|---|
| `src/main.py` | Startup, event handlers, every slash command (`@tree.command`), `update_setting`, `send_error` |
| `src/events.py` | Reaction and message events, the daily task |
| `src/utils.py` | Posting to the board, embeds, `validate_message`, leaderboards, logging |
| `src/message_reactions.py` | Reaction counting methods and the emoji whitelist |
| `src/commands.py` | `/help` and `/get_server_config` embeds, command helpers |
| `src/repositories/` | All SQL, one module per table. `server_config_repo.py` owns the settings table |
| `src/classes/server_class.py` | The in-memory server config, served to the reaction path without DB lookups |
| `src/translations/messages.py` | User-facing text |
| `src/enums/command_refs.py` | Clickable mentions for every command (see below) |
| `src/validation.py` | Input bounds and emoji parsing |
| `src/environment.py` | Dev versus production (`DEV_TEST=True`) and production-only secrets |
| `src/server_stats.py`, `src/stats/` | Developer-only statistics report, not part of the bot |

## Project rules

- **It is Hall of Fame, not a starboard bot.** It counts every emoji, offers several counting
  methods, keeps reply context, and adds recognition on top. Never describe it as a starboard in copy.
- **Production secrets load only in production.** Gate any live credential (bot token, Top.gg and
  other list-site keys, production DB) behind `environment.py`. Never read `.env` values into output.
- **`/feedback` text is private.** Never quote it verbatim in issues, release notes or anywhere
  public; paraphrase it with no names or servers.
- **CI must be green before a merge**, and only the user merges.
- **Behaviour changes hit every server on deploy.** Changing counting, defaults or post layout needs a
  migration path for existing rows (`ADD COLUMN IF NOT EXISTS`) and a note on who is affected.

## Command mentions

Every slash command has a clickable mention in `src/enums/command_refs.py`, for example
`SET_HALL_OF_FAME_CHANNEL = "</set_hall_of_fame_channel:1393576242237804768>"`.

- In bot code, use the constant (`command_refs.LEADERBOARD`), never a hardcoded `</name:id>`.
- Anywhere else a command should be clickable (announcements, issue replies), copy it from that file.
- Check the name in a constant against `@tree.command(name=...)`, since constants go stale on renames.
  Add or update the constant whenever a command is added or renamed.
- Never read the bot token or call the Discord API for an ID. Ask the user; they copy it with Developer
  Mode on, under Server Settings > Integrations > Hall of Fame.

## Skills

| Task | Skill |
|---|---|
| Add or change a command or server setting | `add-command` |
| Run tests, the stress harness or the stats report | `dev-environment` |
| Check a branch or PR before it reaches production | `production-check` |
| Work through review comments on a PR | `address-pr-review` |
| Turn feedback or bugs into GitHub issues | `report-issue` |
| README changelog and Discord announcement for a release | `release-notes` |
