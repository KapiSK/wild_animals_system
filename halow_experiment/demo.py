"""Local E0 demo using generated JPEGs, NEVER HaLow performance evidence."""
import threading
import uuid
from pathlib import Path
import yaml
from PIL import Image, ImageDraw
from common import load_config
from prepare_corpus import prepare
from server import Receiver
from run_experiment import run
from analyze import analyze


def main():
    base = Path(__file__).resolve().parent
    folder = base / "results" / ("LOCAL_DEMO_" + uuid.uuid4().hex)
    corpus = folder / "corpus"
    corpus.mkdir(parents=True)
    for name,color in [("day","skyblue"),("night","navy"),("vegetation","green")]:
        im = Image.new("RGB",(640,480),color)
        ImageDraw.Draw(im).text((20,20),"SYNTHETIC LOCAL TEST: "+name,fill="white")
        im.save(corpus / (name+".jpg"),quality=90)
    prepare(corpus)
    c = yaml.safe_load((base / "config.yaml").read_text(encoding="utf-8"))
    c["server"].update(host="127.0.0.1",port=0,storage="received")
    c["sender"].update(host="127.0.0.1",source_ip="127.0.0.1",enforce_route=False,manifest="corpus/manifest.csv")
    c["experiment"].update(trials=3,interval_s=0,results="runs",condition_id="LOCAL_SYNTHETIC_ONLY",distance_m=None)
    config = folder / "config.yaml"
    config.write_text(yaml.safe_dump(c,allow_unicode=True),encoding="utf-8")
    settings = load_config(config)["server"]
    server = Receiver(("127.0.0.1",0),settings)
    c["sender"]["port"] = server.server_port
    config.write_text(yaml.safe_dump(c,allow_unicode=True),encoding="utf-8")
    thread = threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    try:
        run_dir = run(config)
        summary = analyze([run_dir],folder / "received",folder / "analysis")
        assert summary["LOCAL_SYNTHETIC_ONLY"]["server_complete_events"] == 3
        assert summary["LOCAL_SYNTHETIC_ONLY"]["ack_successes"] == 3
        print(f"LOCAL DEMO PASSED: {folder}")
    finally:
        server.shutdown()
        server.server_close()


if __name__ == "__main__":
    main()
