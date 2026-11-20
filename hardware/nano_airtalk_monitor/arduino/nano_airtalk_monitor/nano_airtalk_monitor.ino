/*
 * Arduino Nano 33 BLE — MGL Airtalk monitor + encoders + Matek ASPD (v5).
 *
 * Board is nRF52840, 3.3 V I/O, not 5 V tolerant.
 *
 * Airtalk tap (RX only):
 *
 *   Airtalk ---- 10 kΩ ----+---- D4
 *                          |
 *                        18 kΩ
 *                          |
 *   MGL GND ---------------+---- GND
 *
 *   D3 stays INPUT (high-Z) in flight. Never connect MCU TX to Airtalk.
 *   Bench self-test: jumper D3→D4, USB command "test". Not with Airtalk on D4.
 *
 * Encoders: NPN open-collector, 4.7 kΩ pull-up to Nano 3.3 V on every signal.
 *   Roll  HOK38H5-600N-G5-24   600 PPR   D2=A D5=B
 *     RED VCC  BLACK 0V  WHITE A  GREEN B
 *   Pitch Omron E6B2-CWZ6C     2000 PPR  D6=A D7=B D8=Z
 *     BROWN +V  BLUE 0V  BLACK A  WHITE B  ORANGE Z
 *     (Omron E6B2-C datasheet)
 *
 *   Encoder VCC = Nano 5V.  Encoder 0V = Nano GND.
 *   invert=1 disables encoder ISRs (software UART would drop edges).
 *
 * Matek ASPD-4525 (TE 4525DO-DS5AI001DP) I2C:
 *   A4=SDA  A5=SCL  (Wire). Address 0x28. 5V supply, 3.3 V I2C
 *   (level-shift SDA/SCL if the Matek bus is 5 V).
 *
 * Host USB:  115200 8N1
 * Airtalk:   19200 8N1, invert=0 hardware UART on D4.
 *
 *   arduino-cli compile --fqbn arduino:mbed_nano:nano33ble \
 *     hardware/nano_airtalk_monitor/arduino/nano_airtalk_monitor
 */

#include <Arduino.h>
#include <Wire.h>
#include <math.h>
#include <string.h>

static const uint8_t PIN_AT_RX = 4;
static const uint8_t PIN_TEST_TX = 3;
static const uint8_t PIN_ROLL_A = 2;
static const uint8_t PIN_ROLL_B = 5;
static const uint8_t PIN_PITCH_A = 6;
static const uint8_t PIN_PITCH_B = 7;
static const uint8_t PIN_PITCH_Z = 8;

static const uint32_t USB_BAUD = 115200;
static const uint32_t AT_BAUD = 19200;
static const uint16_t BIT_US = 52;
static const uint32_t CTRL_PERIOD_MS = 10;
static const uint32_t ASPD_PERIOD_MS = 20;
static const uint8_t ASPD_I2C_ADDR = 0x28;
static const float ASPD_PMIN_PSI = -1.0f;
static const float ASPD_PMAX_PSI = 1.0f;
static const float PSI_TO_PA = 6894.757f;
static const float RHO_ISA = 1.225f;
static const float MS_TO_KT = 1.943844f;

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

// x4 quadrature: bit1=A, bit0=B. 00→01→11→10→00 is +1.
static const int8_t QEM[16] = {
    0,  +1, -1,  0,
   -1,   0,  0, +1,
   +1,   0,  0, -1,
    0,  -1, +1,  0
};

static volatile int32_t roll_count = 0;
static volatile int32_t pitch_count = 0;
static volatile uint32_t roll_error_count = 0;
static volatile uint32_t pitch_error_count = 0;
static volatile uint32_t pitch_z_count = 0;
static volatile uint8_t roll_prev = 0;
static volatile uint8_t pitch_prev = 0;
static volatile uint8_t zero_valid = 0;
static bool enc_on = false;

static int32_t last_roll_report = 0;
static int32_t last_pitch_report = 0;
static uint32_t last_c_ms = 0;
static uint32_t last_aspd_ms = 0;

static uint16_t aspd_raw = 0;
static uint8_t aspd_st = 3;
static float aspd_psi = 0.0f;
static float aspd_pa = 0.0f;
static float aspd_tc = 0.0f;
static float aspd_ias_kt = 0.0f;
static uint32_t aspd_ok = 0;
static uint32_t aspd_fail = 0;

static uint32_t led_t = 0;
static bool led_on = false;
static char cmd[48];
static uint8_t cmd_len = 0;

// TX pin NC so this object cannot drive Airtalk.
static UART airtalk(NC, digitalPinToPinName(PIN_AT_RX));
static bool hw_uart_on = false;

static void encoder_set(bool on);
static void poll_aspd();

