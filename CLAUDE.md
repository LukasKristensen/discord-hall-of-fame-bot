# Hall of Fame bot

## Command mentions

Every slash command has a ready-made clickable Discord mention in `src/enums/command_refs.py`, for
example `SET_HALL_OF_FAME_CHANNEL = "</set_hall_of_fame_channel:1393576242237804768>"`.

- In bot code, link a command through its constant (`command_refs.LEADERBOARD`), never a hardcoded
  `</name:id>` string.
- Anywhere else a command should be clickable (release announcements, issue replies, docs meant for
  Discord), copy the mention from that file.
- Check the name in a constant against `@tree.command(name=...)` in `src/main.py` before relying on
  it, since a constant can go stale when a command is renamed. When a command is added or renamed,
  add or update its constant as well.
- Never read the bot token or call the Discord API to look up an ID. Ask the user; they can copy it
  in Discord with Developer Mode on, under Server Settings > Integrations > Hall of Fame.
