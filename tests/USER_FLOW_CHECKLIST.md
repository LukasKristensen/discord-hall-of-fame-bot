# User flow checklist

Every flow a server admin, a member or the bot itself goes through, for evaluating a release as a whole.
[RELEASE_TEST_PLAN.md](RELEASE_TEST_PLAN.md) covers what one release changed; this covers everything,
so a regression in an older flow is caught too.

Run it on the development bot (`DEV_TEST=True`) with its own database, never production. You need a server
where you have Manage Server, a second account without it, and a second server for the across-server
flows. Tick each box and note anything wrong next to it. Results worth keeping go in
[MANUAL_TESTS.md](MANUAL_TESTS.md).

The **Covered by** column names the automated tests for the flow. When they pass, the manual step only has
to confirm what they cannot: how Discord renders it, real permissions, and timing.

<br>

## 0. Automated runs

- [ ] Unit and integration suite with `HOF_TEST_DATABASE_URL` set, so nothing is skipped (see the
      `dev-environment` skill): all pass, 0 skipped
- [ ] `tests/stress/reaction_storm.py --scenario spread`, `--scenario storm --events 2000 --concurrency 100`
      and `--scenario mixed`: each ends with OK and `dropped 0`
- [ ] CI is green on the pull request: Tests (unit and database) and Validation Checks

<br>

## 1. Installing and setting up

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | Invite the bot with the default permissions: it creates `#hall-of-fame`, posts the welcome message with Set up, Troubleshoot, Support server and Vote, and picks a threshold from the member count | `test_server_setup`, `integration/test_server_join` |
| [ ] | Invite it without Manage Channels: nothing is created, and the bot says how to finish with `/set_hall_of_fame_channel` | `test_server_setup` |
| [ ] | Invite it to a server with a problem (a role-gated chat channel): the board gets a short note with only a Troubleshoot button, never the full report | `test_setup_check`, `test_server_setup` |
| [ ] | Welcome message buttons still answer after the bot restarts | `test_setup_check` (persistent views) |
| [ ] | Set up opens the settings form (section 3) for an admin, and is refused for a member | `test_commands` |
| [ ] | The bot was added while offline: on startup it is set up and its join recorded once | `test_daily_task`, `integration/test_server_join` |

<br>

## 2. The board

### Reaching it

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | A message one reaction short is not posted. The reaction that reaches the threshold posts it once, as one Components V2 message: author, text, every counted emoji with its count, Jump to message | `test_validate_message`, `integration/test_reaction_path` |
| [ ] | Several members react at the same moment: one post, and its count settles at the real number | stress harness, `test_concurrency` |
| [ ] | Each counting method (`/calculation_method`) on the same reactions gives the counts in the README picture | `test_message_reactions` |
| [ ] | `/include_authors_reaction false`: the author's own reaction stops counting | `test_message_reactions`, `integration/test_reaction_path` |
| [ ] | Super reactions count as one reaction each | none yet, check by hand |
| [ ] | Reactions in the board itself never repost anything | `test_validate_message` |

### What a post shows

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | Images, several images, a video (plays in place), a GIF (loops), a sticker, a file, a voice message, a link preview | `test_post_matrix`, `integration/test_posts` |
| [ ] | A reply shows the quoted message above it. A reply to a deleted message is posted on its own | `test_post_matrix`, `test_hall_of_fame_posting` |
| [ ] | A spoilered image stays covered | `test_post_matrix` |
| [ ] | A forwarded message and a poll are shown, not posted empty | `test_post_matrix` |
| [ ] | Text over Discord's limits is cut with "...", and nobody mentioned in the message is pinged | `test_utils`, `test_post_matrix` |
| [ ] | A post made before the Components V2 upgrade still updates, hides and comes back as an embed | `test_hall_of_fame_posting` |

### Keeping it current

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | More reactions update the count; a reaction that changes nothing costs no edit | `test_hall_of_fame_posting`, stress harness |
| [ ] | Falling under the threshold hides the post (with `/hide_hof_post_below_threshold true`), climbing back restores the same message with its new count | `integration/test_reaction_path` |
| [ ] | With hiding off, a post that falls under stays up | `integration/test_reaction_path` |
| [ ] | A busy board that hits Discord's limit on edits to old posts pauses those edits for 15 minutes, and newer posts keep updating | `test_hall_of_fame_posting` |
| [ ] | The original message is deleted: the next event does not error, and the post stays | `test_hall_of_fame_posting` |

