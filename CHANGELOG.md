# Changelog

What changed in each version of Hall of Fame, newest first. Patch releases are folded into their minor
version, so 2.2 covers 2.2.0 and every 2.2.x after it. For how the bot works today, see the
[README](README.md).

## 2.2
- [x] Added /troubleshoot and a Troubleshoot button on the welcome message and under /get_server_config, which check the board's permissions, how many channels the bot can read and which ones members see but the bot cannot (with the role that would open most of them), an empty emoji whitelist, a threshold above the member count, the daily post limit and the last post.
- [x] Added the Why isn't this on the board? message command, which tells any member why one message is or is not on the board, using the same checks the bot applies when a message is reacted to.
- [x] When the bot joins, it runs the board and channel checks and, if something is wrong, posts a short note with a Troubleshoot button on the board instead of the full report, since the board is public.
- [x] Added /my_data, where a member sees what is stored about them and manages it with buttons: download it as a file, hide their totals across servers, stop the bot featuring their new messages, and delete it, which removes them from every leaderboard, profile and Wrapped. It works in DMs through a user install.
- [x] Added /count_in_global_profiles for admins to leave their server out of members' totals across servers.
- [x] Members can add Hall of Fame to their own account with the Add to your account button under /invite, and use /help, /invite, /vote, /feedback, /user_profile and /my_data in DMs and in servers without the bot. Outside a server with the bot, /user_profile only looks up the member who asked. Every other command stays install-to-server only.
- [x] /feedback is limited to three sends per member a day, counted across DMs and servers.
- [x] A member who asks not to be featured gets nothing new stored: no new posts, no Wrapped, and no place in other members' Wrapped or the server's, including a Wrapped generated before they asked. The repositories enforce this themselves, so no caller can skip it.
- [x] A member's posts count toward leaderboards, profiles and Wrapped up to 10,000 across every server. This keeps what is stored about any one member small enough that /my_data can always export all of it. Posts past that still reach the board but are not credited, and the developer is alerted.
- [x] A /my_data download too big for one file is sent as several complete JSON files instead of failing.
- [x] /user_profile is laid out in columns (this month, all time, every server) with highlights: the best post with a jump link, when the member was last featured and the gap to the next rank. The totals across servers never name a server.
- [x] /user_profile shows the badges a member has earned: monthly champion, 10 to 500 posts, months in a row, featured for a year, a 100-reaction post, 10 posts in one month and featured in 5 or more servers. Badges are worked out from existing posts, never name a server, and leave out other servers when a member hid their totals.
- [x] /user_profile, /leaderboard and the Wrapped commands are turned away with a private note in a Hall of Fame channel that is closed to chat.
- [x] Every Hall of Fame post carries a "Hall of Fame" footer with the bot's logo, and the vote prompt was removed from posts. The invite suggestion moved to the footers of /user_profile, /leaderboard and /hof_wrapped.
- [x] /invite, /vote and /help answer with link buttons, and the welcome message has Troubleshoot, Support server and Vote buttons with shorter closing lines.
- [x] The invite link asks for exactly the permissions the bot uses instead of the Developer Portal defaults, which included thread management. Existing servers keep what they granted.
- [x] The bot's status rotates every ten minutes between the member count and pointers to /invite, /leaderboard and, in December and January, /hof_wrapped. The member count is kept in memory and adjusted as servers join and leave.
- [x] The board channel topic links to the App Directory page. Topics the bot set in an earlier version are moved over by the daily check, and a topic an admin wrote is never changed.
- [x] Servers that removed the bot while it was offline are cleaned up by the daily task after a grace period.
- [x] Rewrote the Privacy Policy and Terms of Service to match what the bot stores, and moved both into the repository as PRIVACY.md and TERMS.md.
- [x] Fixed /user_profile and /leaderboard picking a different champion than the ranks when members tied, or putting an unranked member first.
- [x] Fixed new posts being stored an hour or two off on a database not set to UTC. The daily post limit now resets at midnight UTC, as its notice says.
- [x] Fixed a hidden post that climbed back over the threshold keeping its old reaction count on leaderboards and profiles until the next reaction.
- [x] Fixed /hof_wrapped failing for a member whose most reacted post was longer than Discord allows in one field; the text is now cut to fit. The card also shows the avatar the member uses in the server.
- [x] /hof_wrapped and /server_hof_wrapped answer privately when there is no Wrapped to show, and say why: the server had no Wrapped that year, no post was credited to the member when it was made, or the member asked not to be featured. They also say when the next Wrapped arrives.
- [x] Fixed the daily post limit notice being posted more than once when reactions arrived together, and the limit being re-checked on every reaction for the rest of the day.
- [x] Fixed Wrapped carrying one server's members over into the next server it generated. Wrapped was switched off, so nothing was affected.
- [x] Fixed the monthly snapshot timestamp shifting on every startup on servers not running in UTC.
- [x] Added indexes for the per-server and per-member queries, and run the daily stats rebuild and the data commands under a statement timeout.
- [x] Quieted recurring log lines from servers with a deleted board, top.gg stats posts and chat that was already deleted.
- [x] Logs in the developer channels carry the command and the server ID, never a member's or a server's name.
- [x] Production credentials and the production database are only loaded in production, so a development run cannot reach them.
- [x] Message locks are recreated on each run, so none stays bound to a closed event loop.
- [x] Removed the MongoDB-era tooling, the unused manual sweep and the Google Drive backup script.
- [x] Added integration tests that run the reaction path, joins, the daily task, Wrapped, data deletion, schema upgrades and the stats queries against a real PostgreSQL, which CI now starts for them.
- [x] Added project skills and an expanded CLAUDE.md for development.

