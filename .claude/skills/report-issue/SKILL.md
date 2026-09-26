---
name: report-issue
description: Create GitHub issues on LukasKristensen/discord-hall-of-fame-bot from user feedback (/feedback screenshots or text), bug findings, or feature ideas. Use when asked to "create an issue", "report this", "file these as issues", or when handed feedback submissions to turn into issues.
---

# Report an issue

Turn feedback, bugs, or feature ideas into GitHub issues on `LukasKristensen/discord-hall-of-fame-bot`.

## Rules

- **Never quote user feedback verbatim.** Feedback that arrives through the bot's `/feedback` command was
  sent privately. Paraphrase it in neutral wording and start the request with "Suggested via user
  feedback: ...". Leave out usernames, server names, IDs and anything else that identifies the submitter.
- **Get it right before creating.** GitHub keeps the edit history of an issue body, and anyone who can see
  the issue can read it. Editing a leaked quote out afterwards does not remove it. Draft carefully first.
- **One issue per distinct request.** If several pieces of feedback arrive together, create separate
  issues unless they are clearly the same request.
- **Never delete issues.** If an issue has to go, give the user the command to run themselves:
  `gh issue delete <n> -R LukasKristensen/discord-hall-of-fame-bot --yes`.
- Do not use em dashes in titles or bodies. Use a plain hyphen.

## Steps

1. **Check for duplicates.** Run `gh issue list -R LukasKristensen/discord-hall-of-fame-bot --state all --limit 50`
   and search for related open or closed issues. If one already covers the request, tell the user instead
   of creating another.
2. **Check the code.** Grep the repo to see whether the feature already exists or partly exists (for
   example, the emoji whitelist commands). If it exists but is undocumented, say so in the issue and
   suggest documenting it. For bugs, find the relevant file and function and cite it.
3. **Pick a label.** `enhancement` for feature requests, `bug` for defects, `documentation` for docs-only
   gaps. Use `gh label list` if unsure. Every issue gets at least one label.
4. **Write the issue** using the matching template below. Keep the title short and descriptive (sentence
   case, no "Feature request -" prefix).
5. **Create it** with a heredoc body:

   ```bash
   gh issue create -R LukasKristensen/discord-hall-of-fame-bot --label enhancement --title "..." --body "$(cat <<'EOF'
   ...
   EOF
   )"
   ```

6. **Report back** with a markdown link per issue, written as
   `[Title (LukasKristensen/discord-hall-of-fame-bot#N)](https://github.com/LukasKristensen/discord-hall-of-fame-bot/issues/N)`.

## Templates

### Feature request (`enhancement`)

```markdown
## Request

Suggested via user feedback: <one or two sentences paraphrasing what they want and why>.

- <concrete capability>
- <concrete capability>

<Current behaviour, and any related existing commands or code.>
```

Drop "Suggested via user feedback" when the idea did not come from a user.

### Bug (`bug`)

```markdown
## Problem

<What goes wrong, pointing at the file and function, e.g. `update_leaderboard` in `src/utils.py`.>

## Who is affected

<Which servers or configurations hit it.>

## Steps to reproduce

1. ...
2. ...

## Possible fixes

- ...
```
