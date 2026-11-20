from web.app.services import system as sys_svc


def test_parse_throttled_pi5_undervolt():
    assert sys_svc.parse_throttled("throttled=0x50005") == 0x50005
    assert sys_svc.parse_throttled("throttled=0x0") == 0
    assert sys_svc.parse_throttled("") is None
    assert sys_svc.parse_throttled("VCHI initialization failed") is None


def test_parse_ext5v():
    assert sys_svc.parse_ext5v("EXT5V_V volt=4.83012000V") == 4.83012
    assert sys_svc.parse_ext5v("EXT5V_V volt=5.10234000V") == 5.10234
    assert sys_svc.parse_ext5v("") is None


def test_throttle_flags_0x50005():
    flags = sys_svc.throttle_flags(0x50005)
    assert "undervoltage now" in flags
    assert "throttled now" in flags
    assert "undervoltage occurred" in flags
    assert "throttled occurred" in flags


def test_classify_power_levels():
    assert sys_svc.classify_power(None, None) == (None, None)
    assert sys_svc.classify_power(5.05, 0) == (True, "ok")
    assert sys_svc.classify_power(4.83, 0) == (False, "warn")
    assert sys_svc.classify_power(4.55, 0x50005) == (False, "bad")
    assert sys_svc.classify_power(5.05, 1 << 16) == (True, "warn")


def test_power_status_uses_vcgencmd(monkeypatch):
    def fake_run(cmd, timeout=2.0):
        if cmd[:2] == ["vcgencmd", "get_throttled"]:
            return "throttled=0x50005"
        if cmd[:3] == ["vcgencmd", "pmic_read_adc", "EXT5V_V"]:
            return "EXT5V_V volt=4.83012000V"
        return ""

    monkeypatch.setattr(sys_svc, "_run", fake_run)
    p = sys_svc.power_status()
    assert p["available"] is True
    assert p["ext5v_v"] == 4.83012
    assert p["throttled"] == "0x50005"
    assert p["undervoltage_now"] is True
    assert p["level"] == "bad"
    assert p["ok"] is False


def test_samba_status_up_and_listening(monkeypatch):
    def fake_run(cmd, timeout=2.0):
        if cmd == ["systemctl", "is-active", "smbd.service"]:
            return "active"
        if cmd == ["systemctl", "is-enabled", "smbd.service"]:
            return "enabled"
        return ""

    monkeypatch.setattr(sys_svc, "_run", fake_run)
    monkeypatch.setattr(sys_svc, "_port_listening", lambda port: True)
    s = sys_svc.samba_status()
    assert s["ok"] is True
    assert s["share"] == "cozy-data"
    assert s["smbd"]["active"] == "active"
    assert s["listening_445"] is True


def test_samba_status_down(monkeypatch):
    def fake_run(cmd, timeout=2.0):
        if cmd == ["systemctl", "is-active", "smbd.service"]:
            return "failed"
        if cmd == ["systemctl", "is-enabled", "smbd.service"]:
            return "enabled"
        return ""

    monkeypatch.setattr(sys_svc, "_run", fake_run)
    monkeypatch.setattr(sys_svc, "_port_listening", lambda port: False)
    s = sys_svc.samba_status()
    assert s["ok"] is False
    assert s["smbd"]["active"] == "failed"


def test_port_listening_from_proc(monkeypatch):
    tcp = (
        "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        "   0: 00000000:01BD 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 1 1 0000000000000000 100 0 0 10 0\n"
    )

    def fake_read(path):
        if path == "/proc/net/tcp":
            return tcp.strip()
        return None

    monkeypatch.setattr(sys_svc, "_read_text", fake_read)
    assert sys_svc._port_listening(445) is True
    assert sys_svc._port_listening(139) is False


PROC_STAT = """cpu  100 10 50 800 40 5 15 0 0 0
cpu0 50 5 25 400 20 2 8 0 0 0
intr 0
"""

PROC_STAT_LATER = """cpu  160 20 80 860 50 7 23 0 0 0
cpu0 80 10 40 430 25 3 12 0 0 0
intr 0
"""

PROC_NET = """Inter-|   Receive                                                |  Transmit
 face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
    lo: 100 0 0 0 0 0 0 0 200 0 0 0 0 0 0 0
  wlan0: 1000 1 0 0 0 0 0 0 400 1 0 0 0 0 0 0
  veth0: 9 0 0 0 0 0 0 0 9 0 0 0 0 0 0 0
"""

PROC_DISK = """   8       0 sda 1 0 200 0 3 0 100 0 0 0 0
   8       1 sda1 1 0 10 0 3 0 10 0 0 0 0
 179       0 mmcblk0 10 0 400 0 5 0 80 0 0 0 0
 179       1 mmcblk0p1 10 0 40 0 5 0 8 0 0 0 0
   7       0 loop0 0 0 0 0 0 0 0 0 0 0 0
"""


def test_parse_proc_stat_and_cpu_percent():
    a = sys_svc.parse_proc_stat(PROC_STAT)
    b = sys_svc.parse_proc_stat(PROC_STAT_LATER)
    assert a["total"] == 100 + 10 + 50 + 800 + 40 + 5 + 15
    pct = sys_svc.cpu_percent_from_delta(a, b)
    # iowait is counted as idle for overall busy % (110/180)
    assert pct["percent"] == 61.1
    assert pct["user_pct"] == 38.9
    assert pct["system_pct"] == 22.2
    assert pct["iowait_pct"] == 5.6


def test_parse_proc_net_dev_skips_virtual():
    nets = sys_svc.parse_proc_net_dev(PROC_NET)
    assert "lo" not in nets
    assert "veth0" not in nets
    assert nets["wlan0"]["rx_bytes"] == 1000
    assert nets["wlan0"]["tx_bytes"] == 400


def test_parse_proc_diskstats_whole_disks_only():
    disks = sys_svc.parse_proc_diskstats(PROC_DISK)
    assert "loop0" not in disks
    assert "sda1" not in disks
    assert "mmcblk0p1" not in disks
    assert disks["sda"]["read_bytes"] == 200 * 512
    assert disks["mmcblk0"]["write_bytes"] == 80 * 512
