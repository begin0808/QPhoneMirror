"""QPhoneMirror 主視窗框架（極簡大空間版・執行紀錄獨立彈窗・左下角整合主題風格）。"""

from __future__ import annotations

import ctypes
from ctypes import wintypes
import sys
import threading
import tkinter as tk
from tkinter import messagebox
import webbrowser
from pathlib import Path
from typing import Any, Dict

import customtkinter as ctk
import psutil

from config.settings import (
    APP_NAME,
    APP_VERSION,
    COPYRIGHT_YEAR,
    FACEBOOK_URL,
    STUDIO_NAME,
    STUDIO_URL,
    SettingsManager,
    get_app_dir,
)
from config.themes import (
    CORNER_BTN,
    CORNER_CARD,
    CORNER_INPUT,
    FONT_FAMILY,
    get_theme,
    get_theme_display_names,
    get_theme_id_by_display_name,
)
from core.android_engine import AndroidEngine
from core.binary_manager import BinaryManager
from core.ios_engine import IOSEngine
from core.screen_recorder import ScreenRecorderEngine
from ui.components.clean_option_menu import CleanOptionMenu
from ui.components.log_console import LogWindowManager
from ui.icons import create_facebook_icon, create_menu_icons
from ui.tab_android import AndroidTab
from ui.tab_guide import GuideTab
from ui.tab_ios import IOSTab
from ui.tab_recorder import RecorderTab


