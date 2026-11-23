"""QPhoneMirror 完整操作說明分頁（支援滑鼠選取、Ctrl+C 與右鍵複製文字）。"""

from __future__ import annotations

import tkinter as tk
import tkinter.font as tkfont
from typing import Any, Dict, List, Tuple

import customtkinter as ctk

from config.themes import CORNER_CARD, FONT_FAMILY

GUIDE_CARDS: List[Tuple[str, str]] = [
    (
        "1. 首次使用：三大功能核心皆支援「一鍵下載並安裝」",
        "QPhoneMirror 採輕量化架構，三項核心僅需在首次使用時各點一次「一鍵下載並安裝核心」，完成後皆可永久離線使用：\n"
        "  • 安卓投影核心（Scrcpy + ADB）：自動安裝至 bin/scrcpy，支援有線與無線投影、滑鼠鍵盤操作、截圖與傳檔。\n"
        "  • 蘋果 AirPlay 核心（UxPlay 攜帶版）：自動安裝至 bin/uxplay，內建 mDNS 廣播服務，免額外安裝 Bonjour。\n"
        "  • 電腦螢幕錄影核心（FFmpeg）：自動提取 ffmpeg.exe 至 bin/ffmpeg，支援高畫質 MP4 錄製與雙軌音訊合成。\n"
        "  ※ 若需將軟體複製給其他電腦使用，只要先在自己電腦完成核心下載，再整個資料夾壓縮分享即可開箱即用。",
    ),
    (
        "2. 安卓手機：首次開啟「USB 偵錯」與有線投影",
        "只需要設定一次，手機端完全不須安裝任何程式：\n"
        "  (1) 打開手機「設定」→ 進入「關於手機」→「軟體資訊」（部分廠牌直接位於關於手機內）。\n"
        "  (2) 找到「版本號碼」，連續快速點選 7 下，輸入解鎖密碼後即啟用開發人員模式。\n"
        "  (3) 回到設定主頁最下方，進入「開發人員選項」→ 開啟「USB 偵錯」。\n"
        "  (4) 用 USB 傳輸線接上電腦，手機彈出「允許 USB 偵錯嗎？」時，勾選「一律允許這台電腦」並點選「允許」。\n"
        "  (5) 程式開啟「自動感應手機連線」時會自動跳出手機型號，直接按下「開始投影」即可用滑鼠鍵盤操作手機。",
    ),
    (
        "3. 安卓手機：兩種 Wi-Fi 無線投影方式（插線轉無線 ／ 免插線配對碼）",
        "方式 A — 插線轉無線（最推薦，步驟最少）：\n"
        "  (1) 確認手機與電腦連接同一個 Wi-Fi 網路，先接上 USB 線並確認已偵測到手機。\n"
        "  (2) 按下「插線轉無線」，顯示成功後程式會自動選取 [Wi-Fi] 裝置，拔除傳輸線即可直接開始無線投影。\n"
        "方式 B — 免插線 6 位數配對碼（Android 11 以上，手邊沒線也能連）：\n"
        "  (1) 於手機「開發人員選項 → 無線偵錯」開啟開關，點進「使用配對碼配對裝置」。\n"
        "  (2) 在「安卓手機投影」按下「免插線配對碼設定」，輸入配對 IP:連接埠與 6 位數配對碼並按下「執行配對」。\n"
        "  (3) 配對成功後，在「Wi-Fi 重連」輸入無線偵錯主畫面的 IP:連接埠並按下「連線 Wi-Fi」即完成連線。",
    ),
    (
        "4. 安卓快捷工具箱：截圖、手機純畫面錄影、無線傳檔與虛擬遙控",
        "手機完成有線或 Wi-Fi 無線連線後，可於「安卓手機投影」直接使用以下工具：\n"
        "  • 手機畫面截圖：按下即擷取手機原解析度 PNG 圖片，自動存至設定好的儲存資料夾。\n"
        "  • 投影同步錄影：開啟步驟 2 的「投影時同步錄製 MP4 影片」再開始投影，關閉投影視窗即自動存檔（錄製手機純畫面）。\n"
        "  • 傳送檔案 / 安裝 APK：支援一次多選電腦照片、PDF 或影片，透過有線或無線直接傳進手機「下載 (Download)」資料夾；若選擇 .apk 檔案則自動安裝。\n"
        "  • 虛擬遙控列：直接點選「返回、主畫面、多工切換、音量 -、音量 +、螢幕開關」操作手機。",
    ),
    (
        "5. 免開啟 USB 偵錯的快速無線投影法（Miracast / Smart View）",
        "若只想快速投放手機畫面觀看、不想進入開發人員選項設定：\n"
        "  (1) 到「安卓手機投影」最下方，按下「開啟無線投影接收」開啟 Windows「投影到此電腦」設定頁。\n"
        "  (2) 點選開啟「無線顯示器」應用程式。\n"
        "  (3) 從手機螢幕上方下拉快捷選單，點選「Smart View」、「螢幕投放」或「無線顯示」，選擇這台電腦即可無線投影。",
    ),
    (
        "6. 蘋果 iPhone / iPad：AirPlay 無線投影步驟",
        "蘋果手機與平板無須更改任何系統設定，也不用安裝任何程式：\n"
        "  (1) 確認 iPhone / iPad 與電腦連接在同一個 Wi-Fi 網路。\n"
        "  (2) 切換至「蘋果 AirPlay」分頁，首次使用按下「一鍵下載並安裝核心」完成安裝。\n"
        "  (3) 按下「開啟 AirPlay 接收服務」啟動接收器。\n"
        "  (4) 從 iPhone / iPad 螢幕右上角往下滑開啟「控制中心」→ 點選「螢幕鏡像輸出」→ 選擇這台電腦名稱，畫面與聲音即刻同步。",
    ),
    (
        "7. 高畫質電腦螢幕錄影（全螢幕、指定程式視窗、框選區域與雙軌收音）",
        "不限於手機投影時使用，隨時可切換至「電腦螢幕錄影」分頁錄製任何電腦操作與教學影片：\n"
        "  • 三種錄影範圍：可選擇「全螢幕錄製」、「指定程式視窗錄製（自動偵測並鎖定開啟中的視窗，防止硬體加速黑畫面）」或「滑鼠框選錄影區域」。\n"
        "  • 雙軌聲音收錄：可獨立勾選「錄製電腦系統聲音（電腦播放的音效與線上會議對方聲音，預設關閉）」與「錄製麥克風旁白（支援耳機麥克風）」，兩者同時開啟會自動無損混音。\n"
        "  • 畫質與存檔位置：提供極致／標準／輕量三段清晰度、30/60 FPS 更新率，並可自由「變更儲存資料夾」（同步套用於所有截圖與錄影）。\n"
        "  • 結束錄影時請按下「停止並儲存 MP4」，系統會完整封裝影片檔尾，確保相容於各大播放器與社群傳送。",
    ),
    (
        "8. 鍵盤快捷鍵與常見問題快速排解（FAQ）",
        "【安卓投影視窗常用快捷鍵】\n"
        "  • Alt + F ：切換全螢幕顯示　　• Alt + O ：關閉手機實體螢幕省電（Alt + Shift + O 重新點亮）\n"
        "  • Alt + H 或滑鼠中鍵 ：回到手機主畫面　　• Alt + B 或滑鼠右鍵 ：返回上一頁　　• Alt + 上 / 下鍵 ：調整手機音量\n"
        "【常見問題排解】\n"
        "  • 找不到安卓手機：請確認傳輸線支援資料傳輸（非純充電線），且手機已開啟 USB 偵錯並點選「允許」。\n"
        "  • 無線連線失敗：請確認手機與電腦在同一個 Wi-Fi 網段，且 Windows 防火牆未封鎖 QPhoneMirror。\n"
        "  • 錄影找不到麥克風或想看詳細錯誤：可點選左側「檢視執行紀錄」開啟獨立紀錄視窗，快速查看連線與收音明細。",
    ),
    (
        "9. 安全性說明：開啟「USB 偵錯」與銀行／證券 App 提醒",
        "部分使用者開啟「USB 偵錯」後，打開股票下單或行動銀行 App 時會看到系統提醒，這是金融資安規範的例行提示，不代表手機中毒或已被入侵：\n"
        "  • 不會憑空遭遠端駭客入侵：Android 具有連線授權保護，接到任何新電腦時，手機必須先解鎖並由你親手點選「允許」才能連線。\n"
        "  • 建議日常習慣（最安心）：平常不投影時可關閉「USB 偵錯」，要用 QPhoneMirror 前再開啟（3 秒即完成、免重開機，且對自己電腦的授權紀錄會保留）。\n"
        "  • 外出與公共網路守則：只在「自己的私人電腦」勾選一律允許；外出充電避免直插不明公用 USB 孔；在公共 Wi-Fi 環境請關閉「無線偵錯」。若曾授權過他人電腦，可於開發人員選項點選「撤銷 USB 偵錯授權」一鍵清除。\n"
        "  • 免開 USB 偵錯替代方案：若只想投放手機畫面觀看、不想受金融 App 提醒干擾，可改用「安卓手機投影」最下方的「開啟無線投影接收（Miracast / Smart View）」。",
    ),
]


