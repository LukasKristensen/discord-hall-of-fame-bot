# App Directory listing

Copy for the Hall of Fame page in the Discord App Directory. Paste each block into the matching field in
the Developer Portal. Keep this file in step with the README when commands or defaults change.

Last checked against the bot: 2.1.1.

<br>


## Summary

Developer Portal > App Directory > Summary. Shown in directory search results. Limit 200 characters.

```
Turn your server's best messages into a Hall of Fame. Any emoji can feature a message, and members compete on leaderboards, profiles and a yearly Wrapped.
```

<br>


## Description

Developer Portal > General Information > Description. Shown on the bot's profile when someone clicks
it in a server. Limit 400 characters.

```
Hall of Fame reposts your server's most reacted messages to a hall of fame channel, with images, videos and reply context. Every emoji counts. Members who land there get credit: /leaderboard ranks the server, /user_profile shows monthly and all time standing, and /hof_wrapped gives everyone their year in review. Free, with no vote locks.
```

<br>


## Detailed description

Developer Portal > App Directory > Detailed description. Shown on the app's directory page. Supports
markdown.

```
**Your server's best moments, and the members behind them.**

When a message gets enough reactions, Hall of Fame reposts it to your hall of fame channel. The members who land there get leaderboards, profiles and a yearly Wrapped, so your server has something to compete over.

**The board**
- Any emoji counts, custom server emojis included. Or choose a whitelist of up to 100.
- Images, videos and stickers are carried over, and videos stay playable.
- If the message was a reply, the message it replied to is shown with it, so the joke still makes sense.
- Reaction counts update live. A post that drops below the threshold is hidden until it climbs back.

**The recognition**
- /leaderboard ranks the server by posts and reactions earned.
- /user_profile shows a member's monthly and all time totals and rank.
- /hof_wrapped and /server_hof_wrapped give each member, and the server, a year in review.

**Count it your way**
- Most reactions on one emoji, total reactions, or unique people who reacted.
- Choose whether authors' own reactions count, how old a message can be, and whether only images and videos qualify.

**Getting started**
1. Add the app and accept the permissions it asks for.
2. It creates a #hall-of-fame channel and picks a starting threshold from your member count.
3. React as normal. Change the threshold with /set_reaction_threshold, or use an existing channel with /set_hall_of_fame_channel.

If most of your channels are hidden behind a role, give the bot that role so it can see them.

Free to use, with nothing held back behind voting. Questions or ideas? Join the support server or use /feedback.
```

<br>


## Tags

Up to 5. Picked for what people type when they look for this kind of bot.

```
hall of fame
leaderboard
reactions
highlights
community
```

<br>


## Category

Pick **Social** as the main category, and **Entertainment** as the second if the portal offers it.
Moving away from Moderation and Tools puts the app beside community and fun apps rather than MEE6 and
Dyno, which is where people browsing for this kind of bot look.

<br>


## Images

Upload in this order. The first image is the one most people see.

| Order | What it should show | Source |
|:---|:---|:---|
| 1 | A current hall of fame post with an image and a reply, in the present layout | New screenshot |
| 2 | `/leaderboard` in a real server | New screenshot, or `Assets/all_time_most_hall_of_fame_posts.png` |
| 3 | `/user_profile` for an active member | New screenshot |
| 4 | `/hof_wrapped` | New screenshot |
| 5 | The three counting methods side by side | `Assets/reaction_calculation_methods_wide.jpg` |
| 6 | A short clip: a message gets reactions and appears on the board | New recording, under 30 seconds |

Replace the current screenshot that shows the old "has surpassed 7 reactions" layout.

<br>


## Links

| Field | Link |
|:---|:---|
| Support server | https://discord.gg/r98WC5GHcn |
| GitHub | https://github.com/LukasKristensen/discord-hall-of-fame-bot |
| Vote | https://top.gg/bot/1177041673352663070/vote |

Terms of Service and Privacy Policy are already set and stay as they are.

<br>


## Install permissions

Developer Portal > Installation > Default Install Settings, guild install, scopes `bot` and
`applications.commands`.

Match the invite link, `INVITE_PERMISSIONS` in `src/translations/messages.py` (`275146730576`):

| Permission | Why the bot needs it |
|:---|:---|
| View Channels | See the messages being reacted to |
| Read Message History | Fetch older messages when reactions arrive |
| Send Messages | Post to the hall of fame channel |
| Send Messages in Threads | Answer a ping inside a thread |
| Embed Links | Hall of fame posts, leaderboards and profiles are embeds |
| Use External Emojis | The leaderboard's month and all time emojis |
| Manage Channels | Create the #hall-of-fame channel on join |
| Manage Roles | Set the hall of fame channel's permission overwrites on join |
| Manage Messages | Remove chat from the hall of fame channel when chat there is off |
| Attach Files | Not used yet, asked for so image cards work on servers that install now |
| Add Reactions | Not used yet, asked for ahead of later features |

The current listing also asks for Manage Threads, Create Public Threads and Pin Messages. Nothing in
`src/` uses them, so untick them. Servers that already have the bot keep the permissions they granted.

<br>


## Popular commands

The directory lists a handful of commands with their descriptions. If the portal lets you choose them,
show the ones members use: `/leaderboard`, `/user_profile`, `/hof_wrapped`, `/server_hof_wrapped` and
`/set_reaction_threshold`.
