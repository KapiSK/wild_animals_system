#pragma once
#include <Arduino.h>
#include <SD.h>
#include <WiFi.h>
#include <libssh_esp32.h>
#include <libssh/libssh.h>
#include "sftp_protocol.h"

class CameraSftpClient : private SftpWire {
  ssh_session session = nullptr;
  ssh_channel channel = nullptr;
  SftpProtocol protocol{*this};
  uint32_t started = 0, budget = 60000;
  String remoteRoot;
  const char *failure = "not connected";

  uint32_t remaining() const {
    uint32_t elapsed = millis()-started;
    return elapsed < budget ? budget-elapsed : 0;
  }
  bool timeout() {
    uint32_t left = remaining();
    if (!session || !left) return false;
    long seconds = left > 5000 ? 5 : left/1000;
    long micros = left > 5000 ? 0 : (left%1000)*1000;
    return ssh_options_set(session, SSH_OPTIONS_TIMEOUT, &seconds) == SSH_OK &&
           ssh_options_set(session, SSH_OPTIONS_TIMEOUT_USEC, &micros) == SSH_OK;
  }
  bool send(const uint8_t *data, size_t size) override {
    size_t sent = 0;
    uint32_t progress = millis();
    while (sent < size && remaining() && millis()-progress < 5000) {
      int n = ssh_channel_write(channel, data+sent, size-sent);
      if (n > 0) { sent += n; progress = millis(); }
      else if (n != SSH_AGAIN) return false;
      else delay(1);
    }
    return sent == size;
  }
  bool receive(uint8_t *data, size_t size) override {
    size_t received = 0;
    uint32_t progress = millis();
    while (received < size && remaining() && millis()-progress < 5000) {
      int n = ssh_channel_read_nonblocking(channel, data+received, size-received, 0);
      if (n > 0) { received += n; progress = millis(); }
      else if ((n < 0 && n != SSH_AGAIN) || ssh_channel_is_eof(channel)) return false;
      else delay(1);
    }
    return received == size;
  }
  bool verifyHost(const char *expected) {
    ssh_key key = nullptr;
    unsigned char *digest = nullptr;
    size_t length = 0;
    if (ssh_get_server_publickey(session, &key) != SSH_OK) return false;
    int rc = ssh_get_publickey_hash(key, SSH_PUBLICKEY_HASH_SHA256, &digest, &length);
    ssh_key_free(key);
    if (rc != SSH_OK) return false;
    char *fingerprint = ssh_get_fingerprint_hash(SSH_PUBLICKEY_HASH_SHA256, digest, length);
    bool matches = fingerprint && strcmp(fingerprint, expected) == 0;
    ssh_clean_pubkey_hash(&digest);
    if (fingerprint) ssh_string_free_char(fingerprint);
    return matches;
  }
  bool reject(const char *reason) { failure = reason; close(); return false; }
  String path(const String &relative) const { return remoteRoot + "/" + relative; }

public:
  const char *error() const { return failure; }
  void close() {
    // Nonblocking disposal; never wait for a peer when the wake budget expired.
    if (session) ssh_set_blocking(session, 0);
    if (channel) { ssh_channel_free(channel); channel = nullptr; }
    if (session) { ssh_disconnect(session); ssh_free(session); session = nullptr; }
  }
  bool connected() { return session && channel && remaining() && protocol.valid() && ssh_is_connected(session); }
  bool begin(IPAddress address, uint16_t port, const char *user, const char *fingerprint,
             const char *keyPath, const char *passphrase, const char *root,
             uint32_t cycleStart, uint32_t cycleBudget) {
    close(); started = cycleStart; budget = cycleBudget;
    if (!user[0] || strncmp(fingerprint, "SHA256:", 7) || strlen(fingerprint) != 50 || root[0] != '/')
      return reject("configure user, SHA256 host fingerprint and absolute remote root");
    remoteRoot = root;
    while (remoteRoot.endsWith("/")) remoteRoot.remove(remoteRoot.length()-1);
    File keyFile = SD.open(keyPath, FILE_READ);
    if (!keyFile || !keyFile.size() || keyFile.size() > 8192) {
      keyFile.close(); return reject("private key missing/invalid on SD");
    }
    String privateKey = keyFile.readString(); keyFile.close();
    static bool initialized = false;
    if (!initialized) { libssh_begin(); initialized = true; }
    session = ssh_new();
    if (!session) return reject("SSH allocation failed");
    String host = address.toString();
    unsigned int sshPort = port;
    bool processConfig = false;
    if (ssh_options_set(session, SSH_OPTIONS_HOST, host.c_str()) != SSH_OK ||
        ssh_options_set(session, SSH_OPTIONS_PORT, &sshPort) != SSH_OK ||
        ssh_options_set(session, SSH_OPTIONS_USER, user) != SSH_OK ||
        ssh_options_set(session, SSH_OPTIONS_PROCESS_CONFIG, &processConfig) != SSH_OK ||
        ssh_options_set(session, SSH_OPTIONS_HOSTKEYS, "ssh-ed25519") != SSH_OK ||
        !timeout() || ssh_connect(session) != SSH_OK) return reject("SSH connection failed");
    if (!verifyHost(fingerprint)) return reject("Pi host key mismatch");
    ssh_key key = nullptr;
    int parsed = ssh_pki_import_privkey_base64(privateKey.c_str(), passphrase[0] ? passphrase : nullptr,
                                              nullptr, nullptr, &key);
    // The file remains on SD; clear this temporary copy before continuing.
    for (size_t i = 0; i < privateKey.length(); ++i) privateKey.setCharAt(i, '\0');
    if (parsed != SSH_OK) return reject("private key could not be parsed");
    int authenticated = timeout() ? ssh_userauth_publickey(session, nullptr, key) : SSH_AUTH_ERROR;
    ssh_key_free(key);
    if (authenticated != SSH_AUTH_SUCCESS) return reject("SSH public-key authentication failed");
    channel = ssh_channel_new(session);
    if (!channel || !timeout() || ssh_channel_open_session(channel) != SSH_OK ||
        !timeout() || ssh_channel_request_sftp(channel) != SSH_OK) return reject("SFTP subsystem unavailable");
    ssh_set_blocking(session, 0);
    if (!protocol.begin()) return reject("SFTP v3 negotiation failed");
    failure = "OK"; return true;
  }
  bool putFile(const String &remote, File &file) {
    if (!connected() || !protocol.open(path(remote).c_str(), true)) return false;
    uint8_t buffer[2048];
    size_t sent = 0, expected = file.size();
    while (sent < expected && remaining()) {
      int n = file.read(buffer, sizeof(buffer));
      if (n <= 0 || !protocol.write(buffer, n)) break;
      sent += n;
    }
    bool closed = protocol.closeFile();
    return sent == expected && closed;
  }
  bool putText(const String &remote, const String &text) {
    if (!connected() || !protocol.open(path(remote).c_str(), true)) return false;
    bool sent = protocol.write((const uint8_t *)text.c_str(), text.length());
    bool closed = protocol.closeFile(); return sent && closed;
  }
  bool renameFile(const String &from, const String &to) {
    return connected() && protocol.renameFile(path(from).c_str(), path(to).c_str());
  }
  bool getText(const String &remote, String &text, size_t limit = 2048) {
    text = "";
    if (!connected() || !protocol.open(path(remote).c_str(), false)) return false;
    uint8_t buffer[512];
    bool ok = false;
    while (remaining()) {
      size_t count = 0;
      if (!protocol.read(buffer, sizeof(buffer), count)) break;
      if (!count) { ok = text.length() > 0; break; }
      if (text.length()+count > limit) break;
      if (!text.concat((const char *)buffer, count)) break;
    }
    bool closed = protocol.closeFile(); return ok && closed;
  }
};
