# Discord Hall Of Fame Bot
The purpose of the bot is to monitor the maximum amount of message reactions and repost the message to a board if it surpasses a threshold value. Unlike star bots, this bot is not limited to one emoji but will prompt any emoji reactions.

<br>

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
- [x] Problem with using discord user profile pictures using Discord<=2.0.0
- [x] Deploy on a remote server
- [ ] Improve the embed layout of messages
- [ ] Improve media output
- [ ] Create a command for updating variable names
- [ ] Make a folder for each server with private value preferences
- [x] Improve database structure to mongodb
- [x] Functionality for checking historical messages (it should run through all the messages and post the ones above the reaction value threshold
- [ ] When posting the message highlight the reaction emoji from the original message
- [x] Fix message IDs not being saved/loaded correctly when validating if it has already been sent
- [x] Create a getRandom() function for grabbing a random hall-of-fame post
