"""QPhoneMirror 跨平台手機投影工具程式入口點。"""

from __future__ import annotations

import sys
from pathlib import Path

# 確保專案根目錄在模組搜尋路徑中
ROOT_DIR = Path(__file__).resolve().parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import customtkinter as ctk

from ui.app_window import QPhoneMirrorApp


def main() -> None:
    ctk.set_default_color_theme("green")
    app = QPhoneMirrorApp()
    app.mainloop()


if __name__ == "__main__":
    main()
