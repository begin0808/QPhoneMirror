"""QPhoneMirror 一鍵打包腳本（自動更新當日版本號並產出免裝 Python 的獨立 .exe 攜帶版）。"""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
import sys
import zipfile
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "assets"
ICON_PATH = ASSETS_DIR / "qphonemirror.ico"
DIST_NAME = "QPhoneMirror_繁中免安裝版"


def sync_build_version() -> str:
    """自動將 config/settings.py 與 README_使用說明.txt 的版本號更新為當日日期 (VYYYYMMDD)。"""
    today_ver = f"V{datetime.now().strftime('%Y%m%d')}"
    today_year = datetime.now().strftime("%Y")

    settings_file = ROOT / "config" / "settings.py"
    if settings_file.is_file():
        content = settings_file.read_text(encoding="utf-8")
        content = re.sub(r'APP_VERSION\s*=\s*"V\d{8}"', f'APP_VERSION = "{today_ver}"', content)
        content = re.sub(r'COPYRIGHT_YEAR\s*=\s*"\d{4}"', f'COPYRIGHT_YEAR = "{today_year}"', content)
        settings_file.write_text(content, encoding="utf-8")

    readme_file = ROOT / "README_使用說明.txt"
    if readme_file.is_file():
        r_content = readme_file.read_text(encoding="utf-8")
        r_content = re.sub(r"版本：V\d{8}", f"版本：{today_ver}", r_content)
        readme_file.write_text(r_content, encoding="utf-8")

    return today_ver


def generate_cute_icon(icon_path: Path) -> Path:
    """使用 Pillow 繪製可愛馬卡龍薄荷＋櫻花粉圓角手機圖示 (.ico)。"""
    icon_path.parent.mkdir(parents=True, exist_ok=True)
    size = 256
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    # 薄荷綠大圓角背景
    draw.rounded_rectangle([14, 14, 242, 242], radius=64, fill="#56C596")
    # 奶油白圓角手機外框
    draw.rounded_rectangle([68, 36, 188, 220], radius=30, fill="#FFFDF9", outline="#3D405B", width=6)
    # 櫻花粉螢幕內頁
    draw.rounded_rectangle([82, 58, 174, 188], radius=16, fill="#FF8BA7")
    # 可愛表情細節
    draw.ellipse([104, 102, 118, 116], fill="#FFFDF9")
    draw.ellipse([138, 102, 152, 116], fill="#FFFDF9")
    draw.arc([110, 114, 146, 142], start=15, end=165, fill="#FFFDF9", width=5)
    # 底部 Home 圓點
    draw.ellipse([120, 198, 136, 212], fill="#56C596")

    img.save(
        icon_path,
        format="ICO",
        sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)],
    )
    return icon_path


def build() -> None:
    version = sync_build_version()
    print(f"正在準備打包 QPhoneMirror.exe ({version}) ...")
    generate_cute_icon(ICON_PATH)
    print(f"已產生專屬彩色圖示：{ICON_PATH}")

    cmd = [
        sys.executable,
        "-m",
        "PyInstaller",
        "--noconfirm",
        "--clean",
        "--windowed",
        "--onedir",
        "--name",
        "QPhoneMirror",
        "--icon",
        str(ICON_PATH),
        "--collect-all",
        "customtkinter",
        "--collect-all",
        "soundcard",
        "--exclude-module",
        "matplotlib",
        "--exclude-module",
        "scipy",
        "--exclude-module",
        "pandas",
        "--exclude-module",
        "pytest",
        "--exclude-module",
        "IPython",
        "--exclude-module",
        "yaml",
        "--exclude-module",
        "bcrypt",
        "--exclude-module",
        "simplejson",
        "--add-data",
        f"{ASSETS_DIR};assets",
        str(ROOT / "main.py"),
    ]

    print("正在執行 PyInstaller 封裝...")
    res = subprocess.run(cmd, cwd=str(ROOT))
    if res.returncode != 0:
        print("PyInstaller 打包失敗，請檢查上方錯誤訊息。")
        sys.exit(res.returncode)

    built_dir = ROOT / "dist" / "QPhoneMirror"
    release_dir = ROOT / "dist" / DIST_NAME
    if release_dir.exists():
        try:
            shutil.rmtree(release_dir)
        except PermissionError:
            print(f"\n[注意] 無法覆寫 {release_dir}：偵測到 QPhoneMirror.exe 正在執行中。")
            print("請先關閉已開啟的 QPhoneMirror 視窗，再重新執行 python build_exe.py。")
            sys.exit(2)
    built_dir.rename(release_dir)

    # 發布版維持零預裝第三方執行檔（由使用者於程式內一鍵下載官方核心，兼顧輕量與開源授權合規）
    target_bin = release_dir / "bin"
    if target_bin.exists():
        shutil.rmtree(target_bin, ignore_errors=True)
    (target_bin / "scrcpy").mkdir(parents=True, exist_ok=True)
    (target_bin / "uxplay").mkdir(parents=True, exist_ok=True)
    (target_bin / "ffmpeg").mkdir(parents=True, exist_ok=True)
    # 確保發布包不含個人設定與暫存錄影檔
    cfg_dir = release_dir / "config"
    if cfg_dir.exists():
        shutil.rmtree(cfg_dir, ignore_errors=True)
    cfg_dir.mkdir(parents=True, exist_ok=True)
    cap_dir = release_dir / "captures"
    if cap_dir.exists():
        shutil.rmtree(cap_dir, ignore_errors=True)
    cap_dir.mkdir(parents=True, exist_ok=True)

    readme_src = ROOT / "README_使用說明.txt"
    if readme_src.exists():
        shutil.copy2(readme_src, release_dir / readme_src.name)

    license_src = ROOT / "LICENSE"
    if license_src.exists():
        shutil.copy2(license_src, release_dir / license_src.name)

    # 產生供 GitHub Releases 直接上傳的乾淨免安裝壓縮檔與 SHA-256 校驗碼
    zip_name = f"QPhoneMirror_{version}_Win64_Portable.zip"
    zip_path = ROOT / "dist" / zip_name
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6) as zf:
        for item in sorted(release_dir.rglob("*")):
            rel = item.relative_to(release_dir.parent)
            if item.is_dir():
                # 保留空資料夾結構 (bin/scrcpy, bin/uxplay, bin/ffmpeg, config, captures)
                if not any(item.iterdir()):
                    zf.writestr(str(rel).replace("\\", "/") + "/", "")
            else:
                zf.write(item, arcname=str(rel).replace("\\", "/"))

    sha256 = hashlib.sha256()
    with open(zip_path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            sha256.update(chunk)
    digest_hex = sha256.hexdigest()
    sha_path = ROOT / "dist" / f"{zip_name}.sha256"
    sha_path.write_text(f"{digest_hex}  {zip_name}\n", encoding="utf-8")

    print(f"\n打包完成！（版本 {version}）")
    print(f"免安裝版資料夾位置：{release_dir}")
    print(f"執行檔位置：{release_dir / 'QPhoneMirror.exe'}")
    print(f"GitHub Release 壓縮檔：{zip_path} ({zip_path.stat().st_size / (1024 * 1024):.1f} MB)")
    print(f"SHA-256：{digest_hex}")


if __name__ == "__main__":
    build()
