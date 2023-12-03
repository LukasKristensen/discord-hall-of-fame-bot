import os
import asyncio
from dotenv import load_dotenv
import interactions

load_dotenv()
TOKEN = os.getenv('KEY')
bot = interactions.Client(token=TOKEN)

@bot.command(
    name="ping",
    description="Example description")

async def my_first_command(ctx: interactions.CommandContext):
    # Introduce a delay of 1 second before responding to avoid rate-limiting
    await asyncio.sleep(1)
    await ctx.send("Pong")

bot.start()
