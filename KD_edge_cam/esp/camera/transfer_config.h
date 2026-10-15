#pragma once

// Optional private overrides (do not commit this file with real credentials).
#if __has_include("transfer_secrets.h")
#include "transfer_secrets.h"
#endif

#define CAMERA_TRANSPORT_HTTP 0
#define CAMERA_TRANSPORT_FTP 1
#define CAMERA_TRANSPORT_SFTP 2
#ifndef CAMERA_TRANSFER_MODE
#ifdef CAMERA_USE_FTP
// Preserve explicitly configured older firmware settings.
#define CAMERA_TRANSFER_MODE CAMERA_USE_FTP
#else
#define CAMERA_TRANSFER_MODE CAMERA_TRANSPORT_SFTP
#endif
#endif
#if CAMERA_TRANSFER_MODE < 0 || CAMERA_TRANSFER_MODE > 2
#error "CAMERA_TRANSFER_MODE must be 0 (HTTP), 1 (FTP), or 2 (SFTP)"
#endif
#ifndef CAMERA_SFTP_PORT
#define CAMERA_SFTP_PORT 22
#endif
#ifndef CAMERA_SFTP_USER
#define CAMERA_SFTP_USER "camera-upload"
#endif
#ifndef CAMERA_SFTP_HOST_FINGERPRINT
#define CAMERA_SFTP_HOST_FINGERPRINT "" // SHA256:... of the Pi ED25519 host key.
#endif
#ifndef CAMERA_SFTP_KEY_PATH
#define CAMERA_SFTP_KEY_PATH "/ssh/camera_ed25519"
#endif
#ifndef CAMERA_SFTP_KEY_PASSPHRASE
#define CAMERA_SFTP_KEY_PASSPHRASE ""
#endif
#ifndef CAMERA_SFTP_REMOTE_ROOT
#define CAMERA_SFTP_REMOTE_ROOT "/transfer"
#endif
#ifndef CAMERA_FTP_PORT
#define CAMERA_FTP_PORT 2121
#endif
#ifndef CAMERA_FTP_USER
#define CAMERA_FTP_USER "camera"
#endif
#ifndef CAMERA_FTP_PASSWORD
#define CAMERA_FTP_PASSWORD "" // Must match the Pi receiver's FTP_PASSWORD.
#endif
