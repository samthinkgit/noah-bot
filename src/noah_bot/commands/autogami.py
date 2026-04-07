import asyncio
import json
import re
from contextlib import suppress
from pathlib import Path

import discord
from discord.ext import commands

from noah_bot.modules.bot_context import get_bot_context
from noah_bot.modules.discord_formatter import (
    _parse_embed_metadata,
    build_loading_embed,
    render_embeds_to_png,
)
from noah_bot.modules.send_message import delete_message, send_message


MEDIA_DIR = Path(__file__).resolve().parents[3] / "media"
TOKEN_GETTER_ARCHIVE = MEDIA_DIR / "autogami_token_getter.rar"
CONSENT_ACCEPT_EMOJI = "✅"
CONSENT_DECLINE_EMOJI = "❌"
AUTOGAMI_V_BATCH_SIZE = 5
AUTOGAMI_V_DELAY_SECONDS = 6
AUTOGAMI_V_RESPONSE_TIMEOUT_SECONDS = 3
WAIFUGAMI_BOT_USER_ID = 722418701852344391
CHEST_TRIGGER_PATTERN = re.compile(r"\.open\s+<treasure\s+type>", re.IGNORECASE)
USER_MENTION_PATTERN = re.compile(r"^<@!?(\d+)>$")
CHEST_TYPE_COLORS = {
    "platinum": 0x424860,
    "bronze": 0xCD8032,
    "silver": 0xAAA9AD,
    "gold": 0xFFD900,
    "diamond": 0xB9F2FF,
    "zeta": 0xFFC0CA,
    "event": 0xFFC0CA,
}


def _build_autogami_help_embed() -> discord.Embed:
    embed = discord.Embed(
        title="Autogami",
        description="Sincroniza tu token y prueba el envio automatizado.",
        color=discord.Color.blurple(),
    )
    embed.add_field(
        name=".noah autogami sync",
        value="Recibe instrucciones y el RAR para sacar tu token.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami sync <token>",
        value="Borra tu mensaje, pide consentimiento y guarda tu token cifrado.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami test",
        value="Envia `test success` usando tu token sincronizado.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami addfav <emoji>",
        value="Guarda un emoji favorito para reaccionar a los `Waifu Claimed!`.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami delfav <emoji>",
        value="Borra un emoji de tus favs de Autogami.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami showfavs",
        value="Muestra todos tus emojis favoritos guardados.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami chestconfig <emoji>",
        value="Configura el emoji para abrir chest automáticamente. Solo admins/Funcionarios.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami v <num> <num> ... [-merge] [-silent]",
        value="Envia `.v` en tandas de 5 con 6s de espera entre cada tanda. Acepta `-user @user`. Alias: `.nv`, `.nvms`. `-silent` requiere `-merge`.",
        inline=False,
    )
    return embed


async def _send_sync_instructions(ctx: commands.Context) -> None:
    lines = [
        f"{ctx.author.mention} sigue estos pasos para sincronizar Autogami:",
        "1. Descarga el RAR adjunto.",
        "2. Extráelo en cualquier carpeta de tu PC.",
        "3. Ejecuta `token_getter.exe`.",
        "4. Copia el token obtenido.",
        "5. Usa `.noah autogami sync <token>` para guardarlo.",
    ]

    if not TOKEN_GETTER_ARCHIVE.exists():
        await ctx.send(
            "❌ No encuentro `media/autogami_token_getter.rar`, así que no puedo enviarte el asistente ahora mismo."
        )
        return

    await ctx.send(
        "\n".join(lines),
        file=discord.File(TOKEN_GETTER_ARCHIVE, filename=TOKEN_GETTER_ARCHIVE.name),
    )


async def _delete_token_message(ctx: commands.Context) -> bool:
    try:
        await ctx.message.delete()
    except (discord.Forbidden, discord.NotFound, discord.HTTPException):
        await ctx.send(
            f"{ctx.author.mention} no he podido borrar tu mensaje, así que no voy a guardar el token. "
            "Bórralo manualmente y vuelve a intentarlo en un canal donde yo pueda eliminar mensajes."
        )
        return False

    return True


