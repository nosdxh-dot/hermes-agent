#!/usr/bin/env python3
"""Build a double-clickable macOS app (Kimi.app) for the HF chat UI.

Generates a Claude Code-purple icon (pure stdlib — no Pillow) and assembles a
proper .app bundle on your Desktop. Double-clicking it starts the local server
(scripts/hf_ui.py) and opens the chat in your browser.

Usage (run once, on your Mac):
    python3 scripts/make_kimi_app.py            # -> ~/Desktop/Kimi.app
    python3 scripts/make_kimi_app.py --apps     # also copy to /Applications

The launcher sources your login shell, so it picks up HF_TOKEN from ~/.zshrc
the same way the `kimi` alias does. No token is baked into the bundle.
"""

import math
import os
import plistlib
import shutil
import struct
import subprocess
import sys
import zlib
from pathlib import Path

APP_NAME = "Kimi"
PORT = 8765
REPO = Path(__file__).resolve().parent.parent
HF_UI = REPO / "scripts" / "hf_ui.py"


# ── Pure-stdlib PNG writer ────────────────────────────────────────────────
def _write_png(path: Path, w: int, h: int, rgba: bytearray) -> None:
    def chunk(typ: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + typ + data
                + struct.pack(">I", zlib.crc32(typ + data) & 0xffffffff))
    raw = bytearray()
    for y in range(h):
        raw.append(0)                       # filter type 0 (none)
        raw += rgba[y * w * 4:(y + 1) * w * 4]
    sig = b"\x89PNG\r\n\x1a\n"
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)   # 8-bit RGBA
    idat = zlib.compress(bytes(raw), 9)
    path.write_bytes(sig + chunk(b"IHDR", ihdr)
                     + chunk(b"IDAT", idat) + chunk(b"IEND", b""))


def generate_icon_png(path: Path, S: int = 1024) -> None:
    """A rounded purple square with a white ❯ chevron — the Claude Code look."""
    top = (0x7C, 0x3A, 0xED)      # --accent-strong
    bot = (0xB1, 0x8C, 0xFF)      # --accent
    white = (0xF4, 0xF0, 0xEB)    # --text
    pad = S * 0.06
    rmin, rmax = pad, S - pad
    radius = (rmax - rmin) * 0.235
    # chevron segments: (left,top) -> (apex,mid) -> (left,bottom)
    lx, ax = S * 0.40, S * 0.605
    ty, my, by = S * 0.30, S * 0.50, S * 0.70
    hw = S * 0.060

    def dseg(px, py, x1, y1, x2, y2):
        vx, vy = x2 - x1, y2 - y1
        t = ((px - x1) * vx + (py - y1) * vy) / (vx * vx + vy * vy)
        t = max(0.0, min(1.0, t))
        return math.hypot(px - (x1 + t * vx), py - (y1 + t * vy))

    def rr_sdf(x, y):
        cx = min(max(x, rmin + radius), rmax - radius)
        cy = min(max(y, rmin + radius), rmax - radius)
        return math.hypot(x - cx, y - cy) - radius

    px = bytearray(S * S * 4)
    for y in range(S):
        fy = y + 0.5
        t = max(0.0, min(1.0, (fy - rmin) / (rmax - rmin)))
        br = int(top[0] + (bot[0] - top[0]) * t)
        bg = int(top[1] + (bot[1] - top[1]) * t)
        bb = int(top[2] + (bot[2] - top[2]) * t)
        for x in range(S):
            fx = x + 0.5
            sd = rr_sdf(fx, fy)
            if sd > 1.0:
                continue                     # transparent outside the square
            ba = max(0.0, min(1.0, 1.0 if sd < -1 else 1.0 - (sd + 1) / 2.0))
            d = min(dseg(fx, fy, lx, ty, ax, my), dseg(fx, fy, ax, my, lx, by))
            ca = 1.0 if d < hw - 1 else (0.0 if d > hw + 1 else 1.0 - (d - (hw - 1)) / 2.0)
            ca = max(0.0, min(1.0, ca))
            r = int(br + (white[0] - br) * ca)
            g = int(bg + (white[1] - bg) * ca)
            b = int(bb + (white[2] - bb) * ca)
            i = (y * S + x) * 4
            px[i], px[i + 1], px[i + 2], px[i + 3] = r, g, b, int(ba * 255)
    _write_png(path, S, S, px)


