---
name: policy-check
description: Check whether the Hall of Fame Privacy Policy (PRIVACY.md) or Terms of Service (TERMS.md) need updating after a feature or behaviour change, and update them. Run it every time a feature is implemented, before reporting the work as done, and as part of production-check. Also use when asked "does the privacy policy need updating", "update the ToS", or when a change stores, reads, shares or shows data in a new way.
---

# Privacy policy and terms check

`PRIVACY.md` and `TERMS.md` are the documents the App Directory, top.gg and the README link to. Discord's
developer policy expects the privacy policy to describe what the bot actually does with data, so a
feature that stores, reads, shares or shows something new can make the policy wrong the day it ships.

Run this after every feature or behaviour change, and always say the outcome in the report, including
"no change needed" and why.

## 1. Decide whether anything changed

Read the diff and answer each question. A yes points at the section to update.

| Question | Where it shows up in the code | Section |
|:---|:---|:---|
| Is something new stored about a server, member or message? | New table or column in `src/repositories/` | Privacy 1 |
| Does the bot read something it did not before? | Intents in `main.py`, new fields read from messages or members | Privacy 2 |
| Is existing data used for a new purpose? | Data shown in another server or outside Discord, cross-server totals, new reports | Privacy 3 |
| Does data go to anyone new? | New list site in `src/api_services/`, a website or redirect host, an analytics service, a new webhook | Privacy 4 |
| Do logs carry new personal fields? | New arguments to `utils.logging` with usernames, IDs or message text | Privacy 1 (Logs) |
| Is a new table cleaned up when the bot leaves? | `events.guild_remove` and the repo delete functions | Privacy 5 |
| Can members see, export or delete something new? | Opt-ins, opt-outs, deletion commands | Privacy 6 |
| Is the bot used in a new way or place? | User installs, new command contexts, paid or supporter features | Terms 1, 4 |
| Is content shown somewhere new? | Public web pages, a cross-server feed, image cards shared outside Discord | Terms 3, Privacy 3 |
| Did the license change? | `LICENSE` | Terms 6 |

No change is needed for wording, layout, buttons, footers, bug fixes, performance work or settings
that only change behaviour inside the server, as long as no new data is stored, read or sent.

## 2. Update the documents

- Edit only the sections the answers point to. Describe what the bot does, in plain words, and never
  promise more than the code does (for example "deleted immediately" only if `guild_remove` deletes it).
- Set the **Effective date** at the top of each file you change to the day of the change.
- Keep the two files consistent with each other and with the README's "Privacy and terms" section.
- A change that gives data to someone new, uses it for a new purpose, or limits what users can do is
  significant: note it for the support server announcement through `release-notes`.

## 3. Report

End the feature's report with one line, for example:

- "Policy check: no change needed, the footer stores and sends nothing new."
- "Policy check: PRIVACY.md section 1 and 5 updated for the new badges table, effective date set to
  18 October 2026. Worth announcing: no."

Leave the edits uncommitted with the feature, so they ship in the same pull request.
