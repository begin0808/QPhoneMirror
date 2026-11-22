"""QPhoneMirror 高畫質電腦螢幕錄影分頁（全螢幕 / 單選程式視窗 / 自訂框選 + 系統音內錄 + 麥克風 + 自訂儲存路徑）。"""

from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
import tkinter as tk
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

from config.settings import (
    SettingsManager,
    format_captures_dir_for_storage,
    get_captures_dir,
    is_dir_writable,
    resolve_captures_dir,
)
from config.themes import CORNER_BADGE, CORNER_BTN, CORNER_CARD, CORNER_INPUT, FONT_FAMILY
from core.binary_manager import BinaryManager
from core.screen_recorder import ScreenRecordOptions, ScreenRecorderEngine, normalize_even_region
from core.window_finder import (
    WindowInfo,
    focus_and_get_window_rect,
    get_primary_monitor_bounds,
    get_virtual_screen_bounds,
    is_window_alive_and_minimized,
    list_open_windows,
)
from ui.components.clean_option_menu import CleanOptionMenu

MODE_LABEL_TO_KEY = {
    "全螢幕錄製": "fullscreen",
    "指定程式視窗錄製": "window",
    "自訂框選區域錄製": "region",
}
MODE_KEY_TO_LABEL = {v: k for k, v in MODE_LABEL_TO_KEY.items()}

QUALITY_LABEL_TO_KEY = {
    "極致高畫質（檔案較大）": "high",
    "標準高清畫質（推薦）": "standard",
    "輕量小檔畫質（適合分享）": "compact",
}
QUALITY_KEY_TO_LABEL = {v: k for k, v in QUALITY_LABEL_TO_KEY.items()}


class RegionSelectorOverlay(tk.Toplevel):
    """全螢幕半透明十字游標框選器：讓使用者直接拖曳滑鼠選定錄影區域。"""

    def __init__(
        self,
        master: tk.Misc,
        on_selected: Callable[[Tuple[int, int, int, int]], None],
        on_cancel: Optional[Callable[[], None]] = None,
    ) -> None:
        super().__init__(master)
        self._on_selected = on_selected
        self._on_cancel = on_cancel
        self._start_x = 0
        self._start_y = 0
        self._rect_id: Optional[int] = None
        self._label_id: Optional[int] = None

        vx, vy, vw, vh = get_virtual_screen_bounds()
        _, _, pw, _ = get_primary_monitor_bounds()
        self._vx = vx
        self._vy = vy

        self.overrideredirect(True)
        self.attributes("-topmost", True)
        self.attributes("-alpha", 0.35)
        # Tk geometry 語法規定負絕對座標必須寫成 +-1920（寫成 -1920 會被解讀為靠右邊距）
        self.geometry(f"{vw}x{vh}+{vx}+{vy}")
        self.configure(bg="#1B2038", cursor="crosshair")

        self._canvas = tk.Canvas(
            self,
            bg="#1B2038",
            highlightthickness=0,
            cursor="crosshair",
        )
        self._canvas.pack(fill="both", expand=True)

        self._canvas.create_text(
            (-vx) + pw // 2,
            (-vy) + 48,
            text="請按住滑鼠左鍵拖曳框選錄影範圍（支援多螢幕），放開即完成選定（按 Esc 取消）",
            fill="#FFFFFF",
            font=(FONT_FAMILY, 16, "bold"),
        )

        self._canvas.bind("<ButtonPress-1>", self._on_press)
        self._canvas.bind("<B1-Motion>", self._on_drag)
        self._canvas.bind("<ButtonRelease-1>", self._on_release)
        self.bind("<Escape>", self._cancel)
        self.focus_force()

    def _on_press(self, event: tk.Event) -> None:
        self._start_x = int(event.x_root)
        self._start_y = int(event.y_root)
        cx = self._start_x - self._vx
        cy = self._start_y - self._vy
        if self._rect_id:
            self._canvas.delete(self._rect_id)
        if self._label_id:
            self._canvas.delete(self._label_id)
        self._rect_id = self._canvas.create_rectangle(
            cx,
            cy,
            cx,
            cy,
            outline="#56C596",
            width=3,
            fill="#8BD3DD",
            stipple="gray25",
        )
        self._label_id = self._canvas.create_text(
            cx + 8,
            max(20, cy - 16),
            text="0 x 0",
            fill="#FFFFFF",
            anchor="w",
            font=(FONT_FAMILY, 13, "bold"),
        )

    def _on_drag(self, event: tk.Event) -> None:
        cur_x, cur_y = int(event.x_root), int(event.y_root)
        x1, x2 = min(self._start_x, cur_x), max(self._start_x, cur_x)
        y1, y2 = min(self._start_y, cur_y), max(self._start_y, cur_y)
        cx1, cy1 = x1 - self._vx, y1 - self._vy
        cx2, cy2 = x2 - self._vx, y2 - self._vy
        if self._rect_id:
            self._canvas.coords(self._rect_id, cx1, cy1, cx2, cy2)
        if self._label_id:
            self._canvas.coords(self._label_id, cx1 + 6, max(24, cy1 - 16))
            self._canvas.itemconfigure(self._label_id, text=f"{x2 - x1} x {y2 - y1}")

    def _on_release(self, event: tk.Event) -> None:
        cur_x, cur_y = int(event.x_root), int(event.y_root)
        x1, x2 = min(self._start_x, cur_x), max(self._start_x, cur_x)
        y1, y2 = min(self._start_y, cur_y), max(self._start_y, cur_y)
        w, h = x2 - x1, y2 - y1
        self.destroy()
        if w >= 64 and h >= 64:
            self._on_selected(normalize_even_region((x1, y1, w, h)))
        elif self._on_cancel:
            self._on_cancel()

    def _cancel(self, _event: tk.Event | None = None) -> None:
        self.destroy()
        if self._on_cancel:
            self._on_cancel()


