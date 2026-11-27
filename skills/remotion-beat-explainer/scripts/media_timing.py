"""Copy locked audio, add a timed poster lead, or verify A/V against an approved master."""

import argparse
from fractions import Fraction
import hashlib
import os
from pathlib import Path
import subprocess
from tempfile import TemporaryDirectory

import av

FPS = 60
RATE = 48000
VIDEO_SCALE = 90000
AAC_FRAME = 1024


def ffmpeg_args(executable):
    return [executable, "-hide_banner", "-nostdin", "-v", "error", "-y"]


def avc_picture_hash(packet):
    data = bytes(packet)
    digest = hashlib.sha256()
    offset = 0
    while offset < len(data):
        size = int.from_bytes(data[offset:offset + 4], "big")
        end = offset + 4 + size
        if size < 1 or end > len(data):
            raise ValueError("Expected MP4 H.264 with four-byte NAL sizes.")
        # The concat demuxer may insert identical codec parameter sets at a keyframe.
        if data[offset + 4] & 31 not in (7, 8):
            digest.update(data[offset:end])
        offset = end
    return digest.digest()


def video_manifest(path, exact):
    with av.open(str(path)) as file:
        track = file.streams.video[0]
        if track.average_rate != FPS:
            raise ValueError(f"{path.name}: expected 60 fps.")
        if exact and track.codec_context.name != "h264":
            raise ValueError("Encoded-picture verification expects H.264.")
        packets = []
        for packet in file.demux(track):
            if packet.size:
                stamp = tuple(value * track.time_base for value in (packet.pts, packet.dts, packet.duration))
                packets.append((*stamp, avc_picture_hash(packet) if exact else None))
        return packets, (track.width, track.height)


def audio_manifest(path, start=None):
    with av.open(str(path)) as file:
        track = file.streams.audio[0]
        if track.time_base != Fraction(1, RATE) or track.codec_context.name != "aac":
            raise ValueError(f"{path.name}: expected 48 kHz AAC.")
        packets = [(p.pts, p.dts, p.duration, hashlib.sha256(bytes(p)).digest())
                   for p in file.demux(track) if p.size and (start is None or p.pts >= start)]
        return packets, track.duration


def verify(before, after, lead_frames=0, exact_video=False, decode_audio=False, ffmpeg="ffmpeg"):
    old_v, original_size = video_manifest(before, exact_video)
    new_v, new_size = video_manifest(after, exact_video)
    delay = Fraction(lead_frames, FPS)
    if original_size != new_size or len(new_v) != len(old_v) + lead_frames:
        raise ValueError("Picture dimensions or number of frames differ.")
    if any(p[0] != Fraction(index, FPS) for index, p in enumerate(new_v)):
        raise ValueError("The output is missing one or more 60 fps timestamps.")
    if new_v[lead_frames:] != [(pts+delay, dts+delay, duration, data) for pts,dts,duration,data in old_v]:
        raise ValueError("Picture timestamps or requested picture payload differ.")
    shift = lead_frames * RATE // FPS
    old_a, old_samples = audio_manifest(before)
    new_a, new_samples = audio_manifest(after, old_a[0][0] + shift)
    if new_samples != old_samples + shift or new_a != [
        (pts+shift,dts+shift,duration,data) for pts,dts,duration,data in old_a
    ]:
        raise ValueError("Approved audio packets, timing or duration differ.")
    if decode_audio:
        cmd = ffmpeg_args(ffmpeg)

        def pcm(path):
            return subprocess.check_output([*cmd,"-i",str(path),"-map","0:a:0","-c:a","pcm_f32le","-f","f32le","-"])

        with av.open(str(before)) as file:
            stride = 4 * file.streams.audio[0].channels
        reference, output = pcm(before), pcm(after)
        if reference[:old_samples*stride] != output[shift*stride:(shift+old_samples)*stride]:
            raise ValueError("Decoded audio does not match sample by sample.")
    print(f"Verified {len(new_v)} video frames, unchanged audio packets and {float(delay):.6f}s lead.")


def copy_audio(approved, revised, output, ffmpeg):
    with TemporaryDirectory(prefix="locked-audio-", dir=output.parent) as temp:
        staged = Path(temp) / "video.mp4"
        subprocess.run([
            *ffmpeg_args(ffmpeg), "-i", str(revised), "-i", str(approved),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy",
            "-video_track_timescale", str(VIDEO_SCALE), "-movie_timescale", str(RATE),
            "-movflags", "+faststart", str(staged),
        ], check=True)
        verify(approved, staged)
        staged.replace(output)


def move_audio(packet, offset, track):
    copy = av.Packet(bytes(packet))
    copy.pts = packet.pts + offset
    copy.dts = packet.dts + offset
    copy.duration = packet.duration
    copy.time_base = packet.time_base
    copy.stream = track
    return copy


