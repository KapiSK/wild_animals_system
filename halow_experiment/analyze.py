"""Reconcile sender trials with receiver files; retain failures and unknown outcomes."""
import argparse
import csv
import json
import math
import statistics
import warnings
from collections import defaultdict
from pathlib import Path
from common import digest, write_json


def wilson(k, n):
    if n == 0:
        return [None, None]
    z = 1.959963984540054
    p = k / n
    center = (p + z*z/(2*n)) / (1 + z*z/n)
    half = z * math.sqrt(p*(1-p)/n + z*z/(4*n*n)) / (1 + z*z/n)
    return [max(0, center-half), min(1, center+half)]


def percentile(values, q):
    if not values:
        return None
    values = sorted(values)
    pos = (len(values) - 1) * q
    lo, hi = math.floor(pos), math.ceil(pos)
    return values[lo] + (values[hi] - values[lo]) * (pos-lo)


def reconcile(run, received=None):
    run = Path(run)
    if not (run / "jobs").is_dir():
        raise ValueError("run jobs directory missing: " + str(run))
    if received is not None and not Path(received).is_dir():
        raise ValueError("receiver snapshot directory missing: " + str(received))
    trials = {}
    log = run / "trials.jsonl"
    if log.exists():
        content = log.read_text(encoding="utf-8")
        lines = content.splitlines()
        for number, line in enumerate(lines):
            if line.strip():
                try:
                    r = json.loads(line)
                except json.JSONDecodeError:
                    if number == len(lines)-1 and not content.endswith("\n"):
                        warnings.warn("Truncated final trial record; recovering its pre-written job as unknown")
                        continue
                    raise
                if r["cycle_id"] in trials:
                    raise ValueError("duplicate trial: use separate retry-attempt files")
                trials[r["cycle_id"]] = r
    rows = []
    for file in sorted((run / "jobs").glob("*.json")):
        job = json.loads(file.read_text(encoding="utf-8"))
        r = trials.get(job["cycle_id"], dict(job, status="interrupted_unknown", ack_received=False,
                         complete_ms=None, elapsed_ms=None, utc_started=job["planned_utc"]))
        count = None
        received_bytes = None
        if received is not None:
            count, received_bytes = 0, 0
            for im in r["images"]:
                target = Path(received) / r["device_id"] / r["cycle_id"] / f'{im["index"]}.jpg'
                if target.exists():
                    data = target.read_bytes()
                    if len(data) == im["bytes"] and digest(data) == im["sha256"]:
                        count += 1
                        received_bytes += len(data)
        r = dict(r, verified_images=count, verified_bytes=received_bytes,
                 server_complete=(count == r["image_count"]) if count is not None else None)
        r["ack_lost_after_storage"] = (r["server_complete"] and not r["ack_received"]) if count is not None else None
        rows.append(r)
    return rows


def summarize(rows):
    n = len(rows)
    ack = sum(bool(r["ack_received"]) for r in rows)
    times = [r["complete_ms"] for r in rows if r["ack_received"] and r.get("complete_ms") is not None]
    known = all(r["verified_images"] is not None for r in rows)
    events = sum(bool(r["server_complete"]) for r in rows) if known else None
    images = sum(r["verified_images"] for r in rows) if known else None
    total_images = sum(r["image_count"] for r in rows)
    timed = [r for r in rows if r.get("elapsed_ms") is not None]
    duration = sum(r["elapsed_ms"] for r in timed) / 1000
    return dict(trials=n, failures=n-ack, ack_successes=ack, ack_rate=ack/n if n else None,
                ack_ci95=wilson(ack,n), deadline_success_rate=ack/n if n else None,
                server_complete_events=events, server_event_rate=events/n if known and n else None,
                server_event_ci95=wilson(events,n) if known else [None,None],
                verified_images=images, planned_images=total_images,
                image_rate=images/total_images if known and total_images else None,
                image_ci95=wilson(images,total_images) if known else [None,None],
                ack_lost_after_storage=sum(bool(r["ack_lost_after_storage"]) for r in rows) if known else None,
                median_complete_ms=statistics.median(times) if times else None,
                p95_complete_ms=percentile(times,0.95), p95_exploratory=n<100,
                application_bps=(sum(r["verified_bytes"] for r in rows)*8/duration)
                if known and duration and len(timed)==n else None,
                application_interval="sum of trial elapsed_ms, including failed trials; excludes inter-event wait",
                receiver_evidence_available=known,
                measured_energy_events=sum(r.get("energy_j") is not None for r in rows),
                total_measured_energy_j=sum(r["energy_j"] for r in rows if r.get("energy_j") is not None)
                if any(r.get("energy_j") is not None for r in rows) else None,
                median_connect_ms=statistics.median([r["connect_ms"] for r in rows if r.get("connect_ms") is not None])
                if any(r.get("connect_ms") is not None for r in rows) else None,
                note="Receiver files show eventual storage, not server receipt deadline. Deadline rate refers to sender ACK.")


