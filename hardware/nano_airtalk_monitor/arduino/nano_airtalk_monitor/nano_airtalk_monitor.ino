/*
 * Arduino Nano 33 BLE — receive-only MGL Airtalk monitor (Phase 1).
 *
 * Board is nRF52840, 3.3 V I/O, not 5 V tolerant. Do not feed Airtalk
 * (~5 V Space) into D4 through a series resistor alone.
 *
 * Aircraft tap (RX only):
 *
 *   Airtalk ---- 10 kΩ ----+---- D4
 *                          |
 *                        18 kΩ
 *                          |
 *   MGL GND ---------------+---- GND
 *
 *   V at D4 ≈ 5.0 × 18 / 28 ≈ 3.21 V. D3 stays INPUT (high-Z) in flight.
 *   Never connect MCU TX to Airtalk.
 *
 * Bench self-test: jumper D3→D4 (3.3 V, no divider). USB command "test".
 * Do not run "test" with Airtalk still on D4.
 *
 * Host USB:  115200 8N1  (Serial / native USB)
 * Airtalk:   19200 8N1. Live bus idles high (standard UART) → invert=0
 *            uses nRF UARTE on D4. invert=1 is a software-UART fallback.
 *
 *   arduino-cli compile --fqbn arduino:mbed_nano:nano33ble \
 *     hardware/nano_airtalk_monitor/arduino/nano_airtalk_monitor
 */

#include <Arduino.h>
#include <string.h>

static const uint8_t PIN_AT_RX = 4;
static const uint8_t PIN_TEST_TX = 3;
static const uint32_t USB_BAUD = 115200;
static const uint32_t AT_BAUD = 19200;
static const uint16_t BIT_US = 52;

static const uint8_t AT_STX = 0x82;
static const uint8_t AT_ETX = 0x83;
static const uint8_t AT_CS_INIT = 0xA5;

// Live Airtalk after the divider is idle-high (standard UART). invert=1
// is only for the inverted software sampler.
static volatile bool invert = false;
static volatile uint8_t rx_buf[128];
static volatile uint8_t rx_head = 0;
static volatile uint8_t rx_tail = 0;
static volatile uint16_t rx_overrun = 0;
static volatile uint32_t rx_bytes = 0;
static volatile uint32_t last_rx_us = 0;
static volatile bool rx_irq_armed = false;

static uint32_t led_t = 0;
static bool led_on = false;
static char cmd[48];
static uint8_t cmd_len = 0;

// TX pin NC so this object cannot drive Airtalk.
static UART airtalk(NC, digitalPinToPinName(PIN_AT_RX));
static bool hw_uart_on = false;

static void banner() {
  Serial.print(F("# nano_airtalk_monitor v3 nano33ble\r\n"));
  Serial.print(F("# airtalk 19200 8N1 rx=D4 test_tx=D3 invert="));
  Serial.print(invert ? 1 : 0);
  Serial.print(F(" uart="));
  Serial.print(hw_uart_on ? 1 : 0);
  Serial.print(F("\r\n"));
  Serial.print(F("# io=3.3V divider=10k/18k commands: help invert 0|1 test stats\r\n"));
}

static inline bool is_mark_level(bool high) {
  return invert ? !high : high;
}

static void rx_push(uint8_t b) {
  uint8_t next = (uint8_t)(rx_head + 1) & 127;
  if (next == rx_tail) {
    rx_overrun++;
    return;
  }
  rx_buf[rx_head] = b;
  rx_head = next;
  rx_bytes++;
  last_rx_us = micros();
}

static void on_rx_edge() {
  if (!rx_irq_armed) {
    return;
  }
  bool high = digitalRead(PIN_AT_RX) == HIGH;
  if (is_mark_level(high)) {
    return;
  }

  uint32_t t = micros() + BIT_US + (BIT_US / 2);
  uint8_t val = 0;
  for (uint8_t i = 0; i < 8; i++) {
    while ((int32_t)(micros() - t) < 0) {
    }
    if (is_mark_level(digitalRead(PIN_AT_RX) == HIGH)) {
      val |= (uint8_t)(1 << i);
    }
    t += BIT_US;
  }
  rx_push(val);
}

static void sw_rx_disable() {
  rx_irq_armed = false;
  detachInterrupt(digitalPinToInterrupt(PIN_AT_RX));
}

static void hw_rx_disable() {
  if (hw_uart_on) {
    airtalk.end();
    hw_uart_on = false;
  }
  pinMode(PIN_AT_RX, INPUT);
  pinMode(PIN_TEST_TX, INPUT);
}

static void hw_rx_enable() {
  sw_rx_disable();
  pinMode(PIN_TEST_TX, INPUT);
  airtalk.begin(AT_BAUD);
  hw_uart_on = true;
  pinMode(PIN_TEST_TX, INPUT);
}

static void sw_rx_enable() {
  hw_rx_disable();
  pinMode(PIN_AT_RX, INPUT);
  pinMode(PIN_TEST_TX, INPUT);
  rx_irq_armed = true;
  attachInterrupt(digitalPinToInterrupt(PIN_AT_RX), on_rx_edge, CHANGE);
}

static void apply_rx_mode() {
  if (invert) {
    sw_rx_enable();
  } else {
    hw_rx_enable();
  }
}

static void poll_hw_uart() {
  if (!hw_uart_on) {
    return;
  }
  while (airtalk.available()) {
    int c = airtalk.read();
    if (c >= 0) {
      rx_push((uint8_t)c);
    }
  }
}

