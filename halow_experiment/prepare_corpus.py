"""Record real JPEGs without modifying or padding them."""
import argparse
import csv
from pathlib import Path
from PIL import Image
from common import digest, identifier


def prepare(directory):
    directory = Path(directory).resolve()
    rows = []
    for p in sorted(directory.iterdir()):
        if p.suffix.lower() not in (".jpg", ".jpeg"):
            continue
        image_id = identifier(p.stem)
        if any(r["image_id"] == image_id for r in rows):
            raise ValueError("duplicate image ID: " + image_id)
        with Image.open(p) as im:
            if im.format != "JPEG":
                raise ValueError("not JPEG: " + str(p))
            width, height = im.size
            im.verify()
        data = p.read_bytes()
        rows.append(dict(image_id=image_id, path=p.name, width=width, height=height,
                         bytes=len(data), sha256=digest(data)))
    if not rows:
        raise ValueError("no JPEG files; add real camera JPEGs first")
    with (directory / "manifest.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    return rows


def load_images(manifest, ids):
    manifest = Path(manifest)
    with manifest.open(encoding="utf-8-sig", newline="") as f:
        rows = {r["image_id"]: r for r in csv.DictReader(f)}
    result = []
    for i, name in enumerate(ids, 1):
        r = rows[name]
        p = (manifest.parent / r["path"]).resolve()
        data = p.read_bytes()
        if len(data) != int(r["bytes"]) or digest(data) != r["sha256"]:
            raise ValueError("corpus changed; regenerate manifest: " + name)
        result.append(dict(index=i, image_id=name, path=str(p), bytes=len(data), sha256=r["sha256"]))
    return result


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("directory", nargs="?", default="corpus")
    print(f"Recorded {len(prepare(p.parse_args().directory))} images")
