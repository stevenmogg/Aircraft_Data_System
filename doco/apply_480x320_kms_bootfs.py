# Fix live Stratux SD for 480x320 on Pi 5 (KMS)
#
# Why previous attempts failed:
#   Stratux boots with firmware bcm2708_fb, which copies EDID size (often 1920x1080).
#   Legacy config.txt hdmi_cvt / framebuffer_* do not override that on Pi 5.
#   cmdline video=HDMI-A-* only works after enabling dtoverlay=vc4-kms-v3d-pi5.
#
# Apply with the card mounted at /Volumes/bootfs (Pi powered off), then boot.

python3 - <<'PY'
from pathlib import Path
boot = Path("/Volumes/bootfs")
assert boot.exists(), "Mount the SD boot partition at /Volumes/bootfs first"

cfg = boot / "config.txt"
cmd = boot / "cmdline.txt"

text = cfg.read_text()
lines = []
skip = (
    "disable_fw_kms_setup",
    "hdmi_ignore_edid",
    "hdmi_force_hotplug",
    "hdmi_group",
    "hdmi_mode",
    "hdmi_cvt",
    "hdmi_drive",
    "framebuffer_width",
    "framebuffer_height",
    "framebuffer_depth",
    "max_framebuffers",
    "dtoverlay=vc4-kms-v3d",
)
for line in text.splitlines():
    s = line.strip()
    if s.startswith("# 480x320") or s.startswith("# Stratux images default") or s.startswith("# Bookworm/Pi") or s.startswith("# Early-firmware") or s.startswith("# Ignore EDID") or s.startswith("# Prevent firmware"):
        continue
    if any(s.startswith(p) for p in skip):
        continue
    lines.append(line)

block = """
# 480x320 HDMI panel (Pi 5) — real KMS so cmdline video= is honoured
dtoverlay=vc4-kms-v3d-pi5
max_framebuffers=2
disable_fw_kms_setup=1
"""
cfg.write_text("\n".join(lines).rstrip() + "\n" + block, encoding="utf-8", newline="\n")

parts = [p for p in cmd.read_text().strip().split() if not p.startswith("video=HDMI-A-")]
video = ["video=HDMI-A-1:480x320M@60D", "video=HDMI-A-2:480x320M@60D"]
cmd.write_text(" ".join(video + parts) + "\n", encoding="utf-8", newline="\n")
print("Updated", cfg)
print("Updated", cmd)
print(cmd.read_text())
print("--- display lines ---")
print("\n".join(l for l in cfg.read_text().splitlines() if "vc4" in l or "framebuf" in l or "disable_fw" in l or "480" in l))
PY
