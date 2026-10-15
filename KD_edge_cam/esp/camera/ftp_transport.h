#pragma once
#include <Arduino.h>
#include <FS.h>
#include <WiFi.h>

// Small passive FTP client. No image-sized RAM allocation; control replies and
// receipt JSON are bounded. Network timeouts also respect the wake-cycle budget.
class CameraFtpClient {
  WiFiClient control;
  IPAddress peer;
  uint32_t started = 0, budget = 60000;

  uint32_t remaining() {
    uint32_t elapsed = millis() - started;
    return elapsed < budget ? budget - elapsed : 0;
  }

  bool readLine(String &line) {
    line = "";
    uint32_t began = millis();
    while (remaining() && millis() - began < 5000) {
      while (control.available()) {
        char ch = control.read();
        if (ch == '\n') { line.trim(); return true; }
        if (line.length() >= 511) { close(); return false; }
        line += ch;
      }
      if (!control.connected()) break;
      delay(1);
    }
    close();
    return false;
  }

  int reply(String &line) {
    if (!readLine(line) || line.length() < 3) return -1;
    int code = line.substring(0, 3).toInt();
    if (line.length() > 3 && line[3] == '-') {
      String end = line.substring(0, 3) + " ";
      for (int n = 0; n < 32; ++n) {
        if (!readLine(line)) return -1;
        if (line.startsWith(end)) return code;
      }
      close();
      return -1;
    }
    return code;
  }

  int command(const String &text, String &line) {
    if (!remaining() || !control.connected() || text.indexOf('\r') >= 0 || text.indexOf('\n') >= 0)
      return -1;
    String wire = text + "\r\n";
    if (control.write((const uint8_t *)wire.c_str(), wire.length()) != wire.length()) {
      close();
      return -1;
    }
    return reply(line);
  }

  bool passive(WiFiClient &data) {
    String line;
    int code = command("EPSV", line);
    int port = 0;
    if (code == 229) {
      int open = line.indexOf('(');
      if (open < 0 || line.length() < (unsigned)(open + 6)) return false;
      char separator = line[open + 1];
      int end = line.indexOf(separator, open + 4);
      if (end < 0) return false;
      port = line.substring(open + 4, end).toInt();
    } else {
      if (command("PASV", line) != 227) return false;
      int open = line.indexOf('(');
      int h1,h2,h3,h4,p1,p2;
      if (open < 0 || sscanf(line.c_str()+open, "(%d,%d,%d,%d,%d,%d)", &h1,&h2,&h3,&h4,&p1,&p2) != 6 ||
          p1 < 0 || p1 > 255 || p2 < 0 || p2 > 255) return false;
      port = p1 * 256 + p2;
    }
    if (port < 1 || port > 65535 || !remaining()) return false;
    // Always use the control peer, not an arbitrary address in a PASV reply.
    uint32_t timeout = remaining();
    if (timeout > 5000) timeout = 5000;
    return data.connect(peer, port, timeout);
  }

  bool sendBytes(WiFiClient &data, const uint8_t *bytes, size_t size) {
    size_t sent = 0;
    uint32_t progress = millis();
    while (sent < size && remaining() && data.connected() && millis()-progress < 5000) {
      int room = data.availableForWrite();
      if (room <= 0) { delay(1); continue; }
      size_t chunk = size-sent;
      if (chunk > (size_t)room) chunk = room;
      size_t written = data.write(bytes+sent, chunk);
      if (written) { sent += written; progress = millis(); }
      else delay(1);
    }
    return sent == size;
  }

  bool finish(WiFiClient &data, bool ok) {
    data.stop();
    if (!ok) { close(); return false; }
    String line;
    return reply(line) == 226;
  }

public:
  void close() { control.stop(); }
  bool connected() { return remaining() && control.connected(); }

  bool begin(IPAddress address, uint16_t port, const char *user, const char *password,
             uint32_t cycleStart, uint32_t cycleBudget) {
    close();
    peer = address; started = cycleStart; budget = cycleBudget;
    if (!password[0] || !remaining()) return false;
    uint32_t timeout = remaining();
    if (timeout > 5000) timeout = 5000;
    if (!control.connect(peer, port, timeout)) return false;
    String line;
    if (reply(line) != 220) { close(); return false; }
    int code = command(String("USER ") + user, line);
    if (code == 331) code = command(String("PASS ") + password, line);
    if (code != 230 || command("TYPE I", line) != 200) { close(); return false; }
    return true;
  }

  bool putFile(const String &remote, File &file) {
    WiFiClient data;
    if (!passive(data)) return false;
    String line;
    int code = command("STOR " + remote, line);
    if (code != 125 && code != 150) { data.stop(); return false; }
    uint8_t buffer[2048];
    size_t total = 0, expected = file.size();
    while (total < expected && remaining()) {
      int count = file.read(buffer, sizeof(buffer));
      if (count <= 0 || !sendBytes(data, buffer, count)) break;
      total += count;
    }
    return finish(data, total == expected);
  }

  bool putText(const String &remote, const String &text) {
    WiFiClient data;
    if (!passive(data)) return false;
    String line;
    int code = command("STOR " + remote, line);
    if (code != 125 && code != 150) { data.stop(); return false; }
    return finish(data, sendBytes(data, (const uint8_t *)text.c_str(), text.length()));
  }

  bool renameFile(const String &from, const String &to) {
    String line;
    return command("RNFR " + from, line) == 350 && command("RNTO " + to, line) == 250;
  }

  bool getText(const String &remote, String &text, size_t limit = 2048) {
    text = "";
    WiFiClient data;
    if (!passive(data)) return false;
    String line;
    int code = command("RETR " + remote, line);
    if (code != 125 && code != 150) { data.stop(); return false; }
    uint32_t progress = millis();
    bool ok = true;
    while ((data.connected() || data.available()) && remaining()) {
      if (data.available()) {
        if (text.length() >= limit) { ok = false; break; }
        text += (char)data.read();
        progress = millis();
      } else {
        if (millis()-progress >= 5000) { ok = false; break; }
        delay(1);
      }
    }
    return finish(data, ok && remaining()) && text.length() > 0;
  }
};
