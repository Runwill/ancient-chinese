"""Create the PBOC icon from the original blue startup mark."""

from __future__ import annotations

import argparse
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont


BLUE = (23, 107, 135)
DARK_THEME_BLUE = (85, 169, 197)
WHITE = (255, 255, 255)
FONT_PATH = Path(r'C:\Windows\Fonts\simkai.ttf')
GLYPH = '漢'


def create_icon(size: int, font_path: Path,
                background: tuple[int, int, int] = BLUE) -> Image.Image:
    """Render the original rounded blue tile at an icon-safe resolution."""
    scale = 4
    edge = size * scale
    radius = round(edge * 8 / 54)
    image = Image.new('RGBA', (edge, edge), (*background, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle((0, 0, edge - 1, edge - 1), radius=radius,
                           fill=(*background, 255))

    font = ImageFont.truetype(str(font_path), round(edge * 26 / 54))
    stroke = max(1, round(edge * .012))
    bounds = draw.textbbox((0, 0), GLYPH, font=font, stroke_width=stroke)
    width = bounds[2] - bounds[0]
    height = bounds[3] - bounds[1]
    x = (edge - width) / 2 - bounds[0]
    y = (edge - height) / 2 - bounds[1] - edge * .012
    draw.text((x, y), GLYPH, font=font, fill=WHITE,
              stroke_width=stroke, stroke_fill=WHITE)
    return image.resize((size, size), Image.Resampling.LANCZOS)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument('--font', type=Path, default=FONT_PATH)
    parser.add_argument('--workspace', type=Path,
                        default=Path(__file__).resolve().parent.parent)
    args = parser.parse_args()

    if not args.font.is_file():
        raise FileNotFoundError(f'Font not found: {args.font}')
    workspace = args.workspace.resolve()
    assets = workspace / 'assets'
    web = workspace / 'web'
    android = (workspace / 'android' / 'app' / 'src' / 'main' / 'res'
               / 'drawable-nodpi')
    android_night = (workspace / 'android' / 'app' / 'src' / 'main' / 'res'
                     / 'drawable-night-nodpi')
    for directory in (assets, web, android, android_night):
        directory.mkdir(parents=True, exist_ok=True)

    master = create_icon(1024, args.font)
    master.save(assets / 'icon-blue-source.png', optimize=True)
    master.save(assets / 'app-icon.png', optimize=True)
    master.save(web / 'app-icon.png', optimize=True)
    create_icon(1024, args.font, DARK_THEME_BLUE).save(
        web / 'app-icon-dark.png', optimize=True)
    create_icon(512, args.font).save(android / 'app_icon.png', optimize=True)
    create_icon(512, args.font, DARK_THEME_BLUE).save(
        android_night / 'app_icon.png', optimize=True)

    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [create_icon(size, args.font, DARK_THEME_BLUE) for size in sizes]
    frames[-1].save(
        assets / 'app-icon.ico', format='ICO',
        sizes=[(size, size) for size in sizes],
        append_images=frames[:-1],
    )


if __name__ == '__main__':
    main()
