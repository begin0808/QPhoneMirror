"""QPhoneMirror Android 手機投影分頁（緊湊版面・減少捲動長度）。"""

from __future__ import annotations

import os
import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable, Dict, List, Optional, Tuple

import customtkinter as ctk

from config.settings import SettingsManager, resolve_captures_dir
from config.themes import CORNER_BADGE, CORNER_BTN, CORNER_CARD, CORNER_INPUT, FONT_FAMILY
from core.android_engine import AndroidDevice, AndroidEngine, MirrorOptions
from core.binary_manager import BinaryManager
from core.miracast_helper import open_windows_wireless_display
from ui.components.clean_option_menu import CleanOptionMenu

RES_LABEL_TO_KEY = {
    "1080p 流暢（推薦）": "1080p",
    "原始超清畫質": "original",
    "720p 輕量": "720p",
}
RES_KEY_TO_LABEL = {v: k for k, v in RES_LABEL_TO_KEY.items()}

BITRATE_LABEL_TO_KEY = {
    "8M 標準清晰": "8M",
    "16M 極致畫質": "16M",
    "4M 輕量流暢": "4M",
}
BITRATE_KEY_TO_LABEL = {v: k for k, v in BITRATE_LABEL_TO_KEY.items()}

REMOTE_KEYS: List[Tuple[str, int]] = [
    ("返回", 4),
    ("主畫面", 3),
    ("多工切換", 187),
    ("音量 -", 25),
    ("音量 +", 24),
    ("螢幕開關", 26),
]


