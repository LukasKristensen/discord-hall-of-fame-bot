# Manual tests

Checks run by hand on the development bot, for behaviour the automated tests can only fake: what
Discord itself accepts, and how the bot looks to a member. Newest first.

## 21 October 2026: member data, the post limit and the export (2.2)

Run on the development bot (`DEV_TEST=True`) in the development server, against the development
database.

### How the posts were made

Thousands of featured posts cannot be made by hand, so a temporary development-only command inserted
them into `hall_of_fame_message` and was removed afterwards. To repeat these tests, insert rows the same
way:

- **Author** is the tester's user ID, **guild** the development server.
- **Message IDs** start at 9,000,000,000,000,000,000. That is far above any Discord ID, so they never
  collide with a real post and can be deleted by range afterwards
  (`DELETE FROM hall_of_fame_message WHERE message_id >= 9000000000000000000`).
- **Dated before today.** The server's daily post limit counts today's posts, and 100 of them would stop
  every post from reaching the board.
- **Channel 0**, so the daily leaderboard update skips them instead of fetching messages that do not
  exist.
- **One reaction each**, so they rank below real posts.

The rows go through the unchanged production code from there: the post limit counts them, `/my_data`
reads them, and the daily task ranks them.

### Post limit (10,000 per member, all servers together)

| Test | Result |
|:---|:---|
| Brought the tester to exactly 10,000 credited posts, then pushed a message over the threshold | It reached the board, was stored without an author, and one critical alert (no ping) reached the log channel |
| Pushed a second message over the threshold | It reached the board, uncredited, with no second alert |
| `/my_data` at the limit | 10,000 featured posts. The posts past the limit were not counted |

### `/my_data` export

| Featured posts | Result |
|:---|:---|
| 10,000 | One file of 2.25 MiB. Exactly 10,000 posts, 10,000 unique message IDs, all IDs written as strings. The uncredited posts were not in it |
| 50,000 | One file of 13 MB. Discord accepted it whole, so its limit in that context is above 10 MiB |
| 150,000 | Discord refused the single file, so it came as 5 parts: four of 8 MiB and one of about 4 MB, each a complete JSON file |
| 2,450,000 | Too big even split: answered with the support-server message, nothing half-sent, and the day's download was not used up |

About 236 bytes per post, so one file stays under Discord's default 10 MiB up to roughly 44,000 posts.

### Not being featured and deleting

| Test | Result |
|:---|:---|
| Delete my data | Removed from every leaderboard, profile and Wrapped. The confirmation was edited in place once the deletes finished |
| Stop featuring me, then posted a message over the threshold | It reached the board but `/my_data` showed no featured posts |
| `/my_data` with only the choice not to be featured stored | Showed that choice with its date, and Feature me again |
| Pressed Delete again on the same day | Answered that the data was already deleted today |

### Found and fixed during these tests

- After a deletion, the summary said nothing of the member's had ever reached a Hall of Fame. It now
  says what is not stored instead.
- Large counts were written without separators ("2450000"). They now read "2,450,000".
- Download was greyed out when the only stored data was a choice. A choice is data about the member,
  so it can now be downloaded.
