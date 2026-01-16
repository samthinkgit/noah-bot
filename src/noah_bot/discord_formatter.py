from PIL import Image, ImageDraw, ImageFont
import requests
import asyncio
from io import BytesIO
from typing import List
import json
from pathlib import Path
from functools import wraps
from typing import Optional
import discord


RARITY_COLORS = {
    "alpha": 0x3A423A,
    "beta": 0x357233,
    "gamma": 0x560000,
    "delta": 0x1D1D1D,
    "sigma": 0xE95C20,
    "epsilon": 0x5E258D,
    "zeta": 0xF54CE7,
    "omega": 0xB9F2FF,
}

RARITY_SYMBOLS = {
    "alpha": "α",
    "beta": "β",
    "gamma": "γ",
    "delta": "δ",
    "sigma": "σ",
    "epsilon": "ε",
    "zeta": "ζ",
    "omega": "ω",
}
RARITY_DISPLAY = {
    "alpha": "Alpha",
    "beta": "Beta",
    "gamma": "Gamma",
    "delta": "Delta",
    "sigma": "Sigma",
    "epsilon": "Epsilon",
    "zeta": "Zeta",
    "omega": "Omega",
}


class WaifuClaimFormatter:
    @staticmethod
    def build_embed(
        user: discord.Member | discord.User,
        waifu_name: str,
        rarity_symbol: str,
    ) -> discord.Embed:
        """
        Builds a 'Waifu Claimed' embed.

        :param user: User who claimed the waifu
        :param waifu_name: Name of the claimed waifu
        :param rarity_symbol: Rarity symbol (e.g. δ, ★, S)
        """

        embed = discord.Embed(
            title=f"🎉 **Congrats {user.mention}!**",
            description=(
                f"You were the **fastest** to claim **[{rarity_symbol}] {waifu_name}**.\n"
            ),
            color=discord.Color.pink(),
        )

        # User avatar as thumbnail
        embed.set_thumbnail(url=user.display_avatar.url)

        embed.set_footer(text="Only one can be the fastest 💨")

        return embed


# ======= Loading bar rendering =======
def render_colored_bar(percent: int, width: int = 24) -> str:
    filled = int(width * percent / 100)
    empty = width - filled

    bar = "█" * filled + "░" * empty

    if percent < 40:
        lang = "diff"
        content = f"- {bar} {percent}%"
    elif percent < 80:
        lang = "fix"
        content = f"{bar} {percent}%"
    else:
        lang = "ini"
        content = f"[{bar} {percent}%]"

    return f"```{lang}\n{content}\n```"


def build_loading_embed(title: str, percent: int) -> discord.Embed:
    embed = discord.Embed(
        title=title,
        description=render_colored_bar(percent),
        color=discord.Color.blurple(),
    )
    return embed


def with_loading(title: str = "Loading...", duration: float = 3.0, steps: int = 25):
    """
    title: Embed title
    duration: Total animation duration in seconds
    steps: Smoothness of the animation
    """

    def decorator(func):
        @wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            delay = duration / steps

            # Initial message
            message = await ctx.send(embed=build_loading_embed(title, 0))

            for step in range(1, steps + 1):
                percent = int(step * 100 / steps)
                await asyncio.sleep(delay)

                try:
                    await message.edit(embed=build_loading_embed(title, percent))
                except discord.NotFound:
                    break

            # Remove loading message
            try:
                await message.delete()
            except discord.NotFound:
                pass

            # Execute real command
            return await func(ctx, *args, **kwargs)

        return wrapper

    return decorator


# ======= Delete button view =======


class DeleteMessageView(discord.ui.View):
    def __init__(
        self, author_id: int, command_message: discord.Message, timeout: int = 120
    ):
        super().__init__(timeout=timeout)
        self.author_id = author_id
        self.command_message = command_message

    @discord.ui.button(label="Delete", style=discord.ButtonStyle.danger)
    async def delete_button(
        self,
        interaction: discord.Interaction,
        button: discord.ui.Button,
    ):
        # Only allow the command author to delete
        if interaction.user.id != self.author_id:
            await interaction.response.send_message(
                "You can't delete this message.",
                ephemeral=True,
            )
            return

        # Delete bot message
        try:
            await interaction.message.delete()
        except discord.NotFound:
            pass

        # Delete command message
        try:
            await self.command_message.delete()
        except discord.NotFound:
            pass


def with_delete_button():
    def decorator(func):
        @wraps(func)
        async def wrapper(ctx, *args, **kwargs):
            original_send = ctx.send

            async def send_with_button(*send_args, **send_kwargs):
                view = DeleteMessageView(
                    author_id=ctx.author.id,
                    command_message=ctx.message,
                )
                send_kwargs["view"] = view
                return await original_send(*send_args, **send_kwargs)

            ctx.send = send_with_button
            return await func(ctx, *args, **kwargs)

        return wrapper

    return decorator


