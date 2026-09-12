#!/usr/bin/env python3
"""Training watchdog for the jobbot RVC model. Runs INSIDE the applio container
(docker exec applio python /data/watch.py), typically every 30 min from host cron.

Each run:
  1. parses train_console.log -> current epoch, step, seconds/epoch, epoch records
  2. for every new weights file logs/jobbot/jobbot_<E>e_<S>s.pth:
       - converts /data/test_en.wav and /data/test_ru.wav -> /data/out/ep<E>_{en,ru}.wav
       - self-reconstruction check on 5 held-out clips (/data/jobbot/val):
         convert clip -> mel-spectrogram L1 distance to the original (lower = closer)
  3. appends one JSON line to /data/watch/log.jsonl and a readable line to watch.log
  4. hard rules: stop training at DEADLINE (local server time) or if free disk < 20 GB
"""
from __future__ import annotations

import datetime as dt
import glob
import json
import os
import re
import shutil
import subprocess
import sys
import time

LOGS = "/app/logs/jobbot"
DATA = "/data"
OUT = f"{DATA}/out"
WATCH = f"{DATA}/watch"
CONSOLE = f"{LOGS}/train_console.log"
DEADLINE = os.environ.get("WATCH_DEADLINE", "09:00")  # HH:MM local time
MIN_FREE_GB = 20
VAL_CLIPS = 5

os.makedirs(OUT, exist_ok=True)
os.makedirs(WATCH, exist_ok=True)


def log(msg: str) -> None:
    line = f"{dt.datetime.now():%Y-%m-%d %H:%M:%S} {msg}"
    print(line)
    with open(f"{WATCH}/watch.log", "a") as f:
        f.write(line + "\n")


def jsonl(obj: dict) -> None:
    obj["ts"] = dt.datetime.now().isoformat(timespec="seconds")
    with open(f"{WATCH}/log.jsonl", "a") as f:
        f.write(json.dumps(obj, ensure_ascii=False) + "\n")


def training_running() -> bool:
    r = subprocess.run(["pgrep", "-f", "rvc/train/train.py"], capture_output=True)
    return r.returncode == 0


def stop_training(reason: str) -> None:
    log(f"STOP training: {reason}")
    subprocess.run(["pkill", "-f", "core.py train"])
    subprocess.run(["pkill", "-f", "rvc/train/train.py"])
    # train.py spawns the real training loop via multiprocessing.spawn; it
    # survives its parent (observed twice) and keeps training and saving.
    time.sleep(3)
    subprocess.run(["pkill", "-f", "multiprocessing.spawn"])
    subprocess.run(["pkill", "-f", "multiprocessing.resource_tracker"])
    jsonl({"event": "stop", "reason": reason})


def parse_console() -> dict:
    if not os.path.exists(CONSOLE):
        return {}
    text = open(CONSOLE, errors="replace").read().replace("\r", "\n")
    records = [ln for ln in text.splitlines() if "| epoch=" in ln]
    last = records[-1] if records else ""
    m = re.search(r"epoch=(\d+) \| step=(\d+)", last)
    epoch = int(m.group(1)) if m else 0
    step = int(m.group(2)) if m else 0
    # seconds per epoch from consecutive record timestamps is not available; use file mtimes
    its = re.findall(r"([0-9.]+)s/it\]", text)
    s_per_it = float(its[-1]) if its else None
    errors = [ln for ln in text.splitlines() if "Error" in ln or "Traceback" in ln]
    return {"epoch": epoch, "step": step, "s_per_it": s_per_it, "last_record": last[:300],
            "error_lines": len(errors), "last_error": errors[-1][:200] if errors else ""}


def losses() -> dict:
    """Latest value of every 'loss' scalar from the tensorboard event files."""
    try:
        from tensorboard.backend.event_processing.event_accumulator import EventAccumulator
    except Exception:  # noqa: BLE001
        return {}
    out: dict = {}
    for d in (LOGS, f"{LOGS}/eval"):
        files = sorted(glob.glob(f"{d}/events*"), key=os.path.getmtime)
        if not files:
            continue
        try:
            ea = EventAccumulator(files[-1], size_guidance={"scalars": 0})
            ea.Reload()
            for tag in ea.Tags().get("scalars", []):
                if "loss" in tag.lower() or "grad" in tag.lower():
                    ev = ea.Scalars(tag)[-1]
                    key = ("eval/" if d.endswith("eval") else "") + tag
                    out[key] = round(float(ev.value), 4)
                    out.setdefault("_step", ev.step)
        except Exception as err:  # noqa: BLE001
            log(f"tensorboard read failed in {d}: {err}")
    return out


