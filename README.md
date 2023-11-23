# Discord Hall Of Fame Bot
The purpose of the bot is to monitor the maximum amount of message reactions and repost the message to a board if it surpasses a threshold value. Unlike star bots, this bot is not limited to one emoji but will prompt any emoji reactions.

## Installing
Create an .env file containing the bot key:
```KEY:SECRET```

Install packages:
```pip install -r requirements.txt```

<br>

## Configuring
Define your Hall Of Fame channel by updating the ID to the discord channel: ```YOUR_DEDICATED_CHANNEL_ID```

Define the amount of reactions necessary for posting: ```reaction_threshold```

<br>

## TODO
- Create a command for updating variable names
- Make a folder for each server with private value preferences
