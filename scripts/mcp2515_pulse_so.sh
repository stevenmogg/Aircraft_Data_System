      again                                                                            again                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                  `p                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                                        #!/bin/bash
# Slow-clock SPI so MCP2515 SO pulses (measure SO pin and Pi pin 21).
# Usage on Pi: sudo ./scripts/mcp2515_pulse_so.sh [seconds]
set -euo pipefail
SECS="${1:-40}"
echo "PULSING SO for ${SECS}s — probe MCP2515 SO and Pi pin 21 NOW"

cleanup() {
  pinctrl set 8 op dh
  pinctrl set 9 a0
  pinctrl set 10 a0
  pinctrl set 11 a0
  echo "DONE — CS high, SPI0 pins restored"
  pinctrl get 8,9,10,11
}
trap cleanup EXIT

pinctrl set 8 op dh
pinctrl set 10 op dl
pinctrl set 11 op dl
pinctrl set 9 ip pn

# Bitbang SPI mode 0, one byte. MOSI from $1 (0-255).
xfer_byte() {
  local b="$1" i bit
  for i in 7 6 5 4 3 2 1 0; do
    bit=$(( (b >> i) & 1 ))
    if [ "$bit" -eq 1 ]; then pinctrl set 10 op dh; else pinctrl set 10 op dl; fi
    pinctrl set 11 op dh
    pinctrl set 11 op dl
  done
}

end=$((SECONDS + SECS))
n=0
while [ "$SECONDS" -lt "$end" ]; do
  pinctrl set 8 op dl
  # RESET then READ CANSTAT (0x03 0x0E 0x00 0x00)
  if [ $((n % 8)) -eq 0 ]; then
    xfer_byte 192   # 0xC0 RESET
  fi
  xfer_byte 3       # 0x03 READ
  xfer_byte 14      # 0x0E CANSTAT
  xfer_byte 0
  xfer_byte 0
  pinctrl set 8 op dh
  n=$((n + 1))
  if [ $((n % 20)) -eq 1 ]; then
    echo "cycle $n  MISO=$(pinctrl get 9 | tr -d '\n')"
  fi
done
