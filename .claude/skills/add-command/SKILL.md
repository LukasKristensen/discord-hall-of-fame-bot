---
name: add-command
description: Add or change a Hall of Fame slash command or per-server setting end to end - the command in main.py, the database column, ServerClass, command_refs, /help, /get_server_config, input validation, reply wording, tests and the README. Use when asked to add a command, add a server option or toggle, rename a command, or improve how an existing command validates input or answers.
---

# Add or change a command or server setting

A setting touches many files, and missing one only shows up in production: a column that is never
loaded, a command absent from `/help`, a mention that links nowhere. Go through the list for every
change and say in the report which items did not apply.

## Command checklist

1. **`src/main.py`** - `@tree.command(name=..., description=...)`. Copy the shape of an existing
   command of the same kind (a toggle like `require_image_or_video` is the shortest template):
   - `if not await ensure_bot_is_loaded(interaction): return`
   - configuration commands: `if not await check_if_user_has_manage_server_permission(interaction): return`
   - `@app_commands.describe(...)` for every option, and `app_commands.Range[int, MIN, MAX]` with the
     bounds in `validation.py` for numbers. Check the bounds again in the handler with
     `validation.out_of_range_message`, since a client can send anything.
   - Refusals and errors go through `send_error` (ephemeral). Successful setting changes go through
     `update_setting`, which answers "already set" instead of writing the same value again.
   - Finish with `utils.logging(..., log_level=log_type.COMMAND)` like the other commands.
2. **Reply text in `src/translations/messages.py`**, not inline. Say what the new value means for the
   server and which command changes related behaviour. Mention other commands through `command_refs`.
3. **`src/enums/command_refs.py`** - add the mention constant. The ID only exists after the bot has
   synced the command globally, so ask the user for it and leave a clear TODO in the report, never a
   made-up ID. Check the name in the constant matches the registered name.
4. **`/help`** - add the command to the right group in `commands.build_help_embed`.
5. **README** - the Commands table for its group, and any section that explains the behaviour
   ("How reactions are counted", the FAQ).

## Extra checklist for a new server setting

1. **Schema** in `src/repositories/server_config_repo.py`:
   - the column in `CREATE TABLE IF NOT EXISTS server_configs`, **and**
     `ALTER TABLE server_configs ADD COLUMN IF NOT EXISTS <col> <TYPE> DEFAULT <default>` for tables
     that already exist in production;
   - the name in `ALLOWED_COLUMNS`, or `update_server_config_param` refuses it;
   - `insert_server_with_parameters` and every SELECT that builds a `ServerClass`
     (`get_server_classes` and friends). New columns go last, and rows are read by index, so update the
     indexes and keep the `row[n] if len(row) > n else <default>` fallback.
2. **`src/classes/server_class.py`** - constructor argument and attribute. If the reaction path needs
   it, add it to `reaction_config()`; that object is served from memory, so the command must update it
   (`update_setting` does this through `setattr`).
3. **Defaults for new servers** in `utils.create_database_context` (the `ServerClass(...)` it builds).
4. **`src/db_backup.py`** - the column lists it copies.
5. **Where the setting takes effect** - usually `utils.validate_message` or `message_reactions.py`.
6. **`/get_server_config`** - add a line in `commands.build_server_config_embed`, in the same group as
   `/help`, with the command that changes it.

## Tests

Add to or update:
- `tests/test_server_config_repo.py` (row mapping), `tests/test_server_class.py`,
  `tests/test_commands.py` (help and config embeds), and the test for the code path the setting
  affects, for example `tests/test_validate_message.py`;
- the helpers that build a full server config by hand also need the new argument: find them with
  `grep -rn "require_image_or_video=" tests` (today `tests/test_validate_message.py` and
  `tests/stress/reaction_storm.py`).

Run the whole suite with the `hof313` interpreter (see `dev-environment`).

## Before finishing

- Leave everything as uncommitted edits.
- Tell the user the command needs its global sync (happens on bot start) before the ID exists, and ask
  for the ID if a mention is needed.
- Add a line to the next release's Development Log only if the user asks; the `release-notes` skill
  collects changes from git at release time.
