/*
 * Pico 2 W USB CDC <-> UART0 bridge for MGL SP-7 / ARMPROG,
 * plus a Wi-Fi AP diagnostic page of live serial traffic.
 *
 * Board: Raspberry Pi Pico 2 W (Earle Philhower Arduino-Pico)
 * UART0: GP0 TX, GP1 RX  --> MAX3232 --> SP-7 RS-232
 *
 * Connect to Wi-Fi "SP7-Bridge" / sp7bridge  then  http://192.168.4.1
 */

#include <WiFi.h>
#include <WebServer.h>
#include "hardware/gpio.h"
#include "hardware/uart.h"

static uint32_t baud = 38400;  // ARMPROG default (not the 57600 data rate)

static const char *AP_SSID = "SP7-Bridge";
static const char *AP_PASS = "sp7bridge";  // WPA2: 8+ chars

#ifndef LED_BUILTIN
#define LED_BUILTIN 25
#endif

WebServer server(80);

static uint32_t bytes_to_sp7 = 0;    // USB -> UART
static uint32_t bytes_from_sp7 = 0;  // UART -> USB
static bool rx_muted = false;        // floating/break: UART keeps fabricating bytes

enum TrafficDir : uint8_t { DIR_TO_SP7 = 0, DIR_FROM_SP7 = 1 };

struct Ev {
  uint32_t seq;
  uint32_t t_ms;
  uint8_t dir;
  uint8_t len;
  uint8_t data[64];
};

static const int LOG_N = 160;
static Ev logbuf[LOG_N];
static uint32_t log_head = 0;
static uint32_t log_count = 0;
static uint32_t log_seq = 0;

static void log_chunk(TrafficDir dir, const uint8_t *data, int n) {
  if (n <= 0) {
    return;
  }
  int off = 0;
  while (off < n) {
    int m = n - off;
    if (m > 64) {
      m = 64;
    }
    Ev &e = logbuf[log_head];
    e.seq = ++log_seq;
    e.t_ms = millis();
    e.dir = (uint8_t)dir;
    e.len = (uint8_t)m;
    memcpy(e.data, data + off, m);
    log_head = (log_head + 1) % LOG_N;
    if (log_count < LOG_N) {
      log_count++;
    }
    off += m;
  }
}

static void uart_rx_idle_high() {
  gpio_pull_up(1);  // GP1 / UART0 RX — idle mark when MAX3232 is unplugged
}

static void uart_clear_errors_and_drain() {
  uart_get_hw(uart0)->rsr = 0;
  while (Serial1.available()) {
    (void)Serial1.read();
  }
}

static void apply_baud(uint32_t rate) {
  baud = rate;
  Serial1.end();
  Serial1.setTX(0);
  Serial1.setRX(1);
  Serial1.begin(baud);
  uart_rx_idle_high();
  uart_clear_errors_and_drain();
  rx_muted = false;
}