async def _request_sync_consent(ctx: commands.Context) -> bool:
    consent_message = await ctx.send(
        "\n".join(
            [
                f"{ctx.author.mention} antes de guardar tu token debes ser consciente de que Noah no puede:",
                "- Leer tus mensajes privados o usar tu cuenta para espiar conversaciones",
                "- Enviar mensajes por su cuenta sin una acción o consentimiento tuyo",
                "- Usar tu token para otra cosa que no sean automatizaciones concretas de Autogami",
                "",
                "Y Noah solo puede usar mensajes específicos que tú decidas automatizar con Autogami.",
                "",
                f"Reacciona con {CONSENT_ACCEPT_EMOJI} para aceptar o con {CONSENT_DECLINE_EMOJI} para cancelar.",
            ]
        )
    )

    for emoji in (CONSENT_ACCEPT_EMOJI, CONSENT_DECLINE_EMOJI):
        try:
            await consent_message.add_reaction(emoji)
        except discord.HTTPException:
            pass

    def reaction_check(reaction: discord.Reaction, user: discord.User | discord.Member) -> bool:
        return (
            user.id == ctx.author.id
            and reaction.message.id == consent_message.id
            and str(reaction.emoji) in {CONSENT_ACCEPT_EMOJI, CONSENT_DECLINE_EMOJI}
        )

    try:
        reaction, _ = await ctx.bot.wait_for(
            "reaction_add",
            timeout=120.0,
            check=reaction_check,
        )
    except asyncio.TimeoutError:
        await consent_message.edit(
            content=f"{ctx.author.mention} sincronización cancelada por tiempo de espera."
        )
        return False

    accepted = str(reaction.emoji) == CONSENT_ACCEPT_EMOJI
    if accepted:
        await consent_message.edit(
            content=f"{ctx.author.mention} consentimiento recibido. Guardando token cifrado..."
        )
        return True

    await consent_message.edit(content=f"{ctx.author.mention} sincronización cancelada.")
    return False


async def _send_autogami_test(ctx: commands.Context, token: str) -> tuple[int, str]:
    if ctx.guild is None:
        raise RuntimeError("Autogami test requires a guild channel.")

    return await asyncio.to_thread(
        send_message,
        "test success",
        token,
        str(ctx.author.id),
        str(ctx.guild.id),
        str(ctx.channel.id),
    )


async def _send_autogami_message(
    ctx: commands.Context,
    token: str,
    message: str,
    acting_user_id: int | None = None,
) -> tuple[int, str]:
    if ctx.guild is None:
        raise RuntimeError("Autogami requires a guild channel.")

    return await asyncio.to_thread(
        send_message,
        message,
        token,
        str(acting_user_id if acting_user_id is not None else ctx.author.id),
        str(ctx.guild.id),
        str(ctx.channel.id),
    )


def _normalize_waifu_identifier(value: str) -> str:
    sanitized = value.strip()
    if sanitized.isdigit():
        return str(int(sanitized))
    return sanitized.casefold()


def _display_name_for_user(user: discord.abc.User) -> str:
    return getattr(user, "display_name", getattr(user, "name", str(user.id)))


def _can_manage_autogami_chests(member: discord.Member) -> bool:
    if member.guild_permissions.administrator:
        return True

    return any(role.name == "Funcionarios" for role in member.roles)


def _iter_embed_text_parts(embed: discord.Embed) -> list[str]:
    parts = [
        embed.title or "",
        embed.description or "",
    ]

    if embed.author and embed.author.name:
        parts.append(embed.author.name)

    if embed.footer and embed.footer.text:
        parts.append(embed.footer.text)

    for field in embed.fields:
        parts.append(field.name or "")
        parts.append(field.value or "")

    return parts


def _find_chest_embed(message: discord.Message) -> discord.Embed | None:
    if message.author.id != WAIFUGAMI_BOT_USER_ID:
        return None

    for embed in message.embeds:
        if any(
            CHEST_TRIGGER_PATTERN.search(text)
            for text in _iter_embed_text_parts(embed)
        ):
            return embed

    return None


def _split_rgb(color_value: int) -> tuple[int, int, int]:
    return (
        (color_value >> 16) & 0xFF,
        (color_value >> 8) & 0xFF,
        color_value & 0xFF,
    )


