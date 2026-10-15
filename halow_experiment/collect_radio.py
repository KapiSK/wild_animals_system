"""Preserve raw driver evidence; unsupported RSSI/MCS remain null."""
import argparse
import json
import platform
import subprocess
import time
from pathlib import Path
from common import append_json, load_config, utc


def command(argv, timeout=10):
    try:
        p = subprocess.run(argv, capture_output=True, text=True, errors="replace", timeout=timeout)
        return dict(command=argv, returncode=p.returncode, stdout=p.stdout, stderr=p.stderr)
    except (OSError, subprocess.TimeoutExpired) as exc:
        return dict(command=argv, returncode=None, stdout=None, stderr=str(exc))


def check_route(settings):
    if not settings["enforce_route"]:
        return {"enforced": False}
    if platform.system() != "Linux":
        raise RuntimeError("HaLow route verification requires Linux; use local config for E0")
    result = command(["ip", "-j", "route", "get", settings["host"], "from", settings["source_ip"]])
    if result["returncode"] != 0:
        raise RuntimeError("route unavailable: " + str(result))
    routes = json.loads(result["stdout"])
    if not routes or routes[0].get("dev") != settings["interface"]:
        raise RuntimeError("route does not use configured HaLow interface: " + str(routes))
    return result


def snapshot(interface):
    return dict(utc=utc(), platform=platform.platform(), python=platform.python_version(),
                rssi_dbm=None, mcs=None, direction="local driver report; see raw output",
                commands=[command(c) for c in [
                    ["ip", "-s", "-j", "link"], ["ip", "-br", "addr"],
                    ["iw", "dev", interface, "info"], ["iw", "dev", interface, "link"],
                    ["iw", "dev", interface, "station", "dump"],
                    ["ethtool", "-i", interface], ["uname", "-a"],
                    ["timedatectl", "show"], ["iperf3", "--version"]]])


def sample(interface):
    return dict(utc=utc(), interface=interface, rssi_dbm=None, mcs=None,
                source="iw station dump", units="see raw driver output", direction="driver dependent",
                raw=command(["iw", "dev", interface, "station", "dump"], timeout=3))


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--output", required=True)
    p.add_argument("--samples", type=int, default=1, help="0: until Ctrl+C")
    args = p.parse_args()
    c = load_config(args.config)
    n = 0
    try:
        while args.samples == 0 or n < args.samples:
            append_json(Path(args.output), sample(c["sender"]["interface"]))
            n += 1
            time.sleep(c["radio"]["interval_s"])
    except KeyboardInterrupt:
        pass