def weights() -> list[tuple[int, str]]:
    out = []
    for p in glob.glob(f"{LOGS}/jobbot_*e_*s.pth"):
        m = re.search(r"_(\d+)e_(\d+)s\.pth$", p)
        if m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def index_path() -> str | None:
    idx = sorted(glob.glob(f"{LOGS}/*.index"))
    return idx[-1] if idx else None


def infer(pth: str, idx: str, src: str, dst: str) -> bool:
    cmd = ["python", "/app/core.py", "infer", "--input-path", src, "--output-path", dst,
           "--pth-path", pth, "--index-path", idx, "--pitch", "0", "--index-rate", "0.5",
           "--f0-method", "rmvpe", "--embedder-model", "contentvec"]
    r = subprocess.run(cmd, cwd="/app", capture_output=True, text=True, timeout=900)
    ok = r.returncode == 0 and os.path.exists(dst) and os.path.getsize(dst) > 1000
    if not ok:
        log(f"infer failed for {os.path.basename(pth)} -> {os.path.basename(dst)}: {r.stderr[-300:]}")
    return ok


def mel_distance(a_path: str, b_path: str) -> float:
    import librosa
    import numpy as np
    a, _ = librosa.load(a_path, sr=16000, mono=True)
    b, _ = librosa.load(b_path, sr=16000, mono=True)
    n = min(len(a), len(b))
    a, b = a[:n], b[:n]
    ma = librosa.power_to_db(librosa.feature.melspectrogram(y=a, sr=16000, n_mels=64), ref=np.max)
    mb = librosa.power_to_db(librosa.feature.melspectrogram(y=b, sr=16000, n_mels=64), ref=np.max)
    return float(np.mean(np.abs(ma - mb)))


def evaluate(epoch: int, pth: str, idx: str) -> dict:
    res: dict = {"epoch": epoch, "pth": os.path.basename(pth)}
    t0 = time.time()
    for lang in ("en", "ru"):
        src = f"{DATA}/test_{lang}.wav"
        dst = f"{OUT}/ep{epoch:04d}_{lang}.wav"
        if os.path.exists(src):
            res[f"test_{lang}"] = infer(pth, idx, src, dst)
    res["infer_s"] = round(time.time() - t0, 1)
    vals = sorted(glob.glob(f"{DATA}/jobbot/val/*.wav"))[:VAL_CLIPS]
    dists = []
    for v in vals:
        dst = f"{OUT}/val_ep{epoch:04d}_{os.path.basename(v)}"
        if infer(pth, idx, v, dst):
            try:
                dists.append(mel_distance(v, dst))
            except Exception as err:  # noqa: BLE001
                log(f"mel_distance failed: {err}")
            finally:
                if os.path.exists(dst):
                    os.remove(dst)
    res["val_mel_dist"] = round(sum(dists) / len(dists), 3) if dists else None
    res["val_n"] = len(dists)
    return res


def main() -> int:
    state_path = f"{WATCH}/state.json"
    state = json.load(open(state_path)) if os.path.exists(state_path) else {"evaluated": []}
    now = dt.datetime.now()
    free_gb = shutil.disk_usage("/app/logs").free / 1e9
    running = training_running()
    info = parse_console()
    ls = losses()
    brief = {k: v for k, v in ls.items() if k in ("loss/g/total", "loss/d/total", "loss/g/mel", "loss/g/kl", "loss/g/fm")}
    log(f"epoch={info.get('epoch')} step={info.get('step')} s/it={info.get('s_per_it')} "
        f"running={running} free={free_gb:.0f}GB weights={len(weights())} errors={info.get('error_lines')} "
        f"losses={brief or ls}")
    jsonl({"event": "status", "running": running, "free_gb": round(free_gb, 1), **info, "losses": ls})

    # hard rules
    dl_h, dl_m = map(int, DEADLINE.split(":"))
    deadline = now.replace(hour=dl_h, minute=dl_m, second=0, microsecond=0)
    if now.hour >= 12:  # evening: deadline is tomorrow morning
        deadline += dt.timedelta(days=1)
    if running and now >= deadline:
        stop_training(f"deadline {DEADLINE} reached")
    if running and free_gb < MIN_FREE_GB:
        stop_training(f"free disk {free_gb:.0f} GB < {MIN_FREE_GB} GB")

    idx = index_path()
    if idx is None:
        log("no index yet; skipping evaluation")
        return 0
    for epoch, pth in weights():
        if epoch in state["evaluated"]:
            continue
        log(f"evaluating epoch {epoch} ({os.path.basename(pth)})")
        res = evaluate(epoch, pth, idx)
        log(f"epoch {epoch}: val_mel_dist={res.get('val_mel_dist')} (n={res.get('val_n')}) "
            f"test_en={res.get('test_en')} test_ru={res.get('test_ru')} infer_s={res.get('infer_s')}")
        jsonl({"event": "eval", **res})
        state["evaluated"].append(epoch)
        json.dump(state, open(state_path, "w"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
