# User journeys

Every path a person can take through Hall of Fame, from start to end, and the test that walks it. The
journey tests drive main's own event handlers and slash commands, the entry points Discord calls, with
Discord faked by [`integration/discord_world.py`](integration/discord_world.py) and a real PostgreSQL
database. They share the setup in [`integration/journeys.py`](integration/journeys.py), and are skipped
without `HOF_TEST_DATABASE_URL` (see the `dev-environment` skill).

Paths are short for the test modules:

- `admin` is `integration/test_journey_admin.py`
- `member` is `integration/test_journey_member.py`
- `my_data` is `integration/test_journey_my_data.py`
- `edges` is `integration/test_journey_edges.py`

What only Discord's rendering can show is marked **manual**, and is in
[RELEASE_TEST_PLAN.md](RELEASE_TEST_PLAN.md).

## Server admins

- [x] **Installing and the first post.** The bot joins, makes `#hall-of-fame` and posts the welcome
      message with the starting threshold and its Troubleshoot and Set up buttons. Troubleshoot gives the
      admin private findings and refuses a member. The admin lowers the threshold, `/get_server_config`
      shows it, and the next message over it is posted.
      `admin` InstallingTests.test_from_install_to_the_first_post
- [x] **An install that failed.** The bot cannot make its board, says so once in a channel it can post
      in, commands say it is not set up, and `/set_hall_of_fame_channel` finishes the setup.
      `admin` InstallingTests.test_an_install_that_failed_is_finished_with_set_hall_of_fame_channel
- [x] **`/troubleshoot`.** It lists a channel the bot cannot read, privately, and refuses members.
      `admin` InstallingTests.test_troubleshoot_finds_a_channel_the_bot_cannot_read,
      test_a_member_cannot_run_troubleshoot
- [x] **Every setting command.** For each of `/set_reaction_threshold`, `/set_post_due_date`,
      `/include_authors_reaction`, `/allow_messages_in_hof_channel`, `/require_image_or_video`,
      `/ignore_bot_messages`, `/hide_hof_post_below_threshold`, `/count_in_global_profiles`,
      `/custom_emoji_check_logic` and `/calculation_method`: a member is refused privately, the admin's
      change is stored and announced, the same value again says nothing changed, and a restart loads it.
      `admin` SettingCommandTests
- [x] **What each setting does to a post.** The author's own reaction, image or video required, other
      bots' messages, unique members, posts kept up below the threshold, a shorter post due date, chat in
      the board, and member commands turned away in a board closed to chat.
      `admin` SettingEffectTests
- [x] **The emoji whitelist.** Refused while off, turned on with the empty-list note, an emoji added (a
      second time refused), other emojis no longer count, removed, cleared, cleared again refused.
      `admin` SettingEffectTests.test_the_whitelist_from_turning_it_on_to_clearing_it
- [x] **The settings form.** Opened from `/get_server_config` or the welcome message's Set up button,
      several settings saved in one private answer, unchanged says so, a wrong number stores nothing, a
      member cannot open it, and picking another channel moves the board with nobody pinged.
      `admin` SettingsFormTests
- [x] **Moving the board.** A channel the bot cannot post in is refused with what is missing, the new
      board gets the announcement with nobody pinged, the next post lands there, and posts on the old board
      keep their counts. `admin` MovingTheBoardTests
- [x] **`/get_server_config`.** Shown with Troubleshoot and Change settings.
      `admin` InstallingTests.test_from_install_to_the_first_post
- [x] **The bot is removed.** Settings and posts are deleted, the leave is recorded, later reactions and
      commands change nothing, and adding it back starts from scratch.
      `admin` RemovalTests
- [ ] **manual:** the command picker shows only the commands a member may use, and a role an admin lets
      see a setting command is still refused (Discord applies `default_permissions`). The refusal itself
      is tested in `admin` SettingCommandTests.

## Members

- [x] **Reaching the board, hiding and coming back.** Under the threshold Why says how far it is, the
      threshold posts it once, credited and pinging nobody, more reactions update the same post, dropping
      below hides it in place with the row kept, and climbing back shows the same post with the new count.
      `member` BoardLifeTests.test_a_message_reaches_the_board_hides_and_comes_back
- [x] **Reactions that do not count.** Other bots' reactions, and reactions on the board's own posts.
      `member` BoardLifeTests.test_reactions_from_bots_and_on_the_board_itself_are_left_out
- [x] **Editing a featured message.** The next reaction shows the new text.
      `member` BoardLifeTests.test_an_edited_message_shows_its_new_text_with_the_next_reaction
- [x] **Deleting a featured message.** The post and its row stay, nothing is logged as an error, and Why
      says the message is gone.
      `member` BoardLifeTests.test_a_featured_message_that_is_deleted_leaves_its_post
- [x] **A moderator deletes a post on the board.** It is not posted again, and its stored count keeps up.
      `member` BoardLifeTests.test_a_post_a_moderator_deleted_is_not_posted_again_but_keeps_counting
