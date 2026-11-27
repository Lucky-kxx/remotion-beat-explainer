"""Measure a local soundtrack and export beat and transient candidates for manual review."""

import argparse
import json
import os
from pathlib import Path
import subprocess

import librosa
import numpy as np
from scipy.signal import butter, find_peaks, sosfiltfilt

RATE = 22050
HOP = 220


def decode(path, ffmpeg, channel):
    audio = subprocess.check_output([
        ffmpeg, "-hide_banner", "-nostdin", "-v", "error", "-i", str(path),
        "-map", "0:a:0", "-ar", str(RATE), "-ac", "2", "-f", "f32le", "-",
    ])
    stereo = np.frombuffer(audio, dtype=np.float32).reshape(-1, 2)
    if channel == "side":
        return (stereo[:, 0] - stereo[:, 1]) * .5
    return stereo.mean(axis=1)


def broadband_onset(audio):
    mel = librosa.feature.melspectrogram(
        y=audio, sr=RATE, n_fft=1024, hop_length=HOP, n_mels=72, fmin=32, fmax=8500
    )
    return librosa.onset.onset_strength(
        S=librosa.power_to_db(mel, ref=np.max), sr=RATE, hop_length=HOP, n_fft=1024, aggregate=np.median
    )


def bass_onset(audio):
    band = butter(2, (35, 170), fs=RATE, btype="bandpass", output="sos")
    bass = sosfiltfilt(band, audio)
    blocks = bass[:len(bass) // HOP * HOP].reshape(-1, HOP)
    rms = np.sqrt(np.mean(blocks ** 2, axis=1))
    scale = np.percentile(rms, 99)
    if scale < max(1e-7, float(np.max(np.abs(audio))) * .001):
        return np.zeros_like(rms)
    smooth = np.convolve(rms / scale, (.25, .5, .25), mode="same")
    return np.maximum(np.diff(smooth, prepend=0), 0)


def measure(path, ffmpeg, channel, fps, bpm):
    audio = decode(path, ffmpeg, channel)
    if len(audio) < RATE*2 or float(np.max(np.abs(audio))) < 1e-5:
        raise ValueError("Choose at least two seconds of audible music. Try mono for near-silent side audio.")
    wide = broadband_onset(audio)
    low = bass_onset(audio)
    tempo, beats = librosa.beat.beat_track(
        onset_envelope=wide, sr=RATE, hop_length=HOP, bpm=bpm, trim=False
    )
    low_hits, strength = find_peaks(
        low, distance=round(.23 * RATE / HOP),
        prominence=max(float(np.percentile(low, 85)), float(np.max(low))*.11, .01),
    )

    def cue(index):
        seconds = int(index) * HOP / RATE
        return {"seconds":round(seconds, 4), "frame":round(seconds*fps)}

    def nearby(index):
        candidates = low_hits[np.abs(low_hits-index) <= round(.10 * RATE / HOP)]
        return cue(candidates[np.argmin(np.abs(candidates-index))]) if len(candidates) else None

    result = {
        "source":path.name,
        "duration_seconds":round(len(audio)/RATE, 4),
        "analysis_channel":channel,
        "fps":fps,
        "estimated_bpm":round(float(np.asarray(tempo).reshape(-1)[0]), 2),
        "bpm_hint":bpm,
        "status":"candidates, not verified downbeats",
        "beats":[dict(cue(i), nearest_low_hit=nearby(i)) for i in beats],
        "low_transients":[dict(cue(i), prominence=round(float(p), 3))
                          for i,p in zip(low_hits, strength["prominences"])],
    }
    return result


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("media", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--ffmpeg", default=os.environ.get("FFMPEG") or "ffmpeg")
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--bpm", type=float, help="Pin an already measured tempo when tracking the beat.")
    parser.add_argument("--channel", choices=("mono","side"), default="mono")
    args = parser.parse_args()
    if args.fps <= 0 or (args.bpm is not None and args.bpm <= 0):
        parser.error("FPS and BPM must be positive.")
    result = measure(args.media,args.ffmpeg,args.channel,args.fps,args.bpm)
    text = json.dumps(result, ensure_ascii=False, indent=2)+"\n"
    if args.output:
        args.output.write_text(text,encoding="utf-8")
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
