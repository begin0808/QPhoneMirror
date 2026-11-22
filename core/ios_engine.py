"""QPhoneMirror Apple iPhone / iPad 投影引擎（封裝 UxPlay AirPlay 接收伺服器）。"""

from __future__ import annotations

import ipaddress
import os
import socket
import subprocess
import sys
import threading
import webbrowser
from typing import Callable, Optional, Set

import psutil

from core.binary_manager import BinaryManager

LogCallback = Optional[Callable[[str], None]]
StatusCallback = Optional[Callable[[str, str], None]]

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
BONJOUR_INFO_URL = "https://support.apple.com/zh-tw/106380"

_VIRTUAL_ADAPTER_KEYWORDS = (
    "vethernet",
    "vmware",
    "virtualbox",
    "vbox",
    "wsl",
    "hyper-v",
    "loopback",
    "tailscale",
    "zerotier",
    "wireguard",
    "tap-",
    "tun",
    "vpn",
    "docker",
    "bluetooth",
)


def get_local_ip() -> str:
    """取得這台電腦目前的區域網路 Wi-Fi / LAN IPv4 位址（優先排除虛擬與 VPN 網卡）。"""
    try:
        addrs = psutil.net_if_addrs()
        stats = psutil.net_if_stats()
        candidates: list[tuple[int, str]] = []
        for if_name, addr_list in addrs.items():
            st = stats.get(if_name)
            if st and not st.isup:
                continue
            low_name = if_name.lower()
            is_virtual = any(k in low_name for k in _VIRTUAL_ADAPTER_KEYWORDS)
            is_wifi = any(k in low_name for k in ("wi-fi", "wifi", "wlan", "無線"))
            for addr in addr_list:
                if addr.family != socket.AF_INET:
                    continue
                try:
                    ip_obj = ipaddress.ip_address(addr.address)
                except ValueError:
                    continue
                if ip_obj.is_loopback or ip_obj.is_link_local or ip_obj.is_unspecified:
                    continue
                # 權重：實體 Wi-Fi (0) < 實體乙太網路 (1) < 其他非虛擬私有網段 (2) < 虛擬網卡 (3)
                if not is_virtual and is_wifi and ip_obj.is_private:
                    prio = 0
                elif not is_virtual and ip_obj.is_private:
                    prio = 1
                elif not is_virtual:
                    prio = 2
                else:
                    prio = 3
                candidates.append((prio, addr.address))
        if candidates:
            candidates.sort(key=lambda item: item[0])
            return candidates[0][1]
    except Exception:
        pass

    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.connect(("8.8.8.8", 80))
        return sock.getsockname()[0]
    except Exception:
        try:
            return socket.gethostbyname(socket.gethostname())
        except Exception:
            return "127.0.0.1"
    finally:
        sock.close()


def check_bonjour_service() -> tuple[bool, str]:
    """檢測 Windows 是否已安裝並啟動 Apple Bonjour Service（AirPlay 廣播搜尋必備）。"""
    if sys.platform != "win32":
        return True, "非 Windows 環境，略過 Bonjour 檢查"

    try:
        svc = psutil.win_service_get("Bonjour Service")
        info = svc.as_dict()
        status = info.get("status", "")
        if status == "running":
            return True, "Apple Bonjour 廣播服務正常運作中"
        return False, f"已安裝 Bonjour，但目前狀態為「{status}」（建議至 Windows 服務啟動）"
    except psutil.NoSuchProcess:
        return (
            False,
            "尚未偵測到 Apple Bonjour 服務（若 iPhone 搜尋不到電腦，建議安裝 Bonjour 或 iTunes）",
        )
    except Exception:
        return False, "無法確認 Bonjour 服務狀態（若已安裝 iTunes 通常已內建）"


def open_bonjour_guide() -> None:
    """開啟 Apple 官方 Bonjour 資訊頁面供使用者下載安裝。"""
    webbrowser.open(BONJOUR_INFO_URL)