class GuideTab(ctk.CTkScrollableFrame):
    """完整操作說明分頁（內文支援滑鼠反白選取、Ctrl+C 複製與右鍵選單複製）。"""

    def __init__(self, master, theme: Dict[str, Any], **kwargs) -> None:
        super().__init__(master, corner_radius=0, **kwargs)
        self._theme = theme
        self._cards: List[Tuple[ctk.CTkFrame, ctk.CTkLabel, ctk.CTkTextbox]] = []
        self._build_ui()
        self.apply_theme(theme)

    def _build_ui(self) -> None:
        self.title_lbl = ctk.CTkLabel(
            self,
            text="操作說明",
            font=(FONT_FAMILY, 19, "bold"),
            anchor="w",
        )
        self.title_lbl.pack(fill="x", padx=12, pady=(0, 1))

        self.subtitle_lbl = ctk.CTkLabel(
            self,
            text="完整功能使用教學與常見問題排解（以下說明文字皆可直接用滑鼠反白選取或按右鍵複製）。",
            font=(FONT_FAMILY, 12),
            anchor="w",
            wraplength=730,
            justify="left",
        )
        self.subtitle_lbl.pack(fill="x", padx=12, pady=(0, 8))

        for header, body in GUIDE_CARDS:
            card = ctk.CTkFrame(self, corner_radius=CORNER_CARD, border_width=2)
            card.pack(fill="x", padx=12, pady=(0, 8))

            h_lbl = ctk.CTkLabel(
                card,
                text=header,
                font=(FONT_FAMILY, 14, "bold"),
                anchor="w",
                wraplength=700,
                justify="left",
            )
            h_lbl.pack(fill="x", padx=14, pady=(8, 3))

            body_box = ctk.CTkTextbox(
                card,
                font=(FONT_FAMILY, 12),
                wrap="word",
                border_width=0,
                corner_radius=0,
                activate_scrollbars=False,
                height=72,
            )
            body_box.insert("1.0", body)
            self._make_selectable_readonly(body_box)
            body_box.pack(fill="x", padx=12, pady=(0, 6))

            body_box.bind("<Configure>", lambda _e, tb=body_box: self._fit_textbox_height(tb))
            self.after(60, lambda tb=body_box: self._fit_textbox_height(tb))

            self._cards.append((card, h_lbl, body_box))

    def _make_selectable_readonly(self, tb: ctk.CTkTextbox) -> None:
        """讓 CTkTextbox 維持唯讀但完全支援滑鼠選取、Ctrl+C、Ctrl+A 與右鍵複製。"""
        inner: tk.Text = tb._textbox

        def _on_key(event: tk.Event) -> str | None:
            ctrl = bool(event.state & 0x4)
            if ctrl and event.keysym.lower() in ("c", "a"):
                return None
            if event.keysym in (
                "Left",
                "Right",
                "Up",
                "Down",
                "Home",
                "End",
                "Prior",
                "Next",
                "Shift_L",
                "Shift_R",
                "Control_L",
                "Control_R",
            ):
                return None
            return "break"

        def _show_context_menu(event: tk.Event) -> None:
            menu = tk.Menu(inner, tearoff=0)
            menu.add_command(label="複製選取文字", command=lambda: self._copy_selection(inner))
            menu.add_command(label="全選此段說明", command=lambda: inner.tag_add("sel", "1.0", "end-1c"))
            try:
                menu.tk_popup(event.x_root, event.y_root)
            finally:
                menu.grab_release()

        inner.bind("<Key>", _on_key)
        inner.bind("<Button-3>", _show_context_menu)
        inner.bind("<Button-2>", lambda _e: "break")
        inner.bind("<MouseWheel>", self._on_child_mousewheel)

    def _on_child_mousewheel(self, event: tk.Event) -> str:
        try:
            self._parent_canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        except Exception:
            pass
        return "break"

    def _copy_selection(self, inner: tk.Text) -> None:
        try:
            text = inner.get("sel.first", "sel.last")
        except tk.TclError:
            text = inner.get("1.0", "end-1c")
        if text:
            self.clipboard_clear()
            self.clipboard_append(text)

    @staticmethod
    def _fit_textbox_height(tb: ctk.CTkTextbox) -> None:
        """依據字型實際行高、換行行數與 Windows DPI 縮放精準計算高度，底部僅保留約一行留白。"""
        try:
            inner: tk.Text = tb._textbox
            res = inner.count("1.0", "end", "displaylines")
            display_lines = int(res[0]) if isinstance(res, tuple) else int(res or 1)
            linespace = max(16, tkfont.Font(font=inner.cget("font")).metrics("linespace"))
            scale = max(1.0, float(tb._get_widget_scaling()))
            new_height = max(36, int((display_lines * linespace) / scale) + 12)
            if abs(tb.cget("height") - new_height) > 2:
                tb.configure(height=new_height)
        except Exception:
            pass

    def apply_theme(self, theme: Dict[str, Any]) -> None:
        self._theme = theme
        self.configure(
            fg_color=theme["bg_main"],
            scrollbar_button_color=theme["border"],
            scrollbar_button_hover_color=theme["accent_primary"],
        )
        self.title_lbl.configure(text_color=theme["text_primary"])
        self.subtitle_lbl.configure(text_color=theme["text_secondary"])

        palette = theme.get("guide_cards", [(theme["bg_card"], theme["border"])])
        for idx, (card, h_lbl, body_box) in enumerate(self._cards):
            bg, border = palette[idx % len(palette)]
            card.configure(fg_color=bg, border_color=border)
            h_lbl.configure(text_color=theme["text_primary"])
            body_box.configure(fg_color=bg, text_color=theme["text_secondary"])
            try:
                body_box._textbox.configure(
                    selectbackground=theme["accent_primary"],
                    selectforeground=theme["text_on_accent"],
                )
            except Exception:
                pass
