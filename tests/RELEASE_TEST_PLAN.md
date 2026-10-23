# Release test plan: 2.2

Every flow to check by hand on the development bot before 2.2 goes to production. Tick each box as you
go, and note anything that looks wrong next to it. Results worth keeping go in
[MANUAL_TESTS.md](MANUAL_TESTS.md).

Run against the development bot (`DEV_TEST=True`) and its own database, never production. Use two
accounts where a step says "second account", and a server where you have Manage Server.

## Before you start

- [ ] The full suite passes: `python -m unittest discover -s tests -t .` with `HOF_TEST_DATABASE_URL` set,
      so the PostgreSQL tests run too (see the `dev-environment` skill)
- [ ] CI is green on the pull request
- [ ] The development database holds no test posts from earlier runs:
      `DELETE FROM hall_of_fame_message WHERE message_id >= 9000000000000000000`
- [ ] The dev bot has restarted, so the command list has synced. `/delete_my_data` and `/profile_privacy`
      are gone from the command picker, and `/my_data` is there

## `/my_data` with nothing stored

Use an account that has never been featured.

- [ ] `/my_data` answers privately: "Hall of Fame stores nothing about you, so there is nothing to
      download or delete.", "Once you are featured, your totals across servers are shown on your
      profile.", and the privacy policy link
- [ ] Download my data and Delete my data are greyed out
- [ ] Hide my totals across servers and Stop featuring me are there
- [ ] A second account cannot press your buttons: it is told only the member who ran the command can

## `/my_data` with posts

Get a few of your messages onto the board first.

- [ ] The summary counts your featured posts, servers and Wrapped entries, with thousands separators
- [ ] Download my data sends one private `hall-of-fame-my-data.json` with your posts, standings and
      choices, and every ID written as a string
- [ ] Pressing Download again the same day says you already downloaded today, and the other buttons
      still work
- [ ] Running `/my_data` again the same day is not limited
- [ ] After two minutes the buttons disappear and the summary stays

## Totals across servers

- [ ] Hide my totals across servers: the line turns to hidden, with today's date, and the button becomes
      Show my totals across servers
- [ ] `/user_profile` in a server no longer shows the every-server column for you, even when you look
      yourself up
- [ ] `/user_profile` in a DM (user install) says your totals are hidden and points to `/my_data`
- [ ] Show my totals across servers brings them back on `/user_profile`

## Not being featured

- [ ] Stop featuring me: the panel says new messages are not featured, with the date, and the button
      becomes Feature me again
- [ ] With earlier posts, the panel says they are kept until you delete them, and Download, the totals
      button and Delete are still offered
- [ ] React to a new message of yours until it passes the threshold: nothing is reposted, and `/my_data`
      shows no new post
- [ ] A second account's message still reaches the board as usual
- [ ] Download right after stopping includes `"not_counted": true`
- [ ] Feature me again: the panel confirms it, and your next message over the threshold is reposted and
      credited to you

## Deleting

- [ ] Delete my data shows the confirmation: you are taken off every leaderboard, profile and Wrapped,
      posts stay on the boards, and a hidden-totals choice is deleted too
- [ ] Cancel says nothing was deleted
- [ ] Confirming answers within a few seconds, even with many posts, and says your data is deleted
- [ ] The done message offers Stop featuring me. Pressing it stores the choice and says so
- [ ] Your posts are still on the board, but `/leaderboard` and `/user_profile` no longer show you after
      the daily update
- [ ] Delete again the same day with nothing stored is allowed (no daily limit when there is nothing to
      delete)
- [ ] Delete again the same day with posts stored says you already deleted today
- [ ] While not featured, Delete my data warns that the choice not to be featured is deleted too.
      Afterwards your next message over the threshold is featured again

## The 10,000 post limit

Bring your account to exactly 10,000 credited posts with test rows, as described under "How the posts
were made" in [MANUAL_TESTS.md](MANUAL_TESTS.md).

