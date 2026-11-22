"""QPhoneMirror Apple iPhone / iPad AirPlay 投影分頁（支援一鍵下載安裝核心，免額外安裝 Bonjour）。"""

from __future__ import annotations

import threading
from pathlib import Path
from tkinter import filedialog
from typing import Any, Callable, Dict

import customtkinter as ctk

from config.settings import SettingsManager
from config.themes import CORNER_BADGE, CORNER_BTN, CORNER_CARD, CORNER_INPUT, FONT_FAMILY
from core.binary_manager import BinaryManager
from core.ios_engine import IOSEngine, check_bonjour_service, get_local_ip, open_bonjour_guide
from ui.components.clean_option_menu import CleanOptionMenu


class IOSTab(ctk.CTkScrollableFrame):
    """蘋果 AirPlay 投影分頁：統一為一鍵下載安裝核心，簡潔易上手。"""

    def __init__(
        self,
        master,
        theme: Dict[str, Any],
        settings: SettingsManager,
        binary_manager: BinaryManager,
        ios_engine: IOSEngine,
        log_cb: Callable[[str], None],
        on_core_updated: Callable[[], None],
        **kwargs,
    ) -> None:
        super().__init__(master, corner_radius=0, **kwargs)
        self._theme = theme
        self.settings = settings
        self.binary_manager = binary_manager
        self.engine = ios_engine
        self.log_cb = log_cb
        self.on_core_updated = on_core_updated
        self._downloading = False

        self._build_ui()
        self.apply_theme(theme)
        self.refresh_environment()

    def _build_ui(self) -> None:
        self.title_lbl = ctk.CTkLabel(
            self,
            text="蘋果 iPhone / iPad AirPlay 投影",
            font=(FONT_FAMILY, 19, "bold"),
            anchor="w",
        )
        self.title_lbl.pack(fill="x", padx=12, pady=(0, 1))

        self.subtitle_lbl = ctk.CTkLabel(
            self,
            text="iPhone 與 iPad 不須額外安裝程式！啟動下方 AirPlay 接收服務後，由手機控制中心點選「螢幕鏡像輸出」即可同步畫面與聲音。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=730,
            justify="left",
        )
        self.subtitle_lbl.pack(fill="x", padx=12, pady=(0, 8))

        # ── 卡片 0：首次使用 AirPlay 核心一鍵下載卡（與安卓、螢幕錄影風格完全統一） ──
        self.core_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)

        core_main_row = ctk.CTkFrame(self.core_card, fg_color="transparent")
        core_main_row.pack(fill="x", padx=14, pady=8)

        core_text_col = ctk.CTkFrame(core_main_row, fg_color="transparent")
        core_text_col.pack(side="left", fill="x", expand=True, padx=(0, 10))

        self.core_title = ctk.CTkLabel(
            core_text_col,
            text="首次使用：尚未安裝蘋果 AirPlay 投影核心（UxPlay）",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.core_title.pack(fill="x")

        self.core_desc = ctk.CTkLabel(
            core_text_col,
            text="按下右側按鈕將自動下載 Windows 攜帶版核心至 bin/uxplay（內建 mDNS 廣播服務，免額外安裝 Bonjour）。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=430,
            justify="left",
        )
        self.core_desc.pack(fill="x", pady=(2, 0))

        core_btn_col = ctk.CTkFrame(core_main_row, fg_color="transparent")
        core_btn_col.pack(side="right")

        self.download_btn = ctk.CTkButton(
            core_btn_col,
            text="一鍵下載並安裝核心",
            width=152,
            height=34,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._start_download_uxplay,
        )
        self.download_btn.pack(side="left", padx=(0, 6))

        self.import_zip_btn = ctk.CTkButton(
            core_btn_col,
            text="手動匯入 .zip",
            width=102,
            height=34,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=self._import_uxplay_zip,
        )
        self.import_zip_btn.pack(side="left")

        self.download_status_lbl = ctk.CTkLabel(
            self.core_card,
            text="",
            font=(FONT_FAMILY, 12),
            anchor="w",
        )
        self.download_bar = ctk.CTkProgressBar(self.core_card, height=8, corner_radius=8)
        self.download_bar.set(0)

        # ── 卡片 1：網路環境檢查 ──
        self.env_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.env_card.pack(fill="x", padx=12, pady=(0, 8))

        self.env_header = ctk.CTkLabel(
            self.env_card,
            text="連線環境檢查（請確認 iPhone / iPad 與電腦連接同一個 Wi-Fi）",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.env_header.pack(fill="x", padx=14, pady=(8, 4))

        env_row = ctk.CTkFrame(self.env_card, fg_color="transparent")
        env_row.pack(fill="x", padx=14, pady=(0, 8))

        info_col = ctk.CTkFrame(env_row, fg_color="transparent")
        info_col.pack(side="left", fill="x", expand=True)

        self.ip_lbl = ctk.CTkLabel(
            info_col,
            text="電腦目前區域網路 IP：偵測中...",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.ip_lbl.pack(fill="x")

        self.bonjour_lbl = ctk.CTkLabel(
            info_col,
            text="廣播服務狀態：檢查中...",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=540,
            justify="left",
        )
        self.bonjour_lbl.pack(fill="x", pady=(2, 0))

        env_btn_col = ctk.CTkFrame(env_row, fg_color="transparent")
        env_btn_col.pack(side="right")

        self.refresh_env_btn = ctk.CTkButton(
            env_btn_col,
            text="重新檢測",
            width=98,
            height=28,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self.refresh_environment,
        )
        self.refresh_env_btn.pack(pady=(0, 4))

        self.bonjour_help_btn = ctk.CTkButton(
            env_btn_col,
            text="Bonjour 說明",
            width=98,
            height=28,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=open_bonjour_guide,
        )
        self.bonjour_help_btn.pack()

        # ── 卡片 2：AirPlay 接收器設定與開關 ──
        self.ctrl_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.ctrl_card.pack(fill="x", padx=12, pady=(0, 8))

        self.ctrl_header = ctk.CTkLabel(
            self.ctrl_card,
            text="AirPlay 接收器控制台",
            font=(FONT_FAMILY, 14, "bold"),
            anchor="w",
        )
        self.ctrl_header.pack(fill="x", padx=14, pady=(8, 6))

        self.status_bubble = ctk.CTkFrame(self.ctrl_card, corner_radius=CORNER_BADGE)
        self.status_bubble.pack(fill="x", padx=14, pady=(0, 8))

        self.airplay_status_lbl = ctk.CTkLabel(
            self.status_bubble,
            text="AirPlay 接收器目前未啟動，按下下方按鈕即可開始接收 iPhone / iPad 畫面。",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
            wraplength=700,
            justify="left",
        )
        self.airplay_status_lbl.pack(fill="x", padx=10, pady=6)

        name_row = ctk.CTkFrame(self.ctrl_card, fg_color="transparent")
        name_row.pack(fill="x", padx=14, pady=(0, 6))

        self.name_lbl = ctk.CTkLabel(name_row, text="在 iPhone 上顯示的電腦名稱：", font=(FONT_FAMILY, 12))
        self.name_lbl.pack(side="left", padx=(0, 6))

        self.name_entry = ctk.CTkEntry(
            name_row,
            height=32,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
        )
        self.name_entry.insert(0, self.settings.get("ios_airplay_name", "QPhoneMirror-電腦"))
        self.name_entry.pack(side="left", fill="x", expand=True)

        opt_row = ctk.CTkFrame(self.ctrl_card, fg_color="transparent")
        opt_row.pack(fill="x", padx=14, pady=(0, 8))

        self.ios_res_lbl = ctk.CTkLabel(opt_row, text="解析度：", font=(FONT_FAMILY, 12))
        self.ios_res_lbl.pack(side="left", padx=(0, 6))
        self.ios_res_var = ctk.StringVar(value=self.settings.get("ios_resolution", "1920x1080"))
        self.ios_res_menu = CleanOptionMenu(
            opt_row,
            variable=self.ios_res_var,
            values=["1920x1080", "1280x720", "2560x1440"],
            width=124,
            height=30,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
        )
        self.ios_res_menu.pack(side="left", padx=(0, 12))

        self.ios_fps_lbl = ctk.CTkLabel(opt_row, text="更新率：", font=(FONT_FAMILY, 12))
        self.ios_fps_lbl.pack(side="left", padx=(0, 6))
        self.ios_fps_var = ctk.StringVar(value=f"{self.settings.get('ios_fps', 60)} FPS")
        self.ios_fps_menu = CleanOptionMenu(
            opt_row,
            variable=self.ios_fps_var,
            values=["60 FPS", "30 FPS"],
            width=92,
            height=30,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12),
            dropdown_font=(FONT_FAMILY, 12),
        )
        self.ios_fps_menu.pack(side="left", padx=(0, 14))

        self.sw_ios_audio = ctk.CTkSwitch(
            opt_row,
            text="同步聲音至電腦",
            font=(FONT_FAMILY, 12),
        )
        if self.settings.get("ios_audio", True):
            self.sw_ios_audio.select()
        self.sw_ios_audio.pack(side="left")

        self.gui_mode_hint_lbl = ctk.CTkLabel(
            self.ctrl_card,
            text="提示：目前使用一鍵下載攜帶版核心，裝置名稱與畫質設定請於啟動後的 UxPlay 視窗內調整。",
            font=(FONT_FAMILY, 11),
            anchor="w",
            wraplength=700,
            justify="left",
        )

        self.btn_row = ctk.CTkFrame(self.ctrl_card, fg_color="transparent")
        self.btn_row.pack(fill="x", padx=14, pady=(0, 10))

        self.start_btn = ctk.CTkButton(
            self.btn_row,
            text="開啟 AirPlay 接收服務",
            height=40,
            corner_radius=18,
            font=(FONT_FAMILY, 14, "bold"),
            command=self._start_airplay,
        )
        self.start_btn.pack(side="left", fill="x", expand=True, padx=(0, 8))

        self.stop_btn = ctk.CTkButton(
            self.btn_row,
            text="停止接收",
            width=116,
            height=40,
            corner_radius=18,
            font=(FONT_FAMILY, 14, "bold"),
            command=self._stop_airplay,
        )
        self.stop_btn.pack(side="left")

        # ── 卡片 3：iPhone 3 步驟說明 ──
        self.tip_card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
        self.tip_card.pack(fill="x", padx=12, pady=(0, 8))

        self.tip_title = ctk.CTkLabel(
            self.tip_card,
            text="iPhone / iPad 快速連線步驟",
            font=(FONT_FAMILY, 13, "bold"),
            anchor="w",
        )
        self.tip_title.pack(fill="x", padx=14, pady=(8, 3))

        self.tip_body = ctk.CTkLabel(
            self.tip_card,
            text=(
                "1. 確認 iPhone / iPad 和這台電腦連接在同一個 Wi-Fi。\n"
                "2. 按下上方「開啟 AirPlay 接收服務」（若首次使用，請先按最上方「一鍵下載並安裝核心」）。\n"
                "3. 從 iPhone 螢幕右上角往下滑開啟「控制中心」→ 點選「螢幕鏡像輸出」→ 選擇這台電腦即可開始同步畫面與聲音。"
            ),
            font=(FONT_FAMILY, 12),
            anchor="w",
            justify="left",
            wraplength=700,
        )
        self.tip_body.pack(fill="x", padx=14, pady=(0, 8))

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

    # ── 功能邏輯 ──
    def refresh_environment(self) -> None:
        status = self.binary_manager.check_status()
        if status.ios_ready:
            self.core_card.pack_forget()
        else:
            self.core_card.pack(fill="x", padx=12, pady=(0, 8), before=self.env_card)

        ip = get_local_ip()
        self.ip_lbl.configure(text=f"電腦目前區域網路 IP：{ip}")

        mode = self.binary_manager.get_uxplay_mode()
        if mode == "gui":
            self.bonjour_lbl.configure(text="廣播服務：已安裝攜帶版 AirPlay 核心（內建 mDNS，免額外安裝 Bonjour）")
            # 攜帶版 GUI 核心不吃命令列參數，停用無效欄位並清楚提示，避免使用者誤以為設定失效
            self.name_entry.configure(state="disabled")
            self.ios_res_menu.configure(state="disabled")
            self.ios_fps_menu.configure(state="disabled")
            self.sw_ios_audio.configure(state="disabled")
            self.gui_mode_hint_lbl.pack(fill="x", padx=14, pady=(0, 8), before=self.btn_row)
        else:
            _, bonjour_msg = check_bonjour_service()
            self.bonjour_lbl.configure(text=f"Bonjour 狀態：{bonjour_msg}")
            self.name_entry.configure(state="normal")
            self.ios_res_menu.configure(state="normal")
            self.ios_fps_menu.configure(state="normal")
            self.sw_ios_audio.configure(state="normal")
            self.gui_mode_hint_lbl.pack_forget()

    def _start_download_uxplay(self) -> None:
        if self._downloading:
            return
        self._downloading = True
        self.download_btn.configure(state="disabled", text="下載安裝中...")
        self.import_zip_btn.configure(state="disabled")
        self.download_status_lbl.pack(fill="x", padx=14, pady=(0, 4))
        self.download_bar.pack(fill="x", padx=14, pady=(0, 8))
        self.download_bar.set(0.05)

        def _progress(val: float, text: str) -> None:
            self._safe_after(0, lambda v=val: self.download_bar.set(v))
            self._safe_after(0, lambda t=text: self.download_status_lbl.configure(text=t))

        def _worker() -> None:
            ok, msg = False, "下載安裝發生異常。"
            try:
                ok, msg = self.binary_manager.download_uxplay(progress_cb=_progress, log_cb=self.log_cb)
            except Exception as exc:
                msg = f"下載安裝失敗：{exc}"

            def _done() -> None:
                self._downloading = False
                self.download_btn.configure(state="normal", text="一鍵下載並安裝核心")
                self.import_zip_btn.configure(state="normal")
                self.download_status_lbl.configure(text=msg if not ok else "安裝完成！")
                self.airplay_status_lbl.configure(text=msg)
                if ok:
                    self.download_status_lbl.pack_forget()
                    self.download_bar.pack_forget()
                    self.refresh_environment()
                    self.on_core_updated()

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _import_uxplay_zip(self) -> None:
        if self._downloading:
            return
        chosen = filedialog.askopenfilename(
            title="請選擇已下載的 UxPlay Windows 壓縮檔 (.zip)",
            filetypes=[("ZIP 壓縮檔", "*.zip"), ("所有檔案", "*.*")],
        )
        if not chosen:
            return

        self._downloading = True
        self.download_btn.configure(state="disabled")
        self.import_zip_btn.configure(state="disabled", text="匯入中...")
        self.download_status_lbl.configure(text="正在解壓縮並匯入 AirPlay 核心，請稍候...")
        self.download_status_lbl.pack(fill="x", padx=14, pady=(0, 4))
        self.download_bar.pack(fill="x", padx=14, pady=(0, 8))
        self.download_bar.set(0.5)

        def _worker() -> None:
            ok, msg = False, "匯入發生異常。"
            try:
                ok, msg = self.binary_manager.import_uxplay_zip(Path(chosen), log_cb=self.log_cb)
            except Exception as exc:
                msg = f"匯入壓縮檔失敗：{exc}"

            def _done() -> None:
                self._downloading = False
                self.download_btn.configure(state="normal")
                self.import_zip_btn.configure(state="normal", text="手動匯入 .zip")
                self.download_status_lbl.pack_forget()
                self.download_bar.pack_forget()
                self.airplay_status_lbl.configure(text=msg)
                if ok:
                    self.refresh_environment()
                    self.on_core_updated()

            self._safe_after(0, _done)

        threading.Thread(target=_worker, daemon=True).start()

    def _start_airplay(self) -> None:
        name = self.name_entry.get().strip() or "QPhoneMirror-電腦"
        fps = int(self.ios_fps_var.get().split()[0])
        res = self.ios_res_var.get()
        audio = bool(self.sw_ios_audio.get())

        self.settings.update(
            {
                "ios_airplay_name": name,
                "ios_fps": fps,
                "ios_resolution": res,
                "ios_audio": audio,
            }
        )

        def _on_status(_state: str, text: str) -> None:
            self._safe_after(0, lambda t=text: self.airplay_status_lbl.configure(text=t))

        _, msg = self.engine.start_airplay(
            display_name=name,
            fps=fps,
            resolution=res,
            audio=audio,
            log_cb=self.log_cb,
            on_status=_on_status,
        )
        self.airplay_status_lbl.configure(text=msg)

    def _stop_airplay(self) -> None:
        self.engine.stop_airplay(log_cb=self.log_cb)
        self.airplay_status_lbl.configure(text="AirPlay 接收器已停止。")

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
        self.download_bar.configure(
            fg_color=theme["bg_input"],
            progress_color=theme["accent_secondary"],
        )

        for card in (self.env_card, self.ctrl_card, self.tip_card):
            card.configure(fg_color=theme["bg_card"], border_color=theme["border"])

        for lbl in (
            self.env_header,
            self.ip_lbl,
            self.ctrl_header,
            self.airplay_status_lbl,
            self.name_lbl,
            self.ios_res_lbl,
            self.ios_fps_lbl,
            self.tip_title,
        ):
            lbl.configure(text_color=theme["text_primary"])

        for lbl in (self.bonjour_lbl, self.tip_body, self.gui_mode_hint_lbl):
            lbl.configure(text_color=theme["text_secondary"])

        self.status_bubble.configure(fg_color=theme["bg_badge"])

        self.name_entry.configure(
            fg_color=theme["bg_input"],
            border_color=theme["border"],
            text_color=theme["text_primary"],
        )

        for menu in (self.ios_res_menu, self.ios_fps_menu):
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

        self.sw_ios_audio.configure(
            text_color=theme["text_primary"],
            progress_color=theme["switch_track_on"],
            button_color=theme["switch_thumb"],
            button_hover_color=theme["switch_thumb_hover"],
            fg_color=theme["switch_track_off"],
        )

        self.download_btn.configure(
            fg_color=theme["accent_secondary"],
            hover_color=theme["accent_secondary_hover"],
            text_color=theme["text_on_accent"],
        )
        self.import_zip_btn.configure(
            fg_color=theme["bg_badge"],
            hover_color=theme["nav_active"],
            text_color=theme["text_primary"],
        )
        self.refresh_env_btn.configure(
            fg_color=theme["accent_info"],
            hover_color=theme["accent_info_hover"],
            text_color=theme["text_on_accent"],
        )
        self.bonjour_help_btn.configure(
            fg_color=theme["bg_badge"],
            hover_color=theme["nav_active"],
            text_color=theme["text_primary"],
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
