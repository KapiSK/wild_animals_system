#pragma once
#include <stdint.h>
#include <stddef.h>
#include <string.h>

// Bounded SFTP v3 subset over an already authenticated SSH subsystem channel.
// LibSSH-ESP32 ships SSH channels but does not ship libssh's SFTP module.
// Only one request and one open file at a time; no whole-image buffering.
class SftpWire {
public:
  virtual bool send(const uint8_t *data, size_t size) = 0;
  virtual bool receive(uint8_t *data, size_t size) = 0;
  virtual ~SftpWire() = default;
};

class SftpProtocol {
  SftpWire &wire;
  uint8_t packet[4096], handle[256];
  size_t used = 0, length = 0, handleSize = 0;
  uint32_t id = 0;
  uint64_t offset = 0;
  bool healthy = false;

  static uint32_t number(const uint8_t *p) {
    return (uint32_t(p[0]) << 24) | (uint32_t(p[1]) << 16) | (uint32_t(p[2]) << 8) | p[3];
  }
  static void encode(uint8_t *p, uint32_t n) {
    p[0] = n >> 24; p[1] = n >> 16; p[2] = n >> 8; p[3] = n;
  }
  bool fail() { healthy = false; return false; }
  void start(uint8_t type) { used = 4; packet[used++] = type; integer(++id); status = 0; }
  void integer(uint32_t n) { encode(packet+used, n); used += 4; }
  bool bytes(const void *data, size_t size) {
    if (size > sizeof(packet)-used-4) return fail();
    integer(size); memcpy(packet+used, data, size); used += size; return true;
  }
  bool text(const char *value) {
    size_t size = strlen(value);
    return size <= 512 ? bytes(value, size) : fail();
  }
  bool exchange(bool version = false) {
    if (!healthy) return false;
    encode(packet, used-4);
    if (!wire.send(packet, used) || !wire.receive(packet, 4)) return fail();
    length = number(packet);
    if (length < 5 || length > sizeof(packet) || !wire.receive(packet, length)) return fail();
    if (version) return packet[0] == 2 && number(packet+1) == 3 ? true : fail();
    if (number(packet+1) != id) return fail();
    if (packet[0] == 101) {
      if (length < 17) return fail();
      status = number(packet+5);
    }
    return true;
  }
  bool acknowledged() { return exchange() && packet[0] == 101 && status == 0; }

public:
  uint32_t status = 0;
  explicit SftpProtocol(SftpWire &stream) : wire(stream) {}
  bool valid() const { return healthy; }
  bool begin() {
    healthy = true; handleSize = 0; id = 0;
    used = 4; packet[used++] = 1; integer(3);
    return exchange(true);
  }
  bool open(const char *path, bool writing) {
    if (handleSize) return false;
    start(3);
    if (!text(path)) return false;
    // WRITE|CREAT|EXCL: retries use a new token, never truncate another upload.
    integer(writing ? 2|8|32 : 1);
    integer(writing ? 4 : 0); // ATTR_PERMISSIONS
    if (writing) integer(0660);
    if (!exchange() || packet[0] != 102) return false;
    if (length < 9) return fail();
    size_t size = number(packet+5);
    if (!size || size > sizeof(handle) || length != size+9) return fail();
    memcpy(handle, packet+9, size); handleSize = size; offset = 0; return true;
  }
  bool write(const uint8_t *data, size_t size) {
    if (!handleSize || size > 2048) return false;
    start(6); bytes(handle, handleSize);
    integer(offset >> 32); integer(uint32_t(offset));
    if (!bytes(data, size) || !acknowledged()) return false;
    offset += size; return true;
  }
  bool read(uint8_t *data, size_t capacity, size_t &count) {
    count = 0;
    if (!handleSize || !capacity || capacity > 2048) return false;
    start(5); bytes(handle, handleSize);
    integer(offset >> 32); integer(uint32_t(offset)); integer(capacity);
    if (!exchange()) return false;
    if (packet[0] == 101) return status == 1; // EOF, distinct from permission/I/O errors
    if (packet[0] != 103 || length < 9) return fail();
    count = number(packet+5);
    if (!count || count > capacity || length != count+9) return fail();
    memcpy(data, packet+9, count); offset += count; return true;
  }
  bool closeFile() {
    if (!handleSize) return false;
    start(4); bytes(handle, handleSize); handleSize = 0;
    return acknowledged();
  }
  bool renameFile(const char *from, const char *to) {
    start(18);
    return text(from) && text(to) && acknowledged();
  }
};