static void banner() {
  Serial.print(F("# nano_airtalk_monitor v5 nano33ble\r\n"));
  Serial.print(F("# airtalk 19200 8N1 rx=D4 test_tx=D3 invert="));
  Serial.print(invert ? 1 : 0);
  Serial.print(F(" uart="));
  Serial.print(hw_uart_on ? 1 : 0);
  Serial.print(F(" enc="));
  Serial.print(enc_on ? 1 : 0);
  Serial.print(F("\r\n"));
  Serial.print(F("# roll D2/D5 HOK 600PPR  pitch D6/D7/D8 Omron 2000PPR+Z\r\n"));
  Serial.print(F("# aspd Matek 4525 I2C A4/A5 addr=0x28  +/-1psi\r\n"));
  Serial.print(F("# io=3.3V pullup=4.7k commands: help stats test invert 0|1 zero [roll|pitch]\r\n"));
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

static uint8_t read_ab(uint8_t pin_a, uint8_t pin_b) {
  uint8_t a = digitalRead(pin_a) == HIGH ? 1 : 0;
  uint8_t b = digitalRead(pin_b) == HIGH ? 1 : 0;
  return (uint8_t)((a << 1) | b);
}

static void quad_step(volatile uint8_t *prev, volatile int32_t *count,
                      volatile uint32_t *errors, uint8_t cur) {
  uint8_t idx = (uint8_t)((*prev << 2) | cur);
  int8_t step = QEM[idx];
  if (step) {
    *count += step;
  } else if (*prev != cur) {
    (*errors)++;
  }
  *prev = cur;
}

static void roll_isr() {
  quad_step(&roll_prev, &roll_count, &roll_error_count,
            read_ab(PIN_ROLL_A, PIN_ROLL_B));
}

static void pitch_isr() {
  quad_step(&pitch_prev, &pitch_count, &pitch_error_count,
            read_ab(PIN_PITCH_A, PIN_PITCH_B));
}

static void pitch_z_isr() {
  pitch_z_count++;
}

static void encoder_set(bool on) {
  if (on == enc_on) {
    return;
  }
  if (enc_on) {
    detachInterrupt(digitalPinToInterrupt(PIN_ROLL_A));
    detachInterrupt(digitalPinToInterrupt(PIN_ROLL_B));
    detachInterrupt(digitalPinToInterrupt(PIN_PITCH_A));
    detachInterrupt(digitalPinToInterrupt(PIN_PITCH_B));
    detachInterrupt(digitalPinToInterrupt(PIN_PITCH_Z));
    enc_on = false;
  }
  if (!on) {
    return;
  }
  pinMode(PIN_ROLL_A, INPUT);
  pinMode(PIN_ROLL_B, INPUT);
  pinMode(PIN_PITCH_A, INPUT);
  pinMode(PIN_PITCH_B, INPUT);
  pinMode(PIN_PITCH_Z, INPUT);
  roll_prev = read_ab(PIN_ROLL_A, PIN_ROLL_B);
  pitch_prev = read_ab(PIN_PITCH_A, PIN_PITCH_B);
  attachInterrupt(digitalPinToInterrupt(PIN_ROLL_A), roll_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_ROLL_B), roll_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_PITCH_A), pitch_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_PITCH_B), pitch_isr, CHANGE);
  attachInterrupt(digitalPinToInterrupt(PIN_PITCH_Z), pitch_z_isr, FALLING);
  enc_on = true;
}

