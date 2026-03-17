import asyncio
import os
import re
from io import BytesIO

import discord
from discord.ext import commands

from noah_bot.commands.relics import register_relics_commands
from noah_bot.commands.tts import register_tts_commands
from noah_bot.commands.vc_stats import register_vc_stats_commands
from noah_bot.commands.waifu import register_waifu_commands
from noah_bot.modules.bot_context import get_bot_context
from noah_bot.modules.discord_formatter import (
    DiscordImageRenderer,
    EmbedTable,
    RARITY_COLORS,
    RARITY_DISPLAY,
    RARITY_SYMBOLS,
    _parse_embed_metadata,
)


def _truncate_discord_message(content: str) -> str:
    if len(content) > 1900:
        return content[:1900] + "..."
    return content


def register_noah_commands(bot: commands.Bot) -> None:
    @bot.group()
    async def noah(ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `.noah help` to see commands.")

    @noah.command()
    async def ping(ctx: commands.Context) -> None:
        await ctx.send("Im alive! 🖤")

    @noah.command()
    async def kill(ctx: commands.Context) -> None:
        await ctx.send("💀 Noah is shutting down.")
        await asyncio.sleep(0.5)
        os._exit(0)

    @noah.command()
    async def help(ctx: commands.Context) -> None:
        chart = EmbedTable(headers=["Command", "Description"], title="Noah AI Commands")
        chart.add_row([".noah ask <question>", "Ask a question to Noah AI."])
        chart.add_row([".noah summary", "Summarize recent channel messages."])
        chart.add_row([".noah behonest <question>", "Ask Noah without filters."])
        chart.add_row(
            [".noah quote <user>", "Quote the replied message in a styled embed."]
        )
        chart.add_row([".noah merge", "Render all images from a replied message."])
        chart.add_row([".noah if <type>", "Invert embed rarity symbol and color."])
        chart.add_row([".noah ping", "Check if Noah is responsive."])
        chart.add_row([".noah kill", "Stop the bot process immediately."])
        chart.add_row([".noah help", "Show Noah AI commands."])
        chart.add_row([".noah vc help", "Show voice stats commands."])
        chart.add_row(
            [".waifuracer setemoji <emoji>", "Set your claim reaction emoji."]
        )
        chart.add_row([".waifuracer help", "Show waifuracer commands."])
        chart.add_row([".noah waifu help", "Show waifu battle commands"])
        chart.add_row([".noah relics help", "Explica el modo noah relics."])
        chart.add_row([".steallist help", "Show steallist commands."])

        await ctx.send(embed=chart.render())

    @noah.command()
    async def ask(ctx: commands.Context, *, question: str) -> None:
        context = get_bot_context(ctx.bot)
        await ctx.typing()

        try:
            response = context.ai_responder.ask(question)
        except Exception:
            await ctx.send("❌ Lo siento, hubo un error al procesar tu solicitud.")
            return

        await ctx.send(_truncate_discord_message(response))

    @noah.command()
    async def summary(ctx: commands.Context) -> None:
        context = get_bot_context(ctx.bot)
        await ctx.typing()

        messages = [message async for message in ctx.channel.history(limit=100)]
        text = [message.content for message in messages]

        try:
            summary_text = context.ai_responder.summarize(str(text))
        except Exception:
            await ctx.send("💀 Noah couldn't survive this summary.")
            return

        await ctx.send(_truncate_discord_message(summary_text))

    @noah.command()
    async def behonest(ctx: commands.Context, *, question: str) -> None:
        context = get_bot_context(ctx.bot)
        await ctx.typing()

        try:
            response = context.ai_responder.ask_without_filters(question)
        except Exception:
            await ctx.send("❌ Lo siento, hubo un error al procesar tu solicitud.")
            return

        await ctx.send(_truncate_discord_message(response))

    @noah.command()
    async def merge(ctx: commands.Context) -> None:
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

        for index, embed in enumerate(replied_msg.embeds, start=1):
            meta = _parse_embed_metadata(embed)

            if embed.image and embed.image.url:
                images.append(
                    {
                        "title": embed.title or f"Image {index}",
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

    @noah.command()
    async def quote(
        ctx: commands.Context, user: discord.Member | discord.User | None = None
    ) -> None:
        if user is None:
            await ctx.send("❌ Use `.noah quote <user>` while replying to a message.")
            return

        if not ctx.message.reference:
            await ctx.send("❌ You must reply to a message to quote it.")
            return

        try:
            replied_msg = await ctx.channel.fetch_message(
                ctx.message.reference.message_id
            )
        except discord.NotFound:
            await ctx.send("❌ Original message not found.")
            return

        content = replied_msg.content.strip()
        if not content:
            await ctx.send("❌ The replied message has no text content to quote.")
            return

        created_at = replied_msg.created_at.strftime("%d/%m/%Y")
        embed_color = (
            user.color
            if isinstance(user, discord.Member) and user.color.value
            else discord.Color.from_rgb(245, 187, 87)
        )

        quoted_lines = "\n".join(
            f"> {line}" if line.strip() else ">"
            for line in content.splitlines()
        )

        embed = discord.Embed(
            description=f"{quoted_lines}\n\n*{user.mention} - {created_at}*",
            color=embed_color,
        )
        embed.set_thumbnail(url=user.display_avatar.url)

        sent_message = await ctx.send(embed=embed)

        try:
            await ctx.message.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        try:
            await replied_msg.delete()
        except (discord.Forbidden, discord.NotFound, discord.HTTPException):
            pass

        for emoji in ("⬆️", "⬇️"):
            try:
                await sent_message.add_reaction(emoji)
            except discord.HTTPException:
                pass

    @noah.command(name="if")
    async def invert_rarity(ctx: commands.Context, rarity: str) -> None:
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
        meta = _parse_embed_metadata(original)

        new_embed = discord.Embed(
            title=original.title,
            description=original.description,
            color=RARITY_COLORS[rarity],
            url=original.url,
        )

        if new_embed.description:
            new_name = RARITY_DISPLAY[rarity]
            new_symbol = RARITY_SYMBOLS[rarity]

            new_embed.description = re.sub(
                r"(Type:\s*)(Alpha|Beta|Gamma|Delta|Sigma|Epsilon|Zeta|Omega)\s*\([^)]*\)",
                rf"\1{new_name} ({new_symbol})",
                new_embed.description,
                count=1,
            )

            if meta.get("rarity"):
                old_symbol = meta["rarity"]
                new_embed.description = new_embed.description.replace(
                    f"({old_symbol})", f"({new_symbol})"
                )

        if original.image and original.image.url:
            new_embed.set_image(url=original.image.url)

        if original.thumbnail and original.thumbnail.url:
            new_embed.set_thumbnail(url=original.thumbnail.url)

        if original.footer and original.footer.text:
            new_embed.set_footer(
                text=original.footer.text,
                icon_url=original.footer.icon_url,
            )

        if original.author and original.author.name:
            new_embed.set_author(
                name=original.author.name,
                icon_url=original.author.icon_url,
                url=original.author.url,
            )

        await ctx.send(embed=new_embed)

    @noah.command()
    async def setlist(ctx: commands.Context) -> None:
        if not ctx.author.guild_permissions.administrator:
            await ctx.send("❌ Only administrators can use this command.")
            return

        members = ctx.message.mentions
        if not members:
            await ctx.send("❌ You must mention at least one user.")
            return

        guild = ctx.guild
        role = discord.utils.get(guild.roles, name="Lista")

        if not role:
            await ctx.send("❌ Role 'Lista' not found.")
            return

        target_ids = {member.id for member in members}
        failed = []

        await ctx.send("Fetching Users...")

        async for member in guild.fetch_members(limit=None):
            if member.id not in target_ids:
                try:
                    await member.remove_roles(role)
                except discord.Forbidden:
                    failed.append(member.display_name)

        for member in members:
            if role not in member.roles:
                try:
                    await member.add_roles(role)
                except discord.Forbidden:
                    failed.append(member.display_name)

        message = "✅ Lista updated.\n"
        if failed:
            message += f"\n⚠ Could not modify: {', '.join(failed)}"

        await ctx.send(message)

    register_waifu_commands(noah)
    register_relics_commands(noah)
    register_tts_commands(noah)
    register_vc_stats_commands(bot, noah)
