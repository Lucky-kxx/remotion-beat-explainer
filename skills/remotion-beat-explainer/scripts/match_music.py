"""Find places in a clean soundtrack that match a known passage in a cut."""

import argparse
import json
import os
from pathlib import Path
import subprocess

import numpy as np
from scipy.signal import correlate, find_peaks

RATE = 8000


def wave(path, ffmpeg):
    decoded = subprocess.check_output([
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-ac", "1", "-ar", str(RATE), "-f", "f32le", "-",
    ])
    return np.frombuffer(decoded, dtype=np.float32)


def measure(edited, clean, at, duration, search_from, search_to):
    anchor, count = round(at * RATE), round(duration * RATE)
    known = edited[anchor:anchor + count].astype(np.float64)
    start = round(search_from * RATE)
    stop = min(len(clean), round(search_to * RATE) + count) if search_to is not None else len(clean)
    source = clean[start:stop].astype(np.float64)
    if len(known) != count or len(source) < count:
        raise ValueError("The comparison and search windows must contain the whole passage.")
    known -= known.mean()
    norm = np.linalg.norm(known)
    if norm < 1e-5:
        raise ValueError("Choose an audible passage just before the unwanted splice.")
    total = np.concatenate(([0.], np.cumsum(source)))
    energy = np.concatenate(([0.], np.cumsum(source ** 2)))
    partial = total[count:] - total[:-count]
    power = energy[count:] - energy[:-count] - partial ** 2 / count
    dots = correlate(source, known, mode="valid", method="fft")
    score = dots / (norm * np.sqrt(np.maximum(1e-12, power)))
    score[power < 1e-10] = 0
    peaks = find_peaks(score, distance=round(.30 * RATE))[0]
    indices = set(peaks)
    indices.add(int(np.argmax(score)))
    best = sorted(indices, key=lambda i: score[i], reverse=True)[:5]
    return [{
        "clean_seconds": round((start+i)/RATE, 5),
        "offset_seconds": round((start+i-anchor)/RATE, 5),
        "similarity": round(float(np.clip(score[i], -1, 1)), 4),
        "gain_to_match_edit": round(float(dots[i]/power[i]), 3) if power[i] > 1e-10 else None,
    } for i in best]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("edited", type=Path)
    parser.add_argument("clean", type=Path)
    parser.add_argument("--at", type=float, required=True, help="Start second of a known passage before the problem.")
    parser.add_argument("--window", type=float, default=.75)
    parser.add_argument("--search-from", type=float, default=0)
    parser.add_argument("--search-to", type=float)
    parser.add_argument("--ffmpeg", default=os.environ.get("FFMPEG") or "ffmpeg")
    args = parser.parse_args()
    if args.at<0 or args.window<.2 or args.search_from<0 or (
        args.search_to is not None and args.search_to<args.search_from
    ):
        parser.error("Use nonnegative times and a comparison window of at least 0.2 seconds.")
    result = measure(
        wave(args.edited,args.ffmpeg), wave(args.clean,args.ffmpeg), args.at,
        args.window, args.search_from, args.search_to,
    )
    print(json.dumps({
        "edited_passage_seconds": args.at,
        "duration_seconds": args.window,
        "candidates": result,
    }, indent=2))


if __name__ == "__main__":
    main()