class QPhoneMirrorApp(ctk.CTk):
    """QPhoneMirror 跨平台手機投影主視窗。"""

    def __init__(self) -> None:
        super().__init__()

        self.settings = SettingsManager()
        self.binary_manager = BinaryManager()
        self.android_engine = AndroidEngine(self.binary_manager)
        self.ios_engine = IOSEngine(self.binary_manager)
        self.recorder_engine = ScreenRecorderEngine(self.binary_manager)

        self.current_theme_id = self.settings.get("theme", "pastel_cute")
        self.theme: Dict[str, Any] = get_theme(self.current_theme_id)
        ctk.set_appearance_mode(self.theme["appearance_mode"])

        self.title(f"{APP_NAME} 跨平台手機投影工具 {APP_VERSION}")
        self.geometry("1020x740")
        self.minsize(900, 640)
        self._try_set_icon()

        # 僅於左側選單使用高解析全彩圖示（另含左下角版權列 FB 圖示）
        self._menu_icons = create_menu_icons()
        self._fb_icon = create_facebook_icon(16)

        # 獨立彈出式執行紀錄管理器（不佔用主畫面底部高度）
        self.log_manager = LogWindowManager(self, theme=self.theme)

        self._active_tab = "android"
        self._closing = False
        self._build_layout()
        self._apply_theme_all()
        self._refresh_sidebar_status()

        # CustomTkinter 在 Windows 下預設會於 mainloop() 才顯示視窗，
        # 切勿於 __init__ 手動呼叫 withdraw()，直接於此計算正中央座標即可無閃爍置中顯示。
        self._center_on_screen(1020, 740)

        if self.binary_manager.check_status().android_ready:
            self.after(400, self.tab_android.scan_devices)

        self.protocol("WM_DELETE_WINDOW", self._on_close)

    def _center_on_screen(self, logical_w: int, logical_h: int) -> None:
        """讀取 Windows 實際實體工作區（排除工作列），將視窗精準置於螢幕正中央。"""
        self.update_idletasks()
        scale = max(1.0, float(self._get_window_scaling()))
        phys_w = max(self.winfo_width(), int(logical_w * scale))
        phys_h = max(self.winfo_height(), int(logical_h * scale))

        wa_left, wa_top, wa_right, wa_bottom = (
            0,
            0,
            int(self.winfo_screenwidth() * scale),
            int(self.winfo_screenheight() * scale),
        )
        if sys.platform == "win32":
            try:
                rect = wintypes.RECT()
                # SPI_GETWORKAREA = 0x0030，取得不含工作列的實際實體像素範圍
                if ctypes.windll.user32.SystemParametersInfoW(0x0030, 0, ctypes.byref(rect), 0):
                    wa_left, wa_top, wa_right, wa_bottom = rect.left, rect.top, rect.right, rect.bottom
                else:
                    wa_right = ctypes.windll.user32.GetSystemMetrics(0)
                    wa_bottom = ctypes.windll.user32.GetSystemMetrics(1)
            except Exception:
                pass

        # 考量 Windows 標題列外框高度（約 32px）
        titlebar_h = int(32 * scale)
        x = wa_left + max(0, (wa_right - wa_left - phys_w) // 2)
        y = wa_top + max(0, (wa_bottom - wa_top - phys_h - titlebar_h) // 2)
        tk.Tk.geometry(self, f"+{x}+{y}")

    def _try_set_icon(self) -> None:
        candidates = [
            get_app_dir() / "assets" / "qphonemirror.ico",
            Path(__file__).resolve().parent.parent / "assets" / "qphonemirror.ico",
        ]
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            candidates.insert(0, Path(meipass) / "assets" / "qphonemirror.ico")

        for candidate in candidates:
            if candidate.is_file():
                try:
                    self.iconbitmap(str(candidate))
                    return
                except Exception:
                    pass

    def _build_layout(self) -> None:
        # ── 主體區域（上下多餘列皆已移除，最大垂直空間留給右側主操作區） ──
        self.body_frame = ctk.CTkFrame(self, fg_color="transparent")
        self.body_frame.pack(fill="both", expand=True, padx=12, pady=(10, 10))

        # 左側圓角選單欄（頂部 QPhoneMirror，底部整合核心狀態、主題風格與版權宣告）
        self.sidebar = ctk.CTkFrame(self.body_frame, width=212, corner_radius=CORNER_CARD, border_width=2)
        self.sidebar.pack(side="left", fill="y", padx=(0, 10))
        self.sidebar.pack_propagate(False)

        self.brand_title = ctk.CTkLabel(
            self.sidebar,
            text=APP_NAME,
            font=(FONT_FAMILY, 20, "bold"),
            anchor="w",
        )
        self.brand_title.pack(fill="x", padx=16, pady=(12, 8))

        self.brand_divider = ctk.CTkFrame(self.sidebar, height=1)
        self.brand_divider.pack(fill="x", padx=14, pady=(0, 8))

        self.nav_buttons: Dict[str, ctk.CTkButton] = {}
        nav_items = [
            ("android", "  安卓手機投影", self._menu_icons["android"]),
            ("ios", "  蘋果 AirPlay", self._menu_icons["ios"]),
            ("recorder", "  電腦螢幕錄影", self._menu_icons["recorder"]),
            ("guide", "  操作說明", self._menu_icons["guide"]),
        ]
        for key, label, icon_img in nav_items:
            btn = ctk.CTkButton(
                self.sidebar,
                text=label,
                image=icon_img,
                compound="left",
                height=42,
                corner_radius=CORNER_BTN,
                font=(FONT_FAMILY, 14, "bold"),
                anchor="w",
                command=lambda k=key: self._switch_tab(k),
            )
            btn.pack(fill="x", padx=12, pady=4)
            self.nav_buttons[key] = btn

        # 左側選單最下方：版權宣告（可點選前往官網）
        self.copyright_box = ctk.CTkFrame(self.sidebar, fg_color="transparent")
        self.copyright_box.pack(side="bottom", pady=(0, 8))

        self.copyright_prefix = ctk.CTkLabel(
            self.copyright_box,
            text=f"© {COPYRIGHT_YEAR} ",
            font=(FONT_FAMILY, 10),
        )
        self.copyright_prefix.pack(side="left")

        self.studio_link = ctk.CTkLabel(
            self.copyright_box,
            text=STUDIO_NAME,
            font=(FONT_FAMILY, 10, "underline"),
            cursor="hand2",
        )
        self.studio_link.pack(side="left")
        self.studio_link.bind("<Button-1>", lambda _e: webbrowser.open(STUDIO_URL))

        self.fb_link = ctk.CTkLabel(
            self.copyright_box,
            text="",
            image=self._fb_icon,
            width=18,
            cursor="hand2",
        )
        self.fb_link.pack(side="left", padx=(6, 0))
        self.fb_link.bind("<Button-1>", lambda _e: webbrowser.open(FACEBOOK_URL))

        # 左下角：主題風格切換卡
        self.theme_card = ctk.CTkFrame(self.sidebar, corner_radius=CORNER_CARD, border_width=1)
        self.theme_card.pack(side="bottom", fill="x", padx=10, pady=(0, 6))

        self.theme_lbl = ctk.CTkLabel(
            self.theme_card,
            text="主題風格",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.theme_lbl.pack(fill="x", padx=10, pady=(8, 4))

        self.theme_var = ctk.StringVar(value=self.theme["display_name"])
        self.theme_menu = CleanOptionMenu(
            self.theme_card,
            variable=self.theme_var,
            values=get_theme_display_names(),
            height=30,
            corner_radius=CORNER_INPUT,
            font=(FONT_FAMILY, 12, "bold"),
            dropdown_font=(FONT_FAMILY, 12),
            command=self._on_theme_changed,
        )
        self.theme_menu.pack(fill="x", padx=10, pady=(0, 10))

        # 左下角：核心狀態與彈出執行紀錄按鈕卡
        self.status_card = ctk.CTkFrame(self.sidebar, corner_radius=CORNER_CARD, border_width=1)
        self.status_card.pack(side="bottom", fill="x", padx=10, pady=(0, 8))

        self.status_card_title = ctk.CTkLabel(
            self.status_card,
            text="投影核心狀態",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.status_card_title.pack(fill="x", padx=10, pady=(8, 4))

        self.android_core_lbl = ctk.CTkLabel(
            self.status_card,
            text="Android：檢測中...",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.android_core_lbl.pack(fill="x", padx=10, pady=1)

        self.ios_core_lbl = ctk.CTkLabel(
            self.status_card,
            text="iPhone：檢測中...",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.ios_core_lbl.pack(fill="x", padx=10, pady=1)

        self.recorder_core_lbl = ctk.CTkLabel(
            self.status_card,
            text="螢幕錄影：檢測中...",
            font=(FONT_FAMILY, 12, "bold"),
            anchor="w",
        )
        self.recorder_core_lbl.pack(fill="x", padx=10, pady=(1, 6))

        self.recheck_btn = ctk.CTkButton(
            self.status_card,
            text="重新檢測核心",
            height=28,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12, "bold"),
            command=self._recheck_all_cores,
        )
        self.recheck_btn.pack(fill="x", padx=10, pady=(0, 5))

        self.open_log_btn = ctk.CTkButton(
            self.status_card,
            text="檢視執行紀錄",
            height=28,
            corner_radius=CORNER_BTN,
            font=(FONT_FAMILY, 12),
            command=self.log_manager.show,
        )
        self.open_log_btn.pack(fill="x", padx=10, pady=(0, 8))

        # ── 右側內容分頁容器 ──
        self.content_container = ctk.CTkFrame(self.body_frame, fg_color="transparent")
        self.content_container.pack(side="right", fill="both", expand=True)

        self.tab_android = AndroidTab(
            self.content_container,
            theme=self.theme,
            settings=self.settings,
            binary_manager=self.binary_manager,
            android_engine=self.android_engine,
            log_cb=self.log_manager.append,
            on_core_updated=self._refresh_sidebar_status,
        )
        self.tab_ios = IOSTab(
            self.content_container,
            theme=self.theme,
            settings=self.settings,
            binary_manager=self.binary_manager,
            ios_engine=self.ios_engine,
            log_cb=self.log_manager.append,
            on_core_updated=self._refresh_sidebar_status,
        )
        self.tab_recorder = RecorderTab(
            self.content_container,
            theme=self.theme,
            settings=self.settings,
            binary_manager=self.binary_manager,
            recorder_engine=self.recorder_engine,
            log_cb=self.log_manager.append,
            on_core_updated=self._refresh_sidebar_status,
            on_minimize_app=self.iconify,
            on_restore_app=self._restore_window,
        )
        self.tab_guide = GuideTab(self.content_container, theme=self.theme)

        self._tabs = {
            "android": self.tab_android,
            "ios": self.tab_ios,
            "recorder": self.tab_recorder,
            "guide": self.tab_guide,
        }
        self._switch_tab("android")

    def _restore_window(self) -> None:
        self.deiconify()
        self.lift()
        self.focus_force()

    def _switch_tab(self, tab_key: str) -> None:
        self._active_tab = tab_key
        for key, frame in self._tabs.items():
            if key == tab_key:
                frame.pack(fill="both", expand=True)
            else:
                frame.pack_forget()
        self._update_nav_button_styles()

    def _update_nav_button_styles(self) -> None:
        t = self.theme
        for key, btn in self.nav_buttons.items():
            if key == self._active_tab:
                btn.configure(
                    fg_color=t["nav_active"],
                    hover_color=t["nav_active"],
                    text_color=t["text_primary"],
                    border_width=2,
                    border_color=t["accent_primary"],
                )
            else:
                btn.configure(
                    fg_color="transparent",
                    hover_color=t["nav_hover"],
                    text_color=t["text_secondary"],
                    border_width=0,
                )

    def _on_theme_changed(self, display_name: str) -> None:
        new_id = get_theme_id_by_display_name(display_name)
        self.current_theme_id = new_id
        self.theme = get_theme(new_id)
        self.settings.set("theme", new_id)
        ctk.set_appearance_mode(self.theme["appearance_mode"])
        self._apply_theme_all()

    def _apply_theme_all(self) -> None:
        t = self.theme
        self.configure(fg_color=t["bg_main"])

        self.sidebar.configure(fg_color=t["bg_sidebar"], border_color=t["border"])
        self.brand_title.configure(text_color=t["text_primary"])
        self.brand_divider.configure(fg_color=t["border"])

        self.theme_card.configure(fg_color=t["bg_card"], border_color=t["border"])
        self.theme_lbl.configure(text_color=t["text_primary"])
        self.theme_menu.configure(
            fg_color=t["bg_input"],
            button_color=t["accent_secondary"],
            button_hover_color=t["accent_secondary_hover"],
            text_color=t["text_primary"],
            arrow_color=t["text_on_accent"],
            dropdown_fg_color=t["bg_card"],
            dropdown_text_color=t["text_primary"],
            dropdown_hover_color=t["nav_hover"],
        )

        self.status_card.configure(fg_color=t["bg_card"], border_color=t["border"])
        self.status_card_title.configure(text_color=t["text_primary"])
        self.recheck_btn.configure(
            fg_color=t["bg_badge"],
            hover_color=t["nav_active"],
            text_color=t["text_primary"],
        )
        self.open_log_btn.configure(
            fg_color=t["bg_input"],
            hover_color=t["nav_hover"],
            text_color=t["text_secondary"],
            border_width=1,
            border_color=t["border"],
        )

        self.copyright_prefix.configure(text_color=t["text_secondary"])
        self.studio_link.configure(text_color=t["accent_primary_hover"])

        self._update_nav_button_styles()
        self._refresh_sidebar_status()
        self.tab_android.apply_theme(t)
        self.tab_ios.apply_theme(t)
        self.tab_recorder.apply_theme(t)
        self.tab_guide.apply_theme(t)
        self.log_manager.apply_theme(t)

    def _refresh_sidebar_status(self) -> None:
        status = self.binary_manager.check_status()
        t = self.theme

        if status.android_ready:
            self.android_core_lbl.configure(text="Android：已就緒", text_color=t["status_ok"])
        else:
            self.android_core_lbl.configure(text="Android：待下載", text_color=t["status_warn"])

        if status.ios_ready:
            self.ios_core_lbl.configure(text="iPhone：已就緒", text_color=t["status_ok"])
        else:
            self.ios_core_lbl.configure(text="iPhone：待下載", text_color=t["status_warn"])

        if status.recorder_ready:
            self.recorder_core_lbl.configure(text="螢幕錄影：已就緒", text_color=t["status_ok"])
        else:
            self.recorder_core_lbl.configure(text="螢幕錄影：待下載", text_color=t["status_warn"])

    def _recheck_all_cores(self) -> None:
        self.binary_manager.invalidate_cache()
        status = self.binary_manager.check_status(force=True)
        self._refresh_sidebar_status()
        self.tab_android.refresh_core_banner()
        self.tab_ios.refresh_environment()
        self.tab_recorder.refresh_core_banner()
        self.log_manager.append(
            f"核心檢測完成 | {status.android_message} | {status.ios_message} | {status.recorder_message}"
        )

    def _is_own_adb_running(self) -> bool:
        """僅偵測由本程式 bin/scrcpy 啟動的 adb.exe，避免誤關 Android Studio 等其他工具的 adb server。"""
        scrcpy_dir = self.binary_manager.scrcpy_dir.resolve()
        try:
            for p in psutil.process_iter(["name", "exe"]):
                if (p.info.get("name") or "").lower() != "adb.exe":
                    continue
                exe_path = p.info.get("exe")
                if exe_path:
                    try:
                        if Path(exe_path).resolve().is_relative_to(scrcpy_dir):
                            return True
                    except Exception:
                        pass
        except Exception:
            pass
        return False

    def _finalize_destroy(self) -> None:
        self.log_manager.shutdown()
        try:
            self.destroy()
        except Exception:
            pass

    def _on_close(self) -> None:
        """關閉主視窗前安全停止定時器、錄影／合成與子程序；收尾期間鎖住介面避免重複操作。"""
        if self._closing:
            return

        recording_busy = self.recorder_engine.is_busy()
        if recording_busy:
            confirm = messagebox.askyesno(
                "正在錄製或封裝電腦螢幕影片",
                "目前正在錄製或合成電腦螢幕影片，關閉前將自動安全完成 MP4 儲存。\n確定要結束並關閉程式嗎？",
                parent=self,
            )
            if not confirm:
                return

        self._closing = True
        self.tab_android.stop_polling()
        self.tab_recorder.stop_timer_only()

        own_adb_running = self._is_own_adb_running()
        has_active_jobs = (
            recording_busy
            or self.android_engine.is_mirroring()
            or self.ios_engine.is_running()
            or own_adb_running
        )
        if not has_active_jobs:
            self._finalize_destroy()
            return

        self.title(f"{APP_NAME} — 正在安全儲存與結束，請稍候...")
        # 收尾期間隱藏主內容區並顯示提示，避免使用者於背景收尾時再觸發新錄影或投影
        try:
            self.body_frame.pack_forget()
            closing_lbl = ctk.CTkLabel(
                self,
                text="正在安全封裝錄影與結束背景連線，完成後將自動關閉視窗，請稍候...",
                font=(FONT_FAMILY, 14, "bold"),
                text_color=self.theme["text_primary"],
            )
            closing_lbl.pack(expand=True)
        except Exception:
            pass

        def _cleanup_worker() -> None:
            try:
                if self.recorder_engine.is_recording():
                    self.recorder_engine.stop_recording(log_cb=self.log_manager.append)
                elif self.recorder_engine.is_busy():
                    self.recorder_engine.wait_until_idle(timeout=300)
                if self.android_engine.is_mirroring():
                    self.android_engine.stop_all(log_cb=self.log_manager.append)
                if self.ios_engine.is_running():
                    self.ios_engine.stop_airplay(log_cb=self.log_manager.append)
                if own_adb_running:
                    self.android_engine.kill_adb_server()
            finally:
                try:
                    self.after(0, self._finalize_destroy)
                except Exception:
                    pass

        threading.Thread(target=_cleanup_worker, daemon=True).start()
