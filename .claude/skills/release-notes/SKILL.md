---
name: release-notes
description: Prepare a Hall of Fame bot release - update the README (Development Log and any outdated docs) and draft the Discord announcement for the community, covering everything done since the last feature release (the last major or minor version bump). Use when asked to "write release notes", "draft the update post", "announce version X", "changelog for the support server", or similar.
---

# Release notes

Every release request produces two things from the same list of changes:

1. **README update** - a new version section in the README "Development Log", plus fixes to any part
   of the README the release made outdated. The reader is anyone browsing the repo, so it can be more
   complete and a bit more technical.
2. **Discord announcement** - the update post for the Hall of Fame support server. The reader is a
   server admin or member, not a developer: every line should say what changed for them.

## Rules

- **README is an uncommitted edit.** Edit `README.md` in the working tree and leave staging and
  committing to the user.
- **Discord post is ready to paste.** The user copies it and posts it manually, so never post, send
  or publish it yourself. Return it in a ```` ```md ```` code fence containing exactly the message
  text and nothing else (see "Paste-ready checklist").
- **Both must agree.** Every item in the Discord post must be in the README section. The README may
  have more (tests, CI, refactors), the Discord post may not.
- **Stay under 2000 characters** (Discord's message limit). If it does not fit, trim the "Behind the
  scenes" section first, then merge small items. If it still does not fit, split it into two messages
  at a section boundary and say so.
- **User impact, not commit messages (Discord).** Rewrite "Batch the leaderboard lookup" as "/leaderboard loads
  faster on large servers". Drop changes nobody outside the codebase would notice (tests, CI, refactors,
  review-fix commits) or fold them into one "Behind the scenes" line.
- **Call it Hall of Fame**, never a "starboard" bot.
- **No verbatim user feedback.** If a change came from `/feedback`, say "Requested by the community"
  at most. No usernames, server names or quotes.
- No em dashes. Use a plain hyphen.
- Only include changes that are actually in the release. If a commit is ambiguous, read the diff
  (`git show <hash>`) before describing it rather than guessing from the message.

## Steps

1. **Find the release range.** An announcement covers everything done since the last *feature*
   release, meaning the last time the major or minor number changed (2.0.0, 2.1.0, ...). Patch
   releases in between (2.1.1, 2.1.2, ...) are never announced on their own, so their changes all
   belong in the next announcement.
   - The version lives in `VERSION` in `src/constants/version.py`. There are no git tags, so list its
     history:
     ```bash
     git log --format="%h %ad %s" --date=short -G 'VERSION =' -- src/constants/version.py
     git show <hash>:src/constants/version.py
     ```
   - The **target** is the version being announced. If the user did not name it, it is the next minor
     version after the last feature release (2.1.0 -> 2.2.0).
   - The **base** is the most recent commit that set `VERSION` to a feature release *lower* than the
     target. If `VERSION` has already been bumped to the target, skip that commit and use the one before.
   - The range is `<base>..HEAD` on the branch being released. If that branch is not merged into
     `main` yet, say so in the report.
   - Cross-check with the README "Development Log": the section for the base version (e.g. `### 2.1`)
     lists what was already announced. Leave those items out even if a commit in the range touches them.
     If a section for the target version already exists (the skill ran before), update that section
     instead of adding a second one.
   - Tell the user the base commit, its version and date, and the number of commits in the range
     before writing the draft.
2. **Collect the changes.** Read every commit in the range, not just the most recent ones.
   ```bash
   git log --no-merges --format="%h %ad %s%n%b" --date=short <base>..HEAD
   gh pr list -R LukasKristensen/discord-hall-of-fame-bot --state merged --search "merged:>=<base date>" --limit 100
   gh issue list -R LukasKristensen/discord-hall-of-fame-bot --state closed --search "closed:>=<base date>" --limit 100
   ```
   Merged PR descriptions and closed issues often explain the "why" better than commit messages.
   Several commits often make up one change (a feature plus its review fixes); merge them into one
   bullet.
   Also read [upcoming.md](upcoming.md): the user's own notes for the next release (announcements,
   community news, roadmap). Every item there must end up in the Discord post. Items about the code
   also go in the README; community news and personal notes do not.
3. **Update the README.**
   - **Development Log:** add `### {major}.{minor}` directly under `## Development Log`, above the
     previous version, in the same style as the existing sections (see "README Development Log").
   - **Rest of the README:** for every change in the range, check whether the README now says
     something wrong or is missing something. Typical cases: a new or renamed command missing from
     the "Commands" tables, a changed default (threshold, limits) in "Quick start" or the FAQ, a new
     setting that deserves a line in "How reactions are counted". Fix those in place, keeping the
     existing tone and structure, and do not rewrite sections that are still accurate.
4. **Write the Discord post.**
   - **Sort each change** into one of the sections in "Discord template" below. Skip empty sections.
   - **Link commands.** Mention slash commands as clickable Discord mentions `</name:command_id>`,
     copied from `src/enums/command_refs.py` (see "Command mentions"). Check the name against
     `@tree.command(name=...)` in `src/main.py`, since commands get renamed.
   - **Fill in the template**, then check the character count
     (`python -c "import sys; print(len(sys.stdin.read()))"` on the text, or count it yourself).
