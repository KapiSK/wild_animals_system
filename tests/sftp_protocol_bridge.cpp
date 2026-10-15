// Native test bridge for the exact SFTP v3 implementation used by the camera.
#include "../KD_edge_cam/esp/camera/sftp_protocol.h"
#ifdef _WIN32
#define EXPORT extern "C" __declspec(dllexport)
#else
#define EXPORT extern "C"
#endif
using Callback = int (*)(void *, uint8_t *, size_t);
struct Bridge : SftpWire {
  Callback tx, rx;
  void *context;
  SftpProtocol protocol;
  Bridge(Callback send, Callback receive, void *ctx) : tx(send), rx(receive), context(ctx), protocol(*this) {}
  bool send(const uint8_t *p, size_t n) override { return tx(context, const_cast<uint8_t *>(p), n) != 0; }
  bool receive(uint8_t *p, size_t n) override { return rx(context, p, n) != 0; }
};
EXPORT Bridge *client_new(Callback tx, Callback rx, void *ctx) { return new Bridge(tx, rx, ctx); }
EXPORT void client_free(Bridge *b) { delete b; }
EXPORT int client_begin(Bridge *b) { return b->protocol.begin(); }
EXPORT int client_open(Bridge *b, const char *p, int w) { return b->protocol.open(p, w != 0); }
EXPORT int client_write(Bridge *b, uint8_t *p, size_t n) { return b->protocol.write(p, n); }
EXPORT int client_read(Bridge *b, uint8_t *p, size_t n, size_t *count) { return b->protocol.read(p, n, *count); }
EXPORT int client_close(Bridge *b) { return b->protocol.closeFile(); }
EXPORT int client_rename(Bridge *b, const char *from, const char *to) { return b->protocol.renameFile(from, to); }
EXPORT int client_valid(Bridge *b) { return b->protocol.valid(); }
EXPORT unsigned client_status(Bridge *b) { return b->protocol.status; }
