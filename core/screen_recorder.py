"""QPhoneMirror 高畫質電腦螢幕錄影引擎（FFmpeg gdigrab + WASAPI 系統聲音內錄與耳機麥克風雙軌收音）。"""

from __future__ import annotations

from collections import deque
import ctypes
import os
import re
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import warnings
import wave
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Callable, Deque, List, Optional, Tuple

import numpy as np
import psutil

from config.settings import resolve_captures_dir
from core.binary_manager import BinaryManager
from core.window_finder import get_primary_monitor_bounds, get_virtual_screen_bounds

LogCallback = Optional[Callable[[str], None]]
ExitCallback = Optional[Callable[[int, Optional[Path]], None]]

CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if sys.platform == "win32" else 0
SAMPLE_RATE = 48000
CHANNELS = 2
CHUNK_FRAMES = 2400  # 50ms per block


@dataclass
class ScreenRecordOptions:
    """電腦螢幕錄影參數設定。"""

    mode: str = "fullscreen"  # "fullscreen", "window", "region"
    region: Tuple[int, int, int, int] = (100, 100, 1280, 720)
    fps: int = 30
    quality: str = "high"  # "high" (CRF 18), "standard" (CRF 23), "compact" (CRF 28)
    draw_mouse: bool = True
    mic_enabled: bool = False
    mic_device: str = ""
    system_audio: bool = False  # 電腦系統聲音內錄（電腦播放音效／線上會議對方聲音），預設關閉
    target_window_title: str = ""
    target_hwnd: int = 0


def normalize_even_region(region: Tuple[int, int, int, int]) -> Tuple[int, int, int, int]:
    """將框選區域或視窗的寬與高校正為不小於 64 的偶數，保留多螢幕負座標。"""
    x, y, w, h = (int(region[0]), int(region[1]), int(region[2]), int(region[3]))
    w = max(64, w - (w % 2))
    h = max(64, h - (h % 2))
    return (x, y, w, h)


def clamp_region_to_virtual_screen(
    region: Tuple[int, int, int, int],
    virtual_bounds: Optional[Tuple[int, int, int, int]] = None,
) -> Optional[Tuple[int, int, int, int]]:
    """將錄影區域與 Windows 虛擬桌面做交集裁切，保留負座標並確保不超出螢幕邊界導致 FFmpeg 啟動失敗。"""
    vx, vy, vw, vh = virtual_bounds if virtual_bounds is not None else get_virtual_screen_bounds()
    v_right = vx + vw
    v_bottom = vy + vh

    x, y, w, h = (int(region[0]), int(region[1]), int(region[2]), int(region[3]))
    left = max(vx, x)
    top = max(vy, y)
    right = min(v_right, x + w)
    bottom = min(v_bottom, y + h)

    cw = right - left
    ch = bottom - top
    cw = cw - (cw % 2)
    ch = ch - (ch % 2)
    if cw < 64 or ch < 64:
        return None
    return (left, top, cw, ch)


def _unique_output_path(directory: Path, prefix: str, suffix: str) -> Path:
    """產生不覆蓋既有檔案的唯一輸出檔名。"""
    base = f"{prefix}_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
    candidate = directory / f"{base}{suffix}"
    if not candidate.exists():
        return candidate
    for idx in range(1, 1000):
        alt = directory / f"{base}_{idx}{suffix}"
        if not alt.exists():
            return alt
    return directory / f"{base}_{int(time.time() * 1000)}{suffix}"


