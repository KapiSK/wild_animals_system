"""One event, isolated in a process so a slow HTTP peer cannot extend its deadline."""
import argparse
import http.client
import ipaddress
import json
import multiprocessing as mp
import time
from common import digest, load_config, utc


def _worker(pipe, settings, job):
    conn = None
    retries = 0
    try:
        # Numeric address avoids unbounded DNS resolution and records an exact endpoint.
        ipaddress.ip_address(settings["host"])
        for image in job["images"]:
            from pathlib import Path
            data = Path(image["path"]).read_bytes()
            if len(data) != image["bytes"] or digest(data) != image["sha256"]:
                raise ValueError("corpus changed after planning")
        headers = {"X-Device-Id": job["device_id"], "X-Cycle-Id": job["cycle_id"]}
        steps = [("/upload", im) for im in job["images"]] + [("/complete", None)]
        for endpoint, im in steps:
            for attempt in range(settings["max_retries"] + 1):
                try:
                    if conn is None:
                        source = (settings["source_ip"], 0) if settings.get("source_ip") else None
                        conn = http.client.HTTPConnection(settings["host"], settings["port"],
                                                          timeout=settings["connect_timeout_s"], source_address=source)
                        conn.connect()
                        conn.sock.settimeout(settings["event_deadline_s"])
                    h = dict(headers)
                    if im:
                        body = Path(im["path"]).read_bytes()
                        h.update({"X-Img-Index": str(im["index"]), "X-Content-SHA256": im["sha256"],
                                  "Content-Type": "image/jpeg"})
                    else:
                        body = json.dumps({"images": job["images"]}).encode()
                        h["Content-Type"] = "application/json"
                    h["Content-Length"] = str(len(body))
                    conn.request("POST", endpoint, body, h)
                    response = conn.getresponse()
                    raw = response.read(65537)
                    if len(raw) > 65536:
                        raise ValueError("oversized response")
                    obj = json.loads(raw)
                    if response.status != 200:
                        raise ValueError(f"HTTP {response.status}: {obj}")
                    if obj.get("device_id") != job["device_id"] or obj.get("cycle_id") != job["cycle_id"]:
                        raise ValueError("response identity mismatch")
                    if im:
                        if any(obj.get(k) != im[k] for k in ("index", "bytes", "sha256")):
                            raise ValueError("upload acknowledgement mismatch")
                        pipe.send({"kind": "image_ack", "index": im["index"]})
                    else:
                        if obj.get("complete") is not True or obj.get("received_indices") != list(range(1, len(job["images"]) + 1)):
                            raise ValueError("incomplete acknowledgement")
                        pipe.send({"kind": "complete", "at_ns": time.perf_counter_ns()})
                    if not settings["reuse_connection"]:
                        conn.close()
                        conn = None
                    break
                except (OSError, http.client.HTTPException, ValueError) as exc:
                    if conn:
                        conn.close()
                        conn = None
                    # 4xx and malformed replies are protocol failures, not transient retries.
                    if attempt >= settings["max_retries"] or isinstance(exc, ValueError):
                        raise
                    retries += 1
                    pipe.send({"kind": "retry", "count": retries})
                    time.sleep(settings.get("retry_delay_s", 1))
    except Exception as exc:
        pipe.send({"kind": "error", "error": f"{type(exc).__name__}: {exc}"})
    finally:
        if conn:
            conn.close()
        pipe.close()


def send_event(settings, job):
    result = dict(job, utc_started=utc(), connect_ms=None, complete_ms=None,
                  server_complete=None, ack_received=False, status="failed", app_retries=0,
                  rssi_dbm=None, mcs=None, energy_j=None, error_code=None, image_acks=[])
    context = mp.get_context("spawn")
    parent, child = context.Pipe(duplex=False)
    process = context.Process(target=_worker, args=(child, settings, job), daemon=True)
    started = time.perf_counter_ns()
    deadline = started + int(settings["event_deadline_s"] * 1e9)
    process.start()
    child.close()
    try:
        while True:
            remaining = (deadline - time.perf_counter_ns()) / 1e9
            if remaining <= 0:
                result.update(status="deadline_exceeded", error_code="event_deadline")
                break
            if not parent.poll(min(remaining, 0.1)):
                if not process.is_alive():
                    result["error_code"] = "worker_exited"
                    break
                continue
            try:
                message = parent.recv()
            except EOFError:
                result["error_code"] = "worker_eof"
                break
            if message["kind"] == "image_ack":
                result["image_acks"].append(message["index"])
            elif message["kind"] == "retry":
                result["app_retries"] = message["count"]
            elif message["kind"] == "error":
                result["error_code"] = message["error"]
                break
            elif message["kind"] == "complete":
                if message["at_ns"] <= deadline:
                    result.update(status="success", ack_received=True, server_complete=True,
                                  complete_ms=(message["at_ns"] - started) / 1e6)
                else:
                    result.update(status="deadline_exceeded", error_code="event_deadline")
                break
    except KeyboardInterrupt:
        result.update(status="interrupted", error_code="keyboard_interrupt")
    finally:
        if process.is_alive():
            process.terminate()
        process.join(timeout=2)
        parent.close()
    result["elapsed_ms"] = (time.perf_counter_ns() - started) / 1e6
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description="Retry one saved job with the SAME event ID; outputs a separate attempt log")
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--job", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    from pathlib import Path
    from common import write_json
    if Path(args.output).exists():
        p.error("output already exists")
    c = load_config(args.config)
    from collect_radio import check_route
    check_route(c["sender"])
    result = send_event(c["sender"], json.loads(Path(args.job).read_text(encoding="utf-8")))
    write_json(args.output, result)
    print(result["status"])
