"""Integrate externally measured voltage/current; include failed events."""
import argparse
import csv
import math
from collections import defaultdict
from common import write_json


def integrate(path):
    groups = defaultdict(list)
    with open(path,encoding="utf-8-sig",newline="") as f:
        for r in csv.DictReader(f):
            t,v,a = (float(r[k]) for k in ("time_s","voltage_v","current_a"))
            if not all(math.isfinite(x) for x in (t,v,a)) or v < 0 or a < 0:
                raise ValueError("expected finite, nonnegative voltage/current")
            groups[(r["device_id"],r["cycle_id"])].append((t,v*a))
    result = []
    for (device,cycle), samples in groups.items():
        if len(samples)<2 or any(b[0]<=a[0] for a,b in zip(samples,samples[1:])):
            raise ValueError("each event needs >=2 samples in strictly increasing timestamp order")
        energy = sum((b[0]-a[0])*(a[1]+b[1])/2 for a,b in zip(samples,samples[1:]))
        result.append(dict(device_id=device,cycle_id=cycle,energy_j=energy,
                           duration_s=samples[-1][0]-samples[0][0],samples=len(samples)))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("csv")
    p.add_argument("--output",required=True)
    args=p.parse_args()
    from pathlib import Path
    if Path(args.output).exists():
        p.error("output exists")
    rows=integrate(args.csv)
    write_json(args.output,dict(events=rows,total_energy_j=sum(r["energy_j"] for r in rows)))
