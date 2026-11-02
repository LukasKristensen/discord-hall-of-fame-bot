# Release test plan: 3.0

Every flow to check by hand on the development bot before 3.0 goes to production. Tick each box as you
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

- [x] `/my_data` answers privately: "Hall of Fame stores nothing about you, so there is nothing to
      download or delete.", "Once you are featured, your totals across servers are shown on your
      profile.", and the privacy policy link
- [x] Download my data and Delete my data are greyed out
- [x] Hide my totals across servers and Stop featuring me are there
- [x] A second account cannot press your buttons: the panel is private, so it never sees them. Should one
      be shown, the bot answers that only the member who ran the command can use it (`interaction_check`,
      covered in `tests/test_member_data.py`)
- [x] The summary counts your featured posts, servers and Wrapped entries, with thousands separators
- [x] Download my data sends one private `hall-of-fame-my-data.json` with your posts, standings and
      choices, and every ID written as a string
- [x] Pressing Download again the same day says you already downloaded today, and the other buttons
      still work
- [x] Running `/my_data` again the same day is not limited
- [x] After two minutes the buttons disappear and the summary stays

## Totals across servers

- [x] Hide my totals across servers: the line turns to hidden, with today's date, and the button becomes
      Show my totals across servers
- [x] `/user_profile` in a server no longer shows the every-server column for you, even when you look
      yourself up
- [x] `/user_profile` in a DM (user install) says your totals are hidden and points to `/my_data`
- [x] Show my totals across servers brings them back on `/user_profile`

## Not being featured

- [x] Stop featuring me: the panel says new messages are not featured, with the date, and the button
      becomes Feature me again
- [x] With earlier posts, the panel says they are kept until you delete them, and Download, the totals
      button and Delete are still offered
- [x] React to a new message of yours until it passes the threshold: nothing is reposted, and `/my_data`
      shows no new post
- [x] A second account's message still reaches the board as usual
- [x] Download right after stopping includes `"not_counted": true`
- [x] Feature me again: the panel confirms it, and your next message over the threshold is reposted and
      credited to you

## Deleting

- [x] Delete my data shows the confirmation: you are taken off every leaderboard, profile and Wrapped,
      posts stay on the boards, and a hidden-totals choice is deleted too
- [x] Cancel says nothing was deleted
- [x] Confirming answers within a few seconds, even with many posts, and says your data is deleted
- [x] The done message offers Stop featuring me. Pressing it stores the choice and says so
- [x] Your posts are still on the board, but `/leaderboard` and `/user_profile` no longer show you after
      the daily update
- [x] Right after deleting, `/my_data` stores nothing, so Delete is greyed out and there is nothing to refuse
- [x] Delete again the same day with posts stored says you already deleted today
- [x] While not featured, Delete my data warns that the choice not to be featured is deleted too.
      Afterwards your next message over the threshold is featured again

## The 10,000 post limit

Bring your account to exactly 10,000 credited posts with test rows, as described under "How the posts
were made" in [MANUAL_TESTS.md](MANUAL_TESTS.md).

- [x] Your next message over the threshold reaches the board but is not credited to you
- [x] The log channel gets one critical alert, without a ping, with your user ID
- [x] A second message over the threshold is also uncredited, with no second alert
- [x] `/my_data` still shows 10,000 featured posts

## Exporting large amounts of data

Use test rows again.

- [x] Around 50,000 posts: one file if Discord accepts it, otherwise parts
- [x] Around 150,000 posts: Discord refuses one file, and you get several parts, each a complete JSON file,
      with a message saying how many
- [x] Over 2,000,000 posts: you are pointed to the support server, nothing is half sent, and you can still
      download again the same day

## Logs

Watch the developer log channels while going through the steps above.

- [x] Command logs say which command was used and carry a server ID, never a username or server name
- [x] Joins, leaves and setup problems carry the server ID, never the server name
- [ ] Deleting data, stopping or restarting featuring and downloading log "A member ...", never who
- [ ] The post limit alert is the only log with a member's user ID

## Command picker

Restart the Discord client if the picker still shows the old list.

- [x] As a member without Manage Server, typing `/` offers only `/help`, `/leaderboard`, `/user_profile`,
      `/hof_wrapped`, `/server_hof_wrapped`, `/my_data`, `/get_server_config`, `/invite`, `/vote` and
      `/feedback`, and Apps still has Why isn't this on the board?
- [ ] As an admin with Manage Server, all 25 commands are offered
- [x] Let a role without Manage Server use `/set_reaction_threshold` under Server Settings > Integrations >
      Hall of Fame: that role now sees it, and running it is refused privately

## Setup check and joining

- [x] `/troubleshoot` answers the admin privately with the findings
- [x] A member without Manage Server does not see `/troubleshoot`, and pressing Troubleshoot on the
      welcome message is refused
- [x] Add the dev bot to a new server: if something is wrong, a short note with a Troubleshoot button
      appears on the board, and the button opens the full findings for an admin
- [ ] The welcome message's Troubleshoot, Support server and Vote buttons work, also after the bot restarts
- [x] `/get_server_config` has a Troubleshoot button: an admin gets the findings privately, a member is refused
- [ ] Turn on Private Channel Obfuscation for the dev bot (Developer Portal > Bot) and restart it: a channel
      only a member role can see is listed as hidden from the bot, with the note to give it the members'
      role. Giving the bot that role and running `/troubleshoot` again counts the channel as read
