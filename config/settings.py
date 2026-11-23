"""QPhoneMirror 路徑解析、版本常數與使用者偏好設定管理。"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Callable, Dict, Optional

APP_NAME = "QPhoneMirror"
APP_VERSION = "V20261124"
COPYRIGHT_YEAR = "2026"
STUDIO_NAME = "Studio0808 智造實驗室"
STUDIO_URL = "https://begin0808.github.io/studio0808/"
FACEBOOK_URL = "https://www.facebook.com/begin.li.1/"
GITHUB_URL = "https://github.com/begin0808/QPhoneMirror"


def get_app_dir() -> Path:
    """回傳應用程式根目錄（支援一般 Python 執行與 PyInstaller 打包後的 .exe）。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def get_bin_dir() -> Path:
    """外部開源核心執行檔目錄。"""
    return get_app_dir() / "bin"


def get_scrcpy_dir() -> Path:
    """Scrcpy 與 ADB 核心存放目錄。"""
    return get_bin_dir() / "scrcpy"


def get_uxplay_dir() -> Path:
    """UxPlay (AirPlay 接收器) 核心存放目錄。"""
    return get_bin_dir() / "uxplay"


def get_ffmpeg_dir() -> Path:
    """FFmpeg 電腦螢幕錄影核心存放目錄。"""
    return get_bin_dir() / "ffmpeg"


def get_default_captures_dir() -> Path:
    """預設螢幕截圖與錄影輸出目錄。"""
    return get_app_dir() / "captures"


def get_settings_path() -> Path:
    """設定檔 settings.json 的存放路徑。"""
    return get_app_dir() / "config" / "settings.json"


def is_dir_writable(target_dir: Path) -> bool:
    """驗證指定資料夾是否可建立且具備寫入權限（不含殘留測試檔）。"""
    try:
        target_dir.mkdir(parents=True, exist_ok=True)
        probe = target_dir / f".qpm_write_probe_{os.getpid()}"
        probe.write_bytes(b"ok")
        probe.unlink(missing_ok=True)
        return True
    except Exception:
        return False


def format_captures_dir_for_storage(chosen_dir: Path) -> str:
    """若路徑位於程式目錄底下則改存相對路徑，方便整個免安裝資料夾跨電腦搬移。"""
    app_dir = get_app_dir().resolve()
    default_dir = get_default_captures_dir().resolve()
    resolved = chosen_dir.resolve()
    if resolved == default_dir:
        return ""
    try:
        rel = resolved.relative_to(app_dir)
        return str(rel)
    except ValueError:
        return str(resolved)


def resolve_captures_dir(log_cb: Optional[Callable[[str], None]] = None) -> Path:
    """回傳可用且可寫入的截圖與錄影資料夾；若自訂路徑失效或唯讀則自動回退至預設 captures/。"""
    default_dir = get_default_captures_dir()
    settings_path = get_settings_path()
    custom = ""
    if settings_path.is_file():
        try:
            raw = json.loads(settings_path.read_text(encoding="utf-8"))
            if isinstance(raw, dict):
                custom = str(raw.get("captures_dir", "")).strip()
        except Exception:
            pass

    if custom:
        raw_path = Path(custom)
        is_abs = raw_path.is_absolute()
        candidate = raw_path if is_abs else (get_app_dir() / raw_path)
        # 絕對路徑若在新電腦不存在則不默默重建舊路徑，安全回退預設目錄並提示
        if is_abs:
            exists_ok = False
            try:
                exists_ok = candidate.is_dir()
            except Exception:
                exists_ok = False
            if exists_ok and is_dir_writable(candidate):
                return candidate
        else:
            if is_dir_writable(candidate):
                return candidate
        if log_cb:
            try:
                log_cb(f"自訂儲存資料夾不存在或沒有寫入權限（{candidate}），已自動回退至預設目錄：{default_dir}")
            except Exception:
                pass

    default_dir.mkdir(parents=True, exist_ok=True)
    return default_dir


def get_captures_dir() -> Path:
    """回傳目前有效的螢幕截圖與錄影輸出目錄（優先採用可寫入的使用者自訂路徑）。"""
    return resolve_captures_dir()


DEFAULT_SETTINGS: Dict[str, Any] = {
    "theme": "pastel_cute",
    "captures_dir": "",
    "android_resolution": "1080p",
    "android_fps": 60,
    "android_bitrate": "8M",
    "android_turn_screen_off": True,
    "android_stay_awake": True,
    "android_audio": True,
    "android_always_on_top": False,
    "android_record_video": False,
    "android_auto_detect": True,
    "android_last_ip": "",
    "android_wifi_port": 5555,
    "ios_airplay_name": "QPhoneMirror-電腦",
    "ios_fps": 60,
    "ios_resolution": "1920x1080",
    "ios_audio": True,
    "recorder_mode": "fullscreen",
    "recorder_region": [100, 100, 1280, 720],
    "recorder_fps": 30,
    "recorder_quality": "high",
    "recorder_draw_mouse": True,
    "recorder_mic_enabled": False,
    "recorder_mic_device": "",
    "recorder_system_audio": False,
    "recorder_minimize_on_start": False,
}


class SettingsManager:
    """負責讀取與儲存使用者偏好設定（settings.json）。"""

    def __init__(self, settings_path: Path | None = None) -> None:
        self.path = settings_path or get_settings_path()
        self._data: Dict[str, Any] = dict(DEFAULT_SETTINGS)
        self.load()

    def load(self) -> Dict[str, Any]:
        """從磁碟載入設定；若檔案損毀則先備份為 .bak 再採用預設值。"""
        self._data = dict(DEFAULT_SETTINGS)
        if self.path.exists():
            try:
                raw = json.loads(self.path.read_text(encoding="utf-8"))
                if isinstance(raw, dict):
                    self._data.update(raw)
                else:
                    raise ValueError("settings root is not a dict")
            except Exception:
                try:
                    bak = self.path.with_suffix(".json.bak")
                    os.replace(self.path, bak)
                except Exception:
                    pass
                self.save()
        else:
            self.save()
        return dict(self._data)

    def save(self) -> bool:
        """以原子寫入方式將目前設定儲存至 settings.json，避免寫入中斷造成設定檔毀損。"""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(".json.tmp")
            tmp_path.write_text(
                json.dumps(self._data, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            os.replace(tmp_path, self.path)
            return True
        except Exception:
            return False

    def get(self, key: str, default: Any = None) -> Any:
        return self._data.get(key, DEFAULT_SETTINGS.get(key, default))

    def set(self, key: str, value: Any, auto_save: bool = True) -> None:
        self._data[key] = value
        if auto_save:
            self.save()

    def update(self, values: Dict[str, Any], auto_save: bool = True) -> None:
        self._data.update(values)
        if auto_save:
            self.save()

    @property
    def data(self) -> Dict[str, Any]:
        return dict(self._data)
