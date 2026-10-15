"""E1: one load level per invocation; inspect loss before raising UDP load."""
import argparse
import json
import subprocess
import uuid
from pathlib import Path
from collect_radio import check_route, command, snapshot
from common import load_config, write_json


def receiver_stats(raw, udp=False):
    end = raw.get("end", {})
    if not udp:
        return end.get("sum_received")
    streams = [s.get("udp",{}) for s in end.get("streams",[])]
    received = [s for s in streams if s.get("sender") is False]
    if received:
        return received[0]
    summary = end.get("sum",{})
    if summary.get("sender") is False:
        return summary
    remote = raw.get("server_output_json",{}).get("end",{})
    if remote.get("sum"):
        return remote["sum"]
    return None


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--config",default="config.yaml")
    p.add_argument("--udp",help="one bitrate, e.g. 100K; omit for TCP")
    args = p.parse_args()
    c = load_config(args.config)
    s, spec = c["sender"], c["iperf"]
    folder = Path(c["experiment"]["results"]) / ("iperf_"+uuid.uuid4().hex)
    folder.mkdir(parents=True,exist_ok=False)
    write_json(folder / "config.json", c)
    write_json(folder / "before.json", snapshot(s["interface"]))
    for i in range(1,spec["trials"]+1):
        argv = ["iperf3","-c",s["host"],"-t",str(spec["duration_s"]),"-J","--get-server-output"]
        if s.get("source_ip"):
            argv += ["-B",s["source_ip"]]
        if args.udp:
            argv += ["-u","-b",args.udp]
        record = dict(command=argv, receiver=None)
        try:
            record["route"] = check_route(s)
            result = command(argv, timeout=spec["timeout_s"])
            record.update(result)
            if result["stdout"]:
                (folder / f"{i:03d}.raw.json").write_text(result["stdout"],encoding="utf-8")
                record["receiver"] = receiver_stats(json.loads(result["stdout"]),bool(args.udp))
        except (RuntimeError, ValueError) as exc:
            record["error"] = str(exc)
        write_json(folder / f"{i:03d}.json",record)
    write_json(folder / "after.json", snapshot(s["interface"]))
    print(folder)
