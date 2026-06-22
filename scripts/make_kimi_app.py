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


def _resolve_build_token() -> str:
    """Find HF_TOKEN at build time: env first, then the user's login zsh."""
    tok = os.environ.get("HF_TOKEN", "").strip()
    if tok:
        return tok
    try:
        out = subprocess.run(["/bin/zsh", "-ilc", "print -r -- $HF_TOKEN"],
                             capture_output=True, text=True, timeout=10)
        for line in reversed(out.stdout.splitlines()):
            line = line.strip()
            if line.startswith("hf_"):
                return line
    except Exception:
        pass
    return ""


LAUNCHER = r"""#!/bin/bash
# This app does NOT stay running. It starts the chat server detached (nohup),
# opens the browser, and exits cleanly. That avoids the "application is not open
# anymore" error you get when a GUI app's main process blocks or dies. The token
# + python path are baked in at build time (a Finder launch can't read ~/.zshrc).
LOG="$HOME/Library/Logs/Kimi.log"
PORT=__PORT__
URL="http://127.0.0.1:$PORT"

export HF_TOKEN="${HF_TOKEN:-__TOKEN__}"
PY="__PYTHON__"
[ -x "$PY" ] || PY="$(command -v python3 || echo /usr/bin/python3)"

{
  echo "=== Kimi launch $(date) ==="
  echo "python=$PY token_len=${#HF_TOKEN}"
} >>"$LOG" 2>&1

if [ -z "$HF_TOKEN" ]; then
  osascript -e 'display dialog "Kimi has no HF_TOKEN baked in. Re-run the builder from a terminal where HF_TOKEN is set:\n\n  python3 ~/hermes-agent/scripts/make_kimi_app.py" buttons {"OK"} with title "Kimi" with icon caution'
  exit 0
fi

# Start the server only if it is not already listening.
if ! lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "starting server: $PY __HFUI__" >>"$LOG" 2>&1
  nohup "$PY" "__HFUI__" "$HF_TOKEN" "$PORT" >>"$LOG" 2>&1 &
  sleep 1.6
fi

open "$URL"
exit 0
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

    # Launcher — bake in the token + python captured from the build environment.
    token = _resolve_build_token()
    python = sys.executable or "/usr/bin/python3"
    print(f"  baking: python={python} token_len={len(token)}")
    if not token:
        print("  WARNING: HF_TOKEN not found in this shell — the app will prompt"
              " you to rebuild. Run: export HF_TOKEN=hf_... then re-run this.")
    launch = macos / "launch"
    launch.write_text(LAUNCHER
                      .replace("__PORT__", str(PORT))
                      .replace("__TOKEN__", token)
                      .replace("__PYTHON__", python)
                      .replace("__HFUI__", str(HF_UI)))
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


COMMAND_FILE = r"""#!/bin/bash
# Double-click me: Terminal opens and runs the HF chat server in the foreground.
# You see exactly what happens, it inherits your shell environment, and it can
# never "bounce" or report "not open anymore" the way a .app bundle can.
# Stop it with Ctrl-C or by closing this window.
export HF_TOKEN="${HF_TOKEN:-__TOKEN__}"
PY="__PYTHON__"
[ -x "$PY" ] || PY="$(command -v python3 || echo /usr/bin/python3)"
PORT=__PORT__
URL="http://127.0.0.1:$PORT"
echo "Starting HF chat at $URL  (python: $PY)"
if lsof -ti:"$PORT" >/dev/null 2>&1; then
  echo "Already running — just opening the browser."
  open "$URL"; exit 0
fi
( sleep 1.6; open "$URL" ) &
exec "$PY" "__HFUI__" "$HF_TOKEN" "$PORT"
"""


def build_command_file(dest_dir: Path) -> Path:
    token = _resolve_build_token()
    python = sys.executable or "/usr/bin/python3"
    cmd = dest_dir / f"{APP_NAME}.command"
    cmd.write_text(COMMAND_FILE
                   .replace("__PORT__", str(PORT))
                   .replace("__TOKEN__", token)
                   .replace("__PYTHON__", python)
                   .replace("__HFUI__", str(HF_UI)))
    cmd.chmod(0o755)
    return cmd


def main() -> int:
    if sys.platform != "darwin":
        print("This builds a macOS launcher and must be run on your Mac.", file=sys.stderr)
        return 1
    if not HF_UI.exists():
        print(f"Cannot find {HF_UI}", file=sys.stderr)
        return 1

    desktop = Path.home() / "Desktop"

    # The bulletproof launcher first — a double-clickable .command.
    cmd = build_command_file(desktop)
    print(f"✓ Created {cmd}  (double-click this — most reliable)")

    # The pretty .app with the custom icon (can be finicky on some setups).
    print(f"\nBuilding {APP_NAME}.app …")
    app = build_app(desktop)
    print(f"✓ Created {app}")

    if "--apps" in sys.argv:
        dest = Path("/Applications") / f"{APP_NAME}.app"
        if dest.exists():
            shutil.rmtree(dest)
        shutil.copytree(app, dest)
        print(f"✓ Copied to {dest}")

    print("\nTwo launchers are on your Desktop:")
    print(f"  • {APP_NAME}.command  — double-click; opens Terminal + browser (always works)")
    print(f"  • {APP_NAME}.app      — pretty icon; right-click → Open the first time")
    print("\nIf .command warns about an unidentified developer: right-click → Open.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
