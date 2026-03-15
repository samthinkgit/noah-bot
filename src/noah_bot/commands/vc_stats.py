from datetime import datetime

import discord
from discord.ext import commands

from noah_bot.modules.bot_context import get_bot_context
from noah_bot.modules.discord_formatter import EmbedTable


def _format_minutes(total_minutes: int) -> str:
    hours, minutes = divmod(max(total_minutes, 0), 60)
    if hours == 0:
        return f"{minutes} min"
    return f"{hours}h {minutes}m"


def _format_hours(hours_value: float | None) -> str:
    if hours_value is None:
        return "-"

    if float(hours_value).is_integer():
        return f"{int(hours_value)}h"

    return f"{hours_value:g}h"


def _format_total_hours(total_minutes: int) -> str:
    return f"{max(total_minutes, 0) / 60:.2f}h"


def _format_timestamp(iso_value: str | None) -> str:
    if not iso_value:
        return "-"

    try:
        timestamp = int(datetime.fromisoformat(iso_value).timestamp())
    except ValueError:
        return "-"

    return f"<t:{timestamp}:R>"


def _can_manage_vc_settings(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    return any(role.name == "Funcionarios" for role in member.roles)


def _is_listening(state: discord.VoiceState) -> bool:
    if state.channel is None:
        return False

    return not (state.self_deaf or state.deaf)


def register_vc_stats_commands(bot: commands.Bot, noah_group: commands.Group) -> None:
    @bot.listen("on_ready")
    async def sync_voice_tracking() -> None:
        context = get_bot_context(bot)
        connected_members: list[dict[str, int | str | None]] = []

        for guild in bot.guilds:
            voice_channels = [*guild.voice_channels, *guild.stage_channels]

            for channel in voice_channels:
                for member in channel.members:
                    if member.bot:
                        continue
                    if not member.voice or not _is_listening(member.voice):
                        continue

                    connected_members.append(
                        {
                            "user_id": member.id,
                            "display_name": member.display_name,
                            "channel_id": channel.id,
                            "channel_name": channel.name,
                            "guild_id": guild.id,
                            "guild_name": guild.name,
                        }
                    )

        context.voice_manager.sync_connected_members(connected_members)

    @bot.listen("on_voice_state_update")
    async def track_voice_state(
        member: discord.Member,
        before: discord.VoiceState,
        after: discord.VoiceState,
    ) -> None:
        if member.bot:
            return

        context = get_bot_context(bot)
        before_channel = before.channel if _is_listening(before) else None
        after_channel = after.channel if _is_listening(after) else None

        if before_channel == after_channel:
            return

        context.voice_manager.handle_voice_state_change(
            member.id,
            member.display_name,
            before_channel_id=before_channel.id if before_channel else None,
            before_channel_name=before_channel.name if before_channel else None,
            after_channel_id=after_channel.id if after_channel else None,
            after_channel_name=after_channel.name if after_channel else None,
            guild_id=member.guild.id,
            guild_name=member.guild.name,
        )

    @noah_group.group(name="vc")
    async def vc(ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send("Usa `.noah vc help` para ver los comandos de voz.")

    @vc.command()
    async def help(ctx: commands.Context) -> None:
        chart = EmbedTable(headers=["Command", "Description"], title="Voice Stats")
        chart.add_row([".noah vc summary", "Resumen visual de tus stats de voz."])
        chart.add_row([".noah vc stats", "Muestra tus stats de voz."])
        chart.add_row([".noah vc stats @user", "Muestra las stats de otro usuario."])
        chart.add_row([".noah vc summary @user", "Resumen visual de otro usuario."])
        chart.add_row([".noah vc top", "Ranking de tiempo en voice chat."])
        chart.add_row([".noah vc active", "Usuarios conectados ahora mismo."])
        chart.add_row(
            [
                ".noah vc setminutes @user <minutes>",
                "[Admin/Funcionarios] Fija los minutos totales.",
            ]
        )
        chart.add_row(
            [
                ".noah vc startleveling <hours>",
                "[Admin/Funcionarios] Activa los niveles por horas acumuladas.",
            ]
        )
        await ctx.send(embed=chart.render())

    @vc.command()
    async def stats(
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        target = member or ctx.author
        context = get_bot_context(ctx.bot)
        stats_data = context.voice_manager.get_user_stats(target.id)

        if stats_data is None:
            await ctx.send(f"🔇 {target.display_name} todavía no tiene stats de voz.")
            return

        table = EmbedTable(
            headers=["Campo", "Valor"],
            title=f"🎙️ Voice Stats - {target.display_name}",
            color=discord.Color.teal(),
        )
        table.add_row(["Usuario", target.mention])
        table.add_row(
            [
                "Tiempo total",
                _format_minutes(int(stats_data.get("effective_total_minutes", 0))),
            ]
        )
        table.add_row(["Sesiones", str(int(stats_data.get("sessions", 0)))])
        table.add_row(
            [
                "Estado",
                "Conectado" if stats_data.get("is_connected") else "Desconectado",
            ]
        )

        if stats_data.get("is_connected"):
            table.add_row(
                [
                    "Sesion actual",
                    _format_minutes(int(stats_data.get("current_session_minutes", 0))),
                ]
            )

        active_session = stats_data.get("active_session") or {}
        current_channel_name = active_session.get("channel_name")
        last_channel_name = stats_data.get("last_channel_name")
        table.add_row(["Ultimo canal", current_channel_name or last_channel_name or "-"])
        table.add_row(["Ultima entrada", _format_timestamp(stats_data.get("last_joined_at"))])
        table.add_row(["Ultima salida", _format_timestamp(stats_data.get("last_left_at"))])

        level_data = stats_data.get("level_data")
        if level_data:
            table.add_row(["Nivel", str(level_data["level"])])
            table.add_row(
                [
                    "Req. por nivel",
                    _format_hours(level_data.get("hours_per_level")),
                ]
            )
            table.add_row(
                [
                    "Progreso",
                    (
                        f"{_format_minutes(int(level_data['progress_minutes']))} / "
                        f"{_format_minutes(int(level_data['minutes_per_level']))} "
                        f"({int(level_data['progress_percent'])}%)"
                    ),
                ]
            )
            table.add_row(
                [
                    "Siguiente nivel",
                    f"En {_format_minutes(int(level_data['remaining_minutes']))}",
                ]
            )

        await ctx.send(embed=table.render())

    @vc.command()
    async def summary(
        ctx: commands.Context,
        member: discord.Member | None = None,
    ) -> None:
        target = member or ctx.author
        context = get_bot_context(ctx.bot)
        stats_data = context.voice_manager.get_user_stats(target.id)

        if stats_data is None:
            await ctx.send(f"🔇 {target.display_name} todavía no tiene stats de voz.")
            return

        total_minutes = int(stats_data.get("effective_total_minutes", 0))
        level_data = stats_data.get("level_data")
        embed = discord.Embed(
            title=f"🎙️ Voice Summary - {target.display_name}",
            color=discord.Color.teal(),
        )
        embed.set_thumbnail(url=target.display_avatar.url)
        if level_data:
            embed.description = "\n".join(
                [
                    f"Nivel: `{level_data['level']}`",
                    f"Siguiente nivel en: `{_format_minutes(int(level_data['remaining_minutes']))}`",
                    f"Horas totales: `{_format_total_hours(total_minutes)}`",
                ]
            )
        else:
            embed.description = "\n".join(
                [
                    "Nivel: `Sistema desactivado`",
                    "Siguiente nivel en: `-`",
                    f"Horas totales: `{_format_total_hours(total_minutes)}`",
                ]
            )

        await ctx.send(embed=embed)

    @vc.command()
    async def top(ctx: commands.Context, limit: int = 10) -> None:
        context = get_bot_context(ctx.bot)
        safe_limit = max(1, min(limit, 15))
        guild_member_ids = {member.id for member in ctx.guild.members if not member.bot}
        leveling_config = context.voice_manager.get_leveling_config()
        top_users = context.voice_manager.get_top_users(
            safe_limit,
            guild_member_ids=guild_member_ids,
        )

        if not top_users:
            await ctx.send("📭 Todavía no hay stats de voz registradas.")
            return

        table = EmbedTable(
            headers=["Ranking"],
            title="🏆 Voice Chat Ranking",
            color=discord.Color.gold(),
        )

        for position, user_data in enumerate(top_users, start=1):
            member = ctx.guild.get_member(int(user_data["user_id"]))
            username = member.mention if member else user_data.get("display_name", "Unknown")
            total_time = _format_minutes(int(user_data.get("effective_total_minutes", 0)))
            row_text = f"`#{position}` {username} • `{total_time}`"

            if leveling_config.get("enabled"):
                level_data = user_data.get("level_data")
                level = str(level_data["level"]) if level_data else "1"
                row_text += f" • `Lv {level}`"

            table.add_row([row_text])

        await ctx.send(embed=table.render())

    @vc.command()
    async def active(ctx: commands.Context) -> None:
        context = get_bot_context(ctx.bot)
        active_sessions = context.voice_manager.get_active_sessions(guild_id=ctx.guild.id)

        if not active_sessions:
            await ctx.send("🔇 No hay nadie conectado a voice chat ahora mismo.")
            return

        table = EmbedTable(
            headers=["Usuario", "Canal", "Tiempo"],
            title="🔊 Usuarios en Voice Chat",
            color=discord.Color.green(),
        )

        for session in active_sessions:
            member = ctx.guild.get_member(int(session["user_id"]))
            username = member.mention if member else session.get("display_name", "Unknown")
            table.add_row(
                [
                    username,
                    session.get("channel_name") or "-",
                    _format_minutes(int(session.get("elapsed_minutes", 0))),
                ]
            )

        await ctx.send(embed=table.render())

    @vc.command()
    async def setminutes(
        ctx: commands.Context,
        member: discord.Member,
        minutes: int,
    ) -> None:
        if not _can_manage_vc_settings(ctx.author):
            await ctx.send(
                "❌ Solo administradores o el rol `Funcionarios` pueden usar este comando."
            )
            return

        context = get_bot_context(ctx.bot)
        result = context.voice_manager.set_total_minutes(
            member.id,
            member.display_name,
            minutes,
            guild_id=ctx.guild.id,
            guild_name=ctx.guild.name,
        )

        message = (
            f"✅ Tiempo total de {member.mention} fijado en "
            f"`{_format_minutes(int(result['total_minutes']))}`."
        )

        level_data = result.get("level_data")
        if level_data:
            message += f" Nivel actual: `{level_data['level']}`."

        await ctx.send(message)

    @vc.command()
    async def startleveling(ctx: commands.Context, hours_requisite: float) -> None:
        if not _can_manage_vc_settings(ctx.author):
            await ctx.send(
                "❌ Solo administradores o el rol `Funcionarios` pueden usar este comando."
            )
            return

        if hours_requisite <= 0:
            await ctx.send("❌ Las horas requeridas deben ser mayores que 0.")
            return

        context = get_bot_context(ctx.bot)
        config = context.voice_manager.configure_leveling(hours_requisite)

        await ctx.send(
            "✅ Sistema de niveles activado. "
            f"Cada `{_format_hours(config['hours_per_level'])}` acumuladas "
            f"se sube un nivel."
        )
