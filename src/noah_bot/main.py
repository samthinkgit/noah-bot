import os
import time
import discord
from discord.ext import commands
from dotenv import load_dotenv


from io import BytesIO
from noah_bot.ai import AiResponder
from noah_bot.discord_formatter import (
    DiscordChart,
    UserEmojiManager,
    EmbedTable,
    DiscordImageRenderer,
)
from noah_bot.waifu_game import WaifuGameManager


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
    waifu_manager = WaifuGameManager(json_path="waifu_game.json")

    # Active timers per user
    timeit_sessions = {}
    latest_time_it = None

    # ---------------- EVENTS ---------------- #

    @bot.event
    async def on_ready():
        print(f"Bot connected as {bot.user}")

    # ---------------- TIMEIT / CLAIM ---------------- #

    @bot.command(aliases=["ti"])
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
        chart = EmbedTable(
            headers=["Command", "Description"], title="Waifuracer Commands"
        )
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
            await ctx.send("Use `.noah help` to see commands.")

    @noah.command()
    async def ping(ctx):
        """
        .noah ping
        Check if Noah is responsive.
        """
        await ctx.send("Im alive! 🖤")

    @noah.command()
    async def help(ctx):  # noqa
        chart = EmbedTable(headers=["Command", "Description"], title="Noah AI Commands")
        chart.add_row([".noah ask <question>", "Ask a question to Noah AI."])
        chart.add_row([".noah summary", "Summarize recent channel messages."])
        chart.add_row([".noah behonest <question>", "Ask Noah without filters."])
        chart.add_row([".noah merge", "Render all images from a replied message."])
        chart.add_row([".noah ping", "Check if Noah is responsive."])
        chart.add_row([".noah help", "Show Noah AI commands."])
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

    # ---------------- GET IMAGES FROM REPLIED MESSAGE ---------------- #

    @noah.command()
    async def merge(ctx):
        """
        .merge
        Reply to a message from another bot and Noah will render all embed images
        into a single beautiful image.
        """
        await ctx.typing()
        if not ctx.message.reference:
            await ctx.send("❌ You must reply to a message containing embeds.")
            return

        try:
            replied_msg = await ctx.channel.fetch_message(
                ctx.message.reference.message_id
            )
        except discord.NotFound:
            await ctx.send("❌ Original message not found.")
            return

        images = []

        for i, embed in enumerate(replied_msg.embeds, start=1):
            if embed.image and embed.image.url:
                images.append(
                    {
                        "title": embed.title or f"Image {i}",
                        "url": embed.image.url,
                    }
                )

            if embed.thumbnail and embed.thumbnail.url:
                images.append(
                    {
                        "title": (embed.title or f"Image {i}") + " (thumb)",
                        "url": embed.thumbnail.url,
                    }
                )

        if not images:
            await ctx.send("❌ No images found in the embeds.")
            return

        renderer = DiscordImageRenderer()
        final_image = renderer.render(images)

        buffer = BytesIO()
        final_image.save(buffer, format="PNG")
        buffer.seek(0)

        await ctx.send(file=discord.File(buffer, filename="rendered_images.png"))

    # ---------------- WAIFU GAME ---------------- #
    @noah.group()
    async def waifu(ctx):
        """
        Waifu battle commands.
        """
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `.noah waifu help` to see commands.")

    @waifu.command()
    async def set(ctx, *, args: str):
        """
        .noah waifu set <name> -special <special name>
        """
        if "-special" not in args:
            await ctx.send("❌ Usage: `.noah waifu set <name> -special <special name>`")
            return

        name, special = args.split("-special", 1)
        name = name.strip()
        special = special.strip()

        result = waifu_manager.waifu_set(
            user_id=str(ctx.author.id),
            waifu_name=name,
            special_name=special,
        )

        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        w = result["waifu"]
        stats = w["stats"]

        table = EmbedTable(
            headers=["Stat"],
            title=f"🖤 {w['name']} created",
        )

        table.add_row(["❤️ **Health**: " + f"{w['hp']} / {w['max_hp']}"])
        table.add_row(["🤸‍♀️ **Agility**: " + str(stats["agility"])])
        table.add_row(["🔮 **Mana**: " + str(stats["mana"])])
        table.add_row(["💪 **Recover**: " + str(stats["recover"])])
        table.add_row(["🗡️ **Damage**: " + f"{stats['hit_damage']}" + "\n"])
        table.add_row(["**Dodge Chance**: " + f"{int(stats['dodge_chance'] * 100)}%"])
        table.add_row(
            ["**Special Chance**: " + f"{int(stats['special_chance'] * 100)}%"]
        )
        table.add_row(["**Cooldown**: " + f"{stats['cooldown_seconds'] // 60} min"])
        table.add_row(["**Special Name**: " + w["special_name"]])

        await ctx.send(embed=table.render())

    @waifu.command()
    async def setimage(ctx):
        """
        .noah waifu setimage
        Must reply to a message containing an embed image.
        """
        if not ctx.message.reference:
            await ctx.send("❌ You must reply to a message with an embed image.")
            return

        replied = await ctx.channel.fetch_message(ctx.message.reference.message_id)

        image_url = None

        for embed in replied.embeds:
            if embed.image and embed.image.url:
                image_url = embed.image.url
                break
            if embed.thumbnail and embed.thumbnail.url:
                image_url = embed.thumbnail.url
                break

        if not image_url:
            await ctx.send("❌ No image found in the replied embed.")
            return

        result = waifu_manager.waifu_set_image(
            str(ctx.author.id),
            image_url,
        )

        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        await ctx.send("🖼️ Waifu image set successfully!")

    @waifu.command()
    async def remaining(ctx):
        """
        .noah waifu remaining
        Shows remaining cooldown time or incapacitation time.
        """
        w = waifu_manager.get_waifu(str(ctx.author.id))

        if not w:
            await ctx.send("❌ You don't have a waifu.")
            return

        now = time.time()

        table = EmbedTable(
            headers=["Info"],
            title="⏳ Waifu Status",
        )

        # Incapacitated
        if w.incapacitated_until and not waifu_manager.devmode:
            remaining = int(w.incapacitated_until.timestamp() - now)
            if remaining > 0:
                table.add_row(["**Status**: Incapacitated 🩸"])
                table.add_row(
                    [
                        "**Recovery In**: "
                        + f"{remaining // 3600}h {(remaining % 3600) // 60}m",
                    ]
                )
            else:
                table.add_row(["**Status**: Ready"])
        else:
            # Cooldown logic
            if waifu_manager.devmode or not w.last_attack_at:
                table.add_row(["**Status**: Ready to attack"])
                table.add_row(["**Remaining**: 0 seconds"])
            else:
                cooldown = w.stats.cooldown_seconds()
                elapsed = int(now - w.last_attack_at.timestamp())
                remaining = max(0, cooldown - elapsed)

                table.add_row(["**Cooldown**: " + f"{cooldown // 60} min"])

                if remaining == 0:
                    table.add_row(["**Status**: Ready to attack"])
                    table.add_row(["**Remaining**: 0 seconds"])
                else:
                    table.add_row(["**Status**: Recovering ⏳"])
                    table.add_row(
                        [
                            "**Remaining**: "
                            + f"{remaining // 60} min {remaining % 60} sec",
                        ]
                    )

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    async def attack(ctx, user: discord.Member):
        """
        .noah waifu attack @user
        """
        result = waifu_manager.waifu_attack(
            attacker_id=str(ctx.author.id),
            defender_id=str(user.id),
        )

        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        table = EmbedTable(
            headers=["Event"],
            title="⚔️ Waifu Battle",
        )
        table.description = f"`{str(ctx.author.display_name)}` attacked `{str(user.display_name)}`'s waifu"
        if result["stunned_applied"]:
            table.description += f" using its special attack **{result['special_name']}** and stunned the opponent!"

        if result["dodged"]:
            table.description += "\n 💨 The attack was dodged!"

        if not result["dodged"]:
            table.add_row(["**Damage**: " + f"{result['damage']}"])

            if result["special"]:
                table.add_row(["**Special**: " + f"💥 {result['special_name']}"])

            table.add_row(["**Defender HP**: " + f"{result['defender_hp_after']}"])

            if result["stunned_applied"]:
                table.add_row(["**Stun**: " + "Yes 😵"])

            if result["killed"]:
                table.add_row(["**Status**: 🩸 Incapacitated (24h)"])
                table.add_row(["**Reward**: Full heal + Level Up"])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        if w.image_url:
            embed = table.render()
            embed.set_image(url=w.image_url)
            await ctx.send(embed=embed)
            return

        await ctx.send(embed=table.render())

    @waifu.command()
    async def sleep(ctx):
        """
        .noah waifu sleep
        """
        result = waifu_manager.waifu_sleep(str(ctx.author.id))

        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        table = EmbedTable(
            headers=["Info"],
            title="😴 Waifu Rest",
        )

        table.add_row(["HP Before: " + f"{result['hp_before']}"])
        table.add_row(["HP After: " + f"{result['hp_after']}"])
        table.add_row(["Recovered: " + f"{result['healed']}"])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        if w.image_url:
            embed = table.render()
            embed.set_image(url=w.image_url)
            await ctx.send(embed=embed)
            return

        await ctx.send(embed=table.render())

    @waifu.command()
    async def levelup(ctx):
        """
        .noah waifu levelup
        """
        result = waifu_manager.waifu_levelup(str(ctx.author.id))

        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        table = EmbedTable(
            headers=["Info"],
            title="⬆️ Level Up!",
        )

        table.add_row(["Upgraded Stat: " + str(result["chosen_stat"] + " +2pts")])
        table.add_row(["Pending Levelups: " + str(result["pending_levelups_left"])])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        if w.image_url:
            embed = table.render()
            embed.set_image(url=w.image_url)
            await ctx.send(embed=embed)
            return

        await ctx.send(embed=table.render())

    @waifu.command()
    async def status(ctx):
        """
        .noah waifu status
        """
        w = waifu_manager.get_waifu(str(ctx.author.id))

        if not w:
            await ctx.send("❌ You don't have a waifu.")
            return

        now = time.time()

        table = EmbedTable(
            headers=["Stat"],
            title=f"📊 {w.name} Status",
        )

        if w.incapacitated_until:
            remaining = int(w.incapacitated_until.timestamp() - now)
            if remaining > 0:
                table.add_row(["**Status**: 🩸 Incapacitated"])
                table.add_row(
                    [
                        "**Recovery In**: "
                        + f"{remaining // 3600}h {(remaining % 3600) // 60}m\n",
                    ]
                )
            else:
                table.add_row(["**Status**: Ready\n"])
        else:
            table.add_row(["**Status**: Active\n"])

        table.add_row(["❤️ **HP**: " + f"{w.current_hp} / {w.max_hp()}"])
        table.add_row(["🤸‍♀️ **Agility**: " + str(w.stats.agility)])
        table.add_row(["🔮 **Mana**: " + str(w.stats.mana)])
        table.add_row(["💪 **Recover**: " + str(w.stats.recover)])
        table.add_row(["🗡️ **Damage**: " + str(w.stats.hit_damage())])
        table.add_row(
            ["⏳ **Cooldown**: " + f"{w.stats.cooldown_seconds() // 60} min\n"]
        )
        table.add_row(["**Stunned**: " + ("Yes 😵" if w.is_stunned_now() else "No")])
        table.add_row(["**Special**: " + w.special_name])
        table.add_row(["**Pending Levelups**: " + str(w.pending_levelups)])

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    async def alive(ctx):
        """
        .noah waifu alive
        Checks if waifu can be reactivated after incapacitation.
        """
        w = waifu_manager.get_waifu(str(ctx.author.id))

        if not w:
            await ctx.send("❌ You don't have a waifu.")
            return

        now = time.time()

        if not w.incapacitated_until:
            await ctx.send("🖤 Your waifu is already active.")
            return

        remaining = int(w.incapacitated_until.timestamp() - now)

        if remaining > 0:
            await ctx.send(
                f"🩸 Your waifu is still incapacitated for "
                f"{remaining // 3600}h {(remaining % 3600) // 60}m."
            )
            return

        # Force recovery
        w.incapacitated_until = None
        w.current_hp = w.max_hp()
        waifu_manager._state["users"][str(ctx.author.id)] = (
            waifu_manager._serialize_waifu(w)
        )
        waifu_manager._save()

        await ctx.send("✨ Your waifu has recovered and is alive again!")

    @waifu.command()
    async def help(ctx, user: discord.Member = None):  # noqa
        """
        .noah waifu help
        """
        chart = EmbedTable(headers=["Command"], title="Waifu Game Commands")
        chart.add_row(
            [
                ".noah waifu set <name> -special <special name>: Create your waifu with a special attack.",
            ]
        )
        chart.add_row([".noah waifu status: Show your waifu's current status."])
        chart.add_row([".noah waifu attack @user: Attack another user's waifu."])
        chart.add_row([".noah waifu sleep: Rest and recover HP."])
        chart.add_row(
            [".noah waifu levelup: Use a pending level up to upgrade a stat."]
        )
        chart.add_row(
            [".noah waifu remaining: Show remaining cooldown before next attack."]
        )
        chart.add_row([".noah waifu alive: Check if your waifu can be reactivated."])
        chart.add_row(
            [".noah waifu setimage: Set your waifu's image from a replied embed."]
        )
        chart.add_row([".noah waifu help: Show waifu game commands."])

        await ctx.send(embed=chart.render())

    @waifu.command()
    async def setdevmode(ctx, value: str):
        """
        .setdevmode on/off
        """
        enabled = value.lower() in ("on", "true", "1", "yes")

        waifu_manager.set_devmode(enabled)
        await ctx.send(f"🛠️ Dev mode set to `{enabled}`")

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
        chart = EmbedTable(
            headers=["Command", "Description"], title="StealList Commands"
        )
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

    @bot.command()
    async def test_image(ctx):
        """
        .test_image
        Sends a message with 3 example images using embeds.
        """
        image_urls = [
            "https://i.blogs.es/8dee66/anime/500_333.jpeg"
            "https://placebear.com/400/300",
            "https://picsum.photos/400/300",
        ]

        embeds = []
        for idx, url in enumerate(image_urls, start=1):
            embed = discord.Embed(title=f"Test Image {idx}")
            embed.set_image(url=url)
            embeds.append(embed)

        for embed in embeds:
            await ctx.send(embed=embed)

    # ---------------- RUN ---------------- #

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