- [ ] Your next message over the threshold reaches the board but is not credited to you
- [ ] The log channel gets one critical alert, without a ping, with your user ID
- [ ] A second message over the threshold is also uncredited, with no second alert
- [ ] `/my_data` still shows 10,000 featured posts

## Exporting large amounts of data

Use test rows again.

- [ ] Around 50,000 posts: one file if Discord accepts it, otherwise parts
- [ ] Around 150,000 posts: Discord refuses one file, and you get several parts, each a complete JSON file,
      with a message saying how many
- [ ] Over 2,000,000 posts: you are pointed to the support server, nothing is half sent, and you can still
      download again the same day

## Logs

Watch the developer log channels while going through the steps above.

- [ ] Command logs say which command was used and carry a server ID, never a username or server name
- [ ] Joins, leaves and setup problems carry the server ID, never the server name
- [ ] Deleting data, stopping or restarting featuring and downloading log "A member ...", never who
- [ ] The post limit alert is the only log with a member's user ID

## Command picker

Restart the Discord client if the picker still shows the old list.

- [ ] As a member without Manage Server, typing `/` offers only `/help`, `/leaderboard`, `/user_profile`,
      `/hof_wrapped`, `/server_hof_wrapped`, `/my_data`, `/get_server_config`, `/invite`, `/vote` and
      `/feedback`, and Apps still has Why isn't this on the board?
- [ ] As an admin with Manage Server, all 25 commands are offered
- [ ] Let a role without Manage Server use `/set_reaction_threshold` under Server Settings > Integrations >
      Hall of Fame: that role now sees it, and running it is refused privately

## Setup check and joining

- [ ] `/troubleshoot` answers the admin privately with the findings
- [ ] A member without Manage Server does not see `/troubleshoot`, and pressing Troubleshoot on the
      welcome message is refused
- [ ] Add the dev bot to a new server: if something is wrong, a short note with a Troubleshoot button
      appears on the board, and the button opens the full findings for an admin
- [ ] The welcome message's Troubleshoot, Support server and Vote buttons work, also after the bot restarts
- [ ] `/get_server_config` has a Troubleshoot button: an admin gets the findings privately, a member is refused
- [ ] Apps > Why isn't this on the board? on a message, as a member without Manage Server: a posted message
      links to its post, one short of the threshold shows the count, and one in a channel the bot cannot
      read says so. Only you see the answer, and asking again straight away is refused for a few seconds
- [ ] A friend who pressed Stop featuring me reaches the threshold: you are told only that it cannot be
      featured, and they are told it is their choice, with `/my_data`

## Wrapped

Only if Wrapped can be generated on the development bot.

- [ ] A member who asked not to be featured gets no Wrapped and appears in nobody's fan lists
- [ ] A member who deleted their data while Wrapped ran is left out the same way
- [ ] After Wrapped is generated, a friend presses Stop featuring me: they vanish from your
      `/hof_wrapped` top fans and "fan of", from the reactions you received, and from `/server_hof_wrapped`,
      while their own `/hof_wrapped` still works for them

## Before deploying

- [ ] `PRIVACY.md` and `TERMS.md` carry the effective date you mean to publish (`PRIVACY.md` currently
      says 10 November 2026)
- [ ] CHANGELOG.md and the 2.2 announcement name `/my_data` and not the removed commands,
      and mention the 10,000 post limit
- [ ] Clear the test rows from the development database again

## After deploying

The command IDs only exist once the live bot has synced 2.2, so this is a second, small deploy.

- [ ] Copy the IDs of `/my_data`, `/count_in_global_profiles` and `/troubleshoot` (Developer Mode on, Server
      Settings > Integrations > Hall of Fame) and replace the plain-text `MY_DATA`,
      `COUNT_IN_GLOBAL_PROFILES` and `TROUBLESHOOT` in `src/enums/command_refs.py` with `</name:id>`
- [ ] Deploy again, then check that `/help` and a `/my_data` deletion show the commands as clickable
