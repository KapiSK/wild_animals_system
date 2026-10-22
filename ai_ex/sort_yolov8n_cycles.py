"""Classify complete KDxxxx-1/-2/-3 image cycles using COCO YOLOv8n."""

import argparse
import csv
import hashlib
import json
from pathlib import Path
import re
import shutil
from datetime import datetime, timezone


CLASSES = {0: "person", 14: "bird", 15: "cat", 16: "dog", 17: "horse",
           18: "sheep", 19: "cow", 20: "elephant", 21: "bear",
           22: "zebra", 23: "giraffe"}
CONF = 0.05
PATTERN = re.compile(r"^(KD.+)-([123])$", re.IGNORECASE)


def collect_cycles(root):
    groups, skipped = {}, []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.suffix.lower() not in {".jpg", ".jpeg", ".png"}:
            continue
        relative = path.relative_to(root)
        match = PATTERN.fullmatch(path.stem)
        if not match:
            skipped.append({"path": relative.as_posix(), "reason": "unrecognized_filename"})
            continue
        key = (relative.parent / match[1]).as_posix()
        groups.setdefault(key, {}).setdefault(int(match[2]), []).append(path)
    complete = {}
    for key, frames in groups.items():
        if set(frames) == {1, 2, 3} and all(len(paths) == 1 for paths in frames.values()):
            complete[key] = [frames[i][0] for i in (1, 2, 3)]
        else:
            for paths in frames.values():
                for path in paths:
                    skipped.append({"path": path.relative_to(root).as_posix(),
                                    "reason": "incomplete_or_duplicate_cycle"})
    return complete, skipped


def write_csv(path, rows, fields):
    with path.open("w", encoding="utf-8-sig", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="Input image directory (recursive)")
    parser.add_argument("output", type=Path, help="New output directory outside input")
    parser.add_argument("--model", type=Path,
                        default=Path(__file__).resolve().parents[1] / "yolov8n.pt")
    parser.add_argument("--device", default="cpu", help="cpu or CUDA device, e.g. 0")
    args = parser.parse_args()
    source, output, model_path = args.input.resolve(), args.output.resolve(), args.model.resolve()
    if not source.is_dir():
        parser.error(f"Input directory does not exist: {source}")
    if output == source or source in output.parents:
        parser.error("Output must be outside the input directory.")
    if output.exists():
        parser.error("Output already exists; choose a new directory to avoid mixing runs.")
    if not model_path.is_file():
        parser.error(f"Model not found: {model_path}")
    groups, skipped = collect_cycles(source)
    if not groups:
        parser.error(f"No complete -1/-2/-3 cycles found ({len(skipped)} images skipped).")

    import ultralytics
    from ultralytics import YOLO

    model = YOLO(str(model_path))
    if any(model.names.get(key) != name for key, name in CLASSES.items()):
        parser.error("Model class names do not match the requested COCO classes.")
    output.mkdir(parents=True)
    for label in ("detect", "empty"):
        (output / label).mkdir()
    metadata = {
        "status": "running", "started_utc": datetime.now(timezone.utc).isoformat(),
        "input": str(source), "model": str(model_path),
        "model_sha256": hashlib.sha256(model_path.read_bytes()).hexdigest(),
        "ultralytics_version": ultralytics.__version__, "conf": CONF,
        "classes": CLASSES, "imgsz": 640, "iou": 0.7, "max_det": 300,
        "device": args.device, "rule": "any of 3 images detected => detect",
    }
    metadata_path = output / "run.json"
    metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    write_csv(output / "skipped.csv", skipped, ["path", "reason"])
    image_rows, cycle_rows = [], []
    counts = {"detect": 0, "empty": 0}
    try:
        for index, (key, paths) in enumerate(groups.items(), 1):
            rows = []
            for path in paths:
                result = model.predict(source=str(path), conf=CONF, classes=list(CLASSES),
                                       imgsz=640, iou=0.7, max_det=300,
                                       device=args.device, verbose=False, save=False)[0]
                detections = [
                    {"class_id": int(cls), "class_name": CLASSES[int(cls)],
                     "confidence": float(conf), "xyxy": box}
                    for cls, conf, box in zip(result.boxes.cls.tolist(),
                                              result.boxes.conf.tolist(),
                                              result.boxes.xyxy.tolist())
                    if int(cls) in CLASSES and float(conf) >= CONF
                ]
                rows.append({"path": path.relative_to(source).as_posix(), "cycle": key,
                             "image_detected": bool(detections),
                             "detections": json.dumps(detections)})
            label = "detect" if any(row["image_detected"] for row in rows) else "empty"
            for path, row in zip(paths, rows):
                destination = output / label / path.relative_to(source)
                destination.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(path, destination)
                row["cycle_label"] = label
            image_rows.extend(rows)
            cycle_rows.append({"cycle": key, "label": label,
                               "detected_images": sum(row["image_detected"] for row in rows)})
            counts[label] += 1
            print(f"[{index}/{len(groups)}] {key}: {label}", flush=True)
        metadata["status"] = "complete"
    except Exception as exc:
        metadata["status"] = "failed"
        metadata["error"] = str(exc)
        raise
    finally:
        write_csv(output / "images.csv", image_rows,
                  ["path", "cycle", "image_detected", "cycle_label", "detections"])
        write_csv(output / "cycles.csv", cycle_rows, ["cycle", "label", "detected_images"])
        metadata.update(cycle_counts=counts, skipped_images=len(skipped))
        metadata_path.write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    print(f"Finished: {counts}, skipped images: {len(skipped)}; output: {output}")


if __name__ == "__main__":
    main()
