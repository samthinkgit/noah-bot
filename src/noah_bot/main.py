import os
import re
import random
import time
import discord
from rich import inspect
from discord.ext import commands
from dotenv import load_dotenv


from io import BytesIO
from noah_bot.ai import AiResponder
from noah_bot.discord_formatter import (
    _parse_embed_metadata,
    DiscordChart,
    UserEmojiManager,
    EmbedTable,
    DiscordImageRenderer,
    with_delete_button,
    with_loading,
    RARITY_COLORS,
    RARITY_SYMBOLS,
    RARITY_DISPLAY,
)
from noah_bot.waifu_game import WaifuGameManager, Waifu


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
        chart.add_row([".noah if <type>", "Invert embed rarity symbol and color."])
        chart.add_row([".noah ping", "Check if Noah is responsive."])
        chart.add_row([".noah help", "Show Noah AI commands."])
        chart.add_row(
            [".waifuracer setemoji <emoji>", "Set your claim reaction emoji."]
        )
        chart.add_row([".waifuracer help", "Show waifuracer commands."])
        chart.add_row([".noah waifu help", "Show waifu battle commands"])
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
            meta = _parse_embed_metadata(embed)

            if embed.image and embed.image.url:
                images.append(
                    {
                        "title": embed.title or f"Image {i}",
                        "url": embed.image.url,
                        "meta": meta,
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

    @noah.command(name="if")
    async def invert_rarity(ctx, rarity: str):
        """
        .noah if <type>
        Rewrites the embed rarity name, symbol and color.
        """
        await ctx.typing()

        rarity = rarity.lower()

        if rarity not in RARITY_COLORS:
            await ctx.send("❌ Unknown rarity type.")
            return

        if not ctx.message.reference:
            await ctx.send("❌ You must reply to a message containing an embed.")
            return

        try:
            replied_msg = await ctx.channel.fetch_message(
                ctx.message.reference.message_id
            )
        except Exception:
            await ctx.send("❌ Original message not found.")
            return

        if not replied_msg.embeds:
            await ctx.send("❌ No embed found in the replied message.")
            return

        original = replied_msg.embeds[0]

        # Parse original metadata
        meta = _parse_embed_metadata(original)

        # Clone embed
        new_embed = discord.Embed(
            title=original.title,
            description=original.description,
            color=RARITY_COLORS[rarity],
            url=original.url,
        )

        # Replace rarity line: "Type: Beta    (β)" → "Type: Zeta (ζ)"
        if new_embed.description:
            new_name = RARITY_DISPLAY[rarity]
            new_symbol = RARITY_SYMBOLS[rarity]

            new_embed.description = re.sub(
                r"(Type:\s*)(Alpha|Beta|Gamma|Delta|Sigma|Epsilon|Zeta|Omega)\s*\([^)]*\)",
                rf"\1{new_name} ({new_symbol})",
                new_embed.description,
                count=1,
            )

            # Safety fallback: replace symbol if something odd slipped through
            if meta.get("rarity"):
                old_symbol = meta["rarity"]
                new_embed.description = new_embed.description.replace(
                    f"({old_symbol})",
                    f"({new_symbol})",
                )

        # Copy image
        if original.image and original.image.url:
            new_embed.set_image(url=original.image.url)

        # Copy thumbnail
        if original.thumbnail and original.thumbnail.url:
            new_embed.set_thumbnail(url=original.thumbnail.url)

        # Copy footer
        if original.footer and original.footer.text:
            new_embed.set_footer(
                text=original.footer.text,
                icon_url=original.footer.icon_url,
            )

        # Copy author
        if original.author and original.author.name:
            new_embed.set_author(
                name=original.author.name,
                icon_url=original.author.icon_url,
                url=original.author.url,
            )

        await ctx.send(embed=new_embed)

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
            await ctx.send(f"❌ {result.get('message', 'Error')}")
            return

        w: Waifu = result["waifu"]
        stats = w["stats"]

        color = (
            discord.Color(w.embed_color)
            if w.embed_color
            else discord.Color.blurple()  # noqa
        )
        table = EmbedTable(
            headers=["Stat"], title=f"🖤 {w['name']} created", color=color
        )

        table.add_row([f"❤️ Health: {w['hp']} / {w['max_hp']}"])
        table.add_row([f"🤸‍♀️ Agility: {stats['agility']}"])
        table.add_row([f"🔮 Mana: {stats['mana']}"])
        table.add_row([f"💪 Recover: {stats['recover']}"])
        table.add_row([f"🗡️ Damage: {stats['hit_damage']}"])
        table.add_row([f"Dodge Chance: {int(stats['dodge_chance'] * 100)}%"])
        table.add_row([f"Special Chance: {int(stats['special_chance'] * 100)}%"])
        table.add_row([f"Cooldown: {stats['cooldown_seconds'] // 60} min"])
        table.add_row([f"Special Name: {w['special_name']}"])

        await ctx.send(embed=table.render())

    @waifu.command()
    async def setplayers(ctx, players: commands.Greedy[discord.Member]):
        """.noah waifu setplayers <@user1> <@user2> ...
        Guarda en el JSON la lista de jugadores a monitorizar.
        """

        if not players:
            await ctx.send("❌ Debes mencionar al menos un usuario.")
            return

        player_ids = [str(m.id) for m in players]
        waifu_manager.set_players(player_ids)

        mentions = ", ".join(m.mention for m in players)
        await ctx.send(f"✅ Jugadores configurados para el reporte: {mentions}")

    @waifu.command()
    async def playerreport(ctx):
        """.noah waifu playerreport
        Muestra la vida y estado (stunned/incapacitated) de los jugadores configurados.
        """

        player_ids = waifu_manager.get_players()
        if not player_ids:
            await ctx.send(
                "❌ No hay jugadores configurados. Usa `.noah waifu setplayers <@user1> <@user2> ...`."
            )
            return

        now = time.time()

        table = EmbedTable(
            headers=["Player"],
            title="📋 Waifu Player Report",
            color=discord.Color.blurple(),
        )

        for pid in player_ids:
            member = ctx.guild.get_member(int(pid))
            name = member.mention if member else f"<@{pid}>"

            w = waifu_manager.get_waifu(str(pid))
            if not w:
                table.add_row([name, "-", "❌ No tiene waifu"])
                continue

            if w.incapacitated_until and w.incapacitated_until.timestamp() > now:
                status = "🩸"
            elif w.stunned_until and w.stunned_until.timestamp() > now:
                status = "😵"
            else:
                status = "✅"

            sleep_available = "🛌" if w.can_sleep(w.now()) else "⏳"
            curr_hp = f"0{w.current_hp}" if w.current_hp < 10 else str(w.current_hp)
            max_hp = f"0{w.max_hp()}" if w.max_hp() < 10 else str(w.max_hp())
            hp_text = f"{curr_hp} / {max_hp}"
            table.add_row([f"`({hp_text})` {status} {sleep_available} {name}"])

        embed = table.render()
        await ctx.send(embed=embed)

    @waifu.command()
    async def attack(ctx, user: discord.Member):
        """
        .noah waifu attack @user
        """
        d = waifu_manager.get_waifu(str(user.id))
        if d.is_incapacitated(d.now()):
            await ctx.send(f"❌ {user.display_name}'s waifu is incapacitated.")
            return
        w = waifu_manager.get_waifu(str(ctx.author.id))
        if w.name == d.name:
            await ctx.send("❌ You cannot attack your own waifu.")
            return

        result = waifu_manager.waifu_attack(
            attacker_id=str(ctx.author.id),
            defender_id=str(user.id),
        )

        if not result["ok"]:
            await ctx.send(f"❌ {result.get('message', 'Attack failed')}")
            return

        table = EmbedTable(
            headers=["Event"],
            title="⚔️ Waifu Battle",
            color=(
                discord.Color(w.embed_color)
                if w.embed_color
                else discord.Color.blurple()
            ),
        )
        table.description = (
            f"`{ctx.author.display_name}` attacked `{user.display_name}`'s waifu"
        )

        if result["dodged"]:
            table.add_row(["💨 The attack was dodged!"])
        else:
            table.add_row([f"Damage: {result['damage']}"])
            table.add_row([f"Defender HP: {result['defender_hp_after']}"])

            if result["special"]:
                table.add_row([f"💥 Special: {result['special_name']}"])

            if result["stunned_applied"]:
                table.add_row(["😵 Status: Stunned (3h)"])

            if result["killed"]:
                table.add_row(["🩸 Status: Incapacitated (12h)"])
                table.add_row(["Reward: Half heal + Level Up"])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        embed = table.render()
        if w and w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command(aliases=["rem"])
    @with_delete_button()
    async def remaining(ctx, *, args: str = ""):
        """
        .noah waifu remaining
        """
        target_user = ctx.author

        # Parse optional -user flag
        if "-user" in args:
            parts = args.split("-user", 1)
            _ = parts  # for readability

            if not ctx.message.mentions:
                await ctx.send("❌ Please mention a valid user after `-user`.")
                return

            target_user = ctx.message.mentions[0]

        w = waifu_manager.get_waifu(str(target_user.id))
        if not w:
            await ctx.send("❌ You don't have a waifu.")
            return

        now = time.time()
        table = EmbedTable(
            headers=["Info"],
            title="⏳ Waifu Status",
            color=(
                discord.Color(w.embed_color)
                if w.embed_color
                else discord.Color.blurple()  # noqa
            ),
        )

        if w.stunned_until and not waifu_manager.devmode:
            remaining = int(w.stunned_until.timestamp() - now)
            if remaining > 0:
                table.add_row(["Status: 😵 Stunned"])
                table.add_row(
                    [f"Free in: {remaining // 3600}h {(remaining % 3600) // 60}m"]
                )
                embed = table.render()
                if w.image_url:
                    embed.set_image(url=w.image_url)
                await ctx.send(embed=embed)
                return

        if w.incapacitated_until and not waifu_manager.devmode:
            remaining = int(w.incapacitated_until.timestamp() - now)
            if remaining > 0:
                table.add_row(["Status: 🩸 Incapacitated"])
                table.add_row(
                    [f"Recovery in: {remaining // 3600}h {(remaining % 3600) // 60}m"]
                )
                embed = table.render()
                if w.image_url:
                    embed.set_image(url=w.image_url)
                await ctx.send(embed=embed)
                return

        if waifu_manager.devmode or not w.last_attack_at:
            table.add_row(["Status: Ready to attack"])
        else:
            cooldown = w.stats.cooldown_seconds()
            elapsed = int(now - w.last_attack_at.timestamp())
            remaining = max(0, cooldown - elapsed)

            if remaining == 0:
                table.add_row(["Status: Ready to attack"])
            else:
                table.add_row(["Status: Recovering"])
                table.add_row([f"Remaining: {remaining // 60}m {remaining % 60}s"])

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    async def sleep(ctx):
        """
        .noah waifu sleep
        """
        result = waifu_manager.waifu_sleep(str(ctx.author.id))
        if not result["ok"]:
            await ctx.send(f"❌ {result.get('message', 'Cannot sleep')}")
            return

        table = EmbedTable(headers=["Info"], title="😴 Waifu Rest")
        table.add_row([f"HP Before: {result['hp_before']}"])
        table.add_row([f"HP After: {result['hp_after']}"])
        table.add_row([f"Healed: {result['healed']}"])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        embed = table.render()
        if w and w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    async def levelup(ctx):
        """
        .noah waifu levelup
        """
        result = waifu_manager.waifu_levelup(str(ctx.author.id))
        if not result["ok"]:
            await ctx.send(f"❌ {result.get('message', 'Cannot level up')}")
            return

        table = EmbedTable(headers=["Info"], title="⬆️ Level Up!")
        table.add_row([f"Upgraded stat: {result['chosen_stat']} +1pt"])
        table.add_row([f"Pending Levelups: {result['pending_levelups_left']}"])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        embed = table.render()
        if w and w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    @with_delete_button()
    async def status(ctx, *, args: str = ""):
        """
        .noah waifu status
        .noah waifu status -user @user
        """

        target_user = ctx.author

        # Parse optional -user flag
        if "-user" in args:
            parts = args.split("-user", 1)
            _ = parts  # for readability

            if not ctx.message.mentions:
                await ctx.send("❌ Please mention a valid user after `-user`.")
                return

            target_user = ctx.message.mentions[0]

        w = waifu_manager.get_waifu(str(target_user.id))
        if not w:
            if target_user == ctx.author:
                await ctx.send("❌ You don't have a waifu.")
            else:
                await ctx.send(f"❌ {target_user.display_name} doesn't have a waifu.")
            return

        now = time.time()
        color = (
            discord.Color(w.embed_color)
            if w.embed_color
            else discord.Color.blurple()  # noqa
        )
        table = EmbedTable(
            headers=["Stat"],
            title=f"📊 {w.name} Status ({target_user.display_name})",
            color=color,
        )

        incapacitated = False
        if w.incapacitated_until and w.incapacitated_until.timestamp() > now:
            incapacitated = True
            remaining = int(w.incapacitated_until.timestamp() - now)
            table.add_row(["Status: 🩸 Incapacitated"])
            table.add_row(
                [f"Recovery in: {remaining // 3600}h {(remaining % 3600) // 60}m\n"]
            )
        elif w.stunned_until and w.stunned_until.timestamp() > now:
            remaining = int(w.stunned_until.timestamp() - now)
            table.add_row(["Status: 😵 Stunned"])
            table.add_row(
                [f"Free in: {remaining // 3600}h {(remaining % 3600) // 60}m\n"]
            )
        else:
            table.add_row(["Status: Active\n"])

        table.add_row([f"**Level**: {w.level()}\n"])
        if not incapacitated:
            table.add_row([f"❤️ **HP**: {w.current_hp} / {w.max_hp()}"])
        else:
            table.add_row([f"❤️ **HP**: 0 / {w.max_hp()} (Incapacitated)"])
        table.add_row([f"🤸‍♀️ **Agility**: {w.stats.agility}"])
        table.add_row([f"🔮 **Mana**: {w.stats.mana}"])
        table.add_row([f"💪 **Recover**: {w.stats.recover}"])
        table.add_row([f"🗡️ **Damage**: {w.stats.hit_damage()}"])
        table.add_row([f"⏳ **Cooldown**: {w.stats.cooldown_seconds() // 60} min\n"])
        table.add_row([f"Special: {w.special_name}"])
        table.add_row([f"Pending Levelups: {w.pending_levelups}"])
        table.add_row([f"Last Sleep: {w.last_sleep_date}"])

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    async def alive(ctx):
        """
        .noah waifu alive
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
                f"🩸 Still incapacitated for "
                f"{remaining // 3600}h {(remaining % 3600) // 60}m."
            )
            return

        w.incapacitated_until = None
        w.current_hp = w.max_hp()
        waifu_manager._state["users"][str(ctx.author.id)] = (
            waifu_manager._serialize_waifu(w)
        )
        waifu_manager._save()

        await ctx.send("✨ Your waifu has recovered and is active again!")

    @waifu.command()
    @with_delete_button()
    async def stats(ctx, *, args: str = ""):
        """
        .noah waifu stats
        .noah waifu stats -user @user
        Shows advanced combat probabilities and derived values.
        """

        target_user = ctx.author

        # Parse optional -user flag
        if "-user" in args:
            parts = args.split("-user", 1)
            _ = parts  # for readability

            if not ctx.message.mentions:
                await ctx.send("❌ Please mention a valid user after `-user`.")
                return

            target_user = ctx.message.mentions[0]

        w = waifu_manager.get_waifu(str(target_user.id))
        if not w:
            if target_user == ctx.author:
                await ctx.send("❌ You don't have a waifu.")
            else:
                await ctx.send(f"❌ {target_user.display_name} doesn't have a waifu.")
            return

        table = EmbedTable(
            headers=["Advanced Combat Data"],
            title=f"📊 {w.name} - Advanced Stats ({target_user.display_name})",
            color=(
                discord.Color(w.embed_color)
                if w.embed_color
                else discord.Color.blurple()
            ),
        )

        table.add_row(
            [
                f"🗡️ Damage level: **{w.stats.damage} / 30** "
                f"({w.stats.hit_damage()} pts per Hit)"
            ]
        )

        table.add_row([f"💨 Dodge chance: **{int(w.stats.dodge_chance() * 100)}%**"])
        table.add_row(
            [f"💥 Special trigger chance: **{int(w.stats.special_chance() * 100)}%**"]
        )
        table.add_row(
            [f"⏳ Attack cooldown: **{w.stats.cooldown_seconds() // 60} minutes**"]
        )
        table.add_row(["😵 Stun duration on special: **3 hours**"])
        table.add_row(["🩸 Incapacitation duration (HP = 0): **12 hours**"])
        table.add_row([f"📈 Pending level-ups: **{w.pending_levelups}**"])
        table.add_row([f"🛌 Latest Sleep: **{w.last_sleep_date}**"])

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

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
    async def daily(ctx, stat: str = None):
        """
        .noah waifu daily [stat]
        Gain +1 point in a chosen stat once per day.
        """

        w = waifu_manager.get_waifu(str(ctx.author.id))
        if not w:
            await ctx.send("❌ You don't have a waifu.")
            return

        valid_stats = ["health", "agility", "mana", "recover", "damage"]

        now = w.now()
        today = now.date().isoformat()

        # ✅ SINGLE SOURCE OF TRUTH
        if w.last_daily_date == today and not waifu_manager.devmode:
            await ctx.send("⏳ You already used your daily training today.")
            return

        # Validate stat or pick random
        if stat:
            stat = stat.lower()
            if stat not in valid_stats:
                await ctx.send(
                    "❌ Invalid stat. Choose one of: "
                    "`health`, `agility`, `mana`, `recover`, `damage`"
                )
                return
        else:
            stat = random.choice(valid_stats)

        before = getattr(w.stats, stat)

        # ❌ Reject BEFORE consuming daily
        if before >= 30:
            await ctx.send(f"⚠️ {stat.capitalize()} is already at max (30).")
            return

        # ✅ CONSUME DAILY (atomic point of no return)
        w.last_daily_date = today

        # Apply stat
        setattr(w.stats, stat, before + 1)

        # Adjust HP if health increases
        if stat == "health":
            w.current_hp = min(w.current_hp, w.max_hp())

        waifu_manager._state["users"][str(ctx.author.id)] = (
            waifu_manager._serialize_waifu(w)
        )
        waifu_manager._save()

        table = EmbedTable(
            headers=["Daily Training"],
            title="🌅 Daily Training Complete",
            color=(
                discord.Color(w.embed_color)
                if w.embed_color
                else discord.Color.blurple()
            ),
        )

        table.add_row([f"📈 Stat upgraded: **{stat.capitalize()} +1**"])
        table.add_row([f"🔢 New value: **{getattr(w.stats, stat)} / 30**"])
        table.add_row(["⏳ Available again: **Tomorrow**"])

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    @with_delete_button()
    async def attackedby(ctx, *, args: str = ""):
        """
        .noah waifu attackedby
        .noah waifu attackedby -user @user
        Shows who attacked the waifu and total damage received since last death.
        """

        target_user = ctx.author

        # Parse optional -user flag
        if "-user" in args:
            parts = args.split("-user", 1)
            _ = parts  # keep for readability, no further use

            if not ctx.message.mentions:
                await ctx.send("❌ Please mention a valid user after `-user`.")
                return

            target_user = ctx.message.mentions[0]

        w = waifu_manager.get_waifu(str(target_user.id))
        if not w:
            if target_user == ctx.author:
                await ctx.send("❌ You don't have a waifu.")
            else:
                await ctx.send(f"❌ {target_user.display_name} doesn't have a waifu.")
            return

        if not w.received_hits:
            await ctx.send("🛡️ No attacks received since last death.")
            return

        table = EmbedTable(
            headers=["Attacker"],
            title=f"🩸 Damage Received ({target_user.display_name})",
            color=(
                discord.Color(w.embed_color)
                if w.embed_color
                else discord.Color.blurple()
            ),
        )

        for attacker_id, dmg in sorted(
            w.received_hits.items(), key=lambda x: x[1], reverse=True
        ):
            member = ctx.guild.get_member(int(attacker_id))
            name = member.mention if member else f"<@{attacker_id}>"
            table.add_row([f"{name}: {dmg} HP"])

        embed = table.render()
        if w.image_url:
            embed.set_image(url=w.image_url)

        await ctx.send(embed=embed)

    @waifu.command()
    async def setcolor(ctx, color: str):
        """
        .noah waifu setcolor <hex | random | reset>
        Examples:
        .noah waifu setcolor #ff00ff
        .noah waifu setcolor random
        .noah waifu setcolor reset
        """

        w = waifu_manager.get_waifu(str(ctx.author.id))
        if not w:
            await ctx.send("❌ You don't have a waifu.")
            return

        if color.lower() == "reset":
            result = waifu_manager.waifu_set_color(str(ctx.author.id), None)
            await ctx.send("🎨 Embed color reset to default.")
            return

        if color.lower() == "random":
            value = random.randint(0x000000, 0xFFFFFF)
        else:
            if color.startswith("#"):
                color = color[1:]
            try:
                value = int(color, 16)
            except ValueError:
                await ctx.send(
                    "❌ Invalid color. Use hex like `#ff00ff`, `random`, or `reset`."
                )
                return

        result = waifu_manager.waifu_set_color(str(ctx.author.id), value)
        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        await ctx.send(f"🎨 Waifu embed color set to `#{value:06x}`")

    @waifu.command()
    async def setpeacefulmode(ctx, user: discord.Member):
        """
        .noah waifu setpeacefulmode @user
        Instantly kills a waifu for 1 year (peaceful mode).
        """

        result = waifu_manager.waifu_peaceful_kill(
            attacker_id=str(ctx.author.id),
            target_id=str(user.id),
        )

        if not result["ok"]:
            await ctx.send(f"❌ {result['message']}")
            return

        table = EmbedTable(
            headers=["Peaceful Mode"],
            title="☮️ Peaceful Resolution Applied",
        )

        table.add_row([f"Target: **{user.display_name}**"])
        table.add_row(["Status: ☠️ Instantly incapacitated"])
        table.add_row(["Respawn: **1 year**"])

        w = waifu_manager.get_waifu(str(ctx.author.id))
        embed = table.render()

        if w and w.embed_color is not None:
            embed.color = w.embed_color

        await ctx.send(embed=embed)

    @waifu.command()
    async def help(ctx):  # noqa
        chart = EmbedTable(headers=["Command"], title="Waifu Game Commands")
        chart.add_row([".noah waifu set <name> -special <special name>"])
        chart.add_row([".noah waifu attack @user"])
        chart.add_row([".noah waifu playerreport"])
        chart.add_row([".noah waifu status -user @user"])
        chart.add_row([".noah waifu remaining -user @user"])
        chart.add_row([".noah waifu sleep"])
        chart.add_row([".noah waifu levelup"])
        chart.add_row([".noah waifu stats -user @user"])
        chart.add_row([".noah waifu daily <stat>"])
        chart.add_row([".noah waifu alive"])
        chart.add_row([".noah waifu setimage"])
        chart.add_row([".noah waifu setcolor <hex | random | reset>"])
        chart.add_row([".noah waifu attackedby -user @user"])
        chart.add_row(["[admin] .noah waifu setplayers <@user1> <@user2> ..."])
        await ctx.send(embed=chart.render())

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
    @with_loading("Generating test images...", duration=3)
    async def test_image(ctx):
        """
        .test_image
        Sends a message with 3 example images using embeds.
        """
        image_urls = [
            "https://i.blogs.es/8dee66/anime/500_333.jpeg",
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

    @bot.command()
    async def get_embed(ctx):
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

        for i, embed in enumerate(replied_msg.embeds, start=1):
            inspect(embed)

    # ---------------- RUN ---------------- #

    bot.run(TOKEN)


if __name__ == "__main__":
    main()
