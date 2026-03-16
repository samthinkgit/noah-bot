import subprocess
import tempfile
import urllib.request
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

JARVIS_VIDEO_URL = (
    "https://images-ext-1.discordapp.net/external/"
    "89NV-iHnU4z7bEWPFyqeyxMKJFvyNJVNNtI5N2e3iHE/https/"
    "media.tenor.com/EBjMTsLCenwAAAPo/jarvis-erase.mp4"
)

_FONT_CANDIDATES = (
    Path("C:/Windows/Fonts/arialbd.ttf"),
    Path("C:/Windows/Fonts/arial.ttf"),
    Path("C:/Windows/Fonts/calibri.ttf"),
)


def _find_font_path() -> str | None:
    for candidate in _FONT_CANDIDATES:
        if candidate.exists():
            return str(candidate)
    return None


def _measure_text(draw: ImageDraw.ImageDraw, text: str, font: ImageFont.ImageFont) -> int:
    left, _top, right, _bottom = draw.textbbox((0, 0), text, font=font)
    return right - left


def _split_long_word(
    draw: ImageDraw.ImageDraw,
    word: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    pieces: list[str] = []
    current = ""

    for char in word:
        candidate = f"{current}{char}"
        if current and _measure_text(draw, candidate, font) > max_width:
            pieces.append(current)
            current = char
            continue
        current = candidate

    if current:
        pieces.append(current)

    return pieces


def _wrap_text(
    draw: ImageDraw.ImageDraw,
    text: str,
    font: ImageFont.ImageFont,
    max_width: int,
) -> list[str]:
    lines: list[str] = []
    current = ""

    for raw_word in text.split():
        words = [raw_word]
        if _measure_text(draw, raw_word, font) > max_width:
            words = _split_long_word(draw, raw_word, font, max_width)

        for word in words:
            candidate = word if not current else f"{current} {word}"
            if current and _measure_text(draw, candidate, font) > max_width:
                lines.append(current)
                current = word
                continue
            current = candidate

    if current:
        lines.append(current)

    return lines or [text]


def _load_font(size: int) -> ImageFont.ImageFont:
    font_path = _find_font_path()
    if not font_path:
        return ImageFont.load_default()
    return ImageFont.truetype(font_path, size=size)


def _render_banner(text: str, width: int) -> Image.Image:
    scratch = Image.new("RGB", (width, 100), "white")
    draw = ImageDraw.Draw(scratch)
    horizontal_padding = 22
    vertical_padding = 18
    line_spacing = 8
    max_width = width - (horizontal_padding * 2)
    max_lines = 4

    chosen_font = _load_font(18)
    chosen_lines = _wrap_text(draw, text, chosen_font, max_width)

    for font_size in range(34, 17, -2):
        font = _load_font(font_size)
        lines = _wrap_text(draw, text, font, max_width)
        if len(lines) <= max_lines:
            chosen_font = font
            chosen_lines = lines
            break

    sample_box = draw.textbbox((0, 0), "Ay", font=chosen_font)
    line_height = sample_box[3] - sample_box[1]
    banner_height = (
        vertical_padding * 2
        + (line_height * len(chosen_lines))
        + (line_spacing * max(0, len(chosen_lines) - 1))
    )

    banner = Image.new("RGB", (width, banner_height), "white")
    draw = ImageDraw.Draw(banner)
    current_y = vertical_padding

    for line in chosen_lines:
        text_width = _measure_text(draw, line, chosen_font)
        text_x = max(horizontal_padding, (width - text_width) // 2)
        draw.text((text_x, current_y), line, fill="black", font=chosen_font)
        current_y += line_height + line_spacing

    return banner


def _download_video(target_path: Path) -> None:
    request = urllib.request.Request(
        JARVIS_VIDEO_URL,
        headers={
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/136.0.0.0 Safari/537.36"
            ),
            "Referer": "https://tenor.com/",
        },
    )
    with urllib.request.urlopen(request) as response:
        target_path.write_bytes(response.read())


def _probe_video_size(video_path: Path) -> tuple[int, int]:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-select_streams",
            "v:0",
            "-show_entries",
            "stream=width,height",
            "-of",
            "csv=p=0:s=x",
            str(video_path),
        ],
        capture_output=True,
        check=True,
        text=True,
    )
    width_text, height_text = result.stdout.strip().split("x")
    return int(width_text), int(height_text)


def create_jarvis_gif(message: str) -> bytes:
    text = f"Jarvis, {message.strip()}"

    with tempfile.TemporaryDirectory() as temp_dir:
        temp_path = Path(temp_dir)
        input_video_path = temp_path / "jarvis_source.mp4"
        banner_path = temp_path / "jarvis_banner.png"
        stacked_video_path = temp_path / "jarvis_stacked.mp4"
        palette_path = temp_path / "jarvis_palette.png"
        output_gif_path = temp_path / "jarvis_captioned.gif"

        _download_video(input_video_path)
        width, _height = _probe_video_size(input_video_path)

        banner = _render_banner(text=text, width=width)
        banner.save(banner_path)

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(banner_path),
                "-i",
                str(input_video_path),
                "-filter_complex",
                "[0:v][1:v]vstack=inputs=2[v]",
                "-map",
                "[v]",
                "-an",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-movflags",
                "+faststart",
                str(stacked_video_path),
            ],
            capture_output=True,
            check=True,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(stacked_video_path),
                "-vf",
                "fps=15,scale=498:-1:flags=lanczos,palettegen",
                str(palette_path),
            ],
            capture_output=True,
            check=True,
        )

        subprocess.run(
            [
                "ffmpeg",
                "-y",
                "-i",
                str(stacked_video_path),
                "-i",
                str(palette_path),
                "-lavfi",
                "fps=15,scale=498:-1:flags=lanczos[x];[x][1:v]paletteuse",
                "-loop",
                "0",
                str(output_gif_path),
            ],
            capture_output=True,
            check=True,
        )

        return output_gif_path.read_bytes()