- [x] Mark a channel age-restricted and react a message there past the threshold: nothing is posted, Why
      isn't this on the board? says the channel is age-restricted, and `/troubleshoot` lists the channel.
      Mark the board age-restricted too and react again: the message is posted
- [x] With a post already on the board, mark its source channel age-restricted and react once more: the
      post is hidden. Mark the board age-restricted and react again: it comes back
- [x] Apps > Why isn't this on the board? on a message, as a member without Manage Server: a posted message
      links to its post, one short of the threshold shows the count, and one in a channel the bot cannot
      read says so. Only you see the answer, and asking again straight away is refused for a few seconds
- [x] A friend who pressed Stop featuring me reaches the threshold: you are told only that it cannot be
      featured, and they are told it is their choice, with `/my_data`

## Board posts

- [ ] A reply with a spoilered image, a video and a second image, that @mentions someone, reaches the
      board: one post shows the author, the quoted reply, all three in a gallery with the spoiler covered
      and the video playing in place, every emoji with its count and a Jump to message button that works.
      Nobody is pinged
- [x] More reactions update the count on that post. Removing reactions below the threshold hides it, and
      reacting again brings it back as the same message
- [x] A post made before the upgrade still updates its count as an embed, hides and comes back
- [x] A member's join message, a pin notice and a closed poll, reacted past the threshold, are not posted, and
      Why isn't this on the board? says Discord posted them on its own
- [ ] A message with a text file and one with only a sticker are posted with the file linked and the
      sticker shown

What only Discord's rendering shows. `tests/test_post_matrix.py` checks every other combination of message
and reply from the payload:

- [ ] A Tenor GIF, on its own and as the message replied to, loops as a GIF with no player controls. A GIF
      from another site plays as a video
- [x] A forwarded message, a poll and a message over 300 characters look right: the forward labelled, the
      poll's votes listed, the long text full width under the header
- [x] A forward of a message from this server shows the message it forwards. A forward from another
      server, a forward of a board post, and a forward of a member who pressed Stop featuring me each show
      *The forwarded message is not shown* and none of the forwarded words or media. A forward of a forward
      shows the original, since Discord forwards the original
- [ ] A reply with a picture of its own to a sticker, a file and a GIF says *Sticker: name*, *File: name* and
      *GIF* in the quote
- [ ] A file link on a post that is a day old still opens the file
- [ ] A MOV from a phone plays in the gallery, a voice message is linked as Voice message, and a message
      with three stickers shows the two pictures and names the animated one
- [ ] A link to a post with four images, and a message with a screenshot and an article link, show every
      picture in one gallery

## Settings form

- [x] `/get_server_config` has Change settings next to Troubleshoot. As an admin it opens Hall of Fame settings
      with the current channel, threshold, post age, counting method and ticked rules filled in
- [x] A member without Manage Server who presses it is refused privately, and no form opens
- [x] Change the threshold and two rules and send it: one private answer lists exactly those three, and
      `/get_server_config` shows them
- [x] Send it unchanged: it says nothing changed
- [x] Type 0 or "five" as the threshold along with another change: it is refused, and nothing is stored
- [x] Pick another channel: the board moves, the new channel gets the announcement with nobody pinged, and the
      next post lands there. A channel the bot cannot post in is refused with the missing permissions
- [x] A new server's welcome message has Set up, which opens the same form, also after the bot restarts
- [ ] The join note about hidden channels still has only Troubleshoot

## Feedback

- [x] `/feedback` opens a form with the two text fields and the contact box, and no file upload
- [x] Send one with the contact box ticked and one without: each is answered at once, and the feedback channel
      shows May contact "Yes" and "No"

## Wrapped

Only if Wrapped can be generated on the development bot.

- [ ] `/hof_wrapped` opens a story only you see: Next, Back and Skip to summary work, the fame rate page
      shows "1 in N" with the server average, and the summary offers Show to others
- [ ] Show to others posts the summary in the channel once, without pinging anyone it names. Another member
      presses Year in squares and Top 10 and sees them privately, and Get my Wrapped opens their own story
- [ ] After a restart, the buttons on a summary posted before it still answer
- [ ] A member who asked not to be featured gets no Wrapped and appears in nobody's fan lists
- [ ] A member who deleted their data while Wrapped ran is left out the same way
- [ ] After Wrapped is generated, a friend presses Stop featuring me: they vanish from your
      `/hof_wrapped` top fans and "fan of", from the reactions you received, and from `/server_hof_wrapped`,
      while their own `/hof_wrapped` still works for them

## Before deploying

- [ ] `PRIVACY.md` and `TERMS.md` carry the effective date you mean to publish (`PRIVACY.md` currently
      says 10 November 2026)
- [ ] CHANGELOG.md and the 3.0 announcement name `/my_data` and not the removed commands,
      and mention the 10,000 post limit
- [ ] Clear the test rows from the development database again

## After deploying

The command IDs only exist once the live bot has synced 3.0, so this is a second, small deploy.

- [ ] Copy the IDs of `/my_data`, `/count_in_global_profiles` and `/troubleshoot` (Developer Mode on, Server
      Settings > Integrations > Hall of Fame) and replace the plain-text `MY_DATA`,
      `COUNT_IN_GLOBAL_PROFILES` and `TROUBLESHOOT` in `src/enums/command_refs.py` with `</name:id>`
- [ ] Deploy again, then check that `/help` and a `/my_data` deletion show the commands as clickable
