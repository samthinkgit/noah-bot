import os

import discord
from discord.ext import commands
from dotenv import load_dotenv

from noah_bot.commands import register_commands
from noah_bot.modules.bot_context import create_bot_context


def load_token() -> str:
    load_dotenv()
    token = os.getenv("DISCORD_BOT_TOKEN")

    if not token:
        raise RuntimeError("DISCORD_BOT_TOKEN not found in .env")

    return token


def create_intents() -> discord.Intents:
    intents = discord.Intents.default()
    intents.message_content = True
    intents.members = True
    intents.voice_states = True
    return intents


def create_bot() -> commands.Bot:
    bot = commands.Bot(command_prefix=".", intents=create_intents())
    bot.noah_context = create_bot_context()
    register_commands(bot)
    return bot


def main() -> None:
    bot = create_bot()
    bot.run(load_token())


if __name__ == "__main__":
    main()