def _color_distance(left: int, right: int) -> int:
    left_red, left_green, left_blue = _split_rgb(left)
    right_red, right_green, right_blue = _split_rgb(right)
    return (
        (left_red - right_red) ** 2
        + (left_green - right_green) ** 2
        + (left_blue - right_blue) ** 2
    )


def _resolve_chest_type(embed: discord.Embed) -> str | None:
    if embed.color is None:
        return None

    color_value = embed.color.value
    nearest_type = min(
        ("platinum", "bronze", "silver", "gold", "diamond", "zeta"),
        key=lambda chest_type: _color_distance(
            color_value,
            CHEST_TYPE_COLORS[chest_type],
        ),
    )

    if nearest_type != "zeta":
        return nearest_type

    image_url = ""
    if embed.image and embed.image.url:
        image_url = embed.image.url

    if "zetachest" in image_url.casefold():
        return "zeta"
    return "event"


def _parse_autogami_v_inputs(
    values: tuple[str, ...],
) -> tuple[list[str], set[str], str | None, list[str]]:
    numbers: list[str] = []
    flags: set[str] = set()
    target_user_raw: str | None = None
    errors: list[str] = []

    index = 0
    while index < len(values):
        raw_value = values[index]
        index += 1

        value = raw_value.strip()
        if not value:
            continue

        if value.startswith("-"):
            normalized_flag = value.lower()
            if normalized_flag == "-user":
                while index < len(values) and not values[index].strip():
                    index += 1

                if index >= len(values):
                    errors.append("❌ `-user` requiere una mención o ID de usuario.")
                    break

                target_user_raw = values[index].strip()
                index += 1
                continue

            flags.add(normalized_flag)
            continue

        numbers.append(value)

    return numbers, flags, target_user_raw, errors


def _resolve_autogami_v_target_user(
    ctx: commands.Context,
    raw_target: str | None,
) -> discord.abc.User:
    if raw_target is None:
        return ctx.author

    match = USER_MENTION_PATTERN.fullmatch(raw_target)
    user_id: int | None = None
    if match is not None:
        user_id = int(match.group(1))
    elif raw_target.isdigit():
        user_id = int(raw_target)

    if user_id is not None:
        for mentioned_user in ctx.message.mentions:
            if mentioned_user.id == user_id:
                return mentioned_user

        if ctx.guild is not None:
            member = ctx.guild.get_member(user_id)
            if member is not None:
                return member

    raise ValueError("❌ No he podido resolver el usuario indicado en `-user`.")


def _extract_message_id(response_body: str) -> str | None:
    try:
        payload = json.loads(response_body)
    except (json.JSONDecodeError, TypeError):
        return None

    message_id = payload.get("id")
    if isinstance(message_id, str) and message_id:
        return message_id
    return None


def _response_matches_batch(message: discord.Message, batch: list[str]) -> bool:
    if message.author.id != WAIFUGAMI_BOT_USER_ID:
        return False

    if not message.embeds or len(message.embeds) != len(batch):
        return False

    expected_ids = {_normalize_waifu_identifier(value) for value in batch}
    local_ids = [
        _parse_embed_metadata(embed).get("local_id")
        for embed in message.embeds
    ]
    parsed_ids = {
        _normalize_waifu_identifier(local_id)
        for local_id in local_ids
        if local_id
    }

    if parsed_ids:
        return parsed_ids == expected_ids

    return True


async def _wait_for_waifugami_response(
    ctx: commands.Context,
    batch: list[str],
) -> discord.Message:
    def message_check(message: discord.Message) -> bool:
        return (
            message.channel.id == ctx.channel.id
            and _response_matches_batch(message, batch)
        )

    return await ctx.bot.wait_for(
        "message",
        timeout=AUTOGAMI_V_RESPONSE_TIMEOUT_SECONDS,
        check=message_check,
    )


