#!/usr/bin/env python3
"""生成 PWA 安装图标（task-mobile-install）：
1024 圆角品牌卡片（#ff385c + 白色「旅」）→ 缩放输出 icon-512.png / icon-192.png。
依赖 Pillow；字体优先 PingFang SC（macOS），回退 Hiragino Sans GB。
用法：python3 frontend/scripts/gen_icons.py <frontend/public 目录>
"""
import sys
import os
from PIL import Image, ImageDraw, ImageFont

DEST = sys.argv[1] if len(sys.argv) > 1 else os.path.join(os.path.dirname(__file__), '..', 'public')

FONT_CANDIDATES = [
    '/System/Library/Fonts/PingFang.ttc',
    '/System/Library/Fonts/Hiragino Sans GB.ttc',
    '/Library/Fonts/Arial Unicode.ttf',
]


def load_font(size):
    for path in FONT_CANDIDATES:
        if os.path.exists(path):
            try:
                return ImageFont.truetype(path, size)
            except Exception:
                continue
    return ImageFont.load_default()


def make_icon(size: int) -> Image.Image:
    img = Image.new('RGBA', (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    radius = int(size * 0.18)
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill='#ff385c')

    # 白色「旅」字，垂直水平居中（用 textbbox 精确居中）
    font = load_font(int(size * 0.52))
    text = '旅'
    bbox = d.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    x = (size - tw) / 2 - bbox[0]
    y = (size - th) / 2 - bbox[1]
    d.text((x, y), text, font=font, fill='#ffffff')
    return img


def main() -> int:
    base = os.path.abspath(DEST)
    if not os.path.isdir(base):
        print(f'目录不存在: {base}', file=sys.stderr)
        return 2
    big = make_icon(1024)
    big.save(os.path.join(base, 'icon-512.png'))
    big.resize((192, 192), Image.Resampling.LANCZOS).save(os.path.join(base, 'icon-192.png'))
    print(f'icons written to {base}: icon-512.png, icon-192.png')
    return 0


if __name__ == '__main__':
    sys.exit(main())