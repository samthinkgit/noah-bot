import tempfile

import discord
from discord.ext import commands

from noah_bot.modules.tts import text_to_speech


def register_tts_commands(noah_group: commands.Group) -> None:
    @noah_group.group()
    async def tts(ctx: commands.Context) -> None:
        if ctx.invoked_subcommand is None:
            await ctx.send("Use `.noah tts join` or `.noah tts say`.")

    @tts.command()
    async def join(ctx: commands.Context) -> None:
        if not ctx.author.voice:
            await ctx.send("❌ You must be in a voice channel.")
            return

        channel = ctx.author.voice.channel
        voice_client = ctx.voice_client

        try:
            if voice_client and voice_client.is_connected():
                if voice_client.channel.id == channel.id:
                    await ctx.send("🎤 Already in your voice channel.")
                    return
                await voice_client.move_to(channel)
            else:
                await channel.connect()
        except Exception as exc:
            await ctx.send(f"❌ Voice connection failed: `{exc}`")
            return

        await ctx.send(f"🎤 Joined **{channel.name}**")

    @tts.command(aliases=["nts"])
    async def say(ctx: commands.Context, *, text: str) -> None:
        if not ctx.voice_client:
            await ctx.send("❌ Noah is not in a voice channel. Use `.noah tts join`.")
            return

        voice_client = ctx.voice_client
        stream = text_to_speech(text)
        audio_bytes = b"".join(stream)

        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp3") as tmp:
            tmp.write(audio_bytes)
            tmp_path = tmp.name

        source = discord.FFmpegPCMAudio(tmp_path)

        if voice_client.is_playing():
            voice_client.stop()

        voice_client.play(source)
