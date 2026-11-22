"""QPhoneMirror Android 全品牌投影引擎（封裝 ADB 裝置掃描、Wi-Fi 連線、Scrcpy 投影、截圖錄影、傳檔與遙控）。"""

from __future__ import annotations

import ipaddress
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Optional

import psutil

from config.settings import resolve_captures_dir
from core.binary_manager import BinaryManager
from core.window_finder import send_wm_close_to_pids

LogCallback = Optional[Callable[[str], None]]
ExitCallback = Optional[Callable[[str, int], None]]

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0


@dataclass
class AndroidDevice:
    """代表一台已透過 ADB 偵測到的 Android 手機。"""

    serial: str
    state: str  # device, unauthorized, offline
    model: str
    friendly_name: str
    connection_type: str  # "usb" or "wifi"

    @property
    def display_label(self) -> str:
        conn_tag = "[Wi-Fi]" if self.connection_type == "wifi" else "[USB]"
        if self.state == "device":
            status_tag = "已就緒"
        elif self.state == "unauthorized":
            status_tag = "請在手機點選允許"
        else:
            status_tag = self.state
        return f"{conn_tag} {self.friendly_name} ({self.serial}) — {status_tag}"


@dataclass
class MirrorOptions:
    """Scrcpy 投影參數設定。"""

    resolution: str = "1080p"  # "original", "1080p", "720p"
    fps: int = 60
    bitrate: str = "8M"
    turn_screen_off: bool = True
    stay_awake: bool = True
    audio: bool = True
    always_on_top: bool = False
    record_video: bool = False


