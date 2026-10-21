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

- [ ] `/my_data` answers privately: "No posts, server standings or Wrapped entries are stored about
      you", the totals line, and the privacy policy link
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

## Setup check and joining

- [ ] `/check_setup` answers the admin privately with the findings
- [ ] A member without Manage Server is refused
- [ ] Add the dev bot to a new server: if something is wrong, a short note with a Check setup button
      appears on the board, and the button opens the full findings for an admin
- [ ] The welcome message's Check setup, Support server and Vote buttons work, also after the bot restarts

## Wrapped

Only if Wrapped can be generated on the development bot.

- [ ] A member who asked not to be featured gets no Wrapped and appears in nobody's fan lists
- [ ] A member who deleted their data while Wrapped ran is left out the same way
- [ ] After Wrapped is generated, a friend presses Stop featuring me: they vanish from your
      `/hof_wrapped` top fans and "fan of", from the reactions you received, and from `/server_hof_wrapped`,
      while their own `/hof_wrapped` still works for them

## Before deploying

- [ ] Replace the plain-text `MY_DATA`, `COUNT_IN_GLOBAL_PROFILES` and `CHECK_SETUP` in
      `src/enums/command_refs.py` with their `</name:id>` mentions once the live bot has synced them
- [ ] `PRIVACY.md` and `TERMS.md` carry the effective date you mean to publish (`PRIVACY.md` currently
      says 10 November 2026)
- [ ] The README's Development Log and the 2.2 announcement name `/my_data` and not the removed commands,
      and mention the 10,000 post limit
- [ ] Clear the test rows from the development database again