class EmbedTable:
    """
    Render tables in Discord using embeds.

    - Uses embeds (no markdown)
    - Stable layout (max 3 columns per row)
    - Automatically splits large tables
    """

    def __init__(
        self,
        headers: List[str],
        title: str = None,
        description: str = None,
        color: discord.Color = discord.Color.blurple(),
        max_columns: int = 3,
    ):
        self.headers = headers
        self.rows: List[List[str]] = []
        self.title = title
        self.description = description
        self.color = color
        self.max_columns = max_columns

    def add_row(self, row: List[str]) -> None:
        self.rows.append([str(cell) for cell in row])

    def render(self) -> discord.Embed:
        embed = discord.Embed(
            title=self.title,
            description=self.description,
            color=self.color,
        )

        if not self.rows:
            embed.description = (embed.description or "") + "\n\n_No data available._"
            return embed

        # Convert rows → columns
        columns = list(zip(*self.rows))

        start = 0
        total_columns = len(self.headers)

        while start < total_columns:
            end = start + self.max_columns

            for header, column in zip(
                self.headers[start:end],
                columns[start:end],
            ):
                embed.add_field(
                    name=header,
                    value="\n".join(column),
                    inline=True,
                )

            start = end

            if start < total_columns:
                embed.add_field(name="\u200b", value="\u200b", inline=False)

        embed.set_footer(text=f"Rows: {len(self.rows)}")
        return embed


class DiscordChart:
    """
    Utility class to generate Discord-friendly tables using code blocks.
    """

    def __init__(self, headers: List[str]):
        self.headers = headers
        self.rows: List[List[str]] = []

    def add_row(self, row: List[str]) -> None:
        """
        Add a row to the table.

        Args:
            row (List[str]): Row values as strings.
        """
        self.rows.append(row)

    def _column_widths(self) -> List[int]:
        """
        Calculate max width for each column.
        """
        widths = [len(h) for h in self.headers]

        for row in self.rows:
            for i, cell in enumerate(row):
                widths[i] = max(widths[i], len(cell))

        return widths

    def render(self) -> str:
        """
        Render the table as a Discord code block.

        Returns:
            str: Formatted table.
        """
        widths = self._column_widths()

        def format_row(row: List[str]) -> str:
            return " | ".join(cell.ljust(widths[i]) for i, cell in enumerate(row))

        header = format_row(self.headers)
        separator = "-+-".join("-" * w for w in widths)
        body = "\n".join(format_row(r) for r in self.rows)

        table = f"{header}\n{separator}\n{body}"

        return f"```{table}```"


class UserEmojiManager:
    """
    Manages per-user emojis stored in a JSON file.
    """

    def __init__(self, file_path: str = "user_emojis.json"):
        self.file_path = Path(file_path)
        self._data = self._load()

    def _load(self) -> dict:
        if not self.file_path.exists():
            return {}

        try:
            with self.file_path.open("r", encoding="utf-8") as f:
                return json.load(f)
        except json.JSONDecodeError:
            return {}

    def _save(self) -> None:
        with self.file_path.open("w", encoding="utf-8") as f:
            json.dump(self._data, f, indent=2, ensure_ascii=False)

    def set_emoji(self, user_id: int, emoji: str) -> None:
        """
        Assign an emoji to a user.
        """
        self._data[str(user_id)] = emoji
        self._save()

    def get_emoji(self, user_id: int) -> Optional[str]:
        """
        Retrieve the emoji for a user.
        """
        return self._data.get(str(user_id))

    def remove_emoji(self, user_id: int) -> bool:
        """
        Remove the emoji assigned to a user.
        """
        key = str(user_id)
        if key in self._data:
            del self._data[key]
            self._save()
            return True
        return False