class _WasapiWavRecorder:
    """使用 SoundCard WASAPI 在背景執行緒擷取電腦系統聲音 (Loopback) 或麥克風並寫入 WAV 暫存檔。

    若錄音途中耳機或音訊裝置被拔除，會立即回報提示並自動補寫靜音直到錄影停止，絕不截斷影片。
    """

    def __init__(
        self,
        device_name: str,
        is_loopback: bool,
        out_wav: Path,
        on_notice: LogCallback = None,
    ) -> None:
        self.device_name = device_name
        self.is_loopback = is_loopback
        self.out_wav = out_wav
        self.on_notice = on_notice
        self._stop_event = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.error: Optional[str] = None
        self.frames_written = 0
        self.start_perf: Optional[float] = None
        self.discontinuity_count = 0

    def start(self) -> None:
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=4.0)

    def _notify(self, msg: str) -> None:
        if self.on_notice:
            try:
                self.on_notice(msg)
            except Exception:
                pass

    def _run(self) -> None:
        com_inited = False
        if sys.platform == "win32":
            try:
                hr = ctypes.windll.ole32.CoInitializeEx(None, 0x0)
                com_inited = hr in (0, 1)
            except Exception:
                pass

        label = "系統聲音" if self.is_loopback else "麥克風"
        silence_bytes = np.zeros((CHUNK_FRAMES, CHANNELS), dtype=np.int16).tobytes()
        chunk_sec = CHUNK_FRAMES / float(SAMPLE_RATE)

        try:
            import soundcard as sc

            if self.is_loopback:
                spk = sc.default_speaker()
                if spk is None:
                    raise RuntimeError("找不到預設系統喇叭裝置")
                mic = sc.get_microphone(id=str(spk.name), include_loopback=True)
            else:
                mic = None
                for candidate in sc.all_microphones(include_loopback=False):
                    if candidate.name == self.device_name:
                        mic = candidate
                        break
                if mic is None:
                    mic = sc.default_microphone()
                    if mic is None:
                        raise RuntimeError("找不到可用麥克風裝置")
                    if self.device_name:
                        self._notify(
                            f"提示：找不到指定的麥克風「{self.device_name}」，已自動改用系統預設麥克風「{mic.name}」。"
                        )

            with wave.open(str(self.out_wav), "wb") as wf:
                wf.setnchannels(CHANNELS)
                wf.setsampwidth(2)  # 16-bit PCM
                wf.setframerate(SAMPLE_RATE)

                try:
                    with warnings.catch_warnings(record=True) as caught_warnings:
                        warnings.simplefilter("always")
                        with mic.recorder(samplerate=SAMPLE_RATE, channels=CHANNELS) as rec:
                            self.start_perf = time.perf_counter()
                            while not self._stop_event.is_set():
                                data = rec.record(numframes=CHUNK_FRAMES)
                                if caught_warnings:
                                    for w_item in caught_warnings:
                                        if "discontinuity" in str(w_item.message).lower():
                                            self.discontinuity_count += 1
                                    caught_warnings.clear()

                                if data is None or len(data) == 0:
                                    continue
                                arr = np.asarray(data, dtype=np.float32)
                                if arr.ndim == 1:
                                    arr = np.column_stack((arr, arr))
                                elif arr.shape[1] == 1:
                                    arr = np.repeat(arr, 2, axis=1)
                                elif arr.shape[1] > 2:
                                    arr = arr[:, :2]
                                pcm = (np.clip(arr, -1.0, 1.0) * 32767.0).astype(np.int16)
                                wf.writeframes(pcm.tobytes())
                                self.frames_written += len(pcm)
                except Exception as exc:
                    self.error = str(exc)
                    self._notify(f"注意：{label}在錄影中途發生中斷（{exc}），已自動以靜音補齊並持續錄製完整畫面。")
                    # 若已寫入部分音訊，持續補寫靜音直到手動停止，確保音軌完整不截斷影片
                    if self.frames_written > 0:
                        next_tick = time.perf_counter()
                        while not self._stop_event.is_set():
                            wf.writeframes(silence_bytes)
                            self.frames_written += CHUNK_FRAMES
                            next_tick += chunk_sec
                            wait_s = max(0.005, next_tick - time.perf_counter())
                            self._stop_event.wait(timeout=wait_s)
        except Exception as exc:
            self.error = str(exc)
            self._notify(f"注意：{label}初始化失敗（{exc}），本次錄影將保留畫面。")
        finally:
            if com_inited and sys.platform == "win32":
                try:
                    ctypes.windll.ole32.CoUninitialize()
                except Exception:
                    pass


