"""QPhoneMirror 側邊選單專屬彩色圖示產生器（使用 Pillow 高解析反鋸齒繪製）。"""

from __future__ import annotations

from typing import Dict

import customtkinter as ctk
from PIL import Image, ImageDraw


def _render_super(size: int, draw_fn) -> Image.Image:
    """以 4 倍超採樣繪製並以 LANCZOS 縮放，確保彩色圖示邊緣圓滑細緻。"""
    scale = 4
    canvas_size = size * scale
    img = Image.new("RGBA", (canvas_size, canvas_size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    draw_fn(draw, canvas_size)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def _draw_android(draw: ImageDraw.ImageDraw, s: int) -> None:
    """可愛薄荷綠彩色 Android 機器人頭像。"""
    green = "#49C58B"
    dark_green = "#35A872"
    w_line = max(3, int(s * 0.07))

    draw.line([(s * 0.32, s * 0.28), (s * 0.20, s * 0.12)], fill=green, width=w_line)
    draw.line([(s * 0.68, s * 0.28), (s * 0.80, s * 0.12)], fill=green, width=w_line)
    r_tip = s * 0.045
    draw.ellipse([s * 0.20 - r_tip, s * 0.12 - r_tip, s * 0.20 + r_tip, s * 0.12 + r_tip], fill=green)
    draw.ellipse([s * 0.80 - r_tip, s * 0.12 - r_tip, s * 0.80 + r_tip, s * 0.12 + r_tip], fill=green)

    draw.pieslice([s * 0.12, s * 0.22, s * 0.88, s * 0.94], start=180, end=360, fill=green)
    draw.rounded_rectangle([s * 0.12, s * 0.54, s * 0.88, s * 0.86], radius=int(s * 0.14), fill=green)
    draw.rounded_rectangle([s * 0.18, s * 0.77, s * 0.82, s * 0.86], radius=int(s * 0.06), fill=dark_green)

    eye_r = s * 0.065
    draw.ellipse([s * 0.34 - eye_r, s * 0.48 - eye_r, s * 0.34 + eye_r, s * 0.48 + eye_r], fill="#FFFFFF")
    draw.ellipse([s * 0.66 - eye_r, s * 0.48 - eye_r, s * 0.66 + eye_r, s * 0.48 + eye_r], fill="#FFFFFF")

    blush_r = s * 0.045
    draw.ellipse([s * 0.24 - blush_r, s * 0.60 - blush_r, s * 0.24 + blush_r, s * 0.60 + blush_r], fill="#FF9EB5")
    draw.ellipse([s * 0.76 - blush_r, s * 0.60 - blush_r, s * 0.76 + blush_r, s * 0.60 + blush_r], fill="#FF9EB5")


def _draw_apple(draw: ImageDraw.ImageDraw, s: int) -> None:
    """可愛珊瑚粉紅彩色蘋果圖示（含嫩綠小葉子與白色高光）。"""
    coral = "#FF6F8B"
    coral_deep = "#EE5776"
    leaf = "#56C596"
    stem = "#8D6E63"

    draw.line([(s * 0.50, s * 0.30), (s * 0.50, s * 0.16)], fill=stem, width=max(3, int(s * 0.06)))
    draw.pieslice([s * 0.48, s * 0.08, s * 0.80, s * 0.34], start=180, end=330, fill=leaf)
    draw.ellipse([s * 0.52, s * 0.11, s * 0.74, s * 0.25], fill=leaf)

    draw.ellipse([s * 0.14, s * 0.26, s * 0.62, s * 0.90], fill=coral)
    draw.ellipse([s * 0.38, s * 0.26, s * 0.86, s * 0.90], fill=coral)
    draw.ellipse([s * 0.24, s * 0.48, s * 0.76, s * 0.92], fill=coral)
    draw.arc([s * 0.18, s * 0.40, s * 0.82, s * 0.90], start=25, end=155, fill=coral_deep, width=max(2, int(s * 0.05)))

    draw.ellipse([s * 0.25, s * 0.38, s * 0.36, s * 0.54], fill="#FFD6E0")


def _draw_recorder(draw: ImageDraw.ImageDraw, s: int) -> None:
    """可愛薰衣草紫＋暖橘錄影指示燈彩色攝影機圖示。"""
    body = "#9B7EDE"
    body_deep = "#7E60C4"
    lens_outer = "#FFFFFF"
    lens_inner = "#5DA9F6"
    rec_dot = "#FF6B81"

    # 右側攝影機鏡頭錐體
    draw.polygon(
        [
            (s * 0.66, s * 0.40),
            (s * 0.92, s * 0.26),
            (s * 0.92, s * 0.74),
            (s * 0.66, s * 0.60),
        ],
        fill=body_deep,
    )
    # 圓角主機身
    draw.rounded_rectangle([s * 0.08, s * 0.22, s * 0.72, s * 0.78], radius=int(s * 0.16), fill=body)
    # 可愛大鏡頭圈與水藍鏡片
    draw.ellipse([s * 0.22, s * 0.34, s * 0.54, s * 0.66], fill=lens_outer)
    draw.ellipse([s * 0.28, s * 0.40, s * 0.48, s * 0.60], fill=lens_inner)
    # 鏡片小反光
    draw.ellipse([s * 0.32, s * 0.43, s * 0.38, s * 0.49], fill="#FFFFFF")
    # 右上角珊瑚紅錄影燈
    draw.ellipse([s * 0.54, s * 0.29, s * 0.64, s * 0.39], fill=rec_dot)


def _draw_guide(draw: ImageDraw.ImageDraw, s: int) -> None:
    """可愛天藍封面＋奶油黃展開書本圖示。"""
    blue = "#5DA9F6"
    blue_dark = "#408CE0"
    page_l = "#FFF8E7"
    page_r = "#FFFDF6"
    line_c = "#A9C8EB"

    draw.rounded_rectangle([s * 0.08, s * 0.20, s * 0.92, s * 0.86], radius=int(s * 0.10), fill=blue)
    draw.rectangle([s * 0.47, s * 0.20, s * 0.53, s * 0.86], fill=blue_dark)

    draw.rounded_rectangle([s * 0.14, s * 0.16, s * 0.48, s * 0.78], radius=int(s * 0.08), fill=page_l)
    draw.rounded_rectangle([s * 0.52, s * 0.16, s * 0.86, s * 0.78], radius=int(s * 0.08), fill=page_r)

    lw = max(2, int(s * 0.045))
    for y_ratio in (0.34, 0.48, 0.62):
        y = s * y_ratio
        draw.line([(s * 0.20, y), (s * 0.42, y)], fill=line_c, width=lw)
        draw.line([(s * 0.58, y), (s * 0.80, y)], fill=line_c, width=lw)

    draw.polygon(
        [(s * 0.66, s * 0.16), (s * 0.76, s * 0.16), (s * 0.76, s * 0.34), (s * 0.71, s * 0.28), (s * 0.66, s * 0.34)],
        fill="#FF8BA7",
    )


def _render_facebook_circle(size: int) -> Image.Image:
    """以 4 倍超採樣繪製經典藍底白字圓形 Facebook 'f' 圖示。"""
    scale = 4
    s = size * scale
    img = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    fb_blue = "#1877F2"
    pad = s * 0.04
    draw.ellipse([pad, pad, s - pad, s - pad], fill=fb_blue)

    # 在內部繪製俐落對稱的白色 'f' 幾何字形
    f_layer = Image.new("RGBA", (s, s), (0, 0, 0, 0))
    fd = ImageDraw.Draw(f_layer)
    # 頂部向右彎鉤（外圓 + 內藍挖空）
    fd.ellipse([s * 0.43, s * 0.18, s * 0.75, s * 0.50], fill="#FFFFFF")
    fd.rectangle([s * 0.58, s * 0.18, s * 0.74, s * 0.31], fill="#FFFFFF")
    fd.ellipse([s * 0.57, s * 0.31, s * 0.77, s * 0.51], fill=fb_blue)
    fd.rectangle([s * 0.57, s * 0.38, s * 0.80, s * 0.52], fill=fb_blue)
    # 主幹（向下延伸至圓形底緣）
    fd.rectangle([s * 0.43, s * 0.33, s * 0.57, s * 0.98], fill="#FFFFFF")
    # 橫槓（右側微斜切，還原經典 Facebook 'f' 比例）
    fd.polygon(
        [
            (s * 0.31, s * 0.48),
            (s * 0.72, s * 0.48),
            (s * 0.69, s * 0.60),
            (s * 0.31, s * 0.60),
        ],
        fill="#FFFFFF",
    )

    # 以圓形遮罩裁切底部，確保 'f' 底部完美貼齊藍色圓邊
    mask = Image.new("L", (s, s), 0)
    ImageDraw.Draw(mask).ellipse([pad, pad, s - pad, s - pad], fill=255)
    img.paste(f_layer, (0, 0), mask)
    return img.resize((size, size), Image.Resampling.LANCZOS)


def create_facebook_icon(size: int = 16) -> ctk.CTkImage:
    """建立側邊欄版權宣告旁的圓形藍色 Facebook 圖示。"""
    pil_img = _render_facebook_circle(size)
    return ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(size, size))


def create_menu_icons() -> Dict[str, ctk.CTkImage]:
    """建立側邊選單專用的 4 個全彩圖示。"""
    specs = {
        "android": (22, _draw_android),
        "ios": (22, _draw_apple),
        "recorder": (22, _draw_recorder),
        "guide": (22, _draw_guide),
    }
    icons: Dict[str, ctk.CTkImage] = {}
    for key, (sz, fn) in specs.items():
        pil_img = _render_super(sz, fn)
        icons[key] = ctk.CTkImage(light_image=pil_img, dark_image=pil_img, size=(sz, sz))
    return icons
