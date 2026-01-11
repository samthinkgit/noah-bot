import os
import time
import discord
from discord.ext import commands
from dotenv import load_dotenv


from noah_bot.ai import AiResponder
from noah_bot.discord_formatter import DiscordChart, UserEmojiManager, EmbedTable

from noah_bot.leaderboard import Leaderboard, generate_date
from noah_bot.steallist import StealList


def main():
    # ---------------- ENV ---------------- #

    load_dotenv()
    TOKEN = os.getenv("DISCORD_BOT_TOKEN")

    if not TOKEN:
        raise RuntimeError("DISCORD_BOT_TOKEN not found in .env")

    # ---------------- DISCORD SETUP ---------------- #

    intents = discord.Intents.default()
    intents.message_content = True

    bot = commands.Bot(command_prefix=".", intents=intents)

    leaderboard = Leaderboard()
    emoji_manager = UserEmojiManager()
    ai_responder = AiResponder()
    steallist = StealList()

    # Active timers per user
    timeit_sessions = {}
    latest_time_it = None

    # ---------------- EVENTS ---------------- #

    @bot.event
    async def on_ready():
        print(f"Bot connected as {bot.user}")

    # ---------------- TIMEIT / CLAIM ---------------- #

    @bot.command()
    async def timeit(ctx):
        global latest_time_it
        """
        Starts a timer for the calling user.
        """
        timeit_sessions[ctx.author.id] = time.time()
        latest_time_it = time.time()

    @bot.command()
    async def claim(ctx, *, text: str = None):
        """
        Stops the timer for the calling user and stores the result.
        """
        user_id = ctx.author.id
        user_emoji = emoji_manager.get_emoji(ctx.author.id)
        if user_emoji:
            try:
                await ctx.message.add_reaction(user_emoji)
            except discord.HTTPException:
                pass

        if user_id not in timeit_sessions:
            return

        start_time = timeit_sessions.pop(user_id)
        elapsed = time.time() - start_time

        await ctx.send(
            f"{ctx.author.mention} obtained a time of `{elapsed:.4f}` seconds!"
        )

    # ---------------- WAIFURACER GROUP (with alias) ---------------- #

    @bot.group(name="waifuracer", aliases=["wfr"])
    async def waifuracer(ctx):
        """
        Waifuracer leaderboard commands.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `.waifuracer help` or `.wfr help` to see commands.")

    # ---------------- HELP ----------------GG#

    @waifuracer.command()
    async def help(ctx):
        chart = EmbedTable(headers=["Command", "Description"], title="Waifuracer Commands")
        chart.add_row(
            [".waifuracer add @user <time> [-tag tag]", "Add a new time record."]
        )
        chart.add_row([".waifuracer remove <id>", "Remove a time record by ID."])
        chart.add_row(
            [
                ".waifuracer top [-user @user]",
                "Show top 20 records (optionally by user).",
            ]
        )
        chart.add_row(
            [
                ".waifuracer latest [-user @user]",
                "Show latest 20 records (optionally by user).",
            ]
        )
        chart.add_row([".waifuracer elapsed", "Show elapsed time since last .timeit"])
        chart.add_row([".waifuracer predict", "Predict next waifu appearance time."])
        chart.add_row(
            [".waifuracer setemoji <emoji>", "Set your claim reaction emoji."]
        )
        chart.add_row([".timeit", "Start a waifuracer timer."])
        chart.add_row([".claim", "Stop timer and show result."])

        await ctx.send(embed=chart.render())

    # ---------------- ELAPSED ---------------- #

    @waifuracer.command()
    async def elapsed(ctx):
        global latest_time_it
        """
        .waifuracer elapsed
        """
        if latest_time_it is None:
            await ctx.send("No active timers.")
            return

        elapsed = time.time() - latest_time_it

        await ctx.send(f"Elapsed time since last .timeit: `{elapsed:.4f}` seconds.")

    @waifuracer.command()
    async def predict(ctx):
        global latest_time_it
        """
        .waifuracer elapsed
        """
        if latest_time_it is None:
            await ctx.send("No active timers.")
            return

        elapsed = 240 - (time.time() - latest_time_it)

        await ctx.send(f"Next waifu should appear on `{elapsed:.4f}` seconds.")

    # ---------- SET EMOJI ---------- #
    @waifuracer.command()
    async def setemoji(ctx, emoji: str):
        """
        .wfr setemoji <emoji>
        Sets the reaction emoji for the calling user.
        """
        # Validate emoji by trying to react
        try:
            await ctx.message.add_reaction(emoji)
        except discord.HTTPException:
            await ctx.send("Invalid emoji. Please provide a valid emoji.")
            return

        emoji_manager.set_emoji(ctx.author.id, emoji)
        await ctx.send(f"{ctx.author.mention} your claim emoji is now {emoji}")

    # ---------------- ADD RECORD ---------------- #

    @waifuracer.command()
    async def add(ctx, user: discord.Member, record_time: float, *, args: str = None):
        """
        .waifuracer add @user <time> [-tag tag]
        """
        tag = None

        if args and args.startswith("-tag"):
            tag = args.replace("-tag", "").strip()

        record_id = leaderboard.add_record(
            user_id=user.id,
            username=user.display_name,
            record_time=record_time,
            created_at=generate_date(),
            tag=tag,
        )

        await ctx.send(
            f"Record `{record_id}` added for {user.mention}: "
            f"`{record_time:.4f}` seconds" + (f" (tag: `{tag}`)" if tag else "")
        )

    # ---------------- REMOVE RECORD ---------------- #

    @waifuracer.command()
    async def remove(ctx, record_id: int):
        """
        .waifuracer remove <id>
        """
        success = leaderboard.delete_record_by_id(record_id)

        if success:
            await ctx.send(f"Record `{record_id}` removed.")
        else:
            await ctx.send(f"Record `{record_id}` not found.")

    # ---------------- TOP ---------------- #

    @waifuracer.command()
    async def top(ctx, *, args: str = None):
        """
        .waifuracer top [-user @user]
        """
        user = None

        if args and args.startswith("-user") and ctx.message.mentions:
            user = ctx.message.mentions[0]

        if user:
            records = leaderboard.get_records_by_user(user.id)
            records = sorted(records, key=lambda r: r["record_time"])[:20]
        else:
            records = leaderboard.get_top_n(20)

        if not records:
            await ctx.send("No records available.")
            return

        chart = DiscordChart(headers=["ID", "User", "Time (s)", "Date", "Tag"])

        for r in records:
            chart.add_row(
                [
                    str(r["id"]),
                    r["username"],
                    f'{r["record_time"]:.4f}',
                    r["created_at"],
                    r["tag"] or "-",
                ]
            )

        await ctx.send(chart.render())

    # ---------------- LATEST ---------------- #

    @waifuracer.command()
    async def latest(ctx, *, args: str = None):
        """
        .waifuracer latest [-user @user]
        """
        user = None

        if args and args.startswith("-user") and ctx.message.mentions:
            user = ctx.message.mentions[0]

        if user:
            records = leaderboard.get_records_by_user(user.id)[-20:]
        else:
            records = leaderboard.get_all_records()[-20:]

        if not records:
            await ctx.send("No records available.")
            return

        chart = DiscordChart(headers=["ID", "User", "Time (s)", "Date", "Tag"])

        for r in records:
            chart.add_row(
                [
                    str(r["id"]),
                    r["username"],
                    f'{r["record_time"]:.4f}',
                    r["created_at"],
                    r["tag"] or "-",
                ]
            )

        await ctx.send(chart.render())

    # --------------- NOAH --------------- #
    @bot.group()
    async def noah(ctx):
        """
        Noah AI commands.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `.noah ask <question>` to talk with Noah.")

    @noah.command()
    async def ping(ctx):
        """
        .noah ping
        Check if Noah is responsive.
        """
        await ctx.send("Im alive! 🖤")

    @noah.command()
    async def help(ctx):  # noqa
        chart = EmbedTable(
            headers=["Command", "Description"],title="Noah AI Commands")
        chart.add_row([".noah ask <question>", "Ask a question to Noah AI."])
        chart.add_row([".noah summary", "Summarize recent channel messages."])
        chart.add_row([".noah behonest <question>", "Ask Noah without filters."])
        chart.add_row([".waifuracer help", "Show waifuracer commands."])
        chart.add_row([".waifuracer help", "Show waifuracer commands."])
        chart.add_row([".steallist help", "Show steallist commands."])

        await ctx.send(embed=chart.render())

    @noah.command()
    async def ask(ctx, *, question: str):
        """
        .noah ask <question>
        """
        await ctx.typing()

        try:
            response = ai_responder.ask(question)
        except Exception:
            await ctx.send("❌ Lo siento, hubo un error al procesar tu solicitud.")
            return

        # Safety: Discord message length
        if len(response) > 1900:
            response = response[:1900] + "..."

        await ctx.send(response)

    @noah.command()
    async def summary(ctx):
        """
        .noah summary
        Summarize the last messages in the channel.
        """
        await ctx.typing()

        channel = ctx.channel

        messages = [m async for m in channel.history(limit=100)]
        text = [m.content for m in messages]

        try:
            summary = ai_responder.summarize(str(text))
        except Exception:
            await ctx.send("💀 Noah couldn't survive this summary.")
            return

        if len(summary) > 1900:
            summary = summary[:1900] + "..."

        await ctx.send(summary)

    @noah.command()
    async def behonest(ctx, *, question: str):
        """
        .noah behonest <question>
        """
        await ctx.typing()

        try:
            response = ai_responder.ask_without_filters(question)
        except Exception:
            await ctx.send("❌ Lo siento, hubo un error al procesar tu solicitud.")
            return

        # Safety: Discord message length
        if len(response) > 1900:
            response = response[:1900] + "..."

        await ctx.send(response)

    # ---------------- DEBUG HISTORY ---------------- #
    @bot.command()
    async def debug_history(ctx):
        channel = ctx.channel

        messages = [m async for m in channel.history(limit=None)]
        text = [m.content for m in messages]
        print(text)

        await ctx.send(
            f"DEBUG: I can see **{len(messages)} messages** in this channel."
        )

    # ---------------- STEAL LIST COMMANDS ---------------- #
    @bot.group(name="steallist", aliases=["sl"])
    async def steallist_cmd(ctx):
        """
        StealList commands.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `.steallist help` or `.sl help` to see commands.")

    @steallist_cmd.command()
    async def help(ctx):  # noqa
        chart = EmbedTable(headers=["Command", "Description"], title="StealList Commands")
        chart.add_row(
            [".steallist add @user <waifu>", "Add a waifu to your steal list."]
        )
        chart.add_row([".steallist show", "Show your pending steals."])
        chart.add_row([".steallist show @user", "Show waifus stolen from a user."])
        chart.add_row([".steallist remove <id>", "Remove a waifu by ID."])
        chart.add_row(
            [".steallist clear @user", "Clear all waifus owned by you from that user."]
        )

        await ctx.send(embed=chart.render())

    @steallist_cmd.command()
    async def add(ctx, user: discord.Member, *waifu_words: str):  # noqa
        waifu_name = " ".join(waifu_words).strip()
        record_id = steallist.add_waifu(
            owner_id=ctx.author.id,
            owner_name=ctx.author.display_name,
            target_id=user.id,
            target_name=user.display_name,
            waifu_name=waifu_name,
        )

        await ctx.send(
            f"🗡️ `{waifu_name}` added to your steal list from {user.mention} "
            f"(ID `{record_id}`)"
        )

    @steallist_cmd.command()
    async def show(ctx, user: discord.Member = None):
        records = steallist.get_by_owner(ctx.author.id)
        embed = steallist.render_embed(
            records,
            title="🗡️ Steal List",
            subtitle=f"{ctx.author.display_name}'s pending waifus",
        )
        await ctx.send(embed=embed)

    @steallist_cmd.command()
    async def remove(ctx, record_id: int):  # noqa
        record = steallist.get_by_id(record_id)

        if not record:
            await ctx.send("Record not found.")
            return

        if record["owner_id"] != ctx.author.id:
            await ctx.send("❌ You can only remove your own waifus.")
            return

        steallist.remove_by_id(record_id)
        await ctx.send(f"Removed `{record['waifu_name']}` from your steal list.")

    @steallist_cmd.command()
    async def clear(ctx, user: discord.Member):
        count = steallist.clear_owner(ctx.author.id)

        if count == 0:
            await ctx.send("Nothing to clear.")
        else:
            await ctx.send(f"🧹 Cleared `{count}` waifus from your steal list.")

    # ---------------- RUN ---------------- #

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
