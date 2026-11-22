"""QPhoneMirror 獨立彈出式執行紀錄視窗管理元件（執行緒安全佇列・不佔主畫面空間）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
from datetime import datetime
import queue
import sys
import tkinter as tk
from typing import Any, Dict, List, Optional

import customtkinter as ctk

from config.themes import CORNER_BTN, CORNER_CARD, FONT_FAMILY


class LogWindowManager:
    """於背景持續記錄執行訊息（經由執行緒安全 Queue 傳遞），使用者點選「檢視執行紀錄」時開啟獨立視窗。"""

    MAX_ENTRIES = 500
    POLL_INTERVAL_MS = 100

    def __init__(self, master: ctk.CTk, theme: Dict[str, Any]) -> None:
        self._master = master
        self._theme = theme
        self._entries: List[str] = [
            f"[{datetime.now().strftime('%H:%M:%S')}] QPhoneMirror 已就緒，請從左側選擇投影功能。"
        ]
        self._queue: queue.Queue[str] = queue.Queue()
        self._poll_job: Optional[str] = None
        self._stopped = False

        self._win: Optional[ctk.CTkToplevel] = None
        self._header_lbl: Optional[ctk.CTkLabel] = None
        self._textbox: Optional[ctk.CTkTextbox] = None
        self._copy_btn: Optional[ctk.CTkButton] = None
        self._clear_btn: Optional[ctk.CTkButton] = None
        self._close_btn: Optional[ctk.CTkButton] = None

        self._schedule_drain()

    def _schedule_drain(self) -> None:
        if self._stopped:
            return
        try:
            self._poll_job = self._master.after(self.POLL_INTERVAL_MS, self._drain_queue)
        except Exception:
            self._poll_job = None

    def _drain_queue(self) -> None:
        self._poll_job = None
        if self._stopped:
            return

        batch: List[str] = []
        while True:
            try:
                batch.append(self._queue.get_nowait())
            except queue.Empty:
                break

        if batch:
            self._entries.extend(batch)
            if len(self._entries) > self.MAX_ENTRIES:
                self._entries = self._entries[-self.MAX_ENTRIES :]

            if self._is_open() and self._textbox is not None:
                try:
                    self._textbox.configure(state="normal")
                    self._textbox.insert("end", "\n".join(batch) + "\n")
                    # 同步修剪文字方塊超過 MAX_ENTRIES 的舊行，避免長時間執行記憶體成長
                    line_count = int(self._textbox.index("end-1c").split(".")[0])
                    if line_count > self.MAX_ENTRIES:
                        over = line_count - self.MAX_ENTRIES
                        self._textbox.delete("1.0", f"{over + 1}.0")
                    self._textbox.see("end")
                    self._textbox.configure(state="disabled")
                except Exception:
                    pass

        self._schedule_drain()

    def append(self, message: str) -> None:
        """從任何背景執行緒安全地新增一筆帶時間戳記的執行紀錄（絕不直接呼叫 Tk API 造成死鎖）。"""
        now = datetime.now().strftime("%H:%M:%S")
        line = f"[{now}] {message}"
        try:
            self._queue.put_nowait(line)
        except Exception:
            pass

    def show(self) -> None:
        """開啟或將執行紀錄獨立視窗帶到最前景。"""
        # 先把佇列中待處理訊息刷入 _entries
        self._drain_queue()
        if self._is_open() and self._win is not None:
            self._win.deiconify()
            self._win.lift()
            self._win.focus_force()
            return

        win = ctk.CTkToplevel(self._master)
        win.title("QPhoneMirror - 執行紀錄")
        win.geometry("640x400")
        win.minsize(480, 300)
        win.transient(self._master)
        self._win = win

        top_row = ctk.CTkFrame(win, fg_color="transparent")
        top_row.pack(fill="x", padx=14, pady=(12, 8))

        self._header_lbl = ctk.CTkLabel(
            top_row,
            text="執行紀錄（供檢視連線狀態與錯誤排查）",
            font=(FONT_FAMILY, 14, "bold"),
            anchor="w",
        )
        self._header_lbl.pack(side="left", fill="x", expand=True)

        self._copy_btn = ctk.CTkButton(
            top_row,
            text="複製全部",
            width=82,
            height=28,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._copy_all,
        )
        self._copy_btn.pack(side="right", padx=(6, 0))

        self._clear_btn = ctk.CTkButton(
            top_row,
            text="清空",
            width=62,
            height=28,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=self.clear,
        )
        self._clear_btn.pack(side="right", padx=(6, 0))

        self._textbox = ctk.CTkTextbox(
            win,
            corner_radius=CORNER_CARD,
            font=(FONT_FAMILY, 12),
            wrap="word",
            border_width=2,
        )
        self._textbox.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self._textbox.insert("1.0", "\n".join(self._entries) + ("\n" if self._entries else ""))
        self._textbox.see("end")
        self._textbox.configure(state="disabled")

        bottom_row = ctk.CTkFrame(win, fg_color="transparent")
        bottom_row.pack(fill="x", padx=14, pady=(0, 12))

        self._close_btn = ctk.CTkButton(
            bottom_row,
            text="關閉視窗",
            width=96,
            height=30,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self.close,
        )
        self._close_btn.pack(side="right")

        win.protocol("WM_DELETE_WINDOW", self.close)
        self.apply_theme(self._theme)
        win.update_idletasks()
        scale = max(1.0, float(win._get_window_scaling()))
        phys_w = max(win.winfo_width(), int(640 * scale))
        phys_h = max(win.winfo_height(), int(400 * scale))
        wa_left, wa_top, wa_right, wa_bottom = 0, 0, int(win.winfo_screenwidth() * scale), int(win.winfo_screenheight() * scale)
        if sys.platform == "win32":
            try:
                rect = wintypes.RECT()
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    wa_left, wa_top, wa_right, wa_bottom = rect.left, rect.top, rect.right, rect.bottom
                else:
                    wa_right = ctypes.windll.user32.GetSystemMetrics(0)
                    wa_bottom = ctypes.windll.user32.GetSystemMetrics(1)
            except Exception:
                pass
        titlebar_h = int(32 * scale)
        x = wa_left + max(0, (wa_right - wa_left - phys_w) // 2)
        y = wa_top + max(0, (wa_bottom - wa_top - phys_h - titlebar_h) // 2)
        tk.Toplevel.geometry(win, f"+{x}+{y}")
        win.lift()
        win.focus_force()

    def clear(self) -> None:
        self._entries.clear()
        if self._is_open() and self._textbox is not None:
            self._textbox.configure(state="normal")
            self._textbox.delete("1.0", "end")
            self._textbox.configure(state="disabled")

    def _copy_all(self) -> None:
        self._drain_queue()
        content = "\n".join(self._entries)
        if content:
            try:
                self._master.clipboard_clear()
                self._master.clipboard_append(content)
            except Exception:
                pass

    def shutdown(self) -> None:
        """關閉主視窗前取消背景佇列輪詢並關閉紀錄視窗。"""
        self._stopped = True
        if self._poll_job:
            try:
                self._master.after_cancel(self._poll_job)
            except Exception:
                pass
            self._poll_job = None
        self.close()

    def close(self) -> None:
        if self._is_open() and self._win is not None:
            try:
                self._win.destroy()
            except Exception:
                pass
        self._win = None
        self._header_lbl = None
        self._textbox = None
        self._copy_btn = None
        self._clear_btn = None
        self._close_btn = None

    def _is_open(self) -> bool:
        try:
            return self._win is not None and bool(self._win.winfo_exists())
        except Exception:
            return False

    def apply_theme(self, theme: Dict[str, Any]) -> None:
        self._theme = theme
        if not self._is_open() or self._win is None:
            return
        self._win.configure(fg_color=theme["bg_main"])
        if self._header_lbl:
            self._header_lbl.configure(text_color=theme["text_primary"])
        if self._textbox:
            self._textbox.configure(
                fg_color=theme["bg_log"],
                text_color=theme["text_primary"],
                border_color=theme["border"],
                scrollbar_button_color=theme["border"],
                scrollbar_button_hover_color=theme["accent_primary"],
            )
        if self._copy_btn:
            self._copy_btn.configure(
                fg_color=theme["accent_primary"],
                hover_color=theme["accent_primary_hover"],
                text_color=theme["text_on_accent"],
            )
        if self._clear_btn:
            self._clear_btn.configure(
                fg_color=theme["bg_badge"],
                hover_color=theme["nav_active"],
                text_color=theme["text_primary"],
            )
        if self._close_btn:
            self._close_btn.configure(
                fg_color=theme["bg_badge"],
                hover_color=theme["nav_active"],
                text_color=theme["text_primary"],
            )
