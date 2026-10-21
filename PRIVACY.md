# Privacy Policy for Hall of Fame

Effective date: 10 November 2026

Hall of Fame is a Discord bot operated by Lukas Kristensen, Denmark, who is responsible for the data
described here. Contact: githublukas@gmail.com, or the
[Hall of Fame support server](https://discord.gg/r98WC5GHcn).

## 1. What the bot stores

- **Server settings:** the server ID, the Hall of Fame channel ID, your configuration, the date the bot
  joined, and monthly member counts.
- **Featured messages:** the IDs of the message, its channel and its author, its reaction count and
  time, and the ID of the bot's repost. The text, images and usernames are not stored in our database.
  The repost itself lives in your server's Hall of Fame channel on Discord. At most 10,000 featured
  messages are linked to any one member, across all servers, so `/my_data` can always give you all of
  your data. Messages of yours featured past that are stored without your user ID.
- **Member statistics:** per-server totals and ranks for featured messages and reactions.
- **Totals across servers:** your posts, reactions, titles and badges added up across every server that
  uses the bot, worked out from the data above and shown at the bottom of your profile in any of those
  servers. If you add the bot to your own account, you can also show your own profile in DMs and in servers
  without the bot, where it shows these totals alone. Nobody else can look you up there. They are numbers only, never a server name, server ID or message content. If you hide them
  with the button on `/my_data`, your user ID is stored with the date you hid them. Server admins can leave
  their server out of everyone's totals with `/count_in_global_profiles`.
- **Hall of Fame Wrapped:** yearly statistics per member, including most-used channels and emojis and
  which members react to each other's posts most often.
- **Not featured:** if you press "Stop featuring me" on `/my_data` (it is also offered right after you
  delete your data), your user ID is stored with the date, so the bot remembers not to repost or store
  new messages of yours. When someone else's reply to one of your messages reaches the board, it is
  reposted without your message. Without the record, the bot would have no way to know to leave your
  future messages out. What is already stored about you stays until you delete it, but nothing new is stored about you:
  no new posts, and no Wrapped, since a Wrapped also records whose posts you reacted to. You are left out
  of other members' Wrapped too. Choosing "Feature me again" or deleting your data deletes this record.
- **Support:** feedback sent with `/feedback` and custom profile requests, delivered to a private
  developer channel on Discord.
- **Logs:** which commands were used, when the bot joins or leaves a server and what it is allowed to do
  there, and errors, each with the server's ID, posted to private developer channels on Discord for
  troubleshooting. Logs do not name servers or the members who used a command. The
  one exception is a member reaching the limit of 10,000 featured posts, whose user ID is logged so the
  developer can check it for farmed reactions.

## 2. What the bot reads but does not store

To work, the bot reads reactions and the content and attachments of messages that reach the threshold,
so it can count them and repost them in the same server. Message content is not saved to our database.

When the bot joins a server, and whenever an admin runs `/troubleshoot`, it also reads the server's
channels, roles, channel permissions and member count, to find setup problems such as channels it
cannot see. The result is posted in that server and is not saved.

When a member uses **Why isn't this on the board?** on a message, the bot reads that message, its
reactions and the server's settings to explain whether it reached the board. Only that member sees the
answer, and it is not saved. If the author asked not to be featured, only the author is told that this
is the reason.

## 3. How the data is used

Only to provide the bot's features: posting to the Hall of Fame, leaderboards, profiles and Wrapped,
plus support and troubleshooting. Your totals across servers can be shown in any server with the bot. Outside
those servers, only you can show them, through the bot added to your own account. They are only ever
shown as totals, so they do not reveal which servers you are in, and once you hide them
on `/my_data` they are not shown anywhere. Aggregated statistics that cannot identify anyone are used to improve
the bot. Data is never used for advertising, sold, used to track who people are or which servers they
are in, or used to train AI models. The legal basis is our legitimate interest in running the features a server has chosen to
use.

## 4. Who receives data

- Discord, which hosts all messages, reposts and log channels.
- Bot listing sites where the bot is listed, such as top.gg, which receive only the bot's server count
  and its public command list.
- Authorities, if the law requires it.

Nothing else is shared.

## 5. How long data is kept

- Removing the bot from a server immediately deletes that server's featured messages, member
  statistics, Wrapped data and settings. If the bot was offline when it was removed, Discord does not
  tell it, so the data is deleted once the server has been gone for 7 days and Discord confirms the bot
  no longer has access to it.
- Join and leave dates and monthly member counts are kept as anonymous server statistics.
- Your choice to hide your totals across servers is kept until you show it again or delete your data.
- Other data is kept while the bot is in the server, and deleted on request as described in section 6.
- Deleting your data on `/my_data` immediately deletes your member statistics, Wrapped data and your
  choice to hide your totals, removes you from other members' Wrapped, and removes your user ID from
  your featured messages. The reposts stay in each server's Hall of Fame channel, since they belong to
  that server, but are no longer linked to you. Your choice not to be featured, if you made it, is
  deleted too, so messages of yours featured after that are stored again as usual, unless you press
  "Stop featuring me", which is offered right after deleting.

## 6. Your rights

Everything below is done from `/my_data`, which shows what is stored about you with a button for each:

- **See your data:** `/my_data` lists what is stored about you, including the dates of your choices,
  and "Download my data" sends you a file with all of it.
- **Delete your data:** "Delete my data" deletes it after you confirm, as described in section 5.
- **Object to being featured:** press "Stop featuring me", and the bot stops reposting and storing new
  messages of yours. What is already stored stays until you delete it. "Feature me again" undoes it.
- **Hide your totals across servers:** "Hide my totals across servers".

`/my_data` only answers you, and works in any server with the bot and in DMs once you add the bot to
your account.

You can also ask us to correct your data, limit or object to its use, or send it in a portable format,
by messaging us in the support server. Requests must come from your own Discord account so we know who
is asking; a request by email is answered with a request to confirm it there. We reply within 30 days.
Server admins can delete any repost from their Hall of Fame channel at any time.

You also have the right to complain to a data protection authority; in Denmark that is
[Datatilsynet](https://www.datatilsynet.dk).

## 7. Age

Discord requires users to be at least 13 years old, and so does this bot.

## 8. Security

The database is kept on an access-controlled machine, and the bot's credentials are never shared. No
system is perfectly secure, and we will tell affected users and Discord about any breach as required.

## 9. Changes

Changes are made to this file in the
[GitHub repository](https://github.com/LukasKristensen/discord-hall-of-fame-bot), where its history
shows every earlier version. The effective date above is updated with each change, and significant
changes are announced in the support server.