class DiscordImageRenderer:
    def __init__(
        self,
        background_color=(255, 255, 255),
        padding=40,
        image_size=(300, 300),
        title_height=50,
    ):

        self.font_path_bold = "arialbd.ttf"
        self.background_color = background_color
        self.padding = padding
        self.image_size = image_size
        self.title_height = title_height

        self.font_bold = ImageFont.truetype("DejaVuSans-Bold.ttf", 22)
        self.font_big = ImageFont.truetype("DejaVuSans-Bold.ttf", 40)

    def _download_image(self, url: str) -> Image.Image:
        response = requests.get(url, timeout=10)
        response.raise_for_status()
        return Image.open(BytesIO(response.content)).convert("RGBA")

    def _draw_text_shadow(self, draw, pos, text, font, fill):
        x, y = pos

        # single soft shadow
        draw.text(
            (x + 2, y + 2),
            text,
            font=font,
            fill=(0, 0, 0, 120),
        )

        draw.text(
            (x, y),
            text,
            font=font,
            fill=fill,
        )

    def _fit_font_to_width(self, draw, text, font_path, max_width, start_size):
        size = start_size

        while size > 12:
            try:
                font = ImageFont.truetype(font_path, size)
            except Exception:
                font = ImageFont.load_default()

            bbox = draw.textbbox((0, 0), text, font=font)
            width = bbox[2] - bbox[0]

            if width <= max_width:
                return font

            size -= 2

        return font

    def render(self, images: list[dict]) -> Image.Image:
        count = len(images)
        if count == 0:
            return Image.new("RGBA", (1, 1), (0, 0, 0, 0))

        MAX_COLS = 5
        cols = min(count, MAX_COLS)
        rows = (count + MAX_COLS - 1) // MAX_COLS

        canvas_width = cols * self.image_size[0] + (cols + 1) * self.padding
        canvas_height = (
            rows * (self.image_size[1] + self.title_height) + (rows + 1) * self.padding
        )

        canvas = Image.new("RGBA", (canvas_width, canvas_height), (0, 0, 0, 0))
        draw = ImageDraw.Draw(canvas)

        for idx, data in enumerate(images):
            meta = data.get("meta", {})

            col = idx % cols
            row = idx // cols

            x = self.padding + col * (self.image_size[0] + self.padding)
            y = self.padding + row * (
                self.image_size[1] + self.title_height + self.padding
            )

            img = self._download_image(data["url"])
            img.thumbnail(self.image_size)

            img_x = x + (self.image_size[0] - img.width) // 2
            img_y = y

            canvas.paste(img, (img_x, img_y), img)

            if meta.get("favorite"):
                emoji = meta["favorite"]
                emoji_url = self._emoji_to_twemoji_url(emoji)

                if emoji_url:
                    try:
                        emoji_img = self._download_image(emoji_url)
                        emoji_img = emoji_img.resize((48, 48), Image.LANCZOS)

                        fx = img_x + img.width - emoji_img.width - 6
                        fy = img_y + 6

                        # Clean dark shadow (no glow, no halo)
                        shadow = emoji_img.copy().convert("RGBA")
                        shadow = shadow.point(lambda p: p * 0.6)  # darken

                        canvas.paste(shadow, (fx + 3, fy + 3), shadow)

                        # Main emoji
                        canvas.paste(emoji_img, (fx, fy), emoji_img)

                    except Exception:
                        pass

            if meta.get("local_id"):
                local_id = meta["local_id"]

                font = self.font_big

                bbox = draw.textbbox((0, 0), local_id, font=font)
                text_w = bbox[2] - bbox[0]
                text_h = bbox[3] - bbox[1]

                lx = img_x + (img.width - text_w) // 2
                ly = img_y + img.height - text_h - 20

                draw.text(
                    (lx, ly),
                    local_id,
                    font=font,
                    fill="white",
                    stroke_width=3,
                    stroke_fill="black",
                )

            banner_y = img_y + self.image_size[1]
            draw.rectangle(
                [
                    x,
                    banner_y,
                    x + self.image_size[0],
                    banner_y + self.title_height,
                ],
                fill="white",
            )

            title = data.get("title", "")
            rarity = meta.get("rarity")

            if rarity:
                title = f"{title}  {rarity}"

            bbox = draw.textbbox((0, 0), title, font=self.font_bold)
            tx = x + (self.image_size[0] - (bbox[2] - bbox[0])) // 2
            ty = banner_y + (self.title_height - (bbox[3] - bbox[1])) // 2

            draw.text((tx, ty), title, font=self.font_bold, fill="black")

        return canvas

    def _emoji_to_twemoji_url(self, emoji: str) -> str | None:
        try:
            codepoints = "-".join(f"{ord(c):x}" for c in emoji)
            return f"https://twemoji.maxcdn.com/v/latest/72x72/{codepoints}.png"
        except Exception:
            return None


# Helper function to parse embed metadata from
# `.v <waifu id>` from waifugami
def _parse_embed_metadata(embed):
    meta = {
        "favorite": None,
        "local_id": None,
        "rarity": None,
    }

    rarities = ["Delta", "Beta", "Gamma", "Alpha", "Omega", "Sigma", "Epsilon", "Zeta"]
    if embed.description:
        for line in embed.description.splitlines():
            if line.startswith("Favorite:"):
                meta["favorite"] = line.replace("Favorite:", "").strip()
            elif line.startswith("Local ID:"):
                meta["local_id"] = line.replace("Local ID:", "").strip()

            elif any(rarity in line for rarity in rarities):
                # Extrae símbolo entre paréntesis
                if "(" in line and ")" in line:
                    meta["rarity"] = line[line.find("(") + 1 : line.find(")")]  # noqa

    return meta