5. **Report back** with:
   - what changed in the README (the new Development Log section, plus a one-line list of any other
     README sections you corrected);
   - the Discord post in a code fence (one fence per message if it had to be split, labelled
     "Message 1", "Message 2" above each fence);
   - after the post, a short list of: screenshots to attach, commands written as plain `/name`
     because they have no correct entry in `command_refs.py`, and anything you left out or were unsure about.

   If `VERSION` in `src/constants/version.py` does not match the release, offer to bump it (as an
   uncommitted edit). Once the user confirms the announcement is posted, offer to clear the list in
   `upcoming.md`.

## README Development Log

Match the existing sections in `README.md`:

```markdown
### 2.2
- [x] Added /set_hall_of_fame_channel to pick the Hall of Fame channel manually.
- [x] Fixed Hall of Fame posts failing when the message that was replied to had been deleted.
- [x] The leaderboard updates each post in a single edit instead of three, cutting its daily rate limit cost.
- [x] Added a unit test suite and a Tests workflow that runs on every pull request.
```

- Heading is `major.minor` only, no patch number. Patch releases are folded into it.
- One `- [x]` bullet per change, one full sentence, past tense ("Added", "Fixed") or present tense for
  behaviour ("The leaderboard updates ..."). Commands written as plain `/name`, no Discord mentions.
- Order: new features, then fixes, then performance and stability, then tests, tooling and docs.
- Internal changes are welcome here, but still merge a feature and its follow-up fixes into one bullet.

## Discord template

```md
## :loudspeaker: Hall of Fame {version} is live! @everyone

{One or two sentences on the headline change of this release and why it matters.}

### :sparkles: New
- **{Feature name}** - {what it does, with the </command:id> to use it}.
   - {optional detail, or "See the attachment below."}

### :trophy: Hall of Fame posts
- {Changes to how messages get into, and look in, the Hall of Fame channel.}

### :hammer_and_wrench: Improvements
- {Existing commands or behaviour that got better: faster, clearer, more flexible.}

### :bug: Fixes
- {Fixed {symptom the user saw}, e.g. "Long messages no longer fail to post; they are cut off at 1021 characters with ..."}

### :gear: Behind the scenes
- {Stability, logging, performance, one line each, at most three lines.}

### :speech_balloon: Community
- {News that is not a code change, usually from upcoming.md, e.g. where to report bugs or follow progress.}

### :calendar: {Optional: roadmap or personal note}
{Short, human, first person. Only when the user provides it.}

-# Questions or ideas? Use `/feedback` or report them on GitHub Issues. Enjoying the bot? `/vote` for it on top.gg.
```

### Section guide

| Section | Goes here | Example |
| --- | --- | --- |
| New | New commands, settings or features | Added `/set_hall_of_fame_channel` |
| Hall of Fame posts | Threshold logic, post layout, reactions, channel permissions | Adaptive default threshold on join |
| Improvements | Better wording, speed, UX of existing commands | `/user_profile` explains the 24h window |
| Fixes | Bugs users could see | Reply context missing in embeds |
| Behind the scenes | Logging, error handling, DB, cleanup | Better database error logging |
| Community | Non-code news, usually from `upcoming.md` | Report bugs and track progress on GitHub Issues |

Order items inside a section by how many users notice them, most first. Start each bullet with a verb
in the past tense ("Added", "Fixed", "Improved") or with the feature name in bold for new features.

## Discord formatting

- `##` and `###` render as headings, `-#` renders as small grey subtext, `**bold**` for feature names.
- Emoji shortcodes (`:sparkles:`) work when pasted by a user. Keep one emoji per heading, none in bullets.
- Nested bullets need three spaces of indent.
- Put `@everyone` in the title line only, once.
- Attachments (screenshots, GIFs) cannot be in the text; write "See the attachment below." and remind
  the user which screenshot to attach.

## Paste-ready checklist

Before handing the post back, check that the text inside the fence can be pasted and sent as is:

- No `{...}` template placeholders, `</name:ID>` stubs, TODOs or notes to the user. Anything the
  user needs to know goes outside the fence.
- No triple backticks inside the post, since they would end the fence early. Single backticks are fine.
- Only standard Unicode emoji shortcodes (`:sparkles:`, `:bug:`), which Discord converts on send.
  Custom server emojis only if the user supplied them.
- Links written out in full (`https://github.com/...`), wrapped in `<...>` if the preview embed
  should be suppressed.
- Each message (or each part, if split) is under 2000 characters.

## Command mentions

A mention looks like `</set_hall_of_fame_channel:1393576242237804768>`. Global command IDs stay the
same until a command is deleted or renamed.

The bot already keeps a ready-made mention for every command in `src/enums/command_refs.py`
(`SET_HALL_OF_FAME_CHANNEL = "</set_hall_of_fame_channel:1393576242237804768>"`). Copy mentions from
there. Before using one, check that the name inside it matches `@tree.command(name=...)` in
`src/main.py`; a constant can go stale when a command is renamed.

If a command has no constant, or its constant does not match the registered name, write it as plain
`/name` (with backticks) so the post still works when pasted, and list it after the post so the user
can send the correct ID. They can get an ID in Discord with Developer Mode on, under Server Settings >
Integrations > Hall of Fame. Do not read the bot token or call the Discord API to look IDs up. When
the user supplies an ID, fix or add the constant in `command_refs.py` (an uncommitted edit), since the
bot's own messages link commands through it too.
