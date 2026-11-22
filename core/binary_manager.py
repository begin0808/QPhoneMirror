"""QPhoneMirror 外部核心執行檔檢測與一鍵下載安裝器 (Scrcpy / ADB / UxPlay / FFmpeg)。"""

from __future__ import annotations

from datetime import datetime
import hashlib
import os
import re
import shutil
import tempfile
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import requests

from config.settings import get_bin_dir, get_ffmpeg_dir, get_scrcpy_dir, get_uxplay_dir

ProgressCallback = Optional[Callable[[float, str], None]]
LogCallback = Optional[Callable[[str], None]]


@dataclass
class EngineBinaryStatus:
    """紀錄 Android、iOS 與電腦螢幕錄影三大核心執行檔的就緒狀態。"""

    android_ready: bool
    scrcpy_path: Optional[Path]
    adb_path: Optional[Path]
    ios_ready: bool
    uxplay_path: Optional[Path]
    android_message: str
    ios_message: str
    recorder_ready: bool = False
    ffmpeg_path: Optional[Path] = None
    recorder_message: str = ""


class BinaryManager:
    """負責檢測、定位並一鍵下載設定 bin/ 下的 scrcpy、adb、uxplay 與 ffmpeg。"""

    SCRCPY_RELEASES_API = "https://api.github.com/repos/Genymobile/scrcpy/releases/latest"
    SCRCPY_RELEASES_LATEST_WEB = "https://github.com/Genymobile/scrcpy/releases/latest"
    UXPLAY_RELEASES_API = "https://api.github.com/repos/leapbtw/uxplay-windows/releases/latest"
    UXPLAY_RELEASES_LIST_API = "https://api.github.com/repos/leapbtw/uxplay-windows/releases"
    UXPLAY_RELEASES_WEB = "https://github.com/leapbtw/uxplay-windows/releases"
    UXPLAY_DIRECT_FALLBACK_URL = (
        "https://github.com/leapbtw/uxplay-windows/releases/latest/download/uxplay-windows.zip"
    )
    FFMPEG_RELEASES_API = "https://api.github.com/repos/BtbN/FFmpeg-Builds/releases/latest"
    FFMPEG_FALLBACK_URL = "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip"

    def __init__(self) -> None:
        self.bin_dir = get_bin_dir()
        self.scrcpy_dir = get_scrcpy_dir()
        self.uxplay_dir = get_uxplay_dir()
        self.ffmpeg_dir = get_ffmpeg_dir()
        self._cached_status: Optional[EngineBinaryStatus] = None
        self._ensure_dirs()

    def _ensure_dirs(self) -> None:
        self.scrcpy_dir.mkdir(parents=True, exist_ok=True)
        self.uxplay_dir.mkdir(parents=True, exist_ok=True)
        self.ffmpeg_dir.mkdir(parents=True, exist_ok=True)

    def invalidate_cache(self) -> None:
        """清除核心檢測快取，使下次 check_status() 重新掃描磁碟。"""
        self._cached_status = None

    def _find_in_local_dir(self, local_dir: Path, exe_name: str) -> Optional[Path]:
        direct = local_dir / exe_name
        if direct.is_file():
            return direct
        if local_dir.exists():
            for match in local_dir.rglob(exe_name):
                if match.is_file():
                    return match
        return None

    def find_executable(self, local_dir: Path, exe_name: str) -> Optional[Path]:
        """優先在專屬 bin/ 子目錄尋找執行檔，找不到時再回退系統 PATH。"""
        local = self._find_in_local_dir(local_dir, exe_name)
        if local:
            return local
        from_path = shutil.which(exe_name)
        if from_path:
            return Path(from_path)
        return None

    def get_scrcpy_path(self) -> Optional[Path]:
        return self.find_executable(self.scrcpy_dir, "scrcpy.exe")

    def get_adb_path(self) -> Optional[Path]:
        return self.find_executable(self.scrcpy_dir, "adb.exe")

    def get_uxplay_path(self) -> Optional[Path]:
        """優先在 bin/uxplay 尋找攜帶版或命令列版執行檔，本機找不到時才回退系統 PATH。"""
        candidates = ("uxplay.exe", "uxplay-windows.exe", "UxPlayWindows.exe", "uxplay-studio.exe")
        # 1. 優先檢查本機 bin/uxplay/，避免系統 PATH 意外蓋過攜帶版核心
        for exe_name in candidates:
            found = self._find_in_local_dir(self.uxplay_dir, exe_name)
            if found:
                return found
        if self.uxplay_dir.exists():
            for match in self.uxplay_dir.rglob("*.exe"):
                low = match.name.lower()
                if "uxplay" in low and "unins" not in low:
                    return match
        # 2. 最後才回退系統 PATH
        for exe_name in candidates:
            from_path = shutil.which(exe_name)
            if from_path:
                return Path(from_path)
        return None

    def get_uxplay_mode(self) -> str:
        """回傳已安裝 UxPlay 核心類型：'cli'、'gui' 或 'none'。"""
        path = self.get_uxplay_path()
        if not path:
            return "none"
        if path.name.lower() == "uxplay.exe":
            return "cli"
        return "gui"

    def get_ffmpeg_path(self) -> Optional[Path]:
        return self.find_executable(self.ffmpeg_dir, "ffmpeg.exe")

    def check_status(self, force: bool = False) -> EngineBinaryStatus:
        """回傳 Android、iOS 與電腦螢幕錄影核心的就緒狀態（預設使用快取避免背景頻繁 rglob）。"""
        if not force and self._cached_status is not None:
            # 快速確認快取的執行檔路徑是否仍存在
            c = self._cached_status
            android_ok = (not c.android_ready) or (
                c.scrcpy_path is not None
                and c.scrcpy_path.is_file()
                and c.adb_path is not None
                and c.adb_path.is_file()
            )
            ios_ok = (not c.ios_ready) or (c.uxplay_path is not None and c.uxplay_path.is_file())
            rec_ok = (not c.recorder_ready) or (c.ffmpeg_path is not None and c.ffmpeg_path.is_file())
            if android_ok and ios_ok and rec_ok:
                return c

        scrcpy = self.get_scrcpy_path()
        adb = self.get_adb_path()
        uxplay = self.get_uxplay_path()
        ffmpeg = self.get_ffmpeg_path()

        android_ready = bool(scrcpy and adb)
        ios_ready = bool(uxplay)
        recorder_ready = bool(ffmpeg)

        if android_ready:
            android_msg = "Android 核心 (Scrcpy + ADB) 已就緒"
        else:
            missing = []
            if not scrcpy:
                missing.append("scrcpy.exe")
            if not adb:
                missing.append("adb.exe")
            android_msg = f"尚未安裝 Android 核心（缺少 {', '.join(missing)}），點選即可自動下載"

        if ios_ready:
            ios_msg = "iPhone AirPlay 核心 (UxPlay) 已就緒"
        else:
            ios_msg = "尚未安裝 iPhone AirPlay 核心，點選即可一鍵下載"

        if recorder_ready:
            recorder_msg = "電腦螢幕錄影核心 (FFmpeg) 已就緒"
        else:
            recorder_msg = "尚未安裝 FFmpeg 錄影核心，點選即可自動下載"

        status = EngineBinaryStatus(
            android_ready=android_ready,
            scrcpy_path=scrcpy,
            adb_path=adb,
            ios_ready=ios_ready,
            uxplay_path=uxplay,
            android_message=android_msg,
            ios_message=ios_msg,
            recorder_ready=recorder_ready,
            ffmpeg_path=ffmpeg,
            recorder_message=recorder_msg,
        )
        self._cached_status = status
        return status

    @staticmethod
    def _format_github_rate_limit(resp: requests.Response) -> Optional[str]:
        if resp.status_code == 403 and resp.headers.get("X-RateLimit-Remaining") == "0":
            reset_raw = resp.headers.get("X-RateLimit-Reset", "")
            try:
                reset_dt = datetime.fromtimestamp(int(reset_raw))
                return f"GitHub 暫時限制查詢次數，將於 {reset_dt.strftime('%H:%M')} 後恢復（正在自動切換備援載點）。"
            except Exception:
                return "GitHub 暫時限制查詢次數（正在自動切換備援載點）。"
        return None

    def _stream_download_to_temp(
        self,
        url: str,
        timeout: int,
        progress_start: float,
        progress_span: float,
        expected_digest: str = "",
        progress_cb: ProgressCallback = None,
    ) -> Path:
        """串流下載檔案至 bin/ 暫存檔（避免數百 MB 載入記憶體），並依需要驗證 SHA-256。"""
        self._ensure_dirs()
        tmp_fd, tmp_name = tempfile.mkstemp(prefix=".qpm_dl_", suffix=".zip", dir=str(self.bin_dir))
        os.close(tmp_fd)
        tmp_path = Path(tmp_name)

        hasher = hashlib.sha256() if expected_digest.startswith("sha256:") else None
        try:
            with requests.get(
                url,
                headers={"User-Agent": "QPhoneMirror"},
                stream=True,
                timeout=timeout,
            ) as dl:
                dl.raise_for_status()
                total_size = int(dl.headers.get("content-length", 0))
                downloaded = 0
                with open(tmp_path, "wb") as out_f:
                    for chunk in dl.iter_content(chunk_size=131072):
                        if not chunk:
                            continue
                        out_f.write(chunk)
                        if hasher is not None:
                            hasher.update(chunk)
                        downloaded += len(chunk)
                        if total_size > 0:
                            ratio = progress_start + progress_span * min(downloaded / total_size, 1.0)
                            mb_done = downloaded / (1024 * 1024)
                            mb_total = total_size / (1024 * 1024)
                            self._emit(progress_cb, ratio, f"下載中 {mb_done:.1f} / {mb_total:.1f} MB...")

            if hasher is not None:
                expected_hex = expected_digest.split(":", 1)[1].strip().lower()
                actual_hex = hasher.hexdigest().lower()
                if expected_hex and actual_hex != expected_hex:
                    raise ValueError("檔案完整性驗證失敗（SHA-256 不符），請重新下載。")
            return tmp_path
        except Exception:
            tmp_path.unlink(missing_ok=True)
            raise

    def download_scrcpy(
        self,
        progress_cb: ProgressCallback = None,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """從 GitHub 官方最新 Release 自動下載並解壓縮 scrcpy (含 adb) 到 bin/scrcpy/（含免 API 限流備援）。"""
        self._ensure_dirs()
        tmp_zip: Optional[Path] = None
        try:
            self._emit(progress_cb, 0.05, "正在向 GitHub 查詢最新版 Scrcpy 核心...")
            self._log(log_cb, "正在查詢 Genymobile/scrcpy 最新正式版...")

            download_url = ""
            asset_name = ""
            expected_digest = ""
            tag = "latest"

            try:
                resp = requests.get(
                    self.SCRCPY_RELEASES_API,
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "QPhoneMirror"},
                    timeout=15,
                )
                rate_msg = self._format_github_rate_limit(resp)
                if rate_msg:
                    self._log(log_cb, rate_msg)
                elif resp.status_code == 200:
                    release = resp.json()
                    tag = release.get("tag_name", "latest")
                    for asset in release.get("assets", []):
                        name = str(asset.get("name", ""))
                        if "win64" in name.lower() and name.lower().endswith(".zip"):
                            download_url = asset["browser_download_url"]
                            asset_name = name
                            expected_digest = str(asset.get("digest", "") or "")
                            break
            except Exception as api_exc:
                self._log(log_cb, f"GitHub API 查詢受限或逾時（{api_exc}），改用直連備援網址...")

            # 免 API 限流備援：透過 /releases/latest 網頁轉址取得版號並直接組出下載連結
            if not download_url:
                web_resp = requests.get(
                    self.SCRCPY_RELEASES_LATEST_WEB,
                    headers={"User-Agent": "QPhoneMirror"},
                    allow_redirects=True,
                    timeout=15,
                )
                web_resp.raise_for_status()
                if "/releases/tag/" in web_resp.url:
                    tag = web_resp.url.rstrip("/").split("/releases/tag/")[-1]
                    asset_name = f"scrcpy-win64-{tag}.zip"
                    download_url = f"https://github.com/Genymobile/scrcpy/releases/download/{tag}/{asset_name}"

            if not download_url:
                msg = "找不到適用於 Windows 64 位元的 Scrcpy 壓縮檔，請稍後再試。"
                self._log(log_cb, msg)
                return False, msg

            self._log(log_cb, f"開始下載 {asset_name} ({tag})...")
            self._emit(progress_cb, 0.12, f"正在下載 {asset_name}...")

            tmp_zip = self._stream_download_to_temp(
                download_url,
                timeout=90,
                progress_start=0.12,
                progress_span=0.70,
                expected_digest=expected_digest,
                progress_cb=progress_cb,
            )

            self._emit(progress_cb, 0.85, "正在解壓縮 Scrcpy 與 ADB 核心檔案...")
            self._log(log_cb, "正在解壓縮檔案至 bin/scrcpy/ ...")

            with open(tmp_zip, "rb") as f:
                self._extract_zip_flattened(f, self.scrcpy_dir)

            self.invalidate_cache()
            status = self.check_status(force=True)
            if status.android_ready:
                self._emit(progress_cb, 1.0, f"Scrcpy {tag} 安裝完成！")
                msg = f"Android 核心 Scrcpy {tag}（含 ADB）已自動安裝完成。"
                self._log(log_cb, msg)
                return True, msg

            msg = "解壓縮完成，但未在資料夾中找到 scrcpy.exe / adb.exe。"
            self._log(log_cb, msg)
            return False, msg

        except PermissionError:
            msg = "部分核心檔案正在執行中，請先停止所有安卓投影視窗後再重新安裝。"
            self._log(log_cb, msg)
            return False, msg
        except requests.RequestException as exc:
            msg = f"網路連線失敗，無法自動下載 Scrcpy：{exc}"
            self._log(log_cb, msg)
            return False, msg
        except Exception as exc:
            msg = f"自動安裝 Scrcpy 時發生錯誤：{exc}"
            self._log(log_cb, msg)
            return False, msg
        finally:
            if tmp_zip is not None:
                tmp_zip.unlink(missing_ok=True)

    def download_ffmpeg(
        self,
        progress_cb: ProgressCallback = None,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """從官方開源發布庫自動下載穩定版 Windows FFmpeg，僅提取 ffmpeg.exe 至 bin/ffmpeg/。"""
        self._ensure_dirs()
        tmp_zip: Optional[Path] = None
        try:
            self._emit(progress_cb, 0.05, "正在查詢最新版 FFmpeg 錄影核心...")
            self._log(log_cb, "正在查詢 BtbN/FFmpeg-Builds 最新 Windows 64 位元穩定版...")

            download_url = ""
            asset_name = "ffmpeg-win64-gpl.zip"
            expected_digest = ""
            try:
                resp = requests.get(
                    self.FFMPEG_RELEASES_API,
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "QPhoneMirror"},
                    timeout=15,
                )
                rate_msg = self._format_github_rate_limit(resp)
                if rate_msg:
                    self._log(log_cb, rate_msg)
                elif resp.status_code == 200:
                    assets = resp.json().get("assets", [])
                    stable_candidates = []
                    fallback_candidates = []
                    for asset in assets:
                        name = str(asset.get("name", ""))
                        low = name.lower()
                        if "win64-gpl" in low and "shared" not in low and low.endswith(".zip"):
                            if low.startswith("ffmpeg-n"):
                                stable_candidates.append(asset)
                            else:
                                fallback_candidates.append(asset)
                    # 優先選最新穩定版本（以數字版號排序，正確處理 n10 > n9），次選 master
                    chosen_asset = None
                    if stable_candidates:
                        def _ver_key(a):
                            m = re.search(r"ffmpeg-n(\d+)\.(\d+)(?:\.(\d+))?", str(a.get("name", "")).lower())
                            if m:
                                return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0))
                            return (0, 0, 0)

                        stable_candidates.sort(key=_ver_key, reverse=True)
                        chosen_asset = stable_candidates[0]
                    elif fallback_candidates:
                        chosen_asset = fallback_candidates[0]
                    if chosen_asset:
                        download_url = chosen_asset["browser_download_url"]
                        asset_name = chosen_asset["name"]
                        expected_digest = str(chosen_asset.get("digest", "") or "")
            except Exception:
                pass

            if not download_url:
                download_url = self.FFMPEG_FALLBACK_URL
                asset_name = "ffmpeg-release-essentials.zip"
                expected_digest = ""
                self._log(log_cb, "改用 gyan.dev 官方備援載點下載 FFmpeg...")

            self._log(log_cb, f"開始下載 {asset_name} ...")
            self._emit(progress_cb, 0.12, f"正在下載 {asset_name}...")

            tmp_zip = self._stream_download_to_temp(
                download_url,
                timeout=240,
                progress_start=0.12,
                progress_span=0.72,
                expected_digest=expected_digest,
                progress_cb=progress_cb,
            )

            self._emit(progress_cb, 0.88, "正在提取 ffmpeg.exe 至 bin/ffmpeg/ ...")
            self._log(log_cb, "正在從壓縮檔僅提取 ffmpeg.exe...")

            extracted = False
            target_exe = self.ffmpeg_dir / "ffmpeg.exe"
            tmp_exe = self.ffmpeg_dir / "ffmpeg.exe.tmp"
            with zipfile.ZipFile(tmp_zip, "r") as zf:
                for member in zf.infolist():
                    if member.is_dir():
                        continue
                    if Path(member.filename).name.lower() == "ffmpeg.exe":
                        with zf.open(member, "r") as src, open(tmp_exe, "wb") as dst:
                            shutil.copyfileobj(src, dst)
                        os.replace(tmp_exe, target_exe)
                        extracted = True
                        break

            self.invalidate_cache()
            if extracted and target_exe.is_file():
                self._emit(progress_cb, 1.0, "FFmpeg 錄影核心安裝完成！")
                msg = "電腦螢幕錄影核心 (FFmpeg) 已安裝完成，可立即開始高畫質錄影。"
                self._log(log_cb, msg)
                return True, msg

            msg = "壓縮檔內找不到 ffmpeg.exe，請稍後再試。"
            self._log(log_cb, msg)
            return False, msg

        except PermissionError:
            msg = "ffmpeg.exe 目前正在執行中，請先停止錄影後再重新安裝。"
            self._log(log_cb, msg)
            return False, msg
        except requests.RequestException as exc:
            msg = f"網路連線失敗，無法自動下載 FFmpeg：{exc}"
            self._log(log_cb, msg)
            return False, msg
        except Exception as exc:
            msg = f"自動安裝 FFmpeg 時發生錯誤：{exc}"
            self._log(log_cb, msg)
            return False, msg
        finally:
            if tmp_zip is not None:
                tmp_zip.unlink(missing_ok=True)
            (self.ffmpeg_dir / "ffmpeg.exe.tmp").unlink(missing_ok=True)

    def download_uxplay(
        self,
        progress_cb: ProgressCallback = None,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """從 GitHub 開源專案 leapbtw/uxplay-windows 一鍵下載 Windows 64 位元攜帶版至 bin/uxplay/（含免 API 限流備援）。"""
        self._ensure_dirs()
        tmp_zip: Optional[Path] = None
        try:
            self._emit(progress_cb, 0.05, "正在向 GitHub 查詢最新版 Windows AirPlay 核心...")
            self._log(log_cb, "正在查詢 leapbtw/uxplay-windows 最新攜帶版...")

            download_url = ""
            asset_name = "uxplay-windows.zip"
            expected_digest = ""
            tag = "latest"

            def _pick_x64_zip(assets_list):
                for asset in assets_list:
                    name = str(asset.get("name", "")).lower()
                    if name.endswith(".zip") and "arm64" not in name and "uxplay" in name:
                        return asset
                return None

            try:
                resp = requests.get(
                    self.UXPLAY_RELEASES_API,
                    headers={"Accept": "application/vnd.github+json", "User-Agent": "QPhoneMirror"},
                    timeout=15,
                )
                rate_msg = self._format_github_rate_limit(resp)
                if rate_msg:
                    self._log(log_cb, rate_msg)
                elif resp.status_code == 200:
                    rel = resp.json()
                    tag = rel.get("tag_name", "latest")
                    picked = _pick_x64_zip(rel.get("assets", []))
                    if picked:
                        download_url = picked["browser_download_url"]
                        asset_name = picked["name"]
                        expected_digest = str(picked.get("digest", "") or "")
                if not download_url and not rate_msg:
                    resp_list = requests.get(
                        self.UXPLAY_RELEASES_LIST_API,
                        headers={"Accept": "application/vnd.github+json", "User-Agent": "QPhoneMirror"},
                        timeout=15,
                    )
                    if resp_list.status_code == 200:
                        for rel in resp_list.json():
                            found = _pick_x64_zip(rel.get("assets", []))
                            if found:
                                tag = rel.get("tag_name", "latest")
                                download_url = found["browser_download_url"]
                                asset_name = found["name"]
                                expected_digest = str(found.get("digest", "") or "")
                                break
            except Exception as api_exc:
                self._log(log_cb, f"GitHub API 查詢受限或逾時（{api_exc}），改用直連備援載點...")

            # 免 API 限流備援：直接使用官方 releases/latest/download/uxplay-windows.zip
            if not download_url:
                download_url = self.UXPLAY_DIRECT_FALLBACK_URL
                asset_name = "uxplay-windows.zip"
                expected_digest = ""

            self._log(log_cb, f"開始下載 {asset_name} ({tag})...")
            self._emit(progress_cb, 0.10, f"正在下載 {asset_name}...")

            tmp_zip = self._stream_download_to_temp(
                download_url,
                timeout=240,
                progress_start=0.10,
                progress_span=0.75,
                expected_digest=expected_digest,
                progress_cb=progress_cb,
            )

            self._emit(progress_cb, 0.88, "正在解壓縮 AirPlay 核心檔案至 bin/uxplay/ ...")
            self._log(log_cb, "正在解壓縮檔案至 bin/uxplay/ ...")

            with open(tmp_zip, "rb") as f:
                self._extract_zip_flattened(f, self.uxplay_dir)

            self.invalidate_cache()
            if self.get_uxplay_path():
                self._emit(progress_cb, 1.0, f"AirPlay 核心 ({tag}) 安裝完成！")
                msg = f"蘋果 AirPlay 核心 ({tag}) 已自動安裝完成（內建 mDNS，免額外安裝 Bonjour）。"
                self._log(log_cb, msg)
                return True, msg

            msg = "解壓縮完成但未在資料夾中找到 UxPlay 執行檔，請檢視 bin/uxplay/。"
            self._log(log_cb, msg)
            return False, msg

        except PermissionError:
            msg = "AirPlay 核心正在執行中，請先停止 AirPlay 接收器後再重新安裝。"
            self._log(log_cb, msg)
            return False, msg
        except requests.RequestException as exc:
            msg = f"網路連線失敗，無法自動下載 AirPlay 核心：{exc}"
            self._log(log_cb, msg)
            return False, msg
        except Exception as exc:
            msg = f"自動安裝 AirPlay 核心時發生錯誤：{exc}"
            self._log(log_cb, msg)
            return False, msg
        finally:
            if tmp_zip is not None:
                tmp_zip.unlink(missing_ok=True)

    def import_uxplay_zip(self, zip_path: Path, log_cb: LogCallback = None) -> tuple[bool, str]:
        """允許使用者手動選擇下載好的 UxPlay zip 壓縮檔並自動匯入 bin/uxplay/。"""
        self._ensure_dirs()
        try:
            with open(zip_path, "rb") as f:
                self._extract_zip_flattened(f, self.uxplay_dir)
            self.invalidate_cache()
            if self.get_uxplay_path():
                msg = "已成功匯入 AirPlay 核心，現在可以開始投影 iPhone / iPad。"
                self._log(log_cb, msg)
                return True, msg
            msg = "壓縮檔內找不到 UxPlay 執行檔，請確認選擇的檔案是否正確。"
            self._log(log_cb, msg)
            return False, msg
        except PermissionError:
            msg = "AirPlay 核心檔案正在執行中，請先關閉 AirPlay 接收器後再重新匯入。"
            self._log(log_cb, msg)
            return False, msg
        except Exception as exc:
            msg = f"匯入壓縮檔失敗：{exc}"
            self._log(log_cb, msg)
            return False, msg

    @staticmethod
    def _extract_zip_flattened(file_obj, dest_dir: Path) -> None:
        """解壓縮 zip；若所有檔案都在同一層最外層資料夾內，則自動扁平化展開到 dest_dir，並防範 Zip Slip。"""
        dest_resolved = dest_dir.resolve()
        with zipfile.ZipFile(file_obj) as zf:
            members = [m for m in zf.infolist() if not m.is_dir()]
            top_levels = {Path(m.filename).parts[0] for m in members if Path(m.filename).parts}
            strip_prefix = len(top_levels) == 1 and all(len(Path(m.filename).parts) > 1 for m in members)

            for member in members:
                parts = Path(member.filename).parts
                rel_parts = parts[1:] if strip_prefix else parts
                if not rel_parts:
                    continue
                target_path = dest_dir.joinpath(*rel_parts)
                if not target_path.resolve().is_relative_to(dest_resolved):
                    continue
                target_path.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, "r") as src, open(target_path, "wb") as dst:
                    shutil.copyfileobj(src, dst)

    @staticmethod
    def _emit(cb: ProgressCallback, progress: float, text: str) -> None:
        if cb:
            try:
                cb(progress, text)
            except Exception:
                pass

    @staticmethod
    def _log(cb: LogCallback, message: str) -> None:
        if cb:
            try:
                cb(message)
            except Exception:
                pass