async def _send_autogami_merged_batches(
    ctx: commands.Context,
    captured_batches: list[tuple[list[str], list[discord.Embed]]],
) -> None:
    for index, (batch, embeds) in enumerate(captured_batches, start=1):
        buffer = await asyncio.to_thread(render_embeds_to_png, embeds)
        if buffer is None:
            await ctx.send(
                f"⚠️ No pude hacer merge de la respuesta {index}/{len(captured_batches)} "
                f"para `{'.v ' + ' '.join(batch)}` porque no encontré imágenes."
            )
            continue

        await ctx.send(
            file=discord.File(buffer, filename=f"autogami_merge_{index}.png"),
        )


async def _delete_autogami_silent_messages(
    ctx: commands.Context,
    token: str,
    acting_user_id: int,
    sent_message_id: str | None,
    waifugami_response: discord.Message,
) -> None:
    delete_tasks = []

    if sent_message_id and ctx.guild is not None:
        delete_tasks.append(
            asyncio.to_thread(
                delete_message,
                sent_message_id,
                token,
                str(acting_user_id),
                str(ctx.guild.id),
                str(ctx.channel.id),
            )
        )

    delete_tasks.append(waifugami_response.delete())

    results = await asyncio.gather(*delete_tasks, return_exceptions=True)
    _ = results


async def _update_autogami_progress_message(
    progress_message: discord.Message | None,
    completed_batches: int,
    total_batches: int,
) -> None:
    if progress_message is None or total_batches <= 0:
        return

    percent = int(completed_batches * 100 / total_batches)
    embed = build_loading_embed(
        title=f"Autogami {completed_batches}/{total_batches}",
        percent=percent,
    )
    await progress_message.edit(embed=embed)


async def _run_autogami_v(ctx: commands.Context, values: tuple[str, ...]) -> None:
    if ctx.guild is None:
        await ctx.send("❌ Este comando solo funciona dentro de un servidor.")
        return

    if not values:
        await ctx.send(
            "❌ Usa `.noah autogami v <num> <num> <num> ... [-merge] [-silent]` o `.nv <num> <num> ... [-merge] [-silent]`."
        )
        return

    sanitized_numbers, flags, target_user_raw, parse_errors = _parse_autogami_v_inputs(
        values
    )
    if parse_errors:
        await ctx.send(parse_errors[0])
        return

    merge_requested = "-merge" in flags
    silent_requested = "-silent" in flags
    unknown_flags = sorted(flag for flag in flags if flag not in {"-merge", "-silent"})

    if unknown_flags:
        await ctx.send(f"❌ Flag(s) no reconocidos: {' '.join(unknown_flags)}")
        return

    if silent_requested and not merge_requested:
        await ctx.send("❌ `-silent` solo funciona si también usas `-merge`.")
        return

    if not sanitized_numbers:
        await ctx.send(
            "❌ No has indicado números válidos para enviar con `.v`."
        )
        return

    try:
        target_user = _resolve_autogami_v_target_user(ctx, target_user_raw)
    except ValueError as exc:
        await ctx.send(str(exc))
        return

    context = get_bot_context(ctx.bot)
    token = context.autogami_tokens.get_token(target_user.id)
    if token is None:
        if target_user.id == ctx.author.id:
            await ctx.send(
                "❌ No tienes un token sincronizado. Usa `.noah autogami sync` primero."
            )
            return

        await ctx.send(
            f"❌ {target_user.mention} no tiene un token sincronizado en Autogami."
        )
        return

    batches = [
        sanitized_numbers[index : index + AUTOGAMI_V_BATCH_SIZE]
        for index in range(0, len(sanitized_numbers), AUTOGAMI_V_BATCH_SIZE)
    ]
    captured_batches: list[tuple[list[str], list[discord.Embed]]] = []
    show_progress = merge_requested and silent_requested
    progress_message: discord.Message | None = None

    if show_progress:
        progress_message = await ctx.send(
            embed=build_loading_embed(title=f"Autogami 0/{len(batches)}", percent=0)
        )

    for index, batch in enumerate(batches, start=1):
        command_text = f".v {' '.join(batch)}"
        wait_task: asyncio.Task[discord.Message] | None = None
        if merge_requested:
            wait_task = asyncio.create_task(_wait_for_waifugami_response(ctx, batch))

        try:
            status, body = await _send_autogami_message(
                ctx,
                token,
                command_text,
                acting_user_id=target_user.id,
            )
        except Exception:
            if wait_task is not None:
                wait_task.cancel()
                with suppress(asyncio.CancelledError):
                    await wait_task
            if show_progress:
                with suppress(discord.HTTPException, discord.NotFound):
                    await _update_autogami_progress_message(progress_message, index, len(batches))
            if index < len(batches):
                await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)
            continue

        if not 200 <= status < 300:
            if wait_task is not None:
                wait_task.cancel()
                with suppress(asyncio.CancelledError):
                    await wait_task
            if show_progress:
                with suppress(discord.HTTPException, discord.NotFound):
                    await _update_autogami_progress_message(progress_message, index, len(batches))
            if index < len(batches):
                await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)
            continue

        context.daily_stats.increment_autogami_uses(
            ctx.guild.id,
            ctx.guild.name,
            target_user.id,
            _display_name_for_user(target_user),
        )

        if merge_requested:
            try:
                waifugami_response = await wait_task
            except asyncio.TimeoutError:
                if show_progress:
                    with suppress(discord.HTTPException, discord.NotFound):
                        await _update_autogami_progress_message(progress_message, index, len(batches))
                if index < len(batches):
                    await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)
                continue

            response_embeds = list(waifugami_response.embeds)
            if silent_requested:
                sent_message_id = _extract_message_id(body)
                with suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
                    await _delete_autogami_silent_messages(
                        ctx,
                        token,
                        target_user.id,
                        sent_message_id,
                        waifugami_response,
                    )

            captured_batches.append((batch, response_embeds))

        if show_progress:
            with suppress(discord.HTTPException, discord.NotFound):
                await _update_autogami_progress_message(progress_message, index, len(batches))

        if index < len(batches):
            await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)

    if show_progress and progress_message is not None:
        with suppress(discord.HTTPException, discord.Forbidden, discord.NotFound):
            await progress_message.delete()

    if merge_requested and captured_batches:
        await _send_autogami_merged_batches(ctx, captured_batches)