static void apply_rx_mode() {
  if (invert) {
    encoder_set(false);
    sw_rx_enable();
  } else {
    hw_rx_enable();
    encoder_set(true);
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
  noInterrupts();
  int32_t roll = roll_count;
  int32_t pitch = pitch_count;
  uint32_t rerr = roll_error_count;
  uint32_t perr = pitch_error_count;
  uint32_t zp = pitch_z_count;
  uint8_t z = zero_valid;
  interrupts();

  Serial.print(F("# stats bytes="));
  Serial.print(rx_bytes);
  Serial.print(F(" overrun="));
  Serial.print(rx_overrun);
  Serial.print(F(" invert="));
  Serial.print(invert ? 1 : 0);
  Serial.print(F(" uart="));
  Serial.print(hw_uart_on ? 1 : 0);
  Serial.print(F(" enc="));
  Serial.print(enc_on ? 1 : 0);
  Serial.print(F(" roll="));
  Serial.print(roll);
  Serial.print(F(" pitch="));
  Serial.print(pitch);
  Serial.print(F(" rerr="));
  Serial.print(rerr);
  Serial.print(F(" perr="));
  Serial.print(perr);
  Serial.print(F(" zp="));
  Serial.print(zp);
  Serial.print(F(" z="));
  Serial.print(z);
  Serial.print(F(" psi="));
  Serial.print(aspd_psi, 4);
  Serial.print(F(" pa="));
  Serial.print(aspd_pa, 1);
  Serial.print(F(" tc="));
  Serial.print(aspd_tc, 1);
  Serial.print(F(" praw="));
  Serial.print(aspd_raw);
  Serial.print(F(" pst="));
  Serial.print(aspd_st);
  Serial.print(F(" ias="));
  Serial.print(aspd_ias_kt, 1);
  Serial.print(F(" aspd_ok="));
  Serial.print(aspd_ok);
  Serial.print(F(" aspd_fail="));
  Serial.print(aspd_fail);
  Serial.print(F("\r\n"));
}

static void zero_axis(bool do_roll, bool do_pitch) {
  noInterrupts();
  if (do_roll) {
    roll_count = 0;
    last_roll_report = 0;
  }
  if (do_pitch) {
    pitch_count = 0;
    last_pitch_report = 0;
  }
  zero_valid = 1;
  interrupts();
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
  if (!strcmp(s, "zero")) {
    zero_axis(true, true);
    print_stats();
    return;
  }
  if (!strcmp(s, "zero roll")) {
    zero_axis(true, false);
    print_stats();
    return;
  }
  if (!strcmp(s, "zero pitch")) {
    zero_axis(false, true);
    print_stats();
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

static void poll_aspd() {
  uint32_t now = millis();
  if ((uint32_t)(now - last_aspd_ms) < ASPD_PERIOD_MS) {
    return;
  }
  last_aspd_ms = now;

  Wire.requestFrom((uint8_t)ASPD_I2C_ADDR, (uint8_t)4);
  if (Wire.available() < 4) {
    aspd_st = 3;
    aspd_fail++;
    return;
  }
  uint8_t b0 = (uint8_t)Wire.read();
  uint8_t b1 = (uint8_t)Wire.read();
  uint8_t b2 = (uint8_t)Wire.read();
  uint8_t b3 = (uint8_t)Wire.read();
  while (Wire.available()) {
    Wire.read();
  }

  uint8_t st = (uint8_t)((b0 >> 6) & 0x03);
  uint16_t raw = (uint16_t)(((b0 & 0x3F) << 8) | b1);
  uint16_t traw = (uint16_t)((b2 << 3) | (b3 >> 5));

  aspd_st = st;
  aspd_raw = raw;
  if (st == 0 || st == 2) {
    aspd_ok++;
  } else {
    aspd_fail++;
  }

  // Type A 10%..90% of 14-bit counts, ±1 PSI differential.
  float psi =
      ((float)raw - 1638.3f) / 13106.4f * (ASPD_PMAX_PSI - ASPD_PMIN_PSI) +
      ASPD_PMIN_PSI;
  aspd_psi = psi;
  aspd_pa = psi * PSI_TO_PA;
  aspd_tc = ((float)traw * 200.0f / 2047.0f) - 50.0f;
  if (aspd_pa > 0.0f) {
    aspd_ias_kt = sqrtf(2.0f * aspd_pa / RHO_ISA) * MS_TO_KT;
  } else {
    aspd_ias_kt = 0.0f;
  }
}

static void dump_controls() {
  uint32_t now = millis();
  if ((uint32_t)(now - last_c_ms) < CTRL_PERIOD_MS) {
    return;
  }
  last_c_ms = now;

  noInterrupts();
  int32_t roll = roll_count;
  int32_t pitch = pitch_count;
  uint32_t rerr = roll_error_count;
  uint32_t perr = pitch_error_count;
  uint32_t zp = pitch_z_count;
  uint8_t z = zero_valid;
  uint32_t t = micros();
  interrupts();

  int32_t rd = roll - last_roll_report;
  int32_t pd = pitch - last_pitch_report;
  last_roll_report = roll;
  last_pitch_report = pitch;

  Serial.print(F("C t="));
  Serial.print(t);
  Serial.print(F(" roll="));
  Serial.print(roll);
  Serial.print(F(" pitch="));
  Serial.print(pitch);
  Serial.print(F(" rd="));
  Serial.print(rd);
  Serial.print(F(" pd="));
  Serial.print(pd);
  Serial.print(F(" rerr="));
  Serial.print(rerr);
  Serial.print(F(" perr="));
  Serial.print(perr);
  Serial.print(F(" zp="));
  Serial.print(zp);
  Serial.print(F(" z="));
  Serial.print(z);
  Serial.print(F(" psi="));
  Serial.print(aspd_psi, 4);
  Serial.print(F(" pa="));
  Serial.print(aspd_pa, 1);
  Serial.print(F(" tc="));
  Serial.print(aspd_tc, 1);
  Serial.print(F(" praw="));
  Serial.print(aspd_raw);
  Serial.print(F(" pst="));
  Serial.print(aspd_st);
  Serial.print(F(" ias="));
  Serial.print(aspd_ias_kt, 1);
  Serial.print(F("\r\n"));
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  pinMode(PIN_AT_RX, INPUT);
  pinMode(PIN_TEST_TX, INPUT);
  pinMode(PIN_ROLL_A, INPUT);
  pinMode(PIN_ROLL_B, INPUT);
  pinMode(PIN_PITCH_A, INPUT);
  pinMode(PIN_PITCH_B, INPUT);
  pinMode(PIN_PITCH_Z, INPUT);
  Serial.begin(USB_BAUD);
  delay(400);
  Wire.begin();
  Wire.setClock(100000);
  apply_rx_mode();
  banner();
}

void loop() {
  poll_hw_uart();
  poll_usb_cmd();
  poll_aspd();
  dump_rx();
  dump_controls();

  uint32_t now = millis();
  if (now - led_t >= 500) {
    led_t = now;
    led_on = !led_on;
    digitalWrite(LED_BUILTIN, led_on ? HIGH : LOW);
  }
}