## 2.1
- [x] Mentioning the bot on its own now answers with a help card listing the commands, with a per-channel cooldown so it cannot be spammed.
- [x] /get_server_config shows every setting in one card, grouped by what it affects, with the command that changes each setting next to it.
- [x] /help groups the commands by who uses them and what they change, and links the support server, voting and the source code.
- [x] Settings commands check their input: the reaction threshold is 1 to 1000, the post due date 1 to 3650 days and the emoji whitelist holds up to 100 emojis. Discord shows the allowed range in the command picker.
- [x] Settings commands confirm the new value in plain words, and say so when a setting already had that value instead of saving it again.
- [x] Error replies, such as an invalid value or a missing permission, are only shown to the member who ran the command instead of the whole channel.
- [x] A command that fails now answers with an error message instead of Discord's "The application did not respond", and commands are only offered inside servers.
- [x] Commands now answer with a loading notice while the bot is still starting up, instead of timing out silently.
- [x] /set_hall_of_fame_channel also checks for the Embed Links permission, without which Discord drops every Hall of Fame post silently.
- [x] The Hall of Fame channel is only kept clear of chat when the bot has Manage Messages there, and the bot explains which permission to grant otherwise.
- [x] /user_profile shows the monthly rank as N/A for members with nothing featured this month, instead of ranking them.
- [x] The daily post limit resets at the start of each day instead of covering a rolling 24 hours, and its notice says clearly when posting resumes.
- [x] The setup message explains that the bot cannot see channels hidden behind a role unless it is given that role.
- [x] Fixed the emoji whitelist matching on partial emojis, so a reaction only counts when it is whitelisted exactly.
- [x] Fixed whitelisted custom emojis no longer counting after being renamed; they are now matched by ID, and /unwhitelist_emoji accepts the renamed emoji.
- [x] Fixed the total reactions calculation method discarding a whole reaction instead of a single vote when the author is excluded.
- [x] Fixed Hall of Fame posts failing when the message that was replied to had been deleted, or when a reply had no text of its own.
- [x] Fixed reactions being dropped when several arrived on the same message at once; they now queue so the newest count wins.
- [x] Fixed the daily post limit allowing one more post than the limit it announced.
- [x] Fixed /get_server_config failing in servers that are not set up yet.
- [x] Fixed the clickable /require_image_or_video link in /help and /get_server_config, which pointed at a command ID that does not exist.
- [x] Fixed the daily leaderboard update failing when a featured message's channel was no longer accessible.
- [x] Fixed an error in one server's leaderboard update aborting the updates of other servers running at the same time.
- [x] Fixed developer ping notifications for critical runtime errors, which never triggered.
- [x] Reactions wait for a free database connection during busy moments instead of being dropped, and the connection pool grew from 10 to 20.
- [x] Reaction events serve the server configuration from memory, removing the database lookups from the path that runs most often.
- [x] The daily member statistics are aggregated and ranked by the database in one statement per server, instead of reading every Hall of Fame message into the bot.
- [x] The daily task updates servers in parallel batches, each under a time limit and a database statement timeout, so one stalled server cannot hold up the rest.
- [x] The leaderboard updates each post in a single edit instead of three, cutting its daily rate limit cost.
- [x] Errors while handling a reaction are logged instead of being discarded, with repeats collapsed per server, and the database state is reset cleanly after a restart.
- [x] Duplicate log messages are filtered in memory instead of re-reading the log channel on every single log line.
- [x] Switched to a thread safe database connection pool, since the daily snapshot runs on a worker thread.
- [x] Hall of Fame posts no longer break the Discord message cache when truncating long messages.
- [x] Rebuilt the internal server statistics report as a modular package with a synthetic data mode, and fixed several of its metrics.
- [x] Added a unit test suite and a Tests workflow that runs on every pull request, a reaction stress-test harness, and Dependabot.
- [x] Added psycopg2-binary to requirements.txt, which the bot has always needed in order to start, and pinned Python 3.13.
- [x] Rewrote the README and the Top.gg description around recognition rather than archiving, and documented /hof_wrapped, /server_hof_wrapped, /require_image_or_video and /set_post_due_date, which were missing.
- [x] Published the code under a source-available license, and added CONTRIBUTING.md and the Contributing and License sections of the README.