# ── macOS .app assembly ───────────────────────────────────────────────────
def _build_icns(png: Path, out_icns: Path, work: Path) -> bool:
    iconset = work / "icon.iconset"
    iconset.mkdir(parents=True, exist_ok=True)
    sizes = [16, 32, 64, 128, 256, 512, 1024]
    names = {16: "16x16", 32: "32x32", 128: "128x128", 256: "256x256", 512: "512x512"}
    try:
        for s in sizes:
            base = names.get(s)
            if base:
                subprocess.run(["sips", "-z", str(s), str(s), str(png),
                                "--out", str(iconset / f"icon_{base}.png")],
                               check=True, capture_output=True)
            # @2x retina variants
            half = s // 2
            base2 = names.get(half)
            if base2:
                subprocess.run(["sips", "-z", str(s), str(s), str(png),
                                "--out", str(iconset / f"icon_{base2}@2x.png")],
                               check=True, capture_output=True)
        subprocess.run(["iconutil", "-c", "icns", str(iconset),
                        "-o", str(out_icns)], check=True, capture_output=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False


LAUNCHER = r"""#!/bin/bash
# Launched by Finder with no terminal attached, so we DON'T run an interactive
# shell as the main process (that exits instantly -> the icon just bounces).
# Instead we capture HF_TOKEN and the python3 path from the user's zsh env via
# short subshells, log everything, and surface failures with a dialog.
LOG="$HOME/Library/Logs/Kimi.log"
exec >>"$LOG" 2>&1
echo "=== Kimi launch $(date) ==="
PORT=__PORT__
URL="http://127.0.0.1:$PORT"

# Pull values out of the login+interactive zsh environment (sources ~/.zshrc).
TOKEN="$(/bin/zsh -ilc 'print -r -- $HF_TOKEN' 2>/dev/null | tail -n1)"
PY="$(/bin/zsh -ilc 'command -v python3' 2>/dev/null | tail -n1)"
[ -x "$PY" ] || PY="/usr/bin/python3"
echo "python=$PY token_len=${#TOKEN}"

if [ -z "$TOKEN" ]; then
  osascript -e 'display dialog "Kimi could not find HF_TOKEN.\n\nOpen Terminal and confirm:\n  echo $HF_TOKEN\n\nIt must be exported in ~/.zshrc (export HF_TOKEN=hf_...)." buttons {"OK"} with title "Kimi" with icon caution'
  exit 1
fi

if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "server already up; opening browser"
  open "$URL"
  exit 0
fi
( sleep 1.2; open "$URL" ) &
echo "starting server: $PY __HFUI__"
exec "$PY" "__HFUI__" "$TOKEN"
"""


def build_app(dest_dir: Path) -> Path:
    app = dest_dir / f"{APP_NAME}.app"
    if app.exists():
        shutil.rmtree(app)
    macos = app / "Contents" / "MacOS"
    res = app / "Contents" / "Resources"
    macos.mkdir(parents=True)
    res.mkdir(parents=True)

    # Icon
    png = res / "icon_src.png"
    print("  rendering icon…")
    generate_icon_png(png, 1024)
    icns = res / "icon.icns"
    if _build_icns(png, icns, app / "Contents"):
        print("  icns built ✓")
    else:
        print("  (sips/iconutil unavailable — using PNG fallback; icon may look plain)")
        shutil.copy(png, res / "icon.png")
    png.unlink(missing_ok=True)

    # Launcher
    launch = macos / "launch"
    launch.write_text(LAUNCHER.replace("__PORT__", str(PORT)).replace("__HFUI__", str(HF_UI)))
    launch.chmod(0o755)

    # Info.plist
    info = {
        "CFBundleName": APP_NAME,
        "CFBundleDisplayName": APP_NAME,
        "CFBundleIdentifier": "co.hermes.kimi",
        "CFBundleVersion": "1.0",
        "CFBundleShortVersionString": "1.0",
        "CFBundlePackageType": "APPL",
        "CFBundleExecutable": "launch",
        "CFBundleIconFile": "icon",
        "NSHighResolutionCapable": True,
    }
    with open(app / "Contents" / "Info.plist", "wb") as f:
        plistlib.dump(info, f)

    # Nudge Finder to refresh the icon
    try:
        os.utime(app, None)
        subprocess.run(["touch", str(app)], check=False, capture_output=True)
    except Exception:
        pass
    return app


def main() -> int:
    if sys.platform != "darwin":
        print("This builds a macOS .app and must be run on your Mac.", file=sys.stderr)
        return 1
    if not HF_UI.exists():
        print(f"Cannot find {HF_UI}", file=sys.stderr)
        return 1

    desktop = Path.home() / "Desktop"
    print(f"Building {APP_NAME}.app …")
    app = build_app(desktop)
    print(f"\n✓ Created {app}")

    if "--apps" in sys.argv:
        dest = Path("/Applications") / f"{APP_NAME}.app"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(app, dest)
        print(f"✓ Copied to {dest}")

    print("\nDouble-click it on your Desktop. First launch: right-click → Open")
    print("(Gatekeeper warns on unsigned apps — only needed the first time).")
    return 0


if __name__ == "__main__":
    sys.exit(main())
