"""QPhoneMirror 免偵錯備援通道：一鍵開啟 Windows 原生無線投影（Samsung Smart View / Miracast）。"""

from __future__ import annotations

import os
import subprocess
import sys
from typing import Callable, Optional

LogCallback = Optional[Callable[[str], None]]


def open_windows_wireless_display(log_cb: LogCallback = None) -> tuple[bool, str]:
    """
    一鍵喚起 Windows 內建的「無線顯示器（投影到此電腦）」接收視窗。
    讓未開啟 USB 偵錯的使用者可以直接從手機下拉選單點選 Smart View / 螢幕投放 進行無線投影。
    """
    if sys.platform != "win32":
        msg = "此快速通道僅支援 Windows 系統。"
        if log_cb:
            log_cb(msg)
        return False, msg

    app_uri = "shell:AppsFolder\\Microsoft.PPIProjection_cw5n1h2txyewy!Microsoft.PPIProjection"
    try:
        os.startfile("ms-settings:project")
        if log_cb:
            log_cb("已開啟 Windows「投影到此電腦」設定頁。")
            log_cb("請點選設定頁中的「啟動『無線顯示器』應用程式」，再從手機下拉選單點選 Smart View 進行無線投影。")
        return (
            True,
            "已開啟 Windows「投影到此電腦」設定頁。\n"
            "點選裡面的「啟動『無線顯示器』應用程式」，再用手機下拉選單的 Smart View 搜尋這台電腦即可免設定投影。",
        )
    except Exception:
        try:
            subprocess.Popen(["explorer.exe", app_uri])
            msg = "已嘗試啟動 Windows 無線顯示器接收視窗。"
            if log_cb:
                log_cb(msg)
            return True, msg
        except Exception as exc:
            msg = f"無法自動開啟 Windows 無線投影設定：{exc}"
            if log_cb:
                log_cb(msg)
            return False, msg