class IOSEngine:
    """封裝 UxPlay，讓 Windows 電腦化身 AirPlay 接收器供 iPhone / iPad 投影。"""

    def __init__(self, binary_manager: BinaryManager) -> None:
        self.binary_manager = binary_manager
        self._proc: Optional[subprocess.Popen] = None
        self._lock = threading.Lock()
        self._stopped_pids: Set[int] = set()

    def is_running(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    @staticmethod
    def _is_exe_already_running(exe_name: str) -> bool:
        low = exe_name.lower()
        try:
            for proc in psutil.process_iter(["name"]):
                name = (proc.info.get("name") or "").lower()
                if name == low:
                    return True
        except Exception:
            pass
        return False

    def start_airplay(
        self,
        display_name: str = "QPhoneMirror-電腦",
        fps: int = 60,
        resolution: str = "1920x1080",
        audio: bool = True,
        log_cb: LogCallback = None,
        on_status: StatusCallback = None,
    ) -> tuple[bool, str]:
        """啟動 UxPlay AirPlay 接收服務。"""
        if self.is_running():
            return True, f"AirPlay 接收器「{display_name}」已在廣播並等待 iPhone 連線。"

        uxplay = self.binary_manager.get_uxplay_path()
        if not uxplay:
            msg = "尚未安裝蘋果 AirPlay 核心，請先按下上方「一鍵下載並安裝核心」。"
            self._log(log_cb, msg)
            return False, msg

        mode = self.binary_manager.get_uxplay_mode()
        safe_name = display_name.strip() or "QPhoneMirror-電腦"

        env = os.environ.copy()
        ux_dir = uxplay.parent.resolve()
        extra_paths = [str(ux_dir)]
        if (ux_dir / "bin").is_dir():
            extra_paths.append(str(ux_dir / "bin"))
        env["PATH"] = os.pathsep.join(extra_paths + [env.get("PATH", "")])
        for gst_candidate in (ux_dir / "lib" / "gstreamer-1.0", ux_dir.parent / "lib" / "gstreamer-1.0"):
            if gst_candidate.is_dir():
                env.setdefault("GST_PLUGIN_PATH", str(gst_candidate))
                break

        # 攜帶版 GUI 核心（如 uxplay-windows.exe，內建 mDNS 免裝 Bonjour）
        if mode == "gui":
            if self._is_exe_already_running(uxplay.name):
                msg = f"偵測到 {uxplay.name} 已在系統中執行（請檢查右下角系統匣或工作列）。"
                self._log(log_cb, msg)
                self._emit_status(on_status, "waiting", msg)
                return True, msg

            self._log(log_cb, f"正在啟動 AirPlay 攜帶版接收器 ({uxplay.name})...")
            try:
                proc = subprocess.Popen(
                    [str(uxplay)],
                    cwd=str(ux_dir),
                    env=env,
                )
            except Exception as exc:
                msg = f"啟動 AirPlay 接收器失敗：{exc}"
                self._log(log_cb, msg)
                return False, msg

            with self._lock:
                self._proc = proc
                self._stopped_pids.discard(proc.pid)

            self._emit_status(
                on_status,
                "waiting",
                "AirPlay 接收器已啟動（內建 mDNS，免安裝 Bonjour）！請從 iPhone / iPad 控制中心點選「螢幕鏡像輸出」連線。",
            )
            watcher = threading.Thread(
                target=self._watch_gui_process,
                args=(proc, log_cb, on_status),
                daemon=True,
            )
            watcher.start()
            return True, "AirPlay 接收器已啟動！請從 iPhone / iPad 控制中心點選「螢幕鏡像輸出」選擇這台電腦。"

        # 命令列版核心（uxplay.exe）
        cmd = [
            str(uxplay),
            "-n",
            safe_name,
            "-fps",
            str(fps),
            "-s",
            f"{resolution}@{fps}",
        ]
        if not audio:
            cmd.extend(["-as", "0"])

        self._log(log_cb, f"正在開啟 AirPlay 接收服務：「{safe_name}」({resolution} / {fps}FPS)...")

        try:
            proc = subprocess.Popen(
                cmd,
                cwd=str(ux_dir),
                env=env,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
        except Exception as exc:
            msg = f"啟動 UxPlay 失敗：{exc}"
            self._log(log_cb, msg)
            return False, msg

        with self._lock:
            self._proc = proc
            self._stopped_pids.discard(proc.pid)

        self._emit_status(
            on_status,
            "waiting",
            f"廣播待機中：請在 iPhone 控制中心點選「螢幕鏡像輸出」→ 選擇「{safe_name}」",
        )

        watcher = threading.Thread(
            target=self._watch_process,
            args=(proc, safe_name, log_cb, on_status),
            daemon=True,
        )
        watcher.start()
        return True, f"AirPlay 接收器已啟動！請在 iPhone 上選擇「{safe_name}」即可開始投影。"

    def _watch_gui_process(
        self,
        proc: subprocess.Popen,
        log_cb: LogCallback,
        on_status: StatusCallback,
    ) -> None:
        proc.wait()
        with self._lock:
            is_current = self._proc is proc
            if is_current:
                self._proc = None
            self._stopped_pids.discard(proc.pid)
        if is_current:
            self._log(log_cb, "AirPlay 接收器已關閉。")
            self._emit_status(on_status, "stopped", "AirPlay 接收器目前未啟動")

    def _watch_process(
        self,
        proc: subprocess.Popen,
        display_name: str,
        log_cb: LogCallback,
        on_status: StatusCallback,
    ) -> None:
        if proc.stdout:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if not line:
                    continue
                low = line.lower()
                if "begin streaming" in low or "raop_rtp_mirror" in low or "connection from" in low:
                    self._log(log_cb, "已接收到 iPhone / iPad 的 AirPlay 畫面串流。")
                    self._emit_status(on_status, "connected", "iPhone / iPad 投影連線中")
                elif "connection closed" in low or "teardown" in low:
                    self._log(log_cb, "iPhone 已中斷鏡像，繼續待機等待下次連線。")
                    self._emit_status(on_status, "waiting", f"廣播待機中：請在 iPhone 選擇「{display_name}」")
                elif "bonjour" in low or "dnssd" in low or "error" in low:
                    self._log(log_cb, f"[UxPlay] {line}")

        code = proc.wait()
        with self._lock:
            is_current = self._proc is proc
            if is_current:
                self._proc = None
            was_stopped = proc.pid in self._stopped_pids
            self._stopped_pids.discard(proc.pid)

        if was_stopped:
            self._log(log_cb, "AirPlay 接收器已安全關閉。")
            if is_current:
                self._emit_status(on_status, "stopped", "AirPlay 接收器目前未啟動")
        elif is_current:
            self._log(log_cb, f"AirPlay 服務意外結束（狀態碼 {code}），請檢查是否已安裝 Bonjour 與 GStreamer。")
            self._emit_status(on_status, "error", "AirPlay 服務已停止，請檢視執行紀錄")

    def stop_airplay(self, log_cb: LogCallback = None) -> None:
        """安全終止 UxPlay 及其子程序，不殘留背景程序。"""
        with self._lock:
            proc = self._proc
            self._proc = None
            if proc is not None:
                self._stopped_pids.add(proc.pid)

        if not proc:
            return

        try:
            if proc.poll() is None:
                parent = psutil.Process(proc.pid)
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
        self._log(log_cb, "已停止 iPhone AirPlay 接收器。")

    @staticmethod
    def _log(cb: LogCallback, message: str) -> None:
        if cb:
            try:
                cb(message)
            except Exception:
                pass

    @staticmethod
    def _emit_status(cb: StatusCallback, state: str, text: str) -> None:
        if cb:
            try:
                cb(state, text)
            except Exception:
                pass
