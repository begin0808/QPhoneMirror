"""QPhoneMirror 專屬下拉選單元件（強制微軟正黑體 + 清晰標準下三角箭頭）。"""

from __future__ import annotations

from typing import Optional

import customtkinter as ctk

from config.themes import FONT_FAMILY


class CleanOptionMenu(ctk.CTkOptionMenu):
    """
    修正 CustomTkinter 原生 CTkOptionMenu 的兩項問題：
    1. 強制預設使用微軟正黑體 (Microsoft JhengHei UI)，避免展開清單回退為新細明體。
    2. 以俐落的標準實心下三角形取代 CustomTkinter_shapes_font 字型箭頭，解決 Windows DPI 縮放下箭頭變形問題。
    """

    def __init__(self, master, arrow_color: Optional[str] = None, **kwargs) -> None:
        kwargs.setdefault("font", (FONT_FAMILY, 12))
        kwargs.setdefault("dropdown_font", (FONT_FAMILY, 12))
        self._custom_arrow_color = arrow_color
        super().__init__(master, **kwargs)
        # 以標準實心下三角形覆寫箭頭繪製函式
        self._draw_engine.draw_dropdown_arrow = self._draw_clean_triangle_arrow
        self._draw(no_color_updates=False)

    def _draw_clean_triangle_arrow(self, x_position: float, y_position: float, size: float) -> bool:
        """在右側按鈕中央繪製清晰對稱的實心下三角形箭頭。"""
        cx = round(x_position)
        cy = round(y_position)
        half_w = max(4.0, size * 0.40)
        half_h = max(2.5, size * 0.24)
        coords = (
            cx - half_w,
            cy - half_h,
            cx + half_w,
            cy - half_h,
            cx,
            cy + half_h,
        )

        # 若先前已建立舊字型箭頭物件，先移除改為標準多邊形
        existing = self._canvas.find_withtag("dropdown_arrow")
        if existing and self._canvas.type(existing[0]) != "polygon":
            self._canvas.delete("dropdown_arrow")
            existing = ()

        requires_recoloring = False
        if not existing:
            self._canvas.create_polygon(*coords, tags="dropdown_arrow", outline="", smooth=False)
            self._canvas.tag_raise("dropdown_arrow")
            requires_recoloring = True
        else:
            self._canvas.coords("dropdown_arrow", *coords)

        return requires_recoloring

    def _draw(self, no_color_updates: bool = False) -> None:
        super()._draw(no_color_updates=no_color_updates)
        if self._custom_arrow_color:
            try:
                self._canvas.itemconfig("dropdown_arrow", fill=self._custom_arrow_color)
            except Exception:
                pass

    def configure(self, require_redraw: bool = False, **kwargs) -> None:
        if "arrow_color" in kwargs:
            self._custom_arrow_color = kwargs.pop("arrow_color")
            require_redraw = True
        super().configure(require_redraw=require_redraw, **kwargs)
