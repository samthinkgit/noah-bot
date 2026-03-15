from discord.ext import commands

from noah_bot.commands.core import register_core_commands
from noah_bot.commands.noah import register_noah_commands
from noah_bot.commands.steallist import register_steallist_commands
from noah_bot.commands.waifuracer import register_waifuracer_commands


def register_commands(bot: commands.Bot) -> None:
    register_core_commands(bot)
    register_waifuracer_commands(bot)
    register_noah_commands(bot)
    register_steallist_commands(bot)
