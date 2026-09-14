# Pi 5 onboard fan / thermal control

The official Raspberry Pi 5 **FAN** connector (case / active cooler) is controlled by
**firmware + kernel thermal trips**, not by Stratux `fancontrol`.

## Why not Stratux fancontrol?

| | Pi 5 FAN header | Stratux `fancontrol` |
|--|-----------------|----------------------|
| Hardware | Board 4-pin FAN connector | Discrete PWM on **BCM GPIO18** (pin 12) |
| Driver | `dtparam=fan_temp*` thermal trips | `/opt/stratux/bin/fancontrol` PID → GPIO PWM |
| Cozy choice | **Use this** | Leave **disabled** |

## Cooling curve (Cozy)

Installed into `/boot/firmware/config.txt` by `scripts/setup_pi5_fan.sh` (and image template):

| Level | Temp | Hysteresis | PWM (0–255) |
|-------|------|------------|-------------|
| 0 | 40 °C | 5 °C | 100 |
| 1 | 50 °C | 5 °C | 150 |
| 2 | 60 °C | 5 °C | 200 |
| 3 | 67.5 °C | 5 °C | 255 |

Slightly earlier than Raspberry Pi stock defaults (50 / 60 / 67.5 / 75 °C) for an enclosed avionics case.

## Install on live Pi

```bash
# from Mac repo
scp scripts/setup_pi5_fan.sh stratux:/tmp/
ssh stratux 'sudo bash /tmp/setup_pi5_fan.sh --install'
ssh stratux 'sudo reboot'

# after reboot — audible spin test + status
ssh stratux 'sudo bash /tmp/setup_pi5_fan.sh --test'
ssh stratux 'sudo bash /tmp/setup_pi5_fan.sh --status'
```

Or copy from `/cozy-data-system/scripts/setup_pi5_fan.sh` once deployed.

## Monitor

```bash
vcgencmd measure_temp
cat /sys/class/thermal/thermal_zone0/temp   # millidegrees C
cat /sys/class/thermal/cooling_device0/cur_state
cat /sys/class/thermal/cooling_device0/max_state
```

Stratux UI also shows `CPUTemp` on status pages when Stratux is running.

## Manual override (test only)

```bash
# force max cooling level (listen for fan)
echo 4 | sudo tee /sys/class/thermal/cooling_device0/cur_state
# return to auto
echo 0 | sudo tee /sys/class/thermal/cooling_device0/cur_state
```

(`max_state` is typically 4 on Pi 5; levels map to the `fan_temp*` speeds.)