## 2.0
- [x] Added require_image_or_video server option to enforce media presence in embeds.
- [x] Added welcome message for the support server.
- [x]  Fixed images not appearing in embeds when using links.
- [x]  Improved handling of replies with attachments in embeds.
- [x]  Extended server statistics.
- [x]  Refactored server stats backend from MongoDB to PostgreSQL for improved performance and reliability.
- [x]  Resolved primary key issues for user_id and enforced foreign key constraints.
- [x]  Made timestamps timezone-aware and improved snapshot batching.

## 1.17
- [x] /get_user_profile updated to clarify the 24h calculation window.
- [x] /set_hall_of_fame_channel command added to manually set the Hall of Fame channel, providing more flexibility for server admins.
- [x] Adaptive threshold: On server join, the default reaction threshold now scales automatically based on member count for a more balanced experience.
- [x] Fixed design issues on Hall of Fame posts when replying to messages (caused by a recent Discord library update).
- [x] Added automatic permission validation for the Hall of Fame channel, ensuring the bot has proper write access, along with better debugging feedback.
- [x] Fixed the 1024-character limit issue on messages and referenced messages (long text is now truncated to 1021 characters followed by “...”).
- [x] Reduced the likelihood of voting messages being shown on embeds due to limited interactions.
- [x] Fixed context reply issues inside embeds for improved clarity.
- [x] Improved database exception handling with more detailed logging.
- [x] Added developer ping notifications for critical runtime errors.
- [x] Split production and testing logging environments for safer debugging.
- [x] General backend optimizations, code cleanup, and error log decluttering.

## 1.16
- [x] /user_profile command: You can now view both your own and others' Hall of Fame stats.
  - Displays all-time and monthly Hall of Fame post counts.
  - Highlights top users per server – great for competition and recognition.
  - Automatically updated daily via a recurring job.
