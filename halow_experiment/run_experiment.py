"""Run sequential E0/E2/E3/E4 events with immutable per-trial jobs."""
import argparse
import shutil
import threading
import time
import uuid
from pathlib import Path
from common import append_json, load_config, utc, write_json
from collect_radio import check_route, sample, snapshot
from prepare_corpus import load_images
from sender import send_event


def run(config_path):
    c = load_config(config_path)
    s, e = c["sender"], c["experiment"]
    images = load_images(s["manifest"], s["image_ids"])
    run_id = "run_" + uuid.uuid4().hex
    folder = Path(e["results"]) / run_id
    folder.mkdir(parents=True, exist_ok=False)
    (folder / "jobs").mkdir()
    shutil.copy2(config_path, folder / "config.yaml")
    shutil.copy2(s["manifest"], folder / "manifest.csv")
    write_json(folder / "resolved_config.json", c)
    write_json(folder / "before.json", snapshot(s["interface"]))
    stop = threading.Event()

    def collect():
        while not stop.is_set():
            append_json(folder / "radio.jsonl", sample(s["interface"]))
            stop.wait(max(0.1, c["radio"]["interval_s"]))

    thread = threading.Thread(target=collect, daemon=True)
    thread.start()
    print(f"run directory: {folder}", flush=True)
    try:
        for trial in range(1, e["trials"] + 1):
            start = time.perf_counter()
            job = dict(e, run_id=run_id, trial_id=trial, device_id=s["device_id"],
                       cycle_id=f"{run_id}_{trial:06d}", images=images, image_count=len(images),
                       payload_bytes=sum(im["bytes"] for im in images),
                       reuse_connection=s["reuse_connection"], max_retries=s["max_retries"],
                       storage_fsync=c["server"]["fsync"],
                       event_deadline_s=s["event_deadline_s"], planned_utc=utc())
            write_json(folder / "jobs" / f"{trial:06d}.json", job)
            try:
                route = check_route(s)
                append_json(folder / "routes.jsonl", dict(trial_id=trial, utc=utc(), route=route))
                result = send_event(s, job)
            except Exception as exc:
                result = dict(job, utc_started=utc(), status="route_or_setup_failed", error_code=str(exc),
                              ack_received=False, server_complete=None, complete_ms=None, elapsed_ms=None,
                              connect_ms=None, app_retries=0, rssi_dbm=None, mcs=None, energy_j=None, image_acks=[])
            append_json(folder / "trials.jsonl", result)
            print(f'{trial}/{e["trials"]}: {result["status"]}', flush=True)
            if result["status"] == "interrupted":
                break
            if trial < e["trials"]:
                time.sleep(max(0, e["interval_s"] - (time.perf_counter() - start)))
    except KeyboardInterrupt:
        print("Stopped; completed trials and pre-written jobs are retained.")
    finally:
        stop.set()
        thread.join(timeout=5)
        write_json(folder / "after.json", snapshot(s["interface"]))
    return folder


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config.yaml")
    run(p.parse_args().config)