static uint8_t xor_cs(const uint8_t *p, uint8_t n) {
  uint8_t cs = AT_CS_INIT;
  for (uint8_t i = 0; i < n; i++) {
    cs ^= p[i];
  }
  return cs;
}

static void wire_idle_mark() {
  pinMode(PIN_TEST_TX, OUTPUT);
  digitalWrite(PIN_TEST_TX, invert ? LOW : HIGH);
}

static void wire_level_for_bit(bool bit1) {
  if (invert) {
    digitalWrite(PIN_TEST_TX, bit1 ? LOW : HIGH);
  } else {
    digitalWrite(PIN_TEST_TX, bit1 ? HIGH : LOW);
  }
}

static bool sample_rx_mark() {
  bool high = digitalRead(PIN_AT_RX) == HIGH;
  return is_mark_level(high);
}

static uint8_t duplex_byte(uint8_t tx) {
  wire_level_for_bit(false);
  delayMicroseconds(BIT_US - 4);
  uint8_t rx = 0;
  for (uint8_t i = 0; i < 8; i++) {
    wire_level_for_bit((tx >> i) & 1);
    delayMicroseconds((BIT_US / 2) - 4);
    if (sample_rx_mark()) {
      rx |= (uint8_t)(1 << i);
    }
    delayMicroseconds((BIT_US / 2) - 2);
  }
  wire_level_for_bit(true);
  delayMicroseconds(BIT_US);
  return rx;
}

static void duplex_buf(const uint8_t *p, uint8_t n) {
  hw_rx_disable();
  sw_rx_disable();
  wire_idle_mark();
  delayMicroseconds(BIT_US * 2);
  for (uint8_t i = 0; i < n; i++) {
    rx_push(duplex_byte(p[i]));
  }
  delayMicroseconds(BIT_US * 2);
  pinMode(PIN_TEST_TX, INPUT);
  apply_rx_mode();
}

static void send_test_frames() {
  uint8_t body[] = {0xE4, 0x03, 0x32, 0x12, 0x34};
  uint8_t frame[8];
  frame[0] = AT_STX;
  memcpy(frame + 1, body, sizeof(body));
  frame[6] = xor_cs(body, sizeof(body));
  frame[7] = AT_ETX;

  Serial.print(F("# test invert="));
  Serial.print(invert ? 1 : 0);
  Serial.print(F(" frame="));
  for (uint8_t i = 0; i < sizeof(frame); i++) {
    if (frame[i] < 16) {
      Serial.print('0');
    }
    Serial.print(frame[i], HEX);
    if (i + 1 < sizeof(frame)) {
      Serial.print(' ');
    }
  }
  Serial.print(F("\r\n"));

  for (uint8_t n = 0; n < 3; n++) {
    duplex_buf(frame, sizeof(frame));
    delay(20);
  }
}

static void print_stats() {
  Serial.print(F("# stats bytes="));
  Serial.print(rx_bytes);
  Serial.print(F(" overrun="));
  Serial.print(rx_overrun);
  Serial.print(F(" invert="));
  Serial.print(invert ? 1 : 0);
  Serial.print(F(" uart="));
  Serial.print(hw_uart_on ? 1 : 0);
  Serial.print(F("\r\n"));
}

static void handle_cmd(char *s) {
  while (*s == ' ' || *s == '\t') {
    s++;
  }
  if (*s == 0) {
    return;
  }
  if (!strcmp(s, "help")) {
    banner();
    return;
  }
  if (!strcmp(s, "stats")) {
    print_stats();
    return;
  }
  if (!strcmp(s, "test")) {
    send_test_frames();
    return;
  }
  if (!strncmp(s, "invert ", 7)) {
    invert = (s[7] != '0');
    apply_rx_mode();
    banner();
    return;
  }
  Serial.print(F("# unknown cmd\r\n"));
}

static void poll_usb_cmd() {
  while (Serial.available()) {
    char c = (char)Serial.read();
    if (c == '\r') {
      continue;
    }
    if (c == '\n') {
      cmd[cmd_len] = 0;
      handle_cmd(cmd);
      cmd_len = 0;
      continue;
    }
    if (cmd_len + 1 < sizeof(cmd)) {
      cmd[cmd_len++] = c;
    }
  }
}

static void dump_rx() {
  uint8_t tmp[32];
  uint8_t n = 0;
  uint32_t t0 = 0;

  noInterrupts();
  while (rx_tail != rx_head && n < sizeof(tmp)) {
    if (n == 0) {
      t0 = last_rx_us;
    }
    tmp[n++] = rx_buf[rx_tail];
    rx_tail = (uint8_t)(rx_tail + 1) & 127;
  }
  interrupts();
  if (n == 0) {
    return;
  }

  Serial.print(F("D t="));
  Serial.print(t0);
  Serial.print(F(" n="));
  Serial.print(n);
  Serial.print(F(" hex="));
  for (uint8_t i = 0; i < n; i++) {
    if (tmp[i] < 16) {
      Serial.print('0');
    }
    Serial.print(tmp[i], HEX);
    if (i + 1 < n) {
      Serial.print(' ');
    }
  }
  Serial.print(F("\r\n"));
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_AT_RX, INPUT);
  pinMode(PIN_TEST_TX, INPUT);
  Serial.begin(USB_BAUD);
  delay(400);
  apply_rx_mode();
  banner();
}

void loop() {
  poll_hw_uart();
  poll_usb_cmd();
  dump_rx();

  uint32_t now = millis();
  if (now - led_t >= 500) {
    led_t = now;
    led_on = !led_on;
    digitalWrite(LED_BUILTIN, led_on ? HIGH : LOW);
  }
}
