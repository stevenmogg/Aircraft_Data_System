# Apply 480x320 HDMI mode on a Stratux SD card from the Mac
#
# 1. Power off the Pi and insert the microSD into the Mac.
# 2. The boot partition mounts as "bootfs" (or similar).
# 3. Edit cmdline.txt — MUST remain ONE single line.
# 4. Replace the entire contents with a line like below
#    (keep your existing root=PARTUUID=... values from the current file):

video=HDMI-A-1:480x320MR@60me video=HDMI-A-2:480x320MR@60me systemd.restore_state=0 rfkill.default_state=1 console=tty1 root=PARTUUID=KEEP_EXISTING rootfstype=ext4 fsck.repair=yes rootwait ro init=/sbin/init-overlay

# 5. In config.txt, ensure these lines exist (add if missing):
#
# disable_fw_kms_setup=1
# hdmi_force_hotplug=1
# hdmi_group=2
# hdmi_mode=87
# hdmi_cvt=480 320 60 6 0 0 0
# hdmi_drive=1
#
# 6. Eject the card, boot the Pi, check text size.
#
# If still tiny: try the other micro-HDMI port on the Pi 5, or tell us the
# exact panel brand/model (some 480x320 panels need a vendor mode string).