- [x] **Why isn't this on the board?** Below the threshold, on the board, hidden, gone, posted elsewhere,
      the board itself, and the few seconds before asking again. Every answer is private.
      `member` BoardLifeTests, and the reasons below under edge paths
- [x] **`/leaderboard`.** Ranked after the daily update, public, once a day per member, and open again
      after the next daily task.
      `member` LeaderboardAndProfileTests.test_the_leaderboard_after_the_daily_update
- [x] **`/user_profile`.** Your own, someone else's, someone never featured, a bot refused privately,
      and before the daily update. `member` LeaderboardAndProfileTests
- [x] **`/hof_wrapped` and `/server_hof_wrapped`.** Not made yet, then made from the server's real
      posts: a featured member's card, a member not in it told privately, the server's card.
      `member` WrappedTests
- [x] **`/my_data`: download.** Nothing stored greys out Download and Delete, posts are counted, the
      private file holds them, a second download the same day is refused, another member cannot press the
      buttons, and the daily task lifts the limit.
      `my_data` DownloadAndTotalsTests.test_from_nothing_stored_to_a_download
- [x] **`/my_data`: hide totals.** The every-server column leaves the member's own profile, a DM profile
      says they are hidden, and showing them brings both back.
      `my_data` DownloadAndTotalsTests.test_hiding_and_showing_the_totals_across_servers
- [x] **`/my_data`: stop featuring me and feature me again.** New messages are neither posted nor
      stored, earlier ones stay credited and keep counting, Why tells a friend only that it cannot be
      featured and the author that it was their choice, others are featured as usual, the download says
      `not_counted`, and featuring again credits the next post.
      `my_data` NotBeingFeaturedTests.test_stopping_and_starting_again
- [x] **`/my_data`: delete.** Cancel deletes nothing. Confirming keeps the post on the board credited to
      nobody, takes the member off the leaderboard and profile, and offers Stop featuring me. With only that
      choice stored, deleting again the same day is allowed and removes it. With posts again, it is refused.
      `my_data` DeletingTests.test_deleting_and_coming_back
- [x] **`/my_data` in a DM.** `my_data` DeletingTests.test_my_data_works_from_a_dm
- [x] **`/feedback`.** The form reaches the developer channel, three a day, then refused, also from a DM.
      `member` FeedbackTests
- [x] **`/vote`, `/invite` and `/help`.** Answered with their link buttons in a server and in a DM, and
      `/help` names commands as clickable mentions. `member` LinkCommandTests
- [ ] **manual:** how a post looks (galleries, spoilers, GIFs, replies, stickers, polls, forwards),
      which `tests/test_post_matrix.py` checks from the payload. See "Board posts" in the release plan.
- [ ] **manual:** the `/my_data` buttons disappearing after two minutes, and files over Discord's size
      limit being split. The split itself is tested in `tests/test_member_data.py`.

## Edge paths

- [x] **Opted-out members.** `my_data` NotBeingFeaturedTests, both tests. A member who opts out while
      their post is being sent: `integration/test_member_data_deletion.py` StopFeaturingTests.
- [x] **Age-restricted channels.** A message there is not posted, Why and `/troubleshoot` say so, and an
      age-restricted board takes it. A post whose channel becomes age-restricted hides, and comes back once
      the board is too. `edges` AgeRestrictedChannelTests
- [x] **Flagged media.** Gore is never posted, explicit media only to an age-restricted board, Why says
      it was flagged, and a post Discord flags after it was sent is taken down and stays down.
      `edges` FlaggedMediaTests
- [x] **Channels the bot cannot read.** Reactions are ignored without an error, Why and `/troubleshoot`
      name the channel, and once readable the next reaction counts. `edges` UnreadableChannelTests
- [x] **Missing permissions.** A board the bot cannot post in: nothing stored, Why and `/troubleshoot`
      say what is missing, the daily task warns once, and fixing it posts the message and forgets the
      warning. A deleted board points to `/set_hall_of_fame_channel`. `edges` MissingPermissionTests
- [x] **The daily task.** Counts refreshed from live reactions, statistics rebuilt for the leaderboard
      and profile, cooldowns lifted, the monthly snapshot taken, and a deleted message or a server missing
      for one day does not stop it. `edges` DailyTaskTests
- [x] **User install in DMs and servers without the bot.** The profile is the member's own totals only,
      looking up someone else is refused, a server without the bot counts as outside, and server-only
      commands say the server is not set up. `edges` UserInstallTests
- [x] **The daily post limit and the 10,000 post limit.** Already walked in
      `integration/test_reaction_path.py` GateTests and `integration/test_member_data_deletion.py`
      StopFeaturingTests.
- [ ] **manual:** Private Channel Obfuscation, which only a real bot with the Developer Portal setting
      shows. The flag's handling is tested in `tests/test_setup_check.py`.