def register_autogami_commands(bot: commands.Bot, noah_group: commands.Group) -> None:
    @bot.listen("on_message")
    async def _handle_autogami_chest_spawn(message: discord.Message) -> None:
        if message.guild is None:
            return

        chest_embed = _find_chest_embed(message)
        if chest_embed is None:
            return

        chest_type = _resolve_chest_type(chest_embed)
        if chest_type is None:
            return

        context = get_bot_context(bot)
        chest_emoji = context.autogami_tokens.get_chest_emoji(message.guild.id)
        if not chest_emoji:
            return

        context.autogami_chest_messages[message.id] = chest_type

        try:
            await message.add_reaction(chest_emoji)
        except discord.HTTPException:
            pass

    @bot.listen("on_reaction_add")
    async def _handle_autogami_chest_reaction(
        reaction: discord.Reaction,
        user: discord.User | discord.Member,
    ) -> None:
        if user.bot or reaction.message.guild is None:
            return

        context = get_bot_context(bot)
        chest_type = context.autogami_chest_messages.get(reaction.message.id)
        if chest_type is None:
            return

        configured_emoji = context.autogami_tokens.get_chest_emoji(
            reaction.message.guild.id
        )
        if configured_emoji is None or str(reaction.emoji) != configured_emoji:
            return

        token = context.autogami_tokens.get_token(user.id)
        if token is None:
            return

        try:
            await asyncio.to_thread(
                send_message,
                f".open {chest_type}",
                token,
                str(user.id),
                str(reaction.message.guild.id),
                str(reaction.message.channel.id),
            )
            context.daily_stats.increment_autogami_uses(
                reaction.message.guild.id,
                reaction.message.guild.name,
                user.id,
                _display_name_for_user(user),
            )
        except Exception:
            return

    @noah_group.group()
    async def autogami(ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send(embed=_build_autogami_help_embed())

    @autogami.command()
    async def help(ctx: commands.Context) -> None:
        await ctx.send(embed=_build_autogami_help_embed())

    @autogami.command()
    async def sync(ctx: commands.Context, *, token: str | None = None) -> None:
        if not token:
            await _send_sync_instructions(ctx)
            return

        sanitized_token = token.strip()
        if not sanitized_token:
            await _send_sync_instructions(ctx)
            return

        if not await _delete_token_message(ctx):
            return

        if not await _request_sync_consent(ctx):
            return

        context = get_bot_context(ctx.bot)
        context.autogami_tokens.set_token(
            ctx.author.id,
            sanitized_token,
            username=ctx.author.display_name,
        )
        await ctx.send(
            f"{ctx.author.mention} tu token de Autogami se ha sincronizado y guardado cifrado correctamente."
        )

    @autogami.command()
    async def test(ctx: commands.Context) -> None:
        if ctx.guild is None:
            await ctx.send("❌ Este comando solo funciona dentro de un servidor.")
            return

        context = get_bot_context(ctx.bot)
        token = context.autogami_tokens.get_token(ctx.author.id)
        if token is None:
            await ctx.send(
                "❌ No tienes un token sincronizado. Usa `.noah autogami sync` primero."
            )
            return

        try:
            status, body = await _send_autogami_test(ctx, token)
        except Exception as exc:
            await ctx.send(f"❌ Falló el test de Autogami: {exc}")
            return

        if 200 <= status < 300:
            await ctx.send("✅ Test de Autogami enviado correctamente.")
            return

        error_body = body[:300] if body else "sin respuesta"
        await ctx.send(
            f"❌ El test de Autogami falló con estado HTTP {status}: {error_body}"
        )

    @autogami.command()
    async def addfav(ctx: commands.Context, emoji: str) -> None:
        context = get_bot_context(ctx.bot)
        added = context.autogami_tokens.add_favorite_emoji(ctx.author.id, emoji)
        if added:
            await ctx.send(
                f"{ctx.author.mention} he guardado `{emoji}` en tus favs de Autogami."
            )
            return

        await ctx.send(f"{ctx.author.mention} `{emoji}` ya estaba en tus favs de Autogami.")

    @autogami.command()
    async def delfav(ctx: commands.Context, emoji: str) -> None:
        context = get_bot_context(ctx.bot)
        removed = context.autogami_tokens.remove_favorite_emoji(ctx.author.id, emoji)
        if removed:
            await ctx.send(
                f"{ctx.author.mention} he borrado `{emoji}` de tus favs de Autogami."
            )
            return

        await ctx.send(f"{ctx.author.mention} `{emoji}` no estaba en tus favs de Autogami.")

    @autogami.command()
    async def showfavs(ctx: commands.Context) -> None:
        context = get_bot_context(ctx.bot)
        favorites = context.autogami_tokens.get_favorite_emojis(ctx.author.id)
        if not favorites:
            await ctx.send(
                f"{ctx.author.mention} no tienes favs guardados todavía. Usa `.noah autogami addfav <emoji>`."
            )
            return

        favorites_text = " ".join(favorites)
        await ctx.send(
            f"{ctx.author.mention} tus favs de Autogami son: {favorites_text}"
        )

    @autogami.command()
    async def chestconfig(ctx: commands.Context, emoji: str) -> None:
        if ctx.guild is None:
            await ctx.send("❌ Este comando solo funciona dentro de un servidor.")
            return

        if (
            not isinstance(ctx.author, discord.Member)
            or not _can_manage_autogami_chests(ctx.author)
        ):
            await ctx.send(
                "❌ Solo administradores o el rol `Funcionarios` pueden usar este comando."
            )
            return

        context = get_bot_context(ctx.bot)
        configured = context.autogami_tokens.set_chest_emoji(ctx.guild.id, emoji)
        if not configured:
            await ctx.send("❌ Debes indicar un emoji válido.")
            return

        await ctx.send(
            f"✅ El emoji automático de chest ha quedado configurado en `{emoji}`."
        )

    @autogami.command(name="v")
    async def autogami_v(ctx: commands.Context, *values: str) -> None:
        await _run_autogami_v(ctx, values)

    @bot.command(name="nv")
    async def autogami_v_alias(ctx: commands.Context, *values: str) -> None:
        await _run_autogami_v(ctx, values)

    @bot.command(name="nvms")
    async def autogami_v_merge_silent_alias(ctx: commands.Context, *values: str) -> None:
        await _run_autogami_v(ctx, (*values, "-merge", "-silent"))