static const char INDEX_HTML[] PROGMEM = R"HTML(<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<meta name="viewport" content="width=device-width, initial-scale=1"/>
<title>SP-7 serial bridge</title>
<style>
  :root { font-family: ui-sans-serif, system-ui, sans-serif; color: #e8edf2; background: #121417; }
  body { margin: 0; }
  header { padding: 14px 18px; background: #1b2128; border-bottom: 1px solid #2c3640; }
  h1 { margin: 0; font-size: 18px; font-weight: 600; }
  .sub { color: #9aa8b5; font-size: 13px; margin-top: 4px; }
  main { padding: 14px 18px 24px; }
  .stats { display: flex; flex-wrap: wrap; gap: 8px; margin-bottom: 12px; }
  .chip { background: #1b2128; border: 1px solid #2c3640; border-radius: 8px; padding: 8px 10px; min-width: 110px; }
  .chip b { display: block; font-size: 16px; }
  .chip span { color: #9aa8b5; font-size: 11px; letter-spacing: .04em; text-transform: uppercase; }
  .row { display: flex; gap: 8px; flex-wrap: wrap; align-items: center; margin-bottom: 10px; }
  button, select { background: #2a3340; color: #e8edf2; border: 1px solid #3d4b5c; border-radius: 6px; padding: 6px 10px; }
  button:hover { background: #354252; }
  #log { background: #0d0f12; border: 1px solid #2c3640; border-radius: 8px; height: 70vh; overflow: auto; padding: 8px; font: 12px/1.45 ui-monospace, Menlo, monospace; }
  .e { margin: 0 0 6px; white-space: pre-wrap; word-break: break-all; }
  .tx { color: #7ee0a3; }
  .rx { color: #7ec8e0; }
  .meta { color: #8b98a5; }
  .tag { display: inline-block; min-width: 52px; font-weight: 700; }
  .hint { color: #9aa8b5; font-size: 12px; margin-top: 8px; }
</style>
</head>
<body>
<header>
  <h1>SP-7 serial bridge</h1>
  <div class="sub">USB CDC &harr; UART0 (GP0/GP1) &nbsp;|&nbsp; live bytes on this page do not replace ARMPROG</div>
</header>
<main>
  <div class="stats">
    <div class="chip"><span>Baud</span><b id="baud">—</b></div>
    <div class="chip"><span>To SP-7 (USB→UART)</span><b id="tx">0</b></div>
    <div class="chip"><span>From SP-7 (UART→USB)</span><b id="rx">0</b></div>
    <div class="chip"><span>Wi-Fi clients</span><b id="clients">0</b></div>
    <div class="chip"><span>Uptime</span><b id="up">0s</b></div>
    <div class="chip"><span>UART RX</span><b id="rxstate">ok</b></div>
  </div>
  <div class="row">
    <label>UART baud
      <select id="baudSel">
        <option>9600</option><option>19200</option>
        <option selected>38400</option><option>57600</option><option>115200</option>
      </select>
    </label>
    <button id="apply">Apply baud</button>
    <button id="pause">Pause</button>
    <button id="clear">Clear log</button>
  </div>
  <div id="log"></div>
  <p class="hint">Green = host (ARMPROG) → SP-7. Blue = SP-7 → host. Wake is <code>1B 1B 50 52 4F 47</code> (ESC ESC PROG) at 38400 after SP-7 power-up.</p>
</main>
<script>
let since = 0, paused = false, seenWake = false;
const logEl = document.getElementById('log');
function hex(h){ return (h.match(/.{1,2}/g)||[]).join(' '); }
function ascii(h){
  let o='';
  for(let i=0;i<h.length;i+=2){
    const c=parseInt(h.slice(i,i+2),16);
    o += (c>=32 && c<127) ? String.fromCharCode(c) : '.';
  }
  return o;
}
function add(ev){
  const div=document.createElement('div');
  div.className='e '+(ev.d==='tx'?'tx':'rx');
  const note = (!seenWake && ev.h && ev.h.toLowerCase().includes('1b1b50524f47')) ? '  ← ARMPROG wake' : '';
  if(note) seenWake = true;
  div.innerHTML = '<span class="meta">'+ev.t+'ms</span>  <span class="tag">'+(ev.d==='tx'?'TO SP7':'FROM SP7')+'</span>  '+
    hex(ev.h)+'  <span class="meta">| '+ascii(ev.h)+note+'</span>';
  logEl.appendChild(div);
  if(!paused) logEl.scrollTop = logEl.scrollHeight;
}
async function poll(){
  if(paused){ setTimeout(poll, 400); return; }
  try{
    const r = await fetch('/api/poll?since='+since);
    const j = await r.json();
    document.getElementById('baud').textContent = j.baud;
    document.getElementById('tx').textContent = j.tx;
    document.getElementById('rx').textContent = j.rx;
    document.getElementById('clients').textContent = j.clients;
    document.getElementById('up').textContent = Math.floor(j.uptime/1000)+'s';
    document.getElementById('rxstate').textContent = j.muted ? 'muted (line noise)' : 'ok';
    (j.events||[]).forEach(ev => {
      if (typeof ev.s !== 'number') return;
      if (ev.s <= since) return;
      since = ev.s;
      add(ev);
    });
  }catch(e){}
  setTimeout(poll, 250);
}
document.getElementById('pause').onclick = () => {
  paused = !paused;
  document.getElementById('pause').textContent = paused ? 'Resume' : 'Pause';
};
document.getElementById('clear').onclick = async () => {
  await fetch('/api/clear');
  logEl.innerHTML = '';
  since = 0; seenWake = false;
};
document.getElementById('apply').onclick = async () => {
  const b = document.getElementById('baudSel').value;
  await fetch('/api/baud?rate='+b, {method:'POST'});
};
poll();
</script>
</body></html>
)HTML";

static char json[6144];

static void hex_append(char *&dst, char *end, const uint8_t *data, int n) {
  static const char *hd = "0123456789abcdef";
  for (int i = 0; i < n && dst + 2 < end; i++) {
    *dst++ = hd[data[i] >> 4];
    *dst++ = hd[data[i] & 0x0f];
  }
}

static void handleRoot() {
  server.send_P(200, "text/html", INDEX_HTML);
}

static void handleClear() {
  log_head = 0;
  log_count = 0;
  log_seq = 0;
  bytes_to_sp7 = 0;
  bytes_from_sp7 = 0;
  rx_muted = false;
  uart_clear_errors_and_drain();
  server.send(200, "text/plain", "ok");
}

static void handleBaud() {
  if (!server.hasArg("rate")) {
    server.send(400, "text/plain", "rate");
    return;
  }
  uint32_t rate = strtoul(server.arg("rate").c_str(), nullptr, 10);
  if (rate < 1200 || rate > 230400) {
    server.send(400, "text/plain", "range");
    return;
  }
  apply_baud(rate);
  server.send(200, "text/plain", "ok");
}

static void handlePoll() {
  uint32_t since = 0;
  if (server.hasArg("since")) {
    since = strtoul(server.arg("since").c_str(), nullptr, 10);
  }

  char *dst = json;
  char *end = json + sizeof(json) - 2;
  int n = snprintf(dst, end - dst,
                   "{\"baud\":%lu,\"tx\":%lu,\"rx\":%lu,\"clients\":%d,\"uptime\":%lu,\"muted\":%s,\"events\":[",
                   (unsigned long)baud, (unsigned long)bytes_to_sp7,
                   (unsigned long)bytes_from_sp7, WiFi.softAPgetStationNum(),
                   (unsigned long)millis(), rx_muted ? "true" : "false");
  dst += n;

  bool first = true;
  uint32_t start = (log_count < LOG_N) ? 0 : log_head;
  for (uint32_t i = 0; i < log_count && dst + 80 < end; i++) {
    const Ev &e = logbuf[(start + i) % LOG_N];
    if (e.seq <= since) {
      continue;
    }
    if (!first) {
      *dst++ = ',';
    }
    first = false;
    n = snprintf(dst, end - dst, "{\"s\":%lu,\"t\":%lu,\"d\":\"%s\",\"h\":\"",
                 (unsigned long)e.seq, (unsigned long)e.t_ms,
                 e.dir == DIR_TO_SP7 ? "tx" : "rx");
    dst += n;
    hex_append(dst, end, e.data, e.len);
    if (dst + 3 < end) {
      *dst++ = '"';
      *dst++ = '}';
    }
  }
  if (dst + 3 < end) {
    *dst++ = ']';
    *dst++ = '}';
    *dst = 0;
  } else {
    json[sizeof(json) - 3] = ']';
    json[sizeof(json) - 2] = '}';
    json[sizeof(json) - 1] = 0;
  }
  server.send(200, "application/json", json);
}

static void pump_uart_rx() {
  static uint32_t quiet_from = 0;

  uint32_t rsr = uart_get_hw(uart0)->rsr;
  if (rsr & (UART_UARTRSR_FE_BITS | UART_UARTRSR_OE_BITS | UART_UARTRSR_BE_BITS)) {
    uart_clear_errors_and_drain();
    rx_muted = true;
    quiet_from = millis();
    return;
  }

  if (rx_muted) {
    if (Serial1.available()) {
      uart_clear_errors_and_drain();
      quiet_from = millis();
    } else if (millis() - quiet_from > 30) {
      rx_muted = false;
    }
    return;
  }

  uint8_t buf[64];
  int n = 0;
  while (Serial1.available() && n < 64) {
    int c = Serial1.read();
    if (c < 0) {
      break;
    }
    buf[n++] = (uint8_t)c;
  }
  if (!n) {
    return;
  }

  // MAX3232 with floating RS-232 RX often spews the same byte forever.
  if (n >= 16) {
    bool all_same = true;
    for (int i = 1; i < n; i++) {
      if (buf[i] != buf[0]) {
        all_same = false;
        break;
      }
    }
    if (all_same && Serial1.available()) {
      uart_clear_errors_and_drain();
      rx_muted = true;
      quiet_from = millis();
      log_chunk(DIR_FROM_SP7, buf, 1);
      bytes_from_sp7 += 1;
      return;
    }
  }

  Serial.write(buf, n);
  bytes_from_sp7 += n;
  log_chunk(DIR_FROM_SP7, buf, n);
}

static void pump_bridge() {
  uint8_t buf[64];
  int n = 0;
  while (Serial.available() && n < 64) {
    int c = Serial.read();
    if (c < 0) {
      break;
    }
    buf[n++] = (uint8_t)c;
  }
  if (n) {
    Serial1.write(buf, n);
    bytes_to_sp7 += n;
    log_chunk(DIR_TO_SP7, buf, n);
  }

  pump_uart_rx();
}

void setup() {
  pinMode(LED_BUILTIN, OUTPUT);
  Serial.begin(baud);

  Serial1.setTX(0);
  Serial1.setRX(1);
  Serial1.begin(baud);
  uart_rx_idle_high();

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);

  server.on("/", handleRoot);
  server.on("/api/poll", handlePoll);
  server.on("/api/clear", handleClear);
  server.on("/api/baud", HTTP_POST, handleBaud);
  server.on("/api/baud", HTTP_GET, handleBaud);
  server.begin();
}

void loop() {
  pump_bridge();
  server.handleClient();
  pump_bridge();

  static uint32_t last;
  uint32_t now = millis();
  if (now - last >= 500) {
    last = now;
    digitalWrite(LED_BUILTIN, !digitalRead(LED_BUILTIN));
  }
}