class ScreenRecorderEngine:
    """封裝 FFmpeg 與 WASAPI 音訊擷取，支援全螢幕／單選程式視窗／自訂區域高畫質錄影。"""

    QUALITY_TO_CRF = {
        "high": "18",
        "standard": "23",
        "compact": "28",
    }

    def __init__(self, binary_manager: BinaryManager) -> None:
        self.binary_manager = binary_manager
        self._proc: Optional[subprocess.Popen] = None
        self._output_path: Optional[Path] = None
        self._video_temp_path: Optional[Path] = None
        self._temp_dir: Optional[Path] = None
        self._audio_recorders: List[_WasapiWavRecorder] = []
        self._video_start_perf: float = 0.0
        self._lock = threading.Lock()
        self._stopping = False
        self._finalizing = False
        self._stop_done_event = threading.Event()
        self._stop_done_event.set()
        self._last_saved_path: Optional[Path] = None

    def is_recording(self) -> bool:
        with self._lock:
            return self._proc is not None and self._proc.poll() is None

    def is_busy(self) -> bool:
        """錄影進行中或正在封裝／混流收尾中皆回傳 True。"""
        with self._lock:
            return self._finalizing or (self._proc is not None and self._proc.poll() is None)

    def wait_until_idle(self, timeout: Optional[float] = None) -> bool:
        """等待正在進行中的停止與混流收尾執行緒完成。"""
        return self._stop_done_event.wait(timeout=timeout)

    def list_audio_inputs(self) -> List[str]:
        """優先透過 Windows WASAPI (SoundCard) 即時列出所有麥克風（免等下載 FFmpeg），再以 FFmpeg 備援。"""
        devices: List[str] = []
        try:
            import soundcard as sc

            for mic in sc.all_microphones(include_loopback=False):
                name = str(mic.name).strip()
                if name and name not in devices:
                    devices.append(name)
            if devices:
                return devices
        except Exception:
            pass

        ffmpeg = self.binary_manager.get_ffmpeg_path()
        if not ffmpeg:
            return devices
        try:
            res = subprocess.run(
                [str(ffmpeg), "-hide_banner", "-list_devices", "true", "-f", "dshow", "-i", "dummy"],
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=8,
                creationflags=CREATE_NO_WINDOW,
            )
            combined = f"{res.stdout}\n{res.stderr}"
            in_audio = False
            for line in combined.splitlines():
                if "DirectShow audio devices" in line:
                    in_audio = True
                    continue
                if "DirectShow video devices" in line:
                    in_audio = False
                    continue
                if "(audio)" in line or in_audio:
                    if "Alternative name" in line:
                        continue
                    match = re.search(r'"([^"]+)"', line)
                    if match:
                        dev_name = match.group(1).strip()
                        if dev_name and dev_name not in devices:
                            devices.append(dev_name)
        except Exception:
            pass
        return devices

    def get_default_speaker_name(self) -> str:
        """取得目前 Windows 預設播放裝置（供系統聲音內錄顯示）。"""
        try:
            import soundcard as sc

            spk = sc.default_speaker()
            return str(spk.name) if spk else "系統預設喇叭"
        except Exception:
            return "系統預設喇叭"

    def build_ffmpeg_command(
        self,
        ffmpeg_path: Path,
        options: ScreenRecordOptions,
        output_path: Path,
        include_dshow_mic: bool = False,
        resolved_region: Optional[Tuple[int, int, int, int]] = None,
    ) -> List[str]:
        """組合高畫質 H.264 MP4 電腦螢幕錄影的完整 FFmpeg 視訊指令。"""
        cmd: List[str] = [
            str(ffmpeg_path),
            "-y",
            "-hide_banner",
            "-loglevel",
            "warning",
            "-f",
            "gdigrab",
            "-framerate",
            str(int(options.fps)),
            "-draw_mouse",
            "1" if options.draw_mouse else "0",
        ]

        if options.mode in ("region", "window"):
            x, y, w, h = resolved_region if resolved_region is not None else normalize_even_region(options.region)
            cmd.extend(["-offset_x", str(x), "-offset_y", str(y), "-video_size", f"{w}x{h}"])
        else:
            # 全螢幕模式明確鎖定主螢幕範圍，避免多螢幕環境把全部螢幕拼接成超寬畫面
            px, py, pw, ph = resolved_region if resolved_region is not None else get_primary_monitor_bounds()
            pw = max(64, pw - (pw % 2))
            ph = max(64, ph - (ph % 2))
            cmd.extend(["-offset_x", str(px), "-offset_y", str(py), "-video_size", f"{pw}x{ph}"])

        cmd.extend(["-i", "desktop"])

        has_dshow = bool(include_dshow_mic and options.mic_enabled and options.mic_device.strip())
        if has_dshow:
            cmd.extend(["-f", "dshow", "-i", f"audio={options.mic_device.strip()}"])

        crf = self.QUALITY_TO_CRF.get(options.quality, "18")
        cmd.extend(
            [
                "-c:v",
                "libx264",
                "-crf",
                crf,
                "-preset",
                "veryfast",
                "-pix_fmt",
                "yuv420p",
                "-vf",
                "pad=ceil(iw/2)*2:ceil(ih/2)*2",
            ]
        )

        if has_dshow:
            cmd.extend(["-c:a", "aac", "-b:a", "192k"])

        cmd.append(str(output_path))
        return cmd

    def start_recording(
        self,
        options: ScreenRecordOptions,
        log_cb: LogCallback = None,
        on_exit: ExitCallback = None,
    ) -> tuple[bool, str, Optional[Path]]:
        """啟動高畫質電腦螢幕錄影（支援系統聲音內錄與耳機麥克風雙軌收音）。"""
        if self.is_busy():
            return False, "前一段錄影正在進行或合成封裝中，請稍候完成後再開始新錄影。", self._output_path

        ffmpeg = self.binary_manager.get_ffmpeg_path()
        if not ffmpeg:
            msg = "尚未安裝 FFmpeg 錄影核心，請先按下上方「一鍵下載並安裝核心」。"
            self._log(log_cb, msg)
            return False, msg, None

        # 解析可寫入的儲存資料夾（若自訂路徑失效會自動回退預設 captures/）
        try:
            captures_dir = resolve_captures_dir(log_cb=log_cb)
            captures_dir.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            msg = f"無法存取錄影儲存資料夾：{exc}"
            self._log(log_cb, msg)
            return False, msg, None

        # 驗證與虛擬桌面交集裁切，避免超出螢幕邊界導致 FFmpeg 立即失敗
        resolved_region: Optional[Tuple[int, int, int, int]] = None
        if options.mode in ("region", "window"):
            resolved_region = clamp_region_to_virtual_screen(options.region)
            if resolved_region is None:
                msg = "錄影區域超出螢幕範圍或尺寸小於 64x64，請重新框選或將目標視窗移回螢幕內。"
                self._log(log_cb, msg)
                return False, msg, None
        else:
            resolved_region = get_primary_monitor_bounds()

        final_out = _unique_output_path(captures_dir, "ScreenRecord", ".mp4")

        use_wasapi_audio = bool(options.system_audio or (options.mic_enabled and options.mic_device.strip()))
        audio_recorders: List[_WasapiWavRecorder] = []
        temp_dir: Optional[Path] = None

        if use_wasapi_audio:
            try:
                # 暫存資料夾建在儲存資料夾底下（同磁碟機），杜絕跨磁碟機搬移失敗與 C 槽爆滿
                temp_dir = Path(tempfile.mkdtemp(prefix=".qpm_rec_", dir=str(captures_dir)))
            except Exception as exc:
                msg = f"無法建立錄影暫存資料夾：{exc}"
                self._log(log_cb, msg)
                return False, msg, None

            video_target = temp_dir / "video_only.mp4"
            if options.system_audio:
                audio_recorders.append(
                    _WasapiWavRecorder("", True, temp_dir / "sys_audio.wav", on_notice=log_cb)
                )
            if options.mic_enabled and options.mic_device.strip():
                audio_recorders.append(
                    _WasapiWavRecorder(options.mic_device.strip(), False, temp_dir / "mic_audio.wav", on_notice=log_cb)
                )
        else:
            video_target = final_out

        cmd = self.build_ffmpeg_command(
            ffmpeg,
            options,
            video_target,
            include_dshow_mic=False,
            resolved_region=resolved_region,
        )

        if options.mode == "fullscreen":
            mode_txt = f"全螢幕 {resolved_region[2]}x{resolved_region[3]}"
        elif options.mode == "window":
            w_name = options.target_window_title[:24] or "指定程式視窗"
            mode_txt = f"指定視窗（{w_name}）"
        else:
            mode_txt = f"自訂區域 {resolved_region[2]}x{resolved_region[3]}"

        audio_tags = []
        if options.system_audio:
            audio_tags.append("系統聲音內錄")
        if options.mic_enabled and options.mic_device.strip():
            audio_tags.append(f"麥克風：{options.mic_device.strip()}")
        audio_summary = " ＋ ".join(audio_tags) if audio_tags else "純畫面無聲"

        self._log(log_cb, f"開始電腦螢幕錄影（{mode_txt} / {options.fps}FPS / {audio_summary}），目標：{final_out.name}")
        self._stopping = False

        try:
            # 先啟動 FFmpeg，略等約 200ms 貼近首幀啟動時間再啟動 WASAPI 音訊，降低音畫起點落差
            proc = subprocess.Popen(
                cmd,
                cwd=str(ffmpeg.parent),
                stdin=subprocess.PIPE,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=CREATE_NO_WINDOW,
            )
            video_start_perf = time.perf_counter()
            if audio_recorders:
                time.sleep(0.20)
                if proc.poll() is None:
                    for rec in audio_recorders:
                        rec.start()
        except Exception as exc:
            for rec in audio_recorders:
                rec.stop()
            self._cleanup_temp(temp_dir)
            msg = f"啟動電腦螢幕錄影失敗：{exc}"
            self._log(log_cb, msg)
            return False, msg, None

        with self._lock:
            self._proc = proc
            self._output_path = final_out
            self._video_temp_path = video_target
            self._temp_dir = temp_dir
            self._audio_recorders = audio_recorders
            self._video_start_perf = video_start_perf

        watcher = threading.Thread(
            target=self._watch_process,
            args=(proc, final_out, log_cb, on_exit),
            daemon=True,
        )
        watcher.start()
        return True, f"正在錄製電腦螢幕（{mode_txt} / {audio_summary}）", final_out

    def _watch_process(
        self,
        proc: subprocess.Popen,
        final_out: Path,
        log_cb: LogCallback,
        on_exit: ExitCallback,
    ) -> None:
        tail_lines: Deque[str] = deque(maxlen=8)
        if proc.stdout:
            for raw_line in proc.stdout:
                line = raw_line.strip()
                if line:
                    tail_lines.append(line)
                    self._log(log_cb, f"[FFmpeg] {line}")

        code = proc.wait()
        with self._lock:
            is_manual_stop = self._stopping
            if self._proc is proc and not is_manual_stop:
                self._proc = None
                recorders = list(self._audio_recorders)
                video_temp = self._video_temp_path
                temp_dir = self._temp_dir
                self._audio_recorders = []
                self._video_temp_path = None
                self._temp_dir = None
            else:
                recorders = []
                video_temp = None
                temp_dir = None

        if not is_manual_stop:
            for rec in recorders:
                rec.stop()

            saved_path: Optional[Path] = None
            if temp_dir and video_temp and video_temp != final_out:
                if video_temp.is_file() and video_temp.stat().st_size > 1024:
                    rescue_path = final_out.with_name(f"{final_out.stem}_中斷保留.mp4")
                    try:
                        shutil.move(str(video_temp), str(rescue_path))
                        saved_path = rescue_path
                        self._log(log_cb, f"已搶救意外中斷前的錄影畫面：{rescue_path.name}")
                    except Exception as exc:
                        self._log(log_cb, f"搶救暫存影片失敗：{exc}")
                self._cleanup_temp(temp_dir)
            elif final_out.is_file() and final_out.stat().st_size > 1024:
                saved_path = final_out

            reason_hint = f"（{tail_lines[-1]}）" if tail_lines else ""
            self._log(log_cb, f"電腦螢幕錄影意外中止（狀態碼 {code}）{reason_hint}，請檢視執行紀錄確認原因。")
            if on_exit:
                try:
                    on_exit(code, saved_path)
                except Exception:
                    pass

    def stop_recording(self, log_cb: LogCallback = None) -> tuple[bool, str, Optional[Path]]:
        """安全通知 FFmpeg 寫入 MP4 檔尾並進行防重入保護，若有音訊軌則原子混流成單一 MP4。"""
        with self._lock:
            if self._finalizing:
                wait_ev = self._stop_done_event
                already_finalizing = True
                proc = None
                final_out = self._output_path
                video_temp = None
                temp_dir = None
                recorders: List[_WasapiWavRecorder] = []
                video_start_perf = 0.0
            else:
                already_finalizing = False
                proc = self._proc
                final_out = self._output_path
                video_temp = self._video_temp_path
                temp_dir = self._temp_dir
                recorders = list(self._audio_recorders)
                video_start_perf = self._video_start_perf
                if not proc or proc.poll() is not None:
                    return False, "目前沒有進行中的電腦螢幕錄影。", final_out
                # 鎖定收尾狀態，防止重複呼叫 stop_recording 或關閉程式中斷混流
                self._stopping = True
                self._finalizing = True
                self._stop_done_event.clear()

        if already_finalizing:
            wait_ev.wait()
            saved = self._last_saved_path
            if saved and saved.is_file():
                return True, f"錄影已完成並儲存：{saved.name}", saved
            return True, "錄影已完成收尾。", saved

        try:
            self._log(log_cb, "正在結束錄影並封裝 MP4 影片檔，請稍候...")

            # 先安全結束 FFmpeg（讓音訊完整涵蓋到最後一幀），再停止 WASAPI 錄音
            try:
                if proc.stdin and not proc.stdin.closed:
                    proc.stdin.write("q\n")
                    proc.stdin.flush()
                    proc.stdin.close()
                proc.wait(timeout=8)
            except Exception:
                try:
                    parent = psutil.Process(proc.pid)
                    for child in parent.children(recursive=True):
                        try:
                            child.terminate()
                        except Exception:
                            pass
                    parent.terminate()
                    parent.wait(timeout=3)
                except Exception:
                    try:
                        proc.kill()
                    except Exception:
                        pass

            for rec in recorders:
                rec.stop()

            elapsed_sec = max(1.0, time.perf_counter() - video_start_perf) if video_start_perf else 60.0

            with self._lock:
                self._proc = None
                self._audio_recorders = []
                self._video_temp_path = None
                self._temp_dir = None

            # 若有 WASAPI 音訊暫存軌，以 -c:v copy 高速無損混流為最終 MP4
            if temp_dir and video_temp and final_out and video_temp != final_out:
                valid_recorders = [
                    r
                    for r in recorders
                    if r.out_wav.is_file() and r.frames_written > 0 and r.out_wav.stat().st_size > 44
                ]
                for r in recorders:
                    if r.error:
                        self._log(log_cb, f"音訊收錄提示：{r.error}")
                    if r.discontinuity_count > 0:
                        self._log(log_cb, f"音訊緩衝提醒：錄影期間發生 {r.discontinuity_count} 次微小音訊中斷。")

                if video_temp.is_file() and valid_recorders:
                    mux_ok, mux_err = self._mux_video_and_audio(
                        video_temp,
                        valid_recorders,
                        final_out,
                        elapsed_sec=elapsed_sec,
                        log_cb=log_cb,
                    )
                    if mux_ok:
                        self._cleanup_temp(temp_dir)
                    else:
                        rescued = final_out.with_name(f"{final_out.stem}_無音訊.mp4")
                        try:
                            final_out.parent.mkdir(parents=True, exist_ok=True)
                            shutil.move(str(video_temp), str(rescued))
                            self._cleanup_temp(temp_dir)
                            self._last_saved_path = rescued
                            msg = f"音訊合成失敗（{mux_err}），已保留完整純畫面影片：{rescued.name}"
                            self._log(log_cb, msg)
                            return True, msg, rescued
                        except Exception as move_exc:
                            self._last_saved_path = video_temp
                            msg = f"音訊合成失敗且搬移暫存檔異常（{move_exc}），原始影片保留於：{video_temp}"
                            self._log(log_cb, msg)
                            return False, msg, video_temp
                elif video_temp.is_file():
                    try:
                        final_out.parent.mkdir(parents=True, exist_ok=True)
                        shutil.move(str(video_temp), str(final_out))
                        self._cleanup_temp(temp_dir)
                    except Exception as move_exc:
                        self._last_saved_path = video_temp
                        msg = f"無法將錄影檔搬移至目的地（{move_exc}），原始影片已保留於：{video_temp}"
                        self._log(log_cb, msg)
                        return False, msg, video_temp
                else:
                    self._cleanup_temp(temp_dir)

            if final_out and final_out.is_file() and final_out.stat().st_size > 1024:
                self._last_saved_path = final_out
                msg = f"錄影已完成並儲存至：{final_out}"
                self._log(log_cb, msg)
                return True, f"錄影已完成並儲存：{final_out.name}", final_out

            self._last_saved_path = None
            msg = "已停止錄影（未產生有效檔案，請檢視執行紀錄）。"
            self._log(log_cb, msg)
            return False, msg, final_out
        finally:
            with self._lock:
                self._finalizing = False
            self._stop_done_event.set()

    def _mux_video_and_audio(
        self,
        video_path: Path,
        recorders: List[_WasapiWavRecorder],
        final_out: Path,
        elapsed_sec: float = 60.0,
        log_cb: LogCallback = None,
    ) -> tuple[bool, str]:
        """將視訊軌 (-c:v copy 無損) 與 1~2 條 WAV 音訊軌安全原子合成為最終 MP4。

        - 先輸出到同資料夾的 .muxing.mp4，確認成功後才原子替換為最終檔名。
        - 不使用 -shortest，避免單一音訊異常截斷完整影片。
        - 依錄影長度動態計算逾時，避免長時間高畫質錄影被 60 秒截斷。
        """
        ffmpeg = self.binary_manager.get_ffmpeg_path()
        if not ffmpeg:
            return False, "找不到 FFmpeg 執行檔"

        wav_paths = [r.out_wav for r in recorders]
        self._log(log_cb, f"正在高速合成畫面與 {len(wav_paths)} 條音訊軌至 MP4...")

        mux_tmp = final_out.with_name(f"{final_out.stem}.muxing.mp4")
        cmd: List[str] = [str(ffmpeg), "-y", "-hide_banner", "-loglevel", "warning", "-i", str(video_path)]
        for wp in wav_paths:
            cmd.extend(["-i", str(wp)])

        if len(wav_paths) == 1:
            cmd.extend(
                [
                    "-map",
                    "0:v:0",
                    "-map",
                    "1:a:0",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                ]
            )
        else:
            cmd.extend(
                [
                    "-filter_complex",
                    "[1:a][2:a]amix=inputs=2:duration=longest:dropout_transition=2:normalize=0[aout]",
                    "-map",
                    "0:v:0",
                    "-map",
                    "[aout]",
                    "-c:v",
                    "copy",
                    "-c:a",
                    "aac",
                    "-b:a",
                    "192k",
                    "-movflags",
                    "+faststart",
                ]
            )
        cmd.append(str(mux_tmp))

        # 動態逾時：至少 5 分鐘，長時間錄影自動放寬
        mux_timeout = max(300, int(elapsed_sec * 2.0) + 120)

        try:
            res = subprocess.run(
                cmd,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=mux_timeout,
                creationflags=CREATE_NO_WINDOW,
            )
            if res.returncode == 0 and mux_tmp.is_file() and mux_tmp.stat().st_size > 1024:
                os.replace(mux_tmp, final_out)
                return True, ""

            err_msg = res.stderr.strip() or f"FFmpeg 回傳狀態碼 {res.returncode}"
            self._log(log_cb, f"音訊混流失敗：{err_msg}")
            mux_tmp.unlink(missing_ok=True)
            return False, err_msg
        except subprocess.TimeoutExpired:
            self._log(log_cb, f"音訊混流逾時（超過 {mux_timeout} 秒）。")
            mux_tmp.unlink(missing_ok=True)
            return False, "音訊合成逾時"
        except Exception as exc:
            self._log(log_cb, f"音訊混流發生錯誤：{exc}")
            mux_tmp.unlink(missing_ok=True)
            return False, str(exc)

    @staticmethod
    def _cleanup_temp(temp_dir: Optional[Path]) -> None:
        if not temp_dir or not temp_dir.exists():
            return
        for _ in range(3):
            try:
                for item in temp_dir.iterdir():
                    item.unlink(missing_ok=True)
                temp_dir.rmdir()
                return
            except Exception:
                time.sleep(0.2)

    @staticmethod
    def _log(cb: LogCallback, message: str) -> None:
        if cb:
            try:
                cb(message)
            except Exception:
                pass