- [x] Per-server user tracking: The bot now tracks individual user stats (e.g., HOF posts, reaction counts) per server.
- [x] Wide-format calculation method preview: Added to the </help> embed to visually explain the 3 different reaction calculation strategies.
- [x] Improved message metadata: All message entries now store `author_id` and `created_at` for better historical insight and debugging.
- [x] Migration system: Implemented automated data migration to ensure smoother updates and future rollouts.

## 1.15
- [x] /calculation_method command: Added support for custom calculation methods that determine how reaction counts are evaluated. This allows for more flexible and personalized Hall of Fame behavior per server.
- [x] Sticker support in HOF: Messages featuring stickers can now be included in Hall of Fame posts, with proper rendering (not supported for all stickers).
- [x] Improved setup reliability: The bot now handles failed or incomplete setup processes more gracefully, with clearer error messages.

## 1.14
- [x] Refactored all the external command references to be interactive.
- [x] Added command option /ignore_bot_messages for whether to ignore bot messages or not.
- [x] Top.gg API Integration: The bot now supports top.gg API for stats reporting.
- [x] Server Management: Configuration access now extended to ServerManagers, not just ServerOwners.
- [x] Introduced singleton-based variable handling for better maintainability.
- [x] Fixed an issue where it would not post hall of fame messages from users, when they were from the hall of fame channel.
- [x] Leaderboards disabled by default for new servers: It seems to cause confusion for first-time users.
- [x] Concurrency issue fixed on startup routine for loading server classes

## 1.13
- [x] Fixed Intents for Embed Colors
  - Resolved bug causing inconsistent embed colors.
  - Embed colors now dynamically match the top role color.
- [x] Leaderboard 24h Recurring Job
  - Leaderboard now updates automatically every 24 hours.
- [x] HOF Wrapped Tweaks
  - Minor improvements to the Hall of Fame Wrapped (December event).

## 1.12
- [x] ``/get_server_config`` for viewing the current server settings for the bot
- [x] Added custom emoji whitelist logic for the reaction threshold
  - To enable it: ``/custom_emoji_check_logic``
  - Adding emojis to the whitelist: ``/whitelist_emoji``
  - Removing emojis from the whitelist: ``/unwhitelist_emoji`` or ``/clear_whitelist``

## 1.11
- [x] Approved for top.gg - vote here for the bot: https://top.gg/bot/1177041673352663070
- [x] Slash Commands!
- [x] Refactored code-base for cloud deployment and for handling multiple servers

## 1.10
- [x] Threshold increase and general adjustments

## 1.09
- [x] Hall Of Fame Wrapped

## 1.08
- [x] Better context vísualization of replied messages
- [x] Added user's role color to embed color

## 1.07
- [x] Solved async simultaneous reacting on posts

## 1.06
- [x] LLM outlier detection of voting-based messages, which should not be classified as a Hall Of Fame message. 

## 1.05
- [x] Hall-of-fame posts which are replies to previous messages will include the context.

## 1.04
- [x] Only count non-author reactions towards the total amount for threshold
- [x] When a post goes below the threshold remove the embed, but keep the message so that it would be able to be reposted again

## 1.03
- [x] When the reaction counter goes up on an existing hall-of-fame post, it should update the message with the total amount of reactions
- [x] Remove incoming non-bot posts in the hall-of-fame channel

## 1.02
- [x] New gifs should be added to the user/server database as they get posted, instead of having to use the fetch command
- [x] Servers most used gifs
- [x] Users most used gifs

## 1.01
- [x] Problem with using discord user profile pictures using Discord<=2.0.0
- [x] Deploy on a remote server
- [x] Improve the embed layout of messages
- [x] Improve media output
- [x] Improve database structure to mongodb
- [x] Functionality for checking historical messages (it should run through all the messages and post the ones above the reaction value threshold
- [x] When posting the message highlight the reaction emoji from the original message
- [x] Fix message IDs not being saved/loaded correctly when validating if it has already been sent
- [x] Create a getRandom() function for grabbing a random hall-of-fame post