class AndroidEngine:
    """封裝 ADB 與 Scrcpy，提供各品牌 Android 手機有線與無線投影及快捷工具控制。"""

    def __init__(self, binary_manager: BinaryManager) -> None:
        self.binary_manager = binary_manager
        self._processes: Dict[str, subprocess.Popen] = {}
        self._lock = threading.Lock()

    def _run_adb(self, args: List[str], timeout: int = 10) -> tuple[bool, str, str]:
        adb = self.binary_manager.get_adb_path()
        if not adb:
            return False, "", "找不到 adb.exe，請先安裝 Android 核心元件。"
        try:
            res = subprocess.run(
                [str(adb), *args],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                creationflags=CREATE_NO_WINDOW,
            )
            return res.returncode == 0, res.stdout.strip(), res.stderr.strip()
        except subprocess.TimeoutExpired:
            return False, "", "ADB 指令逾時，請確認手機連線是否正常。"
        except Exception as exc:
            return False, "", str(exc)

    def list_devices(self) -> tuple[List[AndroidDevice], Optional[str]]:
        """掃描所有透過 USB 或 Wi-Fi 連接的 Android 裝置。"""
        ok, stdout, stderr = self._run_adb(["devices", "-l"], timeout=8)
        if not ok:
            return [], stderr or "無法啟動 ADB 掃描服務。"

        devices: List[AndroidDevice] = []
        for line in stdout.splitlines():
            line = line.strip()
            if not line or line.startswith("List of devices") or line.startswith("*"):
                continue
            parts = line.split()
            if len(parts) < 2:
                continue
            serial = parts[0]
            state = parts[1]
            model = ""
            for token in parts[2:]:
                if token.startswith("model:"):
                    model = token.split(":", 1)[1].strip()
                    break

            friendly = self._format_friendly_name(model, serial)
            is_wifi = (
                ":" in serial
                or "._adb-tls-connect._tcp" in serial
                or "._adb-tls-pairing._tcp" in serial
            )
            conn_type = "wifi" if is_wifi else "usb"
            devices.append(
                AndroidDevice(
                    serial=serial,
                    state=state,
                    model=model,
                    friendly_name=friendly,
                    connection_type=conn_type,
                )
            )
        return devices, None

    @staticmethod
    def _format_friendly_name(model: str, serial: str) -> str:
        if not model:
            return f"Android 手機 ({serial})"
        clean = model.replace("_", " ")
        if clean.startswith("SM-"):
            return f"Samsung ({clean})"
        return clean

    @staticmethod
    def _is_valid_lan_ip(ip_str: str) -> bool:
        try:
            addr = ipaddress.ip_address(ip_str)
            if addr.version != 4 or addr.is_loopback or addr.is_link_local or addr.is_unspecified:
                return False
            return True
        except ValueError:
            return False

    def get_device_ip(self, serial: str) -> Optional[str]:
        """透過 ADB 查詢手機目前連接的 Wi-Fi 區域網路 IPv4 位址（優先鎖定 wlan 介面，避免抓到行動網路或 VPN）。"""
        ok, stdout, _ = self._run_adb(["-s", serial, "shell", "ip", "route"], timeout=6)
        if ok and stdout:
            # 1. 優先比對 Wi-Fi 介面 (wlan0 / swlan0 / wifi*)
            for line in stdout.splitlines():
                m_wifi = re.search(
                    r"\bdev\s+(?:wlan\d+|swlan\d+|wifi\S*)\b.*?\bsrc\s+(\d+\.\d+\.\d+\.\d+)",
                    line,
                )
                if m_wifi and self._is_valid_lan_ip(m_wifi.group(1)):
                    return m_wifi.group(1)

        # 2. 直接查詢 wlan0 / swlan0 介面位址
        for iface in ("wlan0", "swlan0"):
            ok2, stdout2, _ = self._run_adb(
                ["-s", serial, "shell", "ip", "-f", "inet", "addr", "show", iface],
                timeout=6,
            )
            if ok2 and stdout2:
                match2 = re.search(r"inet\s+(\d+\.\d+\.\d+\.\d+)/", stdout2)
                if match2 and self._is_valid_lan_ip(match2.group(1)):
                    return match2.group(1)

        # 3. 備援：getprop dhcp.wlan0.ipaddress
        ok3, stdout3, _ = self._run_adb(
            ["-s", serial, "shell", "getprop", "dhcp.wlan0.ipaddress"],
            timeout=5,
        )
        if ok3 and stdout3 and self._is_valid_lan_ip(stdout3.strip()):
            return stdout3.strip()

        # 4. 最後備援：ip route 中非 rmnet / tun 的私有網段
        if ok and stdout:
            for line in stdout.splitlines():
                if re.search(r"\bdev\s+(?:rmnet|ccmni|tun|ppp|dummy)", line):
                    continue
                m_any = re.search(r"\bsrc\s+(\d+\.\d+\.\d+\.\d+)", line)
                if m_any and self._is_valid_lan_ip(m_any.group(1)):
                    return m_any.group(1)
        return None

    def enable_wifi_mode(
        self,
        serial: str,
        port: int = 5555,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str, Optional[str]]:
        """將已插線的 USB 手機一鍵切換為 Wi-Fi 無線 ADB 連線。"""
        if ":" in serial:
            ip = serial.split(":")[0]
            return True, f"此手機已在無線連線模式 ({serial})。", ip

        self._log(log_cb, f"正在讀取手機 ({serial}) 的 Wi-Fi IP 位址...")
        ip = self.get_device_ip(serial)
        if not ip:
            msg = "讀取不到手機的 Wi-Fi IP，請確認手機與電腦連接同一個 Wi-Fi 網路。"
            self._log(log_cb, msg)
            return False, msg, None

        self._log(log_cb, f"正在開啟手機無線連線埠 (Port {port})...")
        ok, out, err = self._run_adb(["-s", serial, "tcpip", str(port)], timeout=10)
        if not ok:
            msg = f"切換無線模式失敗：{err or out}"
            self._log(log_cb, msg)
            return False, msg, None

        time.sleep(1.5)
        ok_conn, msg_conn = self.connect_wifi(ip, port, log_cb=log_cb)
        if ok_conn:
            success_msg = f"無線切換成功 ({ip}:{port})！現在可以拔除 USB 線並進行無線投影。"
            self._log(log_cb, success_msg)
            return True, success_msg, ip
        return False, msg_conn, ip

    def pair_wifi(
        self,
        pair_host_port: str,
        pairing_code: str,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """Android 11 以上免插線「配對碼」無線配對（adb pair）。"""
        target = pair_host_port.strip()
        code = pairing_code.strip()

        if not target or ":" not in target:
            return False, "請輸入完整的配對 IP 與連接埠（例如 192.168.1.105:38123）。"
        host_part, port_part = target.rsplit(":", 1)
        try:
            ipaddress.ip_address(host_part.strip())
            port_num = int(port_part.strip())
            if not (1 <= port_num <= 65535):
                raise ValueError("port out of range")
        except ValueError:
            return False, "配對 IP 或連接埠格式不正確，請確認格式為「IPv4:連接埠」（例如 192.168.1.105:38123）。"

        if not re.fullmatch(r"\d{6}", code):
            return False, "配對碼須為 6 位數字，請確認手機「使用配對碼配對裝置」畫面上的數字。"

        self._log(log_cb, f"正在使用配對碼與 {target} 進行免插線無線配對...")
        ok, out, err = self._run_adb(["pair", target, code], timeout=15)
        combined = f"{out} {err}".strip()
        low = combined.lower()

        if ok and "successfully paired" in low:
            msg = (
                f"無線配對成功（{target}）！\n"
                "請接著在上方「Wi-Fi 無線重連」欄位輸入手機「無線偵錯」主畫面的 IP:連接埠，再按下「連線 Wi-Fi」即可開始投影。"
            )
            self._log(log_cb, f"已完成免插線無線配對：{target}")
            return True, msg

        msg = f"無線配對失敗：{combined or '請確認手機與電腦在同一個 Wi-Fi，且配對碼尚未過期。'}"
        self._log(log_cb, msg)
        return False, msg

    def connect_wifi(
        self,
        ip: str,
        port: int = 5555,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """透過 IP 與 Port 連線到 Android 手機。"""
        ip = ip.strip()
        if not ip:
            return False, "請先輸入手機的 Wi-Fi IP 位址。"

        target = ip if ":" in ip else f"{ip}:{port}"
        self._log(log_cb, f"正在無線連線至 {target} ...")
        ok, out, err = self._run_adb(["connect", target], timeout=10)
        combined = f"{out} {err}".lower()

        if ok and ("connected to" in combined or "already connected" in combined):
            msg = f"已成功無線連上手機 {target}。"
            self._log(log_cb, msg)
            return True, msg

        if "refused" in combined or "10061" in combined:
            msg = (
                f"無法連線至 {target}（手機尚未開啟無線連線埠）。\n"
                "提示：可先插線按下「插線轉無線」，或使用下方「免插線配對碼設定」完成無線配對。"
            )
        elif "timed out" in combined or "10060" in combined:
            msg = f"連線 {target} 逾時，請確認手機和電腦連接在同一個 Wi-Fi。"
        else:
            msg = f"無線連線失敗：{out or err}"
        self._log(log_cb, msg)
        return False, msg

    def disconnect_wifi(
        self,
        target: Optional[str] = None,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """中斷指定的無線連線（若未指定則中斷全部無線 ADB 連線）。"""
        args = ["disconnect", target] if target else ["disconnect"]
        ok, out, err = self._run_adb(args, timeout=8)
        msg = f"已中斷無線連線：{out}" if ok else f"中斷失敗：{err or out}"
        self._log(log_cb, msg)
        return ok, msg

    def take_screenshot(
        self,
        serial: str,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str, Optional[Path]]:
        """擷取手機目前畫面並以 PNG 格式儲存至 captures 資料夾。"""
        adb = self.binary_manager.get_adb_path()
        if not adb:
            msg = "找不到 adb.exe，請先安裝 Android 核心元件。"
            self._log(log_cb, msg)
            return False, msg, None

        self._log(log_cb, f"正在擷取手機 ({serial}) 畫面截圖...")
        try:
            res = subprocess.run(
                [str(adb), "-s", serial, "exec-out", "screencap", "-p"],
                capture_output=True,
                timeout=15,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode != 0 or not res.stdout:
                err_txt = res.stderr.decode("utf-8", errors="replace").strip()
                msg = f"截圖失敗：{err_txt or '無法取得手機畫面資料。'}"
                self._log(log_cb, msg)
                return False, msg, None

            png_data = res.stdout
            if not png_data.startswith(b"\x89PNG"):
                msg = "截圖資料格式異常，請確認手機已解鎖且連線穩定。"
                self._log(log_cb, msg)
                return False, msg, None

            captures_dir = resolve_captures_dir(log_cb=log_cb)
            captures_dir.mkdir(parents=True, exist_ok=True)
            out_path = self._unique_capture_path(captures_dir, "Screenshot", ".png")
            out_path.write_bytes(png_data)

            msg = f"螢幕截圖已儲存至 {out_path.name}"
            self._log(log_cb, f"螢幕截圖已儲存至：{out_path}")
            return True, msg, out_path
        except subprocess.TimeoutExpired:
            msg = "截圖逾時，請確認手機連線狀態。"
            self._log(log_cb, msg)
            return False, msg, None
        except Exception as exc:
            msg = f"截圖時發生錯誤：{exc}"
            self._log(log_cb, msg)
            return False, msg, None

    def send_files_to_device(
        self,
        serial: str,
        file_paths: List[Path],
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """將電腦檔案透過有線或 Wi-Fi 無線傳送至手機 Download 資料夾，若為 .apk 則自動安裝。"""
        if not file_paths:
            return False, "未選擇任何檔案。"

        ok_count = 0
        fail_items: List[str] = []

        for fp in file_paths:
            p = Path(fp)
            if not p.is_file():
                fail_items.append(f"{p.name}（檔案不存在）")
                continue

            size_mb = p.stat().st_size / (1024 * 1024)
            # 依檔案大小動態放寬逾時（至少 120 秒，大檔以約 1.5 MB/s 估算加上緩衝）
            dyn_timeout = max(120, int(size_mb / 1.5) + 60)

            if p.suffix.lower() == ".apk":
                self._log(log_cb, f"正在安裝應用程式至手機：{p.name} ({size_mb:.1f} MB) ...")
                ok, out, err = self._run_adb(["-s", serial, "install", "-r", str(p)], timeout=dyn_timeout)
                if ok and "success" in f"{out} {err}".lower():
                    ok_count += 1
                    self._log(log_cb, f"已安裝完成：{p.name}")
                else:
                    fail_items.append(f"{p.name}（安裝失敗：{err or out}）")
            else:
                self._log(log_cb, f"正在傳送檔案至手機 Download 資料夾：{p.name} ({size_mb:.1f} MB) ...")
                # 先推送至專屬暫存檔名，成功後再以 shlex.quote 安全改名，絕不誤刪原有檔案且杜絕 shell 注入
                tmp_remote = f"/sdcard/Download/.qpm_upload_{uuid.uuid4().hex[:12]}"
                final_remote = f"/sdcard/Download/{p.name}"
                ok, out, err = self._run_adb(["-s", serial, "push", str(p), tmp_remote], timeout=dyn_timeout)
                if ok:
                    mv_cmd = f"mv -f -- {shlex.quote(tmp_remote)} {shlex.quote(final_remote)}"
                    mv_ok, mv_out, mv_err = self._run_adb(["-s", serial, "shell", mv_cmd], timeout=10)
                    if mv_ok:
                        ok_count += 1
                        self._log(log_cb, f"已傳送至手機下載資料夾：{p.name}")
                    else:
                        rm_cmd = f"rm -f -- {shlex.quote(tmp_remote)}"
                        self._run_adb(["-s", serial, "shell", rm_cmd], timeout=6)
                        fail_items.append(f"{p.name}（寫入目的檔失敗：{mv_err or mv_out}）")
                else:
                    rm_cmd = f"rm -f -- {shlex.quote(tmp_remote)}"
                    self._run_adb(["-s", serial, "shell", rm_cmd], timeout=6)
                    fail_items.append(f"{p.name}（傳送失敗：{err or out}）")

        if not fail_items:
            msg = f"已成功處理 {ok_count} 個檔案（一般檔案位於手機「下載 / Download」資料夾，APK 已自動安裝）。"
            self._log(log_cb, msg)
            return True, msg

        msg = f"完成 {ok_count} 個檔案，另有 {len(fail_items)} 個失敗：{'；'.join(fail_items)}"
        self._log(log_cb, msg)
        return ok_count > 0, msg

    def send_keyevent(
        self,
        serial: str,
        keycode: int,
        key_label: str = "",
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """傳送手機虛擬導航鍵或硬體按鍵指令（支援有線與無線連線）。"""
        ok, out, err = self._run_adb(["-s", serial, "shell", "input", "keyevent", str(keycode)], timeout=6)
        label = key_label or f"KeyCode {keycode}"
        if ok:
            msg = f"已傳送手機按鍵：{label}"
            self._log(log_cb, msg)
            return True, msg
        msg = f"傳送按鍵「{label}」失敗：{err or out}"
        self._log(log_cb, msg)
        return False, msg

    def start_mirror(
        self,
        device: AndroidDevice,
        options: MirrorOptions,
        log_cb: LogCallback = None,
        on_exit: ExitCallback = None,
    ) -> tuple[bool, str]:
        """以非同步子程序啟動 Scrcpy 投影視窗（支援選配 MP4 同步錄影）。"""
        scrcpy = self.binary_manager.get_scrcpy_path()
        if not scrcpy:
            msg = "尚未找到 scrcpy.exe，請先按下上方「一鍵下載並安裝核心」。"
            self._log(log_cb, msg)
            return False, msg

        if device.state == "unauthorized":
            msg = "手機尚未授權！請檢視手機畫面，勾選「一律允許」並點選「允許 USB 偵錯」。"
            self._log(log_cb, msg)
            return False, msg

        if device.state != "device":
            msg = f"手機目前狀態異常 ({device.state})，請重新插拔傳輸線或重新掃描裝置。"
            self._log(log_cb, msg)
            return False, msg

        with self._lock:
            existing = self._processes.get(device.serial)
            if existing and existing.poll() is None:
                msg = f"{device.friendly_name} 目前正在投影中。"
                self._log(log_cb, msg)
                return True, msg

        cmd = [
            str(scrcpy),
            "-s",
            device.serial,
            f"--window-title=QPhoneMirror - {device.friendly_name}",
            f"--max-fps={options.fps}",
            f"--video-bit-rate={options.bitrate}",
        ]

        if options.resolution == "1080p":
            cmd.append("--max-size=1920")
        elif options.resolution == "720p":
            cmd.append("--max-size=1280")

        if options.turn_screen_off:
            cmd.append("--turn-screen-off")
        if options.stay_awake:
            cmd.append("--stay-awake")
        if not options.audio:
            cmd.append("--no-audio")
        if options.always_on_top:
            cmd.append("--always-on-top")

        record_path: Optional[Path] = None
        if options.record_video:
            try:
                captures_dir = resolve_captures_dir(log_cb=log_cb)
                captures_dir.mkdir(parents=True, exist_ok=True)
                safe_serial = re.sub(r"[^A-Za-z0-9_-]+", "_", device.serial).strip("_")[:16] or "dev"
                record_path = self._unique_capture_path(captures_dir, f"Record_{safe_serial}", ".mp4", include_ms=True)
            except Exception as exc:
                msg = f"無法存取錄影儲存資料夾：{exc}"
                self._log(log_cb, msg)
                return False, msg
            cmd.append(f"--record={record_path}")
            self._log(log_cb, f"已開啟投影同步錄影，結束投影時影片將儲存至：{record_path}")

        self._log(log_cb, f"正在啟動 {device.friendly_name} 投影視窗（{options.resolution} / {options.fps}FPS）...")

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(scrcpy.parent),
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:
            msg = f"啟動 Scrcpy 失敗：{exc}"
            self._log(log_cb, msg)
            return False, msg

        with self._lock:
            self._processes[device.serial] = proc

        watcher = threading.Thread(
            target=self._watch_process,
            args=(device, proc, record_path, log_cb, on_exit),
            daemon=True,
        )
        watcher.start()

        if record_path:
            return True, f"{device.friendly_name} 投影與同步錄影已啟動！（錄影檔：{record_path.name}）"
        return True, f"{device.friendly_name} 投影已啟動！（可直接使用電腦滑鼠與鍵盤操作手機）"

    def _watch_process(
        self,
        device: AndroidDevice,
        proc: subprocess.Popen,
        record_path: Optional[Path],
        log_cb: LogCallback,
        on_exit: ExitCallback,
    ) -> None:
        if proc.stdout:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                translated = self._translate_scrcpy_log(line)
                if translated:
                    self._log(log_cb, translated)

        code = proc.wait()
        with self._lock:
            if self._processes.get(device.serial) is proc:
                del self._processes[device.serial]

        if code == 0:
            if record_path and record_path.is_file():
                self._log(log_cb, f"{device.friendly_name} 投影已結束，錄影檔已完整儲存：{record_path.name}。")
            else:
                self._log(log_cb, f"{device.friendly_name} 的投影視窗已正常關閉。")
        else:
            if record_path and record_path.is_file():
                self._log(
                    log_cb,
                    f"{device.friendly_name} 投影異常結束（狀態碼 {code}），錄影檔 {record_path.name} 可能不完整。",
                )
            else:
                self._log(log_cb, f"{device.friendly_name} 投影已結束（狀態碼 {code}），如非手動關閉請檢查連線。")

        if on_exit:
            try:
                on_exit(device.serial, code)
            except Exception:
                pass

    @staticmethod
    def _translate_scrcpy_log(line: str) -> Optional[str]:
        low = line.lower()
        if "unauthorized" in low:
            return "手機尚未點選「允許 USB 偵錯」，請確認手機畫面上的授權視窗。"
        if "device offline" in low:
            return "手機連線中斷 (offline)，請重新插拔傳輸線。"
        if "could not find any adb device" in low:
            return "找不到 Android 手機，請檢查傳輸線與 USB 偵錯開關。"
        if "audio capture" in low and ("warn" in low or "error" in low or "disabled" in low):
            return "提示：此裝置不支援原生音訊轉發（需 Android 11 以上），已自動改為純畫面投影。"
        if "recording complete" in low:
            return f"錄影已完成存檔：{line}"
        if "texture:" in low:
            return f"畫面串流已建立：{line}"
        if "error:" in low or "warn:" in low:
            return f"[Scrcpy] {line}"
        return None

    def stop_all(self, log_cb: LogCallback = None) -> None:
        """並行優雅關閉所有執行中的 Scrcpy 投影視窗（優先送出 WM_CLOSE 讓同步錄影 MP4 完整寫入檔尾）。"""
        with self._lock:
            items = list(self._processes.items())
            self._processes.clear()

        if not items:
            return

        # 並行收集所有執行中的 Scrcpy PID 並統一送出 WM_CLOSE，多台裝置不線性累加等待時間
        alive_items: List[tuple[str, subprocess.Popen]] = []
        all_pids: List[int] = []
        for serial, proc in items:
            if proc.poll() is None:
                alive_items.append((serial, proc))
                all_pids.append(proc.pid)
                try:
                    for child in psutil.Process(proc.pid).children(recursive=True):
                        all_pids.append(child.pid)
                except Exception:
                    pass

        if all_pids and send_wm_close_to_pids(all_pids) > 0:
            deadline = time.monotonic() + 6.0
            for _, proc in alive_items:
                remain = max(0.05, deadline - time.monotonic())
                try:
                    proc.wait(timeout=remain)
                except subprocess.TimeoutExpired:
                    pass

        for serial, proc in items:
            if proc.poll() is None:
                self._terminate_tree(proc)
            self._log(log_cb, f"已停止 {serial} 的投影。")

    def kill_adb_server(self) -> None:
        """關閉背景常駐的 adb server，避免關閉程式後 adb.exe 仍鎖定免安裝資料夾。"""
        adb = self.binary_manager.get_adb_path()
        if not adb:
            return
        try:
            subprocess.run(
                [str(adb), "kill-server"],
                capture_output=True,
                timeout=3,
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception:
            pass

    def is_mirroring(self) -> bool:
        with self._lock:
            return any(p.poll() is None for p in self._processes.values())

    @staticmethod
    def _unique_capture_path(directory: Path, prefix: str, suffix: str, include_ms: bool = False) -> Path:
        now = datetime.now()
        stamp = now.strftime("%Y%m%d_%H%M%S_%f")[:-3] if include_ms else now.strftime("%Y%m%d_%H%M%S")
        base = f"{prefix}_{stamp}"
        candidate = directory / f"{base}{suffix}"
        if not candidate.exists():
            return candidate
        for idx in range(1, 1000):
            alt = directory / f"{base}_{idx}{suffix}"
            if not alt.exists():
                return alt
        return directory / f"{base}_{int(time.time() * 1000)}{suffix}"

    @staticmethod
    def _terminate_tree(proc: subprocess.Popen) -> None:
        try:
            if proc.poll() is not None:
                return
            parent = psutil.Process(proc.pid)
            children = parent.children(recursive=True)
            pids = [proc.pid] + [c.pid for c in children]

            # 方案 A：優先對 Scrcpy 視窗送出 WM_CLOSE，讓 SDL 正常結束並寫入 MP4 檔尾 (moov)
            if send_wm_close_to_pids(pids) > 0:
                try:
                    proc.wait(timeout=6.0)
                    return
                except subprocess.TimeoutExpired:
                    pass

            for child in parent.children(recursive=True):
                try:
                    child.terminate()
                except Exception:
                    pass
            parent.terminate()
            try:
                parent.wait(timeout=3)
            except psutil.TimeoutExpired:
                parent.kill()
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass

    @staticmethod
    def _log(cb: LogCallback, message: str) -> None:
        if cb:
            try:
                cb(message)
            except Exception:
                pass
