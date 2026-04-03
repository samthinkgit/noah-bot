import asyncio
from contextlib import suppress
from pathlib import Path

import discord
from discord.ext import commands

from noah_bot.modules.bot_context import get_bot_context
from noah_bot.modules.discord_formatter import _parse_embed_metadata, render_embeds_to_png
from noah_bot.modules.send_message import send_message


MEDIA_DIR = Path(__file__).resolve().parents[3] / "media"
TOKEN_GETTER_ARCHIVE = MEDIA_DIR / "autogami_token_getter.rar"
CONSENT_ACCEPT_EMOJI = "✅"
CONSENT_DECLINE_EMOJI = "❌"
AUTOGAMI_V_BATCH_SIZE = 5
AUTOGAMI_V_DELAY_SECONDS = 6
AUTOGAMI_V_RESPONSE_TIMEOUT_SECONDS = 3
WAIFUGAMI_BOT_USER_ID = 722418701852344391


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
        name=".noah autogami showfavs",
        value="Muestra todos tus emojis favoritos guardados.",
        inline=False,
    )
    embed.add_field(
        name=".noah autogami v <num> <num> ... [-merge]",
        value="Envia `.v` en tandas de 5 con 6s de espera entre cada tanda. Alias: `.nv`.",
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
) -> tuple[int, str]:
    if ctx.guild is None:
        raise RuntimeError("Autogami requires a guild channel.")

    return await asyncio.to_thread(
        send_message,
        message,
        token,
        str(ctx.author.id),
        str(ctx.guild.id),
        str(ctx.channel.id),
    )


def _normalize_waifu_identifier(value: str) -> str:
    sanitized = value.strip()
    if sanitized.isdigit():
        return str(int(sanitized))
    return sanitized.casefold()


def _parse_autogami_v_inputs(values: tuple[str, ...]) -> tuple[list[str], set[str]]:
    numbers: list[str] = []
    flags: set[str] = set()

    for raw_value in values:
        value = raw_value.strip()
        if not value:
            continue

        if value.startswith("-"):
            flags.add(value.lower())
            continue

        numbers.append(value)

    return numbers, flags


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
    captured_batches: list[tuple[list[str], discord.Message]],
) -> None:
    for index, (batch, response_message) in enumerate(captured_batches, start=1):
        buffer = await asyncio.to_thread(render_embeds_to_png, response_message.embeds)
        if buffer is None:
            await ctx.send(
                f"⚠️ No pude hacer merge de la respuesta {index}/{len(captured_batches)} "
                f"para `{'.v ' + ' '.join(batch)}` porque no encontré imágenes."
            )
            continue

        await ctx.send(
            file=discord.File(buffer, filename=f"autogami_merge_{index}.png"),
        )


async def _run_autogami_v(ctx: commands.Context, values: tuple[str, ...]) -> None:
    if ctx.guild is None:
        await ctx.send("❌ Este comando solo funciona dentro de un servidor.")
        return

    if not values:
        await ctx.send(
            "❌ Usa `.noah autogami v <num> <num> <num> ... [-merge]` o `.nv <num> <num> ... [-merge]`."
        )
        return

    sanitized_numbers, flags = _parse_autogami_v_inputs(values)
    merge_requested = "-merge" in flags
    unknown_flags = sorted(flag for flag in flags if flag != "-merge")

    if unknown_flags:
        await ctx.send(f"❌ Flag(s) no reconocidos: {' '.join(unknown_flags)}")
        return

    if not sanitized_numbers:
        await ctx.send(
            "❌ No has indicado números válidos para enviar con `.v`."
        )
        return

    context = get_bot_context(ctx.bot)
    token = context.autogami_tokens.get_token(ctx.author.id)
    if token is None:
        await ctx.send(
            "❌ No tienes un token sincronizado. Usa `.noah autogami sync` primero."
        )
        return

    batches = [
        sanitized_numbers[index : index + AUTOGAMI_V_BATCH_SIZE]
        for index in range(0, len(sanitized_numbers), AUTOGAMI_V_BATCH_SIZE)
    ]
    captured_batches: list[tuple[list[str], discord.Message]] = []

    for index, batch in enumerate(batches, start=1):
        command_text = f".v {' '.join(batch)}"
        wait_task: asyncio.Task[discord.Message] | None = None
        if merge_requested:
            wait_task = asyncio.create_task(_wait_for_waifugami_response(ctx, batch))

        try:
            status, body = await _send_autogami_message(ctx, token, command_text)
        except Exception:
            if wait_task is not None:
                wait_task.cancel()
                with suppress(asyncio.CancelledError):
                    await wait_task
            if index < len(batches):
                await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)
            continue

        if not 200 <= status < 300:
            if wait_task is not None:
                wait_task.cancel()
                with suppress(asyncio.CancelledError):
                    await wait_task
            if index < len(batches):
                await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)
            continue

        if merge_requested:
            try:
                waifugami_response = await wait_task
            except asyncio.TimeoutError:
                if index < len(batches):
                    await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)
                continue

            captured_batches.append((batch, waifugami_response))

        if index < len(batches):
            await asyncio.sleep(AUTOGAMI_V_DELAY_SECONDS)

    if merge_requested and captured_batches:
        await _send_autogami_merged_batches(ctx, captured_batches)


def register_autogami_commands(bot: commands.Bot, noah_group: commands.Group) -> None:
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
            await ctx.send(f"{ctx.author.mention} he guardado `{emoji}` en tus favs de Autogami.")
            return

        await ctx.send(f"{ctx.author.mention} `{emoji}` ya estaba en tus favs de Autogami.")

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

    @autogami.command(name="v")
    async def autogami_v(ctx: commands.Context, *values: str) -> None:
        await _run_autogami_v(ctx, values)

    @bot.command(name="nv")
    async def autogami_v_alias(ctx: commands.Context, *values: str) -> None:
        await _run_autogami_v(ctx, values)