class AndroidTab(ctk.CTkScrollableFrame):
    """安卓手機投影分頁：緊湊對齊排版，支援有線／無線投影、自動感應、配對碼、截圖錄影與遙控。"""

    AUTO_DETECT_INTERVAL_MS = 3500

    def __init__(
        self,
        master,
        theme: Dict[str, Any],
        settings: SettingsManager,
        binary_manager: BinaryManager,
        android_engine: AndroidEngine,
        log_cb: Callable[[str], None],
        on_core_updated: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, corner_radius=0, **kwargs)
        self._theme = theme
        self.settings = settings
        self.binary_manager = binary_manager
        self.engine = android_engine
        self.log_cb = log_cb
        self.on_core_updated = on_core_updated

        self._devices: List[AndroidDevice] = []
        self._label_to_device: Dict[str, AndroidDevice] = {}
        self._last_device_signature: Optional[List[Tuple[str, str]]] = None
        self._downloading = False
        self._polling_busy = False
        self._polling_stopped = False
        self._auto_detect_job: Optional[str] = None
        self._pair_panel_visible = False
        self._scan_seq = 0
        self._wifi_busy = False
        self._remote_buttons: List[ctk.CTkButton] = []

        self._build_ui()
        self.apply_theme(theme)
        self.refresh_core_banner()
        self._schedule_auto_detect()

    def _safe_after(self, ms: int, callback: Callable[[], None]) -> None:
        if self._polling_stopped:
            return

        def _guarded() -> None:
            if self._polling_stopped:
                return
            try:
                if self.winfo_exists():
                    callback()
            except Exception:
                pass

        try:
            self.after(ms, _guarded)
        except Exception:
            pass

    def _build_ui(self) -> None:
        # 標題貼齊頂部，與左側 QPhoneMirror 齊平，消除多餘上方留白
        self.title_lbl = ctk.CTkLabel(
            self,
            text="安卓手機投影",
            font=(FONT_FAMILY, 19, "bold"),
            anchor="w",
        )
        self.title_lbl.pack(fill="x", padx=12, pady=(0, 1))

        self.subtitle_lbl = ctk.CTkLabel(
            self,
            text="支援各品牌 Android 手機與平板，手機不須額外安裝程式，並可直接用電腦滑鼠與鍵盤操作手機。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=730,
            justify="left",
        )
        self.subtitle_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # ── 卡片 0：首次使用核心自動下載引導卡（右側橫排按鈕，節省一列空間，就緒後自動隱藏） ──
        self.core_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)

        core_main_row = ctk.CTkFrame(self.core_card, fg_color="transparent")
        core_main_row.pack(fill="x", padx=14, pady=8)

        core_text_col = ctk.CTkFrame(core_main_row, fg_color="transparent")
        core_text_col.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.core_title = ctk.CTkLabel(
            core_text_col,
            text="首次使用：尚未安裝 Android 投影核心（Scrcpy + ADB）",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.core_title.pack(fill="x")

        self.core_desc = ctk.CTkLabel(
            core_text_col,
            text="按下右側按鈕，將自動從 GitHub 官方下載並解壓縮至 bin/scrcpy 資料夾，全程約需 10 秒。",
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
            command=self._start_download_scrcpy,
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

        # ── 卡片 1：手機連線、自動感應與有線／無線管理 ──
        self.conn_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.conn_card.pack(fill="x", padx=12, pady=(0, 8))

        conn_top = ctk.CTkFrame(self.conn_card, fg_color="transparent")
        conn_top.pack(fill="x", padx=14, pady=(8, 6))

        self.conn_header = ctk.CTkLabel(
            conn_top,
            text="步驟 1：選擇或連接安卓手機",
            font=(FONT_FAMILY, 14, "bold"),
            anchor="w",
        )
        self.conn_header.pack(side="left")

        self.sw_auto_detect = ctk.CTkSwitch(
            conn_top,
            text="自動感應手機連線",
            font=(FONT_FAMILY, 12, "bold"),
            command=self._on_auto_detect_toggled,
        )
        if self.settings.get("android_auto_detect", True):
            self.sw_auto_detect.select()
        self.sw_auto_detect.pack(side="right")

        self.device_bubble = ctk.CTkFrame(self.conn_card, corner_radius=CORNER_BADGE)
        self.device_bubble.pack(fill="x", padx=14, pady=(0, 6))

        self.device_status_lbl = ctk.CTkLabel(
            self.device_bubble,
            text="準備就緒！請接上 USB 傳輸線，或使用下方 Wi-Fi 無線連線。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=700,
            justify="left",
        )
        self.device_status_lbl.pack(fill="x", padx=10, pady=6)

        dev_row = ctk.CTkFrame(self.conn_card, fg_color="transparent")
        dev_row.pack(fill="x", padx=14, pady=(0, 6))

        self.device_var = ctk.StringVar(value="（尚未偵測到手機）")
        self.device_menu = CleanOptionMenu(
            dev_row,
            variable=self.device_var,
            values=["（尚未偵測到手機）"],
            height=34,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
        )
        self.device_menu.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.scan_btn = ctk.CTkButton(
            dev_row,
            text="掃描手機",
            width=94,
            height=34,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self.scan_devices,
        )
        self.scan_btn.pack(side="left", padx=(0, 6))

        self.to_wifi_btn = ctk.CTkButton(
            dev_row,
            text="插線轉無線",
            width=102,
            height=34,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._convert_usb_to_wifi,
        )
        self.to_wifi_btn.pack(side="left")

        wifi_row = ctk.CTkFrame(self.conn_card, fg_color="transparent")
        wifi_row.pack(fill="x", padx=14, pady=(0, 10))

        self.wifi_lbl = ctk.CTkLabel(
            wifi_row,
            text="Wi-Fi 重連：",
            font=(FONT_FAMILY, 12),
        )
        self.wifi_lbl.pack(side="left", padx=(0, 6))

        self.ip_entry = ctk.CTkEntry(
            wifi_row,
            placeholder_text="輸入手機 IP 或 IP:連接埠（如 192.168.1.105）",
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
        )
        last_ip = self.settings.get("android_last_ip", "")
        if last_ip:
            self.ip_entry.insert(0, last_ip)
        self.ip_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.wifi_connect_btn = ctk.CTkButton(
            wifi_row,
            text="連線 Wi-Fi",
            width=88,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._connect_wifi_ip,
        )
        self.wifi_connect_btn.pack(side="left", padx=(0, 6))

        self.wifi_disconnect_btn = ctk.CTkButton(
            wifi_row,
            text="中斷無線",
            width=76,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=self._disconnect_wifi,
        )
        self.wifi_disconnect_btn.pack(side="left", padx=(0, 6))

        self.pair_toggle_btn = ctk.CTkButton(
            wifi_row,
            text="免插線配對碼設定",
            width=120,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._toggle_pair_panel,
        )
        self.pair_toggle_btn.pack(side="left")

        # 可收合的「免插線配對碼連線（Android 11 以上）」子面板
        self.pair_panel = ctk.CTkFrame(self.conn_card, corner_radius=CORNER_BADGE, border_width=1)

        self.pair_hint_lbl = ctk.CTkLabel(
            self.pair_panel,
            text="免插線無線配對（Android 11 以上）：請於手機「開發人員選項 → 無線偵錯 → 使用配對碼配對裝置」取得資訊",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=690,
            justify="left",
        )
        self.pair_hint_lbl.pack(fill="x", padx=10, pady=(6, 6))

        pair_input_row = ctk.CTkFrame(self.pair_panel, fg_color="transparent")
        pair_input_row.pack(fill="x", padx=10, pady=(0, 8))

        self.pair_host_entry = ctk.CTkEntry(
            pair_input_row,
            placeholder_text="配對 IP 與連接埠（如 192.168.1.105:38123）",
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
        )
        self.pair_host_entry.pack(side="left", fill="x", expand=True, padx=(0, 6))

        self.pair_code_entry = ctk.CTkEntry(
            pair_input_row,
            placeholder_text="6 位數配對碼",
            width=120,
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
        )
        self.pair_code_entry.pack(side="left", padx=(0, 6))

        self.pair_submit_btn = ctk.CTkButton(
            pair_input_row,
            text="執行配對",
            width=88,
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._run_wifi_pair,
        )
        self.pair_submit_btn.pack(side="left")

        # ── 卡片 2：畫質與實用設定 ──
        self.opt_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.opt_card.pack(fill="x", padx=12, pady=(0, 8))

        self.opt_header = ctk.CTkLabel(
            self.opt_card,
            text="步驟 2：畫質與實用設定",
            font=(FONT_FAMILY, 14, "bold"),
            anchor="w",
        )
        self.opt_header.pack(fill="x", padx=14, pady=(8, 6))

        select_row = ctk.CTkFrame(self.opt_card, fg_color="transparent")
        select_row.pack(fill="x", padx=14, pady=(0, 6))
        select_row.grid_columnconfigure((0, 1, 2), weight=1)

        res_col = ctk.CTkFrame(select_row, fg_color="transparent")
        res_col.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.res_lbl = ctk.CTkLabel(res_col, text="畫面解析度", font=(FONT_FAMILY, 12, "bold"), anchor="w")
        self.res_lbl.pack(fill="x", pady=(0, 2))
        saved_res = RES_KEY_TO_LABEL.get(self.settings.get("android_resolution", "1080p"), "1080p 流暢（推薦）")
        self.res_var = ctk.StringVar(value=saved_res)
        self.res_menu = CleanOptionMenu(
            res_col,
            variable=self.res_var,
            values=list(RES_LABEL_TO_KEY.keys()),
            height=30,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=lambda _: self._save_options(),
        )
        self.res_menu.pack(fill="x")

        fps_col = ctk.CTkFrame(select_row, fg_color="transparent")
        fps_col.grid(row=0, column=1, sticky="ew", padx=4)
        self.fps_lbl = ctk.CTkLabel(fps_col, text="更新率 (FPS)", font=(FONT_FAMILY, 12, "bold"), anchor="w")
        self.fps_lbl.pack(fill="x", pady=(0, 2))
        self.fps_var = ctk.StringVar(value=f"{self.settings.get('android_fps', 60)} FPS")
        self.fps_menu = CleanOptionMenu(
            fps_col,
            variable=self.fps_var,
            values=["60 FPS", "90 FPS", "120 FPS"],
            height=30,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=lambda _: self._save_options(),
        )
        self.fps_menu.pack(fill="x")

        br_col = ctk.CTkFrame(select_row, fg_color="transparent")
        br_col.grid(row=0, column=2, sticky="ew", padx=(6, 0))
        self.br_lbl = ctk.CTkLabel(br_col, text="畫質清晰度", font=(FONT_FAMILY, 12, "bold"), anchor="w")
        self.br_lbl.pack(fill="x", pady=(0, 2))
        saved_br = BITRATE_KEY_TO_LABEL.get(self.settings.get("android_bitrate", "8M"), "8M 標準清晰")
        self.br_var = ctk.StringVar(value=saved_br)
        self.br_menu = CleanOptionMenu(
            br_col,
            variable=self.br_var,
            values=list(BITRATE_LABEL_TO_KEY.keys()),
            height=30,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
            command=lambda _: self._save_options(),
        )
        self.br_menu.pack(fill="x")

        sw_grid = ctk.CTkFrame(self.opt_card, fg_color="transparent")
        sw_grid.pack(fill="x", padx=14, pady=(2, 8))
        sw_grid.grid_columnconfigure((0, 1), weight=1)

        self.sw_screen_off = ctk.CTkSwitch(
            sw_grid,
            text="投影時關閉手機螢幕（省電推薦）",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("android_turn_screen_off", True):
            self.sw_screen_off.select()
        self.sw_screen_off.grid(row=0, column=0, sticky="w", pady=3)

        self.sw_audio = ctk.CTkSwitch(
            sw_grid,
            text="同步手機聲音到電腦喇叭",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("android_audio", True):
            self.sw_audio.select()
        self.sw_audio.grid(row=0, column=1, sticky="w", pady=3)

        self.sw_awake = ctk.CTkSwitch(
            sw_grid,
            text="投影時保持手機不休眠",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("android_stay_awake", True):
            self.sw_awake.select()
        self.sw_awake.grid(row=1, column=0, sticky="w", pady=3)

        self.sw_ontop = ctk.CTkSwitch(
            sw_grid,
            text="投影視窗永遠保持在最上層",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("android_always_on_top", False):
            self.sw_ontop.select()
        self.sw_ontop.grid(row=1, column=1, sticky="w", pady=3)

        self.sw_record = ctk.CTkSwitch(
            sw_grid,
            text="投影時同步錄製 MP4 影片（儲存至 captures 資料夾）",
            font=(FONT_FAMILY, 12),
            command=self._save_options,
        )
        if self.settings.get("android_record_video", False):
            self.sw_record.select()
        self.sw_record.grid(row=2, column=0, columnspan=2, sticky="w", pady=3)

        # ── 動作按鈕區 ──
        action_frame = ctk.CTkFrame(self, fg_color="transparent")
        action_frame.pack(fill="x", padx=12, pady=(0, 8))

        self.start_btn = ctk.CTkButton(
            action_frame,
            text="開始投影（支援電腦滑鼠與鍵盤操作）",
            height=42,
            corner_radius=18,
            font=(FONT_FAMILY, 14, "bold"),
            command=self._start_mirror,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            action_frame,
            text="停止投影",
            width=116,
            height=42,
            corner_radius=18,
            font=(FONT_FAMILY, 14, "bold"),
            command=self._stop_mirror,
        )
        self.stop_btn.pack(side="left")

        # ── 卡片 3：手機快捷工具箱與虛擬遙控 ──
        self.tools_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.tools_card.pack(fill="x", padx=12, pady=(0, 8))

        self.tools_header = ctk.CTkLabel(
            self.tools_card,
            text="手機快捷工具箱與虛擬遙控（有線與 Wi-Fi 無線連線皆通用）",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.tools_header.pack(fill="x", padx=14, pady=(8, 6))

        media_row = ctk.CTkFrame(self.tools_card, fg_color="transparent")
        media_row.pack(fill="x", padx=14, pady=(0, 6))
        media_row.grid_columnconfigure((0, 1, 2), weight=1)

        self.screenshot_btn = ctk.CTkButton(
            media_row,
            text="手機畫面截圖",
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._take_screenshot,
        )
        self.screenshot_btn.grid(row=0, column=0, sticky="ew", padx=(0, 6))

        self.send_file_btn = ctk.CTkButton(
            media_row,
            text="傳送檔案 / 安裝 APK",
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._send_files,
        )
        self.send_file_btn.grid(row=0, column=1, sticky="ew", padx=3)

        self.open_captures_btn = ctk.CTkButton(
            media_row,
            text="開啟截圖錄影資料夾",
            height=32,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=self._open_captures_dir,
        )
        self.open_captures_btn.grid(row=0, column=2, sticky="ew", padx=(6, 0))

        remote_row = ctk.CTkFrame(self.tools_card, fg_color="transparent")
        remote_row.pack(fill="x", padx=14, pady=(0, 8))
        remote_row.grid_columnconfigure((0, 1, 2, 3, 4, 5), weight=1)

        self._remote_buttons.clear()
        for col_idx, (key_label, keycode) in enumerate(REMOTE_KEYS):
            btn = ctk.CTkButton(
                remote_row,
                text=key_label,
                height=30,
                corner_radius=CORNER_INPUT,
                font=(FONT_FAMILY, 12, "bold"),
                command=lambda kc=keycode, kl=key_label: self._send_remote_key(kc, kl),
            )
            pad_l = 0 if col_idx == 0 else 3
            pad_r = 0 if col_idx == len(REMOTE_KEYS) - 1 else 3
            btn.grid(row=0, column=col_idx, sticky="ew", padx=(pad_l, pad_r))
            self._remote_buttons.append(btn)

        # ── 卡片 4：免開啟 USB 偵錯快速無線通道（Miracast / Smart View） ──
        self.smartview_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.smartview_card.pack(fill="x", padx=12, pady=(0, 8))

        sv_row = ctk.CTkFrame(self.smartview_card, fg_color="transparent")
        sv_row.pack(fill="x", padx=14, pady=8)

        sv_text_box = ctk.CTkFrame(sv_row, fg_color="transparent")
        sv_text_box.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.sv_title = ctk.CTkLabel(
            sv_text_box,
            text="免開啟 USB 偵錯：Windows 無線投影通道（Miracast / Smart View）",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.sv_title.pack(fill="x")

        self.sv_desc = ctk.CTkLabel(
            sv_text_box,
            text="若不想開啟手機開發者選項，按下右側開啟 Windows 無線投影後，直接從手機下拉選單點選無線投影或 Smart View 即可。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=530,
            justify="left",
        )
        self.sv_desc.pack(fill="x", pady=(1, 0))

        self.smartview_btn = ctk.CTkButton(
            sv_row,
            text="開啟無線投影接收",
            width=152,
            height=34,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._open_smart_view,
        )
        self.smartview_btn.pack(side="right")

    # ── 自動感應手機連線（背景輕量輪詢） ──
    def _on_auto_detect_toggled(self) -> None:
        enabled = bool(self.sw_auto_detect.get())
        self.settings.set("android_auto_detect", enabled)
        if enabled:
            self.log_cb("已開啟自動感應手機連線。")
            self._schedule_auto_detect()
        else:
            if self._auto_detect_job:
                try:
                    self.after_cancel(self._auto_detect_job)
                except Exception:
                    pass
                self._auto_detect_job = None
            self.log_cb("已關閉自動感應手機連線。")

    def _schedule_auto_detect(self) -> None:
        if self._polling_stopped or not bool(self.sw_auto_detect.get()):
            return
        if self._auto_detect_job:
            try:
                self.after_cancel(self._auto_detect_job)
            except Exception:
                pass
        self._auto_detect_job = self.after(self.AUTO_DETECT_INTERVAL_MS, self._auto_detect_tick)

    def _auto_detect_tick(self) -> None:
        self._auto_detect_job = None
        if self._polling_stopped or not bool(self.sw_auto_detect.get()):
            return

        if not self._polling_busy and not self._downloading and self.binary_manager.check_status().android_ready:
            self._polling_busy = True

            def _worker() -> None:
                try:
                    devices, err = self.engine.list_devices()
                    if err is None:
                        sig = [(d.serial, d.state) for d in devices]
                        if sig != self._last_device_signature:
                            self._safe_after(
                                0, lambda d_list=devices: self._apply_device_list(d_list, silent_if_empty=True)
                            )
                finally:
                    self._polling_busy = False

            threading.Thread(target=_worker, daemon=True).start()

        self._schedule_auto_detect()

    def stop_polling(self) -> None:
        """關閉主視窗前停止自動感應定時器。"""
        self._polling_stopped = True
        if self._auto_detect_job:
            try:
                self.after_cancel(self._auto_detect_job)
            except Exception:
                pass
            self._auto_detect_job = None

    # ── 免插線配對碼面板 ──
    def _toggle_pair_panel(self) -> None:
        self._pair_panel_visible = not self._pair_panel_visible
        if self._pair_panel_visible:
            self.pair_panel.pack(fill="x", padx=14, pady=(0, 10))
            self.pair_toggle_btn.configure(text="收合配對碼設定")
        else:
            self.pair_panel.pack_forget()
            self.pair_toggle_btn.configure(text="免插線配對碼設定")

    def _run_wifi_pair(self) -> None:
        host_port = self.pair_host_entry.get().strip()
        code = self.pair_code_entry.get().strip()
        self.pair_submit_btn.configure(state="disabled", text="配對中...")
        self.device_status_lbl.configure(text=f"正在進行免插線無線配對（{host_port}）...")

        def _worker() -> None:
            ok, msg = False, "無線配對發生未知錯誤。"
            try:
                ok, msg = self.engine.pair_wifi(host_port, code, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"無線配對失敗：{exc}"

            def _done() -> None:
                self.pair_submit_btn.configure(state="normal", text="執行配對")
                self.device_status_lbl.configure(text=msg)
                if ok and ":" in host_port:
                    ip_only = host_port.rsplit(":", 1)[0].strip()
                    self.ip_entry.delete(0, "end")
                    self.ip_entry.insert(0, ip_only)
                    self.ip_entry.focus_set()
                    self.pair_code_entry.delete(0, "end")

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # ── 核心檢測與掃描 ──
    def refresh_core_banner(self) -> None:
        status = self.binary_manager.check_status()
        if status.android_ready:
            self.core_card.pack_forget()
        else:
            self.core_card.pack(fill="x", padx=12, pady=(0, 8), before=self.conn_card)

    def _start_download_scrcpy(self) -> None:
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
                ok, msg = self.binary_manager.download_scrcpy(progress_cb=_progress, log_cb=self.log_cb)
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
                    self.scan_devices()

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def scan_devices(
        self,
        preferred_serial: Optional[str] = None,
        auto_start: bool = False,
    ) -> None:
        self._scan_seq += 1
        seq = self._scan_seq
        self.scan_btn.configure(state="disabled", text="掃描中...")
        self.device_status_lbl.configure(text="正在搜尋已連接的安卓手機，請稍候...")

        def _worker() -> None:
            devices, err = [], None
            try:
                devices, err = self.engine.list_devices()
            except Exception as exc:
                err = str(exc)

            def _update() -> None:
                if seq != self._scan_seq:
                    return
                self.scan_btn.configure(state="normal", text="掃描手機")
                if err:
                    self.device_status_lbl.configure(text=f"掃描失敗：{err}")
                    self.log_cb(f"掃描手機失敗：{err}")
                    return
                self._apply_device_list(
                    devices,
                    preferred_serial=preferred_serial,
                    auto_start=auto_start,
                    silent_if_empty=False,
                )

            self._safe_after(0, _update)

        threading.Thread(target=_worker, daemon=True).start()

    def _apply_device_list(
        self,
        devices: List[AndroidDevice],
        preferred_serial: Optional[str] = None,
        auto_start: bool = False,
        silent_if_empty: bool = False,
    ) -> None:
        current_selected = self._get_selected_device()
        keep_serial = preferred_serial or (current_selected.serial if current_selected else None)

        self._devices = devices
        self._last_device_signature = [(d.serial, d.state) for d in devices]
        self._label_to_device.clear()

        if not devices:
            self.device_menu.configure(values=["（尚未偵測到手機）"])
            self.device_var.set("（尚未偵測到手機）")
            self.device_status_lbl.configure(
                text="尚未偵測到手機，請確認 USB 線已插穩且已開啟「USB 偵錯」（可點選左側「操作說明」檢視步驟）。"
            )
            if not silent_if_empty:
                self.log_cb("掃描完成：目前未偵測到已連線的 Android 手機。")
            return

        labels = []
        selected_label = None
        for dev in devices:
            lbl = dev.display_label
            labels.append(lbl)
            self._label_to_device[lbl] = dev
            if keep_serial and dev.serial == keep_serial:
                selected_label = lbl

        if not selected_label:
            for dev in devices:
                if dev.state == "device":
                    selected_label = dev.display_label
                    break

        self.device_menu.configure(values=labels)
        self.device_var.set(selected_label or labels[0])

        ready_count = sum(1 for d in devices if d.state == "device")
        unauth_count = sum(1 for d in devices if d.state == "unauthorized")
        if ready_count > 0:
            chosen_dev = self._get_selected_device() or next(d for d in devices if d.state == "device")
            self.device_status_lbl.configure(
                text=f"已偵測到 {chosen_dev.friendly_name}（共 {len(devices)} 台裝置），按下下方「開始投影」即可同步畫面。"
            )
        elif unauth_count > 0:
            self.device_status_lbl.configure(
                text="已偵測到手機，請在手機畫面上勾選「一律允許」並點選「允許 USB 偵錯」，再重新掃描。"
            )
        else:
            self.device_status_lbl.configure(text="偵測到裝置但連線狀態異常，請重新插拔傳輸線。")

        self.log_cb(f"偵測到 {len(devices)} 台安卓手機：" + ", ".join(d.friendly_name for d in devices))

        if auto_start and ready_count > 0:
            self._launch_selected_mirror()

    def _get_selected_device(self) -> Optional[AndroidDevice]:
        return self._label_to_device.get(self.device_var.get())

    def _require_ready_device(self, action_name: str) -> Optional[AndroidDevice]:
        dev = self._get_selected_device()
        if not dev:
            msg = f"尚未連接安卓手機，請先接上 USB 線或連線 Wi-Fi 後再執行「{action_name}」。"
            self.device_status_lbl.configure(text=msg)
            self.log_cb(msg)
            return None
        if dev.state != "device":
            msg = f"手機目前尚未就緒（{dev.state}），請確認手機已點選「允許 USB 偵錯」。"
            self.device_status_lbl.configure(text=msg)
            self.log_cb(msg)
            return None
        return dev

    def _get_safe_wifi_port(self) -> int:
        try:
            port = int(self.settings.get("android_wifi_port", 5555))
            return port if 1 <= port <= 65535 else 5555
        except Exception:
            return 5555

    def _set_wifi_buttons_state(self, state: str) -> None:
        for btn in (self.to_wifi_btn, self.wifi_connect_btn, self.wifi_disconnect_btn):
            btn.configure(state=state)

    # ── 有線轉無線與 Wi-Fi 連線 ──
    def _convert_usb_to_wifi(self) -> None:
        if self._wifi_busy:
            return
        dev = self._get_selected_device()
        if not dev:
            self.device_status_lbl.configure(text="請先接上 USB 線並按下「掃描手機」，即可一鍵切換為無線連線。")
            self.log_cb("尚未選擇任何 USB 手機，無法切換無線模式。")
            return

        self._wifi_busy = True
        try:
            self._set_wifi_buttons_state("disabled")
        except Exception:
            self._wifi_busy = False
            raise
        self.device_status_lbl.configure(text=f"正在將 {dev.friendly_name} 切換為 Wi-Fi 無線連線，請稍候...")

        def _worker() -> None:
            port = self._get_safe_wifi_port()
            ok, msg, ip = False, "切換無線模式發生異常。", None
            try:
                ok, msg, ip = self.engine.enable_wifi_mode(dev.serial, port=port, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"切換無線模式失敗：{exc}"
            finally:
                def _done() -> None:
                    self._wifi_busy = False
                    self._set_wifi_buttons_state("normal")
                    self.device_status_lbl.configure(text=msg)
                    if ip:
                        self.ip_entry.delete(0, "end")
                        self.ip_entry.insert(0, ip)
                        self.settings.set("android_last_ip", ip)
                    if ok and ip:
                        self.scan_devices(preferred_serial=f"{ip}:{port}")

                self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _connect_wifi_ip(self) -> None:
        if self._wifi_busy:
            return
        ip = self.ip_entry.get().strip()
        if not ip:
            self.device_status_lbl.configure(text="請先輸入手機的 Wi-Fi IP 位址。")
            return

        self._wifi_busy = True
        try:
            self._set_wifi_buttons_state("disabled")
        except Exception:
            self._wifi_busy = False
            raise
        self.settings.set("android_last_ip", ip)
        self.device_status_lbl.configure(text=f"正在無線連線至 {ip} ...")

        def _worker() -> None:
            port = self._get_safe_wifi_port()
            target_serial = ip if ":" in ip else f"{ip}:{port}"
            ok, msg = False, "無線連線發生異常。"
            try:
                ok, msg = self.engine.connect_wifi(ip, port=port, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"無線連線失敗：{exc}"
            finally:
                def _done() -> None:
                    self._wifi_busy = False
                    self._set_wifi_buttons_state("normal")
                    self.device_status_lbl.configure(text=msg)
                    if ok:
                        self._safe_after(200, lambda ts=target_serial: self.scan_devices(preferred_serial=ts))

                self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _disconnect_wifi(self) -> None:
        if self._wifi_busy:
            return
        self._wifi_busy = True
        try:
            self._set_wifi_buttons_state("disabled")
        except Exception:
            self._wifi_busy = False
            raise

        def _worker() -> None:
            msg = "中斷無線連線完成。"
            try:
                _, msg = self.engine.disconnect_wifi(log_cb=self.log_cb)
            except Exception as exc:
                msg = f"中斷無線連線失敗：{exc}"
            finally:
                def _done() -> None:
                    self._wifi_busy = False
                    self._set_wifi_buttons_state("normal")
                    self.device_status_lbl.configure(text=msg)
                    self._safe_after(200, self.scan_devices)

                self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    # ── 快捷工具箱：截圖、傳檔、開啟資料夾、虛擬遙控 ──
    def _take_screenshot(self) -> None:
        dev = self._require_ready_device("手機畫面截圖")
        if not dev:
            return
        self.screenshot_btn.configure(state="disabled", text="截圖中...")
        self.device_status_lbl.configure(text="正在擷取手機畫面，請稍候...")

        def _worker() -> None:
            msg = "截圖失敗。"
            try:
                _, msg, _ = self.engine.take_screenshot(dev.serial, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"截圖失敗：{exc}"

            def _done() -> None:
                self.screenshot_btn.configure(state="normal", text="手機畫面截圖")
                self.device_status_lbl.configure(text=msg)

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _send_files(self) -> None:
        dev = self._require_ready_device("傳送檔案 / 安裝 APK")
        if not dev:
            return
        chosen = filedialog.askopenfilenames(
            title="選擇要傳送至手機的檔案或 APK 安裝檔（可多選）",
            filetypes=[("所有檔案", "*.*"), ("Android 安裝檔", "*.apk")],
        )
        if not chosen:
            return

        paths = [Path(p) for p in chosen]
        self.send_file_btn.configure(state="disabled", text="傳輸中...")
        self.device_status_lbl.configure(text=f"正在傳送 {len(paths)} 個檔案至手機，請稍候...")

        def _worker() -> None:
            msg = "傳檔失敗。"
            try:
                _, msg = self.engine.send_files_to_device(dev.serial, paths, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"傳檔失敗：{exc}"

            def _done() -> None:
                self.send_file_btn.configure(state="normal", text="傳送檔案 / 安裝 APK")
                self.device_status_lbl.configure(text=msg)

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _open_captures_dir(self) -> None:
        try:
            cap_dir = resolve_captures_dir(log_cb=self.log_cb)
            cap_dir.mkdir(parents=True, exist_ok=True)
            os.startfile(str(cap_dir))
            self.log_cb(f"已開啟截圖與錄影資料夾：{cap_dir}")
        except Exception as exc:
            self.log_cb(f"無法開啟資料夾：{exc}")

    def _send_remote_key(self, keycode: int, key_label: str) -> None:
        dev = self._require_ready_device(f"虛擬遙控：{key_label}")
        if not dev:
            return

        def _worker() -> None:
            try:
                _, msg = self.engine.send_keyevent(dev.serial, keycode, key_label=key_label, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"傳送按鍵失敗：{exc}"
            self._safe_after(0, lambda m=msg: self.device_status_lbl.configure(text=m))

        threading.Thread(target=_worker, daemon=True).start()

    # ── 投影設定與啟動 ──
    def _save_options(self) -> None:
        res_key = RES_LABEL_TO_KEY.get(self.res_var.get(), "1080p")
        fps_val = int(self.fps_var.get().split()[0])
        br_key = BITRATE_LABEL_TO_KEY.get(self.br_var.get(), "8M")
        self.settings.update(
            {
                "android_resolution": res_key,
                "android_fps": fps_val,
                "android_bitrate": br_key,
                "android_turn_screen_off": bool(self.sw_screen_off.get()),
                "android_audio": bool(self.sw_audio.get()),
                "android_stay_awake": bool(self.sw_awake.get()),
                "android_always_on_top": bool(self.sw_ontop.get()),
                "android_record_video": bool(self.sw_record.get()),
            }
        )

    def _build_mirror_options(self) -> MirrorOptions:
        self._save_options()
        return MirrorOptions(
            resolution=RES_LABEL_TO_KEY.get(self.res_var.get(), "1080p"),
            fps=int(self.fps_var.get().split()[0]),
            bitrate=BITRATE_LABEL_TO_KEY.get(self.br_var.get(), "8M"),
            turn_screen_off=bool(self.sw_screen_off.get()),
            stay_awake=bool(self.sw_awake.get()),
            audio=bool(self.sw_audio.get()),
            always_on_top=bool(self.sw_ontop.get()),
            record_video=bool(self.sw_record.get()),
        )

    def _start_mirror(self) -> None:
        dev = self._get_selected_device()
        if not dev:
            self.device_status_lbl.configure(text="正在自動掃描並準備啟動投影...")
            self.scan_devices(auto_start=True)
            return
        self._launch_selected_mirror()

    def _launch_selected_mirror(self) -> None:
        dev = self._get_selected_device()
        if not dev:
            return

        opts = self._build_mirror_options()
        _, msg = self.engine.start_mirror(
            device=dev,
            options=opts,
            log_cb=self.log_cb,
            on_exit=lambda serial, code: self._safe_after(
                0, lambda: self.device_status_lbl.configure(text="投影視窗已關閉，隨時可再次按下「開始投影」。")
            ),
        )
        self.device_status_lbl.configure(text=msg)

    def _stop_mirror(self) -> None:
        self.stop_btn.configure(state="disabled", text="停止中...")
        self.device_status_lbl.configure(text="正在安全關閉投影視窗並完成存檔，請稍候...")

        def _worker() -> None:
            try:
                self.engine.stop_all(log_cb=self.log_cb)
            finally:
                def _done() -> None:
                    self.stop_btn.configure(state="normal", text="停止投影")
                    self.device_status_lbl.configure(text="已安全停止所有安卓投影視窗。")

                self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _open_smart_view(self) -> None:
        _, msg = open_windows_wireless_display(log_cb=self.log_cb)
        self.device_status_lbl.configure(text=msg)

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

        for card in (self.conn_card, self.opt_card, self.tools_card, self.smartview_card):
            card.configure(fg_color=theme["bg_card"], border_color=theme["border"])

        self.pair_panel.configure(fg_color=theme["bg_card_alt"], border_color=theme["border_pink"])
        self.pair_hint_lbl.configure(text_color=theme["text_secondary"])

        for lbl in (
            self.conn_header,
            self.opt_header,
            self.tools_header,
            self.device_status_lbl,
            self.wifi_lbl,
            self.res_lbl,
            self.fps_lbl,
            self.br_lbl,
            self.sv_title,
        ):
            lbl.configure(text_color=theme["text_primary"])

        self.sv_desc.configure(text_color=theme["text_secondary"])
        self.device_bubble.configure(fg_color=theme["bg_badge"])

        for menu in (self.device_menu, self.res_menu, self.fps_menu, self.br_menu):
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

        for entry in (self.ip_entry, self.pair_host_entry, self.pair_code_entry):
            entry.configure(
                fg_color=theme["bg_input"],
                border_color=theme["border"],
                text_color=theme["text_primary"],
                placeholder_text_color=theme["text_secondary"],
            )

        for sw in (self.sw_auto_detect, self.sw_screen_off, self.sw_audio, self.sw_awake, self.sw_ontop, self.sw_record):
            sw.configure(
                text_color=theme["text_primary"],
                progress_color=theme["switch_track_on"],
                button_color=theme["switch_thumb"],
                button_hover_color=theme["switch_thumb_hover"],
                fg_color=theme["switch_track_off"],
            )

        self.scan_btn.configure(
            fg_color=theme["accent_info"],
            hover_color=theme["accent_info_hover"],
            text_color=theme["text_on_accent"],
        )
        self.to_wifi_btn.configure(
            fg_color=theme["accent_warn"],
            hover_color=theme["accent_warn_hover"],
            text_color=theme["text_on_accent"],
        )
        self.wifi_connect_btn.configure(
            fg_color=theme["accent_primary"],
            hover_color=theme["accent_primary_hover"],
            text_color=theme["text_on_accent"],
        )
        self.wifi_disconnect_btn.configure(
            fg_color=theme["bg_badge"],
            hover_color=theme["nav_active"],
            text_color=theme["text_primary"],
        )
        self.pair_toggle_btn.configure(
            fg_color=theme["bg_badge"],
            hover_color=theme["nav_active"],
            text_color=theme["text_primary"],
        )
        self.pair_submit_btn.configure(
            fg_color=theme["accent_secondary"],
            hover_color=theme["accent_secondary_hover"],
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

        self.screenshot_btn.configure(
            fg_color=theme["accent_info"],
            hover_color=theme["accent_info_hover"],
            text_color=theme["text_on_accent"],
        )
        self.send_file_btn.configure(
            fg_color=theme["accent_primary"],
            hover_color=theme["accent_primary_hover"],
            text_color=theme["text_on_accent"],
        )
        self.open_captures_btn.configure(
            fg_color=theme["bg_badge"],
            hover_color=theme["nav_active"],
            text_color=theme["text_primary"],
        )
        for btn in self._remote_buttons:
            btn.configure(
                fg_color=theme["bg_input"],
                hover_color=theme["nav_active"],
                text_color=theme["text_primary"],
                border_width=1,
                border_color=theme["border"],
            )

        self.smartview_btn.configure(
            fg_color=theme["accent_info"],
            hover_color=theme["accent_info_hover"],
            text_color=theme["text_on_accent"],
        )