### What keeps a message off

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | Older than `/set_post_due_date` days: not posted, but a post already up keeps updating | `test_validate_message`, `integration/test_reaction_path` |
| [ ] | From a bot, with `/ignore_bot_messages true` | `test_validate_message` |
| [ ] | Without an image or video, with `/require_image_or_video true` | `test_validate_message` |
| [ ] | From an age-restricted channel when the board is not: not posted; a post already up hides at its next reaction and returns once the board is age-restricted | `test_validate_message`, `integration/test_reaction_path` |
| [ ] | Media Discord flags: explicit stays off a board that is not age-restricted, gore and self-harm always; the bot takes down its own post if Discord flags it later | `test_validate_message`, `test_flagged_media` |
| [ ] | The author pressed Stop featuring me: not posted; a reply to them is posted without their message | `test_member_data`, `integration/test_member_data_deletion` |
| [ ] | The server's 100 posts for today are used: one notice on the board, nothing more until midnight UTC | `test_validate_message`, `integration/test_reaction_path` |
| [ ] | A channel the bot cannot read: nothing happens and nothing errors | `test_validate_message` |
| [ ] | Chat in the board, with `/allow_messages_in_hof_channel false`: removed, with a short reminder that disappears; without Manage Messages the bot leaves it | `test_hof_channel_moderation` |

<br>

## 3. Settings (admins)

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | `/get_server_config` shows every setting with the command that changes it, and has Change settings and Troubleshoot | `test_commands` |
| [ ] | Change settings opens the form filled with the current values. Changing some sends one answer naming exactly those; sending it unchanged says nothing changed; an invalid threshold is refused and nothing is stored | `test_commands`, `integration/test_server_settings` |
| [ ] | Each settings command once: `/set_reaction_threshold` (1 to 1000), `/set_post_due_date` (1 to 3650), `/calculation_method` (answers with the picture), `/include_authors_reaction`, `/hide_hof_post_below_threshold`, `/ignore_bot_messages`, `/require_image_or_video`, `/allow_messages_in_hof_channel`, `/count_in_global_profiles` | `test_main`, `test_validation`, `integration/test_server_settings` |
| [ ] | Each one says so when the setting already had that value, and an out-of-range value is refused privately | `test_main` |
| [ ] | `/set_hall_of_fame_channel` to a channel missing a permission names it; to a good one moves the board and the next post lands there | `test_main`, `integration/test_server_settings` |
| [ ] | Emoji whitelist: `/custom_emoji_check_logic` on with an empty list (every emoji still counts), `/whitelist_emoji` a standard and a custom emoji, rename the custom one (still counts), `/unwhitelist_emoji`, `/clear_whitelist`, the 100 emoji limit | `test_main`, `test_message_reactions`, `test_validation` |
| [ ] | A member without Manage Server does not see the settings commands, and running one anyway (role given access under Integrations) is refused privately | `test_main` |
| [ ] | A setting changed takes effect on the very next reaction, without a restart | `test_server_class` |

<br>

## 4. Troubleshooting

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | `/troubleshoot` on a healthy server: everything OK, only the admin sees it | `test_setup_check` |
| [ ] | Board missing, or missing View, Send, Read History or Embed Links | `test_setup_check` |
| [ ] | A chat channel behind a member role the bot lacks: listed with the role that would open it | `test_setup_check` |
| [ ] | With Private Channel Obfuscation on for the dev bot: that channel is listed as hidden from the bot, with the note to give it the members' role | `test_setup_check` (manual: needs the Developer Portal toggle) |
| [ ] | Age-restricted channels the board leaves out are listed, as information only | `test_setup_check` |
| [ ] | A Discoverable server gets the note that the board can appear on Discord's web pages | `test_setup_check` |
| [ ] | Empty whitelist, a threshold above the member count, the daily limit reached, no post in 30 days | `test_setup_check` |
| [ ] | Why isn't this on the board? as a member, for each reason: posted (with link), hidden, short of the threshold (with how the server counts), too old, from a bot, no media, age-restricted, flagged media, unreadable channel, no board, cannot post, daily limit, opted-out author (only the author is told it was their choice) | `test_message_check`, `integration/test_message_check` |
| [ ] | Asking again straight away is refused for a few seconds | `test_main` |

<br>