class RecorderTab(ctk.CTkScrollableFrame):
    """高畫質電腦螢幕錄影分頁（支援全螢幕、單選程式視窗、框選區域、系統聲音內錄、麥克風與自訂存檔目錄）。"""

    def __init__(
        self,
        master,
        theme: Dict[str, Any],
        settings: SettingsManager,
        binary_manager: BinaryManager,
        recorder_engine: ScreenRecorderEngine,
        log_cb: Callable[[str], None],
        on_core_updated: Callable[[], None],
        on_minimize_app: Callable[[], None],
        on_restore_app: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, corner_radius=0, **kwargs)
        self._theme = theme
        self.settings = settings
        self.binary_manager = binary_manager
        self.engine = recorder_engine
        self.log_cb = log_cb
        self.on_core_updated = on_core_updated
        self.on_minimize_app = on_minimize_app
        self.on_restore_app = on_restore_app

        self._downloading = False
        self._timer_job: Optional[str] = None
        self._record_start_ts: float = 0.0
        self._active_target_hwnd: int = 0
        self._window_map: Dict[str, WindowInfo] = {}

        saved_reg = self.settings.get("recorder_region", [100, 100, 1280, 720])
        if isinstance(saved_reg, (list, tuple)) and len(saved_reg) == 4:
            self._region: Tuple[int, int, int, int] = normalize_even_region(
                (int(saved_reg[0]), int(saved_reg[1]), int(saved_reg[2]), int(saved_reg[3]))
            )
        else:
            self._region = (100, 100, 1280, 720)

        self._build_ui()
        self.apply_theme(theme)
        self.refresh_core_banner()
        self._update_mode_controls()

        # 不必等 FFmpeg，啟動即可透過 Windows WASAPI 即時偵測耳機麥克風與運作中程式
        self.after(250, self.refresh_microphones)
        self.after(350, self.refresh_windows)

    def _build_ui(self) -> None:
        self.title_lbl = ctk.CTkLabel(
            self,
            text="電腦螢幕錄影",
            font=(FONT_FAMILY, 19, "bold"),
            anchor="w",
        )
        self.title_lbl.pack(fill="x", padx=12, pady=(0, 1))

        self.subtitle_lbl = ctk.CTkLabel(
            self,
            text="高畫質錄製整個電腦螢幕、指定程式視窗或自訂區域，支援系統聲音內錄與耳機麥克風收音。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=730,
            justify="left",
        )
        self.subtitle_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # ── 卡片 0：首次使用 FFmpeg 核心自動下載卡 ──
        self.core_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)

        core_main_row = ctk.CTkFrame(self.core_card, fg_color="transparent")
        core_main_row.pack(fill="x", padx=14, pady=8)

        core_text_col = ctk.CTkFrame(core_main_row, fg_color="transparent")
        core_text_col.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.core_title = ctk.CTkLabel(
            core_text_col,
            text="首次使用：尚未安裝電腦螢幕錄影核心（FFmpeg）",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.core_title.pack(fill="x")

        self.core_desc = ctk.CTkLabel(
            core_text_col,
            text="按下右側按鈕，將自動從官方開源發布庫下載並僅提取 ffmpeg.exe 至 bin/ffmpeg 資料夾。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=520,
            justify="left",
        )
        self.core_desc.pack(fill="x", pady=(2, 0))

        self.download_btn = ctk.CTkButton(
            core_main_row,
            text="一鍵下載並安裝核心",
            width=152,
            height=34,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._start_download_ffmpeg,
        )
        self.download_btn.pack(side="right")

        self.download_status_lbl = ctk.CTkLabel(
            self.core_card,
            text="",
            font=(FONT_FAMILY, 12),
            anchor="w",
        )
        self.download_bar = ctk.CTkProgressBar(self.core_card, height=8, corner_radius=8)
        self.download_bar.set(0)

        # ── 卡片 1：步驟 1：選擇錄影範圍與聲音來源 ──
        self.scope_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.scope_card.pack(fill="x", padx=12, pady=(0, 8))

        self.scope_header = ctk.CTkLabel(
            self.scope_card,
            text="步驟 1：選擇錄影範圍與聲音收錄",
            font=(FONT_FAMILY, 14, "bold"),
            anchor="w",
        )
        self.scope_header.pack(fill="x", padx=14, pady=(8, 6))

        self.status_bubble = ctk.CTkFrame(self.scope_card, corner_radius=CORNER_BADGE)
        self.status_bubble.pack(fill="x", padx=14, pady=(0, 8))

        self.status_lbl = ctk.CTkLabel(
            self.status_bubble,
            text="準備就緒！選擇全螢幕、指定程式視窗或滑鼠框選區域，按下「開始電腦螢幕錄影」即可錄製。",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
            wraplength=700,
            justify="left",
        )
        self.status_lbl.pack(fill="x", padx=10, pady=6)

        # 錄影範圍模式列
        mode_row = ctk.CTkFrame(self.scope_card, fg_color="transparent")
        mode_row.pack(fill="x", padx=14, pady=(0, 6))

        self.mode_lbl = ctk.CTkLabel(mode_row, text="錄影範圍：", font=(FONT_FAMILY, 12, "bold"))
        self.mode_lbl.pack(side="left", padx=(0, 6))

        saved_mode = MODE_KEY_TO_LABEL.get(self.settings.get("recorder_mode", "fullscreen"), "全螢幕錄製")
        self.mode_var = ctk.StringVar(value=saved_mode)
        self.mode_menu = CleanOptionMenu(
            mode_row,
            variable=self.mode_var,
            values=list(MODE_LABEL_TO_KEY.keys()),
            width=176,
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=self._on_mode_changed,
        )
        self.mode_menu.pack(side="left", padx=(0, 8))

        self.select_region_btn = ctk.CTkButton(
            mode_row,
            text="滑鼠框選錄影區域",
            width=132,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._open_region_selector,
        )
        self.select_region_btn.pack(side="left", padx=(0, 8))

        self.region_info_lbl = ctk.CTkLabel(
            mode_row,
            text=self._format_region_text(),
            font=(FONT_FAMILY, 12),
            anchor="w",
        )
        self.region_info_lbl.pack(side="left", fill="x", expand=True)

        # 指定程式視窗選擇列（選「指定程式視窗錄製」時展開）
        self.window_row = ctk.CTkFrame(self.scope_card, fg_color="transparent")

        self.window_lbl = ctk.CTkLabel(self.window_row, text="目標程式：", font=(FONT_FAMILY, 12, "bold"))
        self.window_lbl.pack(side="left", padx=(0, 6))

        self.window_var = ctk.StringVar(value="（請點選重新掃描程式）")
        self.window_menu = CleanOptionMenu(
            self.window_row,
            variable=self.window_var,
            values=["（請點選重新掃描程式）"],
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
        )
        self.window_menu.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.refresh_win_btn = ctk.CTkButton(
            self.window_row,
            text="重新掃描程式",
            width=114,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self.refresh_windows,
        )
        self.refresh_win_btn.pack(side="left")

        # 電腦系統聲音內錄列（預設關閉）
        self.sys_audio_row = ctk.CTkFrame(self.scope_card, fg_color="transparent")
        self.sys_audio_row.pack(fill="x", padx=14, pady=(2, 4))

        self.sw_sys_audio = ctk.CTkSwitch(
            self.sys_audio_row,
            text="錄製電腦系統聲音（可錄線上會議對方講話與電腦播放音效，預設關閉）",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("recorder_system_audio", False):
            self.sw_sys_audio.select()
        self.sw_sys_audio.pack(side="left")

        # 麥克風旁白列
        mic_row = ctk.CTkFrame(self.scope_card, fg_color="transparent")
        mic_row.pack(fill="x", padx=14, pady=(2, 10))

        self.sw_mic = ctk.CTkSwitch(
            mic_row,
            text="錄製麥克風旁白",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("recorder_mic_enabled", False):
            self.sw_mic.select()
        self.sw_mic.pack(side="left", padx=(0, 10))

        saved_mic = self.settings.get("recorder_mic_device", "") or "（尚未偵測麥克風）"
        self.mic_var = ctk.StringVar(value=saved_mic)
        self.mic_menu = CleanOptionMenu(
            mic_row,
            variable=self.mic_var,
            values=[saved_mic],
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=lambda _: self._save_options(),
        )
        self.mic_menu.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.refresh_mic_btn = ctk.CTkButton(
            mic_row,
            text="重新掃描麥克風",
            width=114,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self.refresh_microphones,
        )
        self.refresh_mic_btn.pack(side="left")

        # ── 卡片 2：步驟 2：高畫質參數與儲存位置 ──
        self.opt_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.opt_card.pack(fill="x", padx=12, pady=(0, 8))

        self.opt_header = ctk.CTkLabel(
            self.opt_card,
            text="步驟 2：畫質設定與存檔資料夾",
            font=(FONT_FAMILY, 14, "bold"),
            anchor="w",
        )
        self.opt_header.pack(fill="x", padx=14, pady=(8, 6))

        select_row = ctk.CTkFrame(self.opt_card, fg_color="transparent")
        select_row.pack(fill="x", padx=14, pady=(0, 6))
        select_row.grid_columnconfigure((0, 1), weight=1)

        fps_col = ctk.CTkFrame(select_row, fg_color="transparent")
        fps_col.grid(row=0, column=0, sticky="ew", padx=(0, 8))
        self.fps_lbl = ctk.CTkLabel(fps_col, text="錄影更新率 (FPS)", font=(FONT_FAMILY, 12, "bold"), anchor="w")
        self.fps_lbl.pack(fill="x", pady=(0, 2))
        saved_fps = "60 FPS（極致流暢）" if int(self.settings.get("recorder_fps", 30)) >= 60 else "30 FPS（教學推薦）"
        self.fps_var = ctk.StringVar(value=saved_fps)
        self.fps_menu = CleanOptionMenu(
            fps_col,
            variable=self.fps_var,
            values=["30 FPS（教學推薦）", "60 FPS（極致流暢）"],
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=lambda _: self._save_options(),
        )
        self.fps_menu.pack(fill="x")

        q_col = ctk.CTkFrame(select_row, fg_color="transparent")
        q_col.grid(row=0, column=1, sticky="ew", padx=(8, 0))
        self.quality_lbl = ctk.CTkLabel(q_col, text="影片畫質清晰度", font=(FONT_FAMILY, 12, "bold"), anchor="w")
        self.quality_lbl.pack(fill="x", pady=(0, 2))
        saved_q = QUALITY_KEY_TO_LABEL.get(self.settings.get("recorder_quality", "high"), "極致高畫質（檔案較大）")
        self.quality_var = ctk.StringVar(value=saved_q)
        self.quality_menu = CleanOptionMenu(
            q_col,
            variable=self.quality_var,
            values=list(QUALITY_LABEL_TO_KEY.keys()),
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=lambda _: self._save_options(),
        )
        self.quality_menu.pack(fill="x")

        sw_row = ctk.CTkFrame(self.opt_card, fg_color="transparent")
        sw_row.pack(fill="x", padx=14, pady=(2, 6))
        sw_row.grid_columnconfigure((0, 1), weight=1)

        self.sw_mouse = ctk.CTkSwitch(
            sw_row,
            text="錄影時顯示滑鼠游標（教學推薦）",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("recorder_draw_mouse", True):
            self.sw_mouse.select()
        self.sw_mouse.grid(row=0, column=0, sticky="w", pady=2)

        self.sw_minimize = ctk.CTkSwitch(
            sw_row,
            text="開始錄影時自動縮小本視窗",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("recorder_minimize_on_start", False):
            self.sw_minimize.select()
        self.sw_minimize.grid(row=0, column=1, sticky="w", pady=2)

        # 自訂儲存資料夾列（同步套用於截圖與所有錄影）
        save_dir_row = ctk.CTkFrame(self.opt_card, fg_color="transparent")
        save_dir_row.pack(fill="x", padx=14, pady=(2, 10))

        self.save_dir_lbl = ctk.CTkLabel(
            save_dir_row,
            text=self._format_save_dir_text(),
            font=(FONT_FAMILY, 12),
            anchor="w",
        )
        self.save_dir_lbl.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.change_dir_btn = ctk.CTkButton(
            save_dir_row,
            text="變更儲存資料夾",
            width=116,
            height=30,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._choose_captures_dir,
        )
        self.change_dir_btn.pack(side="left", padx=(0, 6))

        self.reset_dir_btn = ctk.CTkButton(
            save_dir_row,
            text="恢復預設",
            width=76,
            height=30,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=self._reset_captures_dir,
        )
        self.reset_dir_btn.pack(side="left")

        # ── 動作按鈕列 ──
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=12, pady=(0, 8))

        self.start_btn = ctk.CTkButton(
            action_frame,
            text="開始電腦螢幕錄影",
            height=42,
            corner_radius=18,
            font=(FONT_FAMILY, 14, "bold"),
            command=self._start_recording,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            action_frame,
            text="停止並儲存 MP4",
            width=152,
            height=42,
            corner_radius=18,
            font=(FONT_FAMILY, 14, "bold"),
            command=self._stop_recording,
        )
        self.stop_btn.pack(side="left", padx=(0, 8))

        self.open_dir_btn = ctk.CTkButton(
            action_frame,
            text="開啟錄影資料夾",
            width=130,
            height=42,
            corner_radius=18,
            font=(FONT_FAMILY, 13),
            command=self._open_captures_dir,
        )
        self.open_dir_btn.pack(side="left")

        # ── 卡片 3：使用小提示 ──
        self.tip_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.tip_card.pack(fill="x", padx=12, pady=(0, 8))

        self.tip_title = ctk.CTkLabel(
            self.tip_card,
            text="電腦螢幕錄影實用小提示",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.tip_title.pack(fill="x", padx=14, pady=(8, 3))

        self.tip_body = ctk.CTkLabel(
            self.tip_card,
            text=(
                "1. 選擇「指定程式視窗錄製」可直接單選開啟中的視窗（自動鎖定視窗位置與大小，並防止硬體加速黑畫面）。\n"
                "2. 開啟「錄製電腦系統聲音」可同時錄下電腦喇叭輸出的聲音，並可搭配耳機麥克風進行雙軌混音。\n"
                "3. 變更儲存資料夾後，手機畫面截圖、手機同步錄影與電腦螢幕錄影都會自動存進你指定的資料夾。"
            ),
            font=(FONT_FAMILY, 12),
            anchor="w",
            justify="left",
            wraplength=700,
        )
        self.tip_body.pack(fill="x", padx=14, pady=(0, 10))

    # ── 功能邏輯 ──
    def _format_region_text(self) -> str:
        x, y, w, h = self._region
        return f"框選：{w}x{h} (X={x}, Y={y})"

    def _format_save_dir_text(self) -> str:
        cur = str(get_captures_dir())
        if len(cur) > 54:
            cur = "..." + cur[-51:]
        return f"儲存資料夾：{cur}"

    def _on_mode_changed(self, _value: str) -> None:
        self._save_options()
        self._update_mode_controls()
        if MODE_LABEL_TO_KEY.get(self.mode_var.get()) == "window":
            self.refresh_windows()

    def _update_mode_controls(self) -> None:
        mode = MODE_LABEL_TO_KEY.get(self.mode_var.get(), "fullscreen")
        if mode == "window":
            self.window_row.pack(fill="x", padx=14, pady=(0, 6), before=self.sys_audio_row)
            self.region_info_lbl.configure(text="（將自動鎖定所選程式的視窗位置與大小）")
        else:
            self.window_row.pack_forget()
            if mode == "region":
                self.region_info_lbl.configure(text=self._format_region_text())
            else:
                self.region_info_lbl.configure(text="（錄製整個電腦主螢幕畫面）")

    def refresh_core_banner(self) -> None:
        status = self.binary_manager.check_status()
        if status.recorder_ready:
            self.core_card.pack_forget()
        else:
            self.core_card.pack(fill="x", padx=12, pady=(0, 8), before=self.scope_card)

    def _safe_after(self, ms: int, callback: Callable[[], None]) -> None:
        def _guarded() -> None:
            try:
                if self.winfo_exists():
                    callback()
            except Exception:
                pass

        try:
            self.after(ms, _guarded)
        except Exception:
            pass

    def _start_download_ffmpeg(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self.download_btn.configure(state="disabled", text="下載安裝中...")
        self.download_status_lbl.pack(fill="x", padx=14, pady=(0, 4))
        self.download_bar.pack(fill="x", padx=14, pady=(0, 8))
        self.download_bar.set(0.05)

        def _progress(val: float, text: str) -> None:
            self._safe_after(0, lambda v=val: self.download_bar.set(v))
            self._safe_after(0, lambda t=text: self.download_status_lbl.configure(text=t))

        def _worker() -> None:
            ok, msg = False, "下載安裝發生異常。"
            try:
                ok, msg = self.binary_manager.download_ffmpeg(progress_cb=_progress, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"下載安裝失敗：{exc}"

            def _done() -> None:
                self._downloading = False
                self.download_btn.configure(state="normal", text="一鍵下載並安裝核心")
                self.download_status_lbl.configure(text=msg if not ok else "安裝完成！")
                if ok:
                    self.download_status_lbl.pack_forget()
                    self.download_bar.pack_forget()
                    self.refresh_core_banner()
                    self.on_core_updated()
                    self.refresh_microphones()

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _open_region_selector(self) -> None:
        if self.engine.is_recording():
            self.status_lbl.configure(text="錄影進行中無法調整區域，請先停止錄影。")
            return
        self.on_minimize_app()

        def _on_selected(region: Tuple[int, int, int, int]) -> None:
            self._region = region
            self.mode_var.set("自訂框選區域錄製")
            self._update_mode_controls()
            self._save_options()
            self.on_restore_app()
            self.status_lbl.configure(text=f"已鎖定錄影區域：{region[2]} x {region[3]}（起點 X={region[0]}, Y={region[1]}）")
            self.log_cb(f"已選定電腦螢幕錄影區域：X={region[0]}, Y={region[1]}, {region[2]}x{region[3]}")

        def _on_cancel() -> None:
            self.on_restore_app()

        self.after(180, lambda: RegionSelectorOverlay(self.winfo_toplevel(), _on_selected, _on_cancel))

    def refresh_windows(self) -> None:
        windows: List[WindowInfo] = list_open_windows()
        self._window_map.clear()
        if not windows:
            self.window_menu.configure(values=["（未偵測到開啟中的程式視窗）"])
            self.window_var.set("（未偵測到開啟中的程式視窗）")
            return

        labels = []
        for win in windows:
            lbl = win.display_label
            if lbl in self._window_map:
                lbl = f"{lbl} [{win.hwnd}]"
            labels.append(lbl)
            self._window_map[lbl] = win

        cur = self.window_var.get()
        self.window_menu.configure(values=labels)
        self.window_var.set(cur if cur in self._window_map else labels[0])

    def refresh_microphones(self) -> None:
        self.refresh_mic_btn.configure(state="disabled", text="掃描中...")

        def _worker() -> None:
            mics: List[str] = []
            try:
                mics = self.engine.list_audio_inputs()
            except Exception:
                mics = []

            def _done() -> None:
                self.refresh_mic_btn.configure(state="normal", text="重新掃描麥克風")
                if not mics:
                    self.mic_menu.configure(values=["（未偵測到麥克風）"])
                    self.mic_var.set("（未偵測到麥克風）")
                    self.status_lbl.configure(text="未偵測到麥克風裝置，請確認耳機麥克風已正確連接至電腦。")
                    return
                self.mic_menu.configure(values=mics)
                saved = self.settings.get("recorder_mic_device", "")
                chosen = saved if saved in mics else mics[0]
                self.mic_var.set(chosen)
                self._save_options()
                self.log_cb(f"已偵測到 {len(mics)} 組麥克風：" + "、".join(mics))

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _choose_captures_dir(self) -> None:
        chosen = filedialog.askdirectory(
            title="選擇截圖與錄影儲存資料夾",
            initialdir=str(resolve_captures_dir()),
        )
        if not chosen:
            return
        chosen_path = Path(chosen)
        if not is_dir_writable(chosen_path):
            msg = f"所選資料夾沒有寫入權限或無法建立檔案：{chosen}"
            self.status_lbl.configure(text=msg)
            self.log_cb(msg)
            return
        stored_val = format_captures_dir_for_storage(chosen_path)
        self.settings.set("captures_dir", stored_val)
        self.save_dir_lbl.configure(text=self._format_save_dir_text())
        self.status_lbl.configure(text=f"已變更儲存資料夾為：{chosen}")
        self.log_cb(f"已變更截圖與錄影儲存資料夾：{chosen}")

    def _reset_captures_dir(self) -> None:
        self.settings.set("captures_dir", "")
        self.save_dir_lbl.configure(text=self._format_save_dir_text())
        self.status_lbl.configure(text=f"已恢復預設儲存資料夾：{get_captures_dir()}")
        self.log_cb(f"已恢復預設儲存資料夾：{get_captures_dir()}")

    def _save_options(self) -> None:
        mode_key = MODE_LABEL_TO_KEY.get(self.mode_var.get(), "fullscreen")
        fps_val = 60 if self.fps_var.get().startswith("60") else 30
        q_key = QUALITY_LABEL_TO_KEY.get(self.quality_var.get(), "high")
        mic_val = self.mic_var.get()
        if mic_val.startswith("（"):
            mic_val = ""
        self.settings.update(
            {
                "recorder_mode": mode_key,
                "recorder_region": list(self._region),
                "recorder_fps": fps_val,
                "recorder_quality": q_key,
                "recorder_draw_mouse": bool(self.sw_mouse.get()),
                "recorder_mic_enabled": bool(self.sw_mic.get()),
                "recorder_mic_device": mic_val,
                "recorder_system_audio": bool(self.sw_sys_audio.get()),
                "recorder_minimize_on_start": bool(self.sw_minimize.get()),
            }
        )

    def _build_options(self) -> Optional[ScreenRecordOptions]:
        self._save_options()
        mode = MODE_LABEL_TO_KEY.get(self.mode_var.get(), "fullscreen")
        region = self._region
        target_title = ""
        target_hwnd = 0

        if mode == "window":
            win_info = self._window_map.get(self.window_var.get())
            if not win_info:
                self.status_lbl.configure(text="請先按下「重新掃描程式」並選擇要錄製的程式視窗。")
                return None
            live_rect = focus_and_get_window_rect(win_info.hwnd)
            if not live_rect:
                self.status_lbl.configure(text="所選程式視窗已關閉或無法定位，請按「重新掃描程式」更新清單。")
                return None
            region = normalize_even_region(live_rect)
            target_title = win_info.title
            target_hwnd = win_info.hwnd

        mic_val = self.mic_var.get()
        if mic_val.startswith("（"):
            mic_val = ""
        return ScreenRecordOptions(
            mode=mode,
            region=region,
            fps=60 if self.fps_var.get().startswith("60") else 30,
            quality=QUALITY_LABEL_TO_KEY.get(self.quality_var.get(), "high"),
            draw_mouse=bool(self.sw_mouse.get()),
            mic_enabled=bool(self.sw_mic.get()),
            mic_device=mic_val,
            system_audio=bool(self.sw_sys_audio.get()),
            target_window_title=target_title,
            target_hwnd=target_hwnd,
        )

    def _start_recording(self) -> None:
        if self.engine.is_busy():
            self.status_lbl.configure(text="電腦螢幕錄影正在進行或合成封裝中，請稍候。")
            return

        if not self.binary_manager.check_status().recorder_ready:
            self.status_lbl.configure(text="請先按下最上方「一鍵下載並安裝核心」安裝 FFmpeg 後，再開始錄影。")
            return

        opts = self._build_options()
        if opts is None:
            return

        if opts.mic_enabled and not opts.mic_device:
            self.status_lbl.configure(text="已開啟麥克風旁白，但尚未偵測到可用麥克風；請按下「重新掃描麥克風」。")
            return

        def _on_exit(code: int, saved_path) -> None:
            def _ui_done() -> None:
                self._stop_timer()
                self._active_target_hwnd = 0
                self.start_btn.configure(state="normal", text="開始電腦螢幕錄影")
                if saved_path:
                    self.status_lbl.configure(text=f"錄影已結束並保留影片：{saved_path.name}")
                else:
                    self.status_lbl.configure(text=f"錄影已結束（狀態碼 {code}），可檢視執行紀錄。")

            self._safe_after(0, _ui_done)

        ok, msg, _ = self.engine.start_recording(opts, log_cb=self.log_cb, on_exit=_on_exit)
        self.status_lbl.configure(text=msg)
        if ok:
            self._record_start_ts = time.monotonic()
            self._active_target_hwnd = opts.target_hwnd if opts.mode == "window" else 0
            self.start_btn.configure(state="disabled", text="錄影進行中...")
            self._tick_timer()
            if bool(self.sw_minimize.get()):
                self._safe_after(350, self.on_minimize_app)

    def _stop_recording(self) -> None:
        if not self.engine.is_recording():
            self.status_lbl.configure(text="目前沒有進行中的電腦螢幕錄影。")
            return

        self.stop_btn.configure(state="disabled", text="儲存合成中...")
        self.status_lbl.configure(text="正在安全封裝並合成 MP4 影片檔，請稍候...")

        def _worker() -> None:
            msg = "停止錄影時發生未預期錯誤，請檢視執行紀錄。"
            try:
                _, msg, _ = self.engine.stop_recording(log_cb=self.log_cb)
            except Exception as exc:
                msg = f"停止錄影發生錯誤：{exc}"
                self.log_cb(msg)
            finally:
                def _done() -> None:
                    self._stop_timer()
                    self._active_target_hwnd = 0
                    self.stop_btn.configure(state="normal", text="停止並儲存 MP4")
                    self.start_btn.configure(state="normal", text="開始電腦螢幕錄影")
                    self.status_lbl.configure(text=msg)

                self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _tick_timer(self) -> None:
        if not self.engine.is_recording():
            self._stop_timer()
            return
        elapsed = int(max(0.0, time.monotonic() - self._record_start_ts))
        hrs, rem = divmod(elapsed, 3600)
        mins, secs = divmod(rem, 60)
        extra = ""
        if self._active_target_hwnd:
            alive, minimized = is_window_alive_and_minimized(self._active_target_hwnd)
            if not alive:
                extra = "（注意：目標程式視窗已關閉）"
            elif minimized:
                extra = "（注意：目標程式視窗已最小化）"
        self.status_lbl.configure(
            text=f"正在錄製電腦螢幕（{hrs:02d}:{mins:02d}:{secs:02d}）{extra} — 按下下方「停止並儲存 MP4」完成存檔"
        )
        self._timer_job = self.after(1000, self._tick_timer)

    def _stop_timer(self) -> None:
        if self._timer_job:
            try:
                self.after_cancel(self._timer_job)
            except Exception:
                pass
            self._timer_job = None

    def stop_timer_only(self) -> None:
        """僅取消 UI 錄影計時器（由主視窗背景收尾流程呼叫）。"""
        self._stop_timer()

    def _open_captures_dir(self) -> None:
        try:
            cap_dir = resolve_captures_dir(log_cb=self.log_cb)
            cap_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(cap_dir))
            self.log_cb(f"已開啟錄影與截圖資料夾：{cap_dir}")
        except Exception as exc:
            self.log_cb(f"無法開啟資料夾：{exc}")

    def shutdown(self) -> None:
        """關閉主程式時安全停止錄影與計時器，確保 MP4 影片完整寫入。"""
        self._stop_timer()
        if self.engine.is_recording():
            self.engine.stop_recording(log_cb=self.log_cb)

    # ── 主題即時換膚 ──
    def apply_theme(self, theme: Dict[str, Any]) -> None:
        self._theme = theme
        self.configure(
            fg_color=theme["bg_main"],
            scrollbar_button_color=theme["border"],
            scrollbar_button_hover_color=theme["accent_primary"],
        )
        self.title_lbl.configure(text_color=theme["text_primary"])
        self.subtitle_lbl.configure(text_color=theme["text_secondary"])

        self.core_card.configure(fg_color=theme["bg_card_alt"], border_color=theme["border_pink"])
        self.core_title.configure(text_color=theme["text_primary"])
        self.core_desc.configure(text_color=theme["text_secondary"])
        self.download_status_lbl.configure(text_color=theme["text_secondary"])
        self.download_btn.configure(
            fg_color=theme["accent_secondary"],
            hover_color=theme["accent_secondary_hover"],
            text_color=theme["text_on_accent"],
        )
        self.download_bar.configure(
            fg_color=theme["bg_input"],
            progress_color=theme["accent_secondary"],
        )

        for card in (self.scope_card, self.opt_card, self.tip_card):
            card.configure(fg_color=theme["bg_card"], border_color=theme["border"])

        for lbl in (
            self.scope_header,
            self.status_lbl,
            self.mode_lbl,
            self.window_lbl,
            self.opt_header,
            self.fps_lbl,
            self.quality_lbl,
            self.tip_title,
        ):
            lbl.configure(text_color=theme["text_primary"])

        for lbl in (self.region_info_lbl, self.save_dir_lbl, self.tip_body):
            lbl.configure(text_color=theme["text_secondary"])

        self.status_bubble.configure(fg_color=theme["bg_badge"])

        for menu in (self.mode_menu, self.window_menu, self.mic_menu, self.fps_menu, self.quality_menu):
            menu.configure(
                fg_color=theme["bg_input"],
                button_color=theme["accent_primary"],
                button_hover_color=theme["accent_primary_hover"],
                text_color=theme["text_primary"],
                arrow_color=theme["text_on_accent"],
                dropdown_fg_color=theme["bg_card"],
                dropdown_text_color=theme["text_primary"],
                dropdown_hover_color=theme["nav_hover"],
            )

        for sw in (self.sw_sys_audio, self.sw_mic, self.sw_mouse, self.sw_minimize):
            sw.configure(
                text_color=theme["text_primary"],
                progress_color=theme["switch_track_on"],
                button_color=theme["switch_thumb"],
                button_hover_color=theme["switch_thumb_hover"],
                fg_color=theme["switch_track_off"],
            )

        self.select_region_btn.configure(
            fg_color=theme["accent_info"],
            hover_color=theme["accent_info_hover"],
            text_color=theme["text_on_accent"],
        )
        for btn in (self.refresh_win_btn, self.refresh_mic_btn, self.open_dir_btn, self.reset_dir_btn):
            btn.configure(
                fg_color=theme["bg_badge"],
                hover_color=theme["nav_active"],
                text_color=theme["text_primary"],
            )
        self.change_dir_btn.configure(
            fg_color=theme["accent_info"],
            hover_color=theme["accent_info_hover"],
            text_color=theme["text_on_accent"],
        )
        self.start_btn.configure(
            fg_color=theme["accent_primary"],
            hover_color=theme["accent_primary_hover"],
            text_color=theme["text_on_accent"],
        )
        self.stop_btn.configure(
            fg_color=theme["accent_secondary"],
            hover_color=theme["accent_secondary_hover"],
            text_color=theme["text_on_accent"],
        )