def lead_audio(approved, silence, joined, shift):
    with av.open(str(silence)) as base, av.open(str(approved)) as source, av.open(
        str(joined), "w", options={"movie_timescale": str(RATE), "use_editlist": "1"}
    ) as output:
        pre, main = base.streams.audio[0], source.streams.audio[0]
        if main.start_time != 0 or (pre.time_base, pre.codec_context.extradata) != (
            main.time_base, main.codec_context.extradata
        ):
            raise ValueError("The master must use the same stereo 48 kHz AAC LC format as FFmpeg.")
        track = output.add_stream_from_template(main)
        track.time_base = main.time_base
        # Move the silence grid and keep the original AAC priming packet before the cut.
        phase = shift % AAC_FRAME
        for packet in base.demux(pre):
            if not packet.size or packet.pts + phase >= shift - AAC_FRAME:
                break
            output.mux(move_audio(packet, phase, track))
        for packet in source.demux(main):
            if packet.size:
                output.mux(move_audio(packet, shift, track))


def add_cover(approved, poster, output, frames, ffmpeg):
    if frames < 1:
        raise ValueError("Use a positive number of cover frames.")
    with av.open(str(approved)) as original:
        v = original.streams.video[0]
        if (v.codec_context.name, v.codec_context.has_b_frames, v.average_rate, v.start_time) != ("h264", False, FPS, 0):
            raise ValueError("The cover workflow requires a 60 fps H.264 master without B-frames starting at zero.")
        color_matrix, color_tag = {5: ("bt601", "bt470bg"), 6: ("bt601", "smpte170m")}.get(
            v.codec_context.colorspace, ("bt709", "bt709")
        )
        color_range = "full" if v.codec_context.color_range == 2 else "limited"
        width, height = v.width, v.height
    shift = frames * RATE // FPS
    command = ffmpeg_args(ffmpeg)
    with TemporaryDirectory(prefix="cover-lead-", dir=output.parent) as temp:
        work = Path(temp)
        cover, body, silence, clean, joined = (work / part for part in (
            "cover.mp4", "body.mp4", "silence.m4a", "audio.m4a", "video.mp4"
        ))
        subprocess.run([
            *command, "-loop", "1", "-framerate", str(FPS), "-i", str(poster), "-frames:v", str(frames),
            "-vf", f"scale={width}:{height}:out_color_matrix={color_matrix}:out_range={color_range},format=yuv420p",
            "-c:v", "libx264", "-preset", "fast", "-crf", "15", "-bf", "0",
            "-colorspace", color_tag, "-color_range", "pc" if color_range=="full" else "tv",
            "-video_track_timescale", str(VIDEO_SCALE), str(cover),
        ], check=True)
        subprocess.run([
            *command, "-i", str(approved), "-map", "0:v:0", "-c", "copy",
            "-video_track_timescale", str(VIDEO_SCALE), str(body),
        ], check=True)
        subprocess.run([
            *command, "-f", "lavfi", "-i", f"anullsrc=r={RATE}:cl=stereo",
            "-af", f"atrim=end_sample={shift+AAC_FRAME}", "-c:a", "aac", "-b:a", "320k",
            "-movie_timescale", str(RATE), str(silence),
        ], check=True)
        lead_audio(approved, silence, clean, shift)
        playlist = work / "timeline.ffconcat"
        playlist.write_text(
            f"ffconcat version 1.0\nfile cover.mp4\nduration {frames/FPS:.6f}\nfile body.mp4\n", encoding="ascii"
        )
        subprocess.run([
            *command, "-f", "concat", "-i", str(playlist), "-i", str(clean),
            "-map", "0:v:0", "-map", "1:a:0", "-c", "copy", "-video_track_timescale", str(VIDEO_SCALE),
            "-movie_timescale", str(RATE), "-movflags", "+faststart", str(joined),
        ], check=True)
        verify(approved, joined, lead_frames=frames, exact_video=True, decode_audio=True, ffmpeg=ffmpeg)
        joined.replace(output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ffmpeg", default=os.environ.get("FFMPEG") or "ffmpeg")
    actions = parser.add_subparsers(dest="action", required=True)
    check = actions.add_parser("verify")
    check.add_argument("approved", type=Path)
    check.add_argument("revised", type=Path)
    check.add_argument("--lead-frames", type=int, default=0)
    check.add_argument("--exact-video", action="store_true")
    check.add_argument("--decode-audio", action="store_true")
    remux = actions.add_parser("copy-audio")
    remux.add_argument("approved", type=Path)
    remux.add_argument("revised", type=Path)
    remux.add_argument("output", type=Path)
    cover = actions.add_parser("cover-lead")
    cover.add_argument("approved", type=Path)
    cover.add_argument("poster", type=Path)
    cover.add_argument("output", type=Path)
    cover.add_argument("--frames", type=int, required=True)
    args = parser.parse_args()
    if args.action == "verify":
        verify(args.approved, args.revised, args.lead_frames, args.exact_video, args.decode_audio, args.ffmpeg)
    else:
        if args.output.exists():
            parser.error("Choose a new output path.")
        if args.action == "copy-audio":
            copy_audio(args.approved, args.revised, args.output, args.ffmpeg)
        else:
            add_cover(args.approved, args.poster, args.output, args.frames, args.ffmpeg)


if __name__ == "__main__":
    main()