## 5. Recognition (every member)

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | `/leaderboard`: posts and reactions, this month and all time, refreshed daily; a second use the same day is refused; turned away in a board closed to chat | `test_commands`, `test_user_stats` |
| [ ] | `/user_profile` for yourself and another member: columns, ranks (N/A with nothing this month), best post link, last featured, gap to next rank, badges | `test_commands`, `integration/test_profile_badges`, `integration/test_member_views` |
| [ ] | The every-server column appears only when it adds something, never names a server, and disappears when the member hid their totals or a server opted out with `/count_in_global_profiles false` | `test_commands`, `integration/test_member_views` |
| [ ] | Members tied on posts get the same champion in `/leaderboard` and `/user_profile` | none found, check by hand |
| [ ] | `/hof_wrapped` and `/server_hof_wrapped` with a Wrapped, and the private explanation when there is none (no Wrapped that year, nothing credited, opted out), with when the next one comes | `integration/test_wrapped_generation`, `test_wrapped_repos` |
| [ ] | A member over 10,000 credited posts: still posted, not credited, one critical log without a ping | `test_hall_of_fame_posting`, `integration/test_member_data_deletion` |

<br>

## 6. A member's own data

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | `/my_data` with nothing stored and with posts: the summary, and only you can press its buttons | `test_member_data` |
| [ ] | Download my data: one private JSON with every row, IDs as strings; once a day; split into parts when too big | `test_member_data`, `integration/test_member_data_deletion` |
| [ ] | Hide and show my totals across servers | `test_member_data`, `integration/test_member_views` |
| [ ] | Stop featuring me and Feature me again, and their effect on new posts, replies and Wrapped | `test_member_data`, `integration/test_member_data_deletion`, `integration/test_wrapped_generation` |
| [ ] | Delete my data: confirm, cancel, the done message offering Stop featuring me, posts staying on boards uncredited, leaderboards updated the next day | `test_member_data`, `integration/test_member_data_deletion`, `integration/test_removed_authors` |

<br>

## 7. Help, feedback and the user install

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | `/help` lists every command by group with working command mentions; mentioning the bot alone answers the same, at most once per channel per cooldown | `test_commands`, `test_bot_mention` |
| [ ] | `/invite` (server and account buttons), `/vote` | `test_commands` |
| [ ] | `/feedback` for each topic: the form asks for what fits the topic, screenshots are images only, the developer channel gets the report; three a day, a fourth refused | `test_main`, `test_utils` |
| [ ] | Add the bot to your account, then in a DM and in a server without the bot: `/user_profile` (yourself only, totals across servers), `/my_data`, `/help`, `/invite`, `/vote`, `/feedback` work; every other command is not offered | `test_main` |
| [ ] | A command while the bot is still starting answers with the loading notice, and a failing command answers with an error instead of "The application did not respond" | `test_main` |

<br>

## 8. What runs on its own

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | The daily task: leaderboards updated in batches, cooldowns cleared, member statistics rebuilt, one server timing out does not stop the rest | `test_daily_task`, `integration/test_daily_maintenance`, `integration/test_statistics_rebuild` |
| [ ] | A board missing permissions gets a warning at most every 7 days and at most 3 times, and the record is cleared once fixed | `test_daily_task`, `integration/test_daily_maintenance` |
| [ ] | The board topic links to the App Directory; an admin's own topic is never changed | `test_daily_task`, `test_server_setup` |
| [ ] | The status rotates every 10 minutes, with `/hof_wrapped` only in December and January | `test_presence` |
| [ ] | Monthly server snapshots are written once a month, in UTC | `integration/test_snapshots_and_statistics`, `integration/test_time_zone` |
| [ ] | Top.gg and the other list sites get the server count only in production | `test_api_services`, `test_environment` |

<br>

## 9. Leaving

| | Flow | Covered by |
|:---|:---|:---|
| [ ] | Remove the bot from a server: its posts, statistics, Wrapped, settings and permission warnings are deleted at once, and the leave is recorded | `integration/test_server_removal` |
| [ ] | Removed while the bot was offline: deleted by the daily task after 7 days, once Discord confirms the bot has no access, and not when many servers seem missing at once | `integration/test_departed_guild_cleanup`, `test_daily_task` |
| [ ] | Adding it back starts fresh with a new welcome message | `integration/test_server_join` |

<br>

## 10. Logs and privacy, throughout

- [ ] Developer log lines carry a server ID and the command, never a username or a server name
- [ ] The only log with a member's user ID is the 10,000 post alert
- [ ] Nothing is stored about a member who pressed Stop featuring me, in any flow above
      (`OptOutWriteGuardTests` guards every repository write)
- [ ] `PRIVACY.md` and `TERMS.md` still describe what the flows above do (run the `policy-check` skill)
