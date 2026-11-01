# Manual tests

Checks run by hand on the development bot, for behaviour the automated tests can only fake: what
Discord itself accepts, and how the bot looks to a member. Newest first.

## 1 November 2026: Components V2 board posts, message by message (3.0)

Run on the development bot (`DEV_TEST=True`) in the development server, threshold 1, one channel per kind of
message under a "test cases" category so each post names what it tests.

### Passed

| Channel | Message | Result |
|:---|:---|:---|
| plain-text | Short text | Name, channel and text beside the avatar |
| image | One image | Shown in the gallery. A small image makes the card as narrow as the image |
| gif | A GIF | Loops in the gallery. Narrow like a small image |
| video | One video | Plays in place |
| emoji | Only an emoji | Shown beside the avatar at normal size, not jumbo as in the channel |
| forward | A forwarded screenshot | "in #forward · Forwarded" and the image |
| poll | A poll | "Poll", the question in bold and each answer with its votes, "1 vote" and "0 votes" |
| thread / forum post | Text in a forum post | The mention shows the thread's name with its icon |
| reply | A reply to a text message | "Replying to", the quote, a gap, then the poster's name above their words, as in Discord |
| long-text | Over 300 characters | Full width under the header, no avatar |
| long-text | About 1,970 characters | Shown whole. Did not reach the 2,000 cut, see below |
| multi-media | 4 images, 10 images | Laid out as in Discord, 2 by 2 and 1 over 3 by 3, order kept |
| multi-media | Images, a spoiler and a video together | The spoiler covered, the video playing, order kept |
| multi-media | 10 copies of one image and an image link | The first 10 in the gallery and "1 more in the original message" under it. All 10 copies loaded |
| mixed | Text and an image | Text beside the avatar, the image full width below |
| mixed | A reply to a poll | The quote reads *Poll: question*. The app cannot send text and a poll in one message |
| link | A YouTube link alone | The link kept as text, the video's thumbnail as a still picture in the gallery |
| link | A GIF link alone | The link replaced by the GIF, as Discord shows it. Loops as a GIF, no player controls |
| file | Text and an audio file | Text beside the avatar, the file linked by its name under it. No player, unlike the original |
| file | A zip file alone | The file linked by its name under the header, no avatar as there is no text |
| forward | A forward from a channel the bot cannot see | "Forwarded" in the header and *The forwarded message is not shown*, none of its words |
| file | A voice message | Linked as "Voice message" under the header. No player, like an audio file |
| mentions | `@user`, `@role`, `@here`, `@everyone` | Shown as mentions. A second account in the server got no notification and no mention badge |
| link | An image URL alone | The link replaced by the image, as Discord shows it |
| link | Text with an image link | Text and link kept beside the avatar, the image previewed below |
| sticker | An animated (Lottie) sticker | Named in italics where the text goes, *Sticker: name* |
| sticker | A picture sticker, two different reactions | Shown in the gallery. The reactions line lists both emojis with their counts |
| reply | A reply to an image, a reply to a video | The quote, then the answered image or playable video full width, then the reply under its poster's name |
| reply | A reply to a deleted message | "Replying to a deleted message" above the poster's name, no quote |
| reply | A reply to a member who pressed Stop featuring me | Posted with no "Replying to" line and no quote, so the member is not named |

### Found

- **One gallery item can fail to load for good** ([#104](https://github.com/LukasKristensen/discord-hall-of-fame-bot/issues/104)).
  The same video attached four times failed on its first item in 4 of 5 posts, on desktop and mobile.
  Holding the post until the message was 10 seconds old did not help and was reverted. Different files
  in one gallery have always loaded so far, and so did 10 copies of one image, so duplicates alone do not
  cause it: so far only repeated videos have failed.
- **A user mention can read as unknown user.** A new second account, in a browser, saw `@Lukas` on the board
  as "@unknown-user" (in Danish, "@ukendt-bruger"). A post does not carry the users it mentions, so the
  name only shows once the reader's app has loaded that member. After opening the member's profile it
  showed the name. Left as it is: writing names in bold would fix it for the few readers who see it, but
  take the click to the profile from everyone.
- A spoiler once showed uncovered right after posting. A reload covered it, so it was the client, not the
  bot.
- Poll votes are written when the post is made and not updated after.
- Whether a post shows the avatar depends on its text: only posts with up to 300 characters of text have
  it, so media-only and long-text posts look like a different template.

### Ideas from these tests

Not bugs, and nothing decided yet:

- **An avatar on every post.** Only posts with up to 300 characters of text show it today. A third heading
  line with when the message was sent (`<t:...:R>`) would fill the space beside the avatar, so media-only
  and long-text posts could keep it too, and posts would show their date, which none do now.
- **Poll votes that stay current.** Rebuild the poll text when the post is edited, or label the counts as
  at the time it was featured. A closed poll could mark its winning answer.
- **A neater cut at 2,000 characters.** Cut at the last space and end with `…`, instead of mid-word with
  `...`. The docstring of `truncate_content` still describes the old 1,024 character embed field.
- **Jumbo emoji.** A message that is only emoji shows them at normal size. Worth trying whether a full-width
  `TextDisplay`, outside the `Section`, shows them large as Discord does.
- **The parent of a thread.** "in #forum › thread name", so a thread with a vague name still says where it is.
- **A reply to a member who opted out.** It shows no reply line at all. "Replying to a message", with no
  name or quote, keeps the context without naming them, like the line for a deleted message.
- **The title of a YouTube link.** Its thumbnail looks like any picture and opens the picture.
  "-# YouTube · title" under it, from the link preview, says it is a video.
- **Smaller quoted media.** The answered image or video is shown full width, larger than the reply itself.
  A thumbnail beside the quote would put the featured message first, but a thumbnail cannot play a video.
  Kept as it is for now.

- **Audio that plays on the board.** An audio file is only a link, where the original has a player. A
  Components V2 `File` component plays audio, but only for a file uploaded with the post itself, so the bot
  would have to download and upload it again, within the board's upload size limit.

- **A file line that says what it is.** A file shows only as its name, so a post of just a zip reads bare.
  A size, or a 📎 in front, would make it read as a file rather than a stray link.

### Still to run

- **The 2,000 character cut:** needs Nitro, or a lower `post_text_limit` on the development bot.
- **A member who opted out:** check that their message posted after opting out does not reach the board.
  In this run their message was on the board, possibly reacted to before they opted out.
- **file:** whether a file link still opens a day after posting.
- **forward:** a forwarded poll.

## 21 October 2026: member data, the post limit and the export (3.0, then called 2.2)

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