def analyze(runs, received, output, plots=True, energy=None, connections=None):
    output = Path(output)
    rows = [r for run in runs for r in reconcile(run, received)]
    identities = [(r["device_id"], r["cycle_id"]) for r in rows]
    if len(set(identities)) != len(identities):
        raise ValueError("same trial included more than once")
    for source, field in [(energy, "energy_j"), (connections, "connect_ms")]:
        if source:
            extra = json.loads(Path(source).read_text(encoding="utf-8"))["events"]
            by_id = {}
            for measurement in extra:
                key = (measurement["device_id"], measurement["cycle_id"])
                value = measurement[field]
                if key in by_id or not isinstance(value,(int,float)) or not math.isfinite(value) or value < 0:
                    raise ValueError("invalid or duplicate external measurement")
                by_id[key] = value
            for r in rows:
                r[field] = by_id.get((r["device_id"],r["cycle_id"]))
    groups = defaultdict(list)
    daily = defaultdict(list)
    for r in rows:
        groups[r["condition_id"]].append(r)
        daily[(r["condition_id"], r["utc_started"][:10], r.get("site"))].append(r)
    for key, values in groups.items():
        fields = ("distance_m","environment","tx_height_m","rx_height_m","channel","bandwidth_mhz",
                  "tx_power_dbm","duty_enabled","power_mode","event_deadline_s",
                  "reuse_connection","max_retries","storage_fsync")
        fingerprints = {json.dumps([*[r.get(f) for f in fields],
                           [(im["sha256"],im["bytes"]) for im in r["images"]]],sort_keys=True) for r in values}
        if len(fingerprints) != 1:
            raise ValueError("condition_id has inconsistent settings/corpus: " + key)
    output.mkdir(parents=True, exist_ok=False)
    summary = {k: summarize(v) for k,v in groups.items()}
    write_json(output / "summary.json", summary)
    write_json(output / "by_day_site.json", [dict(condition_id=k[0], date_utc=k[1], site=k[2], **summarize(v)) for k,v in daily.items()])
    write_json(output / "reconciled.json", rows)
    if rows:
        keys = sorted(set().union(*(r.keys() for r in rows)) - {"images"})
        with (output / "trials.csv").open("w", encoding="utf-8-sig", newline="") as f:
            w = csv.DictWriter(f, fieldnames=keys, extrasaction="ignore")
            w.writeheader()
            w.writerows(rows)
    if plots and rows:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
        fig, axes = plt.subplots(2,2,figsize=(12,8))
        for key, values in groups.items():
            a = summary[key]
            distance = values[0].get("distance_m")
            if distance is not None:
                rate = a["server_event_rate"]
                ci = a["server_event_ci95"]
                if rate is not None:
                    axes[0,0].errorbar([distance],[rate],yerr=[[rate-ci[0]],[ci[1]-rate]],fmt="o", label=key)
                if a["median_complete_ms"] is not None:
                    axes[0,1].scatter(distance,a["median_complete_ms"]/1000,label=f'{key} median; failures={a["failures"]}')
                    axes[0,1].scatter(distance,a["p95_complete_ms"]/1000,marker="x")
            success = [r for r in values if r["ack_received"] and r.get("complete_ms") is not None]
            axes[1,0].scatter([r["payload_bytes"] for r in success],[r["complete_ms"]/1000 for r in success],label=key)
        axes[1,1].bar(range(len(summary)),[a["ack_rate"] for a in summary.values()])
        axes[1,1].set_xticks(range(len(summary)), list(summary),rotation=30,ha="right")
        for ax, x, y in [(axes[0,0],"Distance (m)","Verified event rate (95% CI)"),
                          (axes[0,1],"Distance (m)","Completion (s); x = p95"),
                          (axes[1,0],"Event JPEG bytes","Completion (s)"),
                          (axes[1,1],"Condition","ACK within deadline rate")]:
            ax.set_xlabel(x)
            ax.set_ylabel(y)
            ax.grid(alpha=.2)
            if ax.get_legend_handles_labels()[0]:
                ax.legend(fontsize=7)
        fig.tight_layout()
        fig.savefig(output / "summary.png",dpi=160)
        plt.close(fig)
        if energy or connections:
            fig, axes = plt.subplots(1,2,figsize=(10,4))
            for index,(key,values) in enumerate(groups.items()):
                for ax,field,scale in [(axes[0],"connect_ms",.001),(axes[1],"energy_j",1)]:
                    measurements = [r[field]*scale for r in values if r.get(field) is not None]
                    ax.scatter([index]*len(measurements),measurements)
            for ax,label in zip(axes,["Radio connection time (s)","Measured event energy (J), failures included"]):
                ax.set_xticks(range(len(groups)),list(groups),rotation=30,ha="right")
                ax.set_ylabel(label)
                ax.grid(alpha=.2)
            fig.tight_layout()
            fig.savefig(output / "power_connection.png",dpi=160)
            plt.close(fig)
    return summary


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("runs", nargs="+")
    p.add_argument("--received", help="complete receiver storage snapshot; omit to keep reception rates unknown")
    p.add_argument("--output", required=True, help="new directory")
    p.add_argument("--no-plots", action="store_true")
    p.add_argument("--energy", help="JSON output of energy.py")
    p.add_argument("--connections", help="external JSON: events containing device_id, cycle_id, connect_ms")
    args = p.parse_args()
    print(json.dumps(analyze(args.runs,args.received,args.output,not args.no_plots,args.energy,args.connections),indent=2))
