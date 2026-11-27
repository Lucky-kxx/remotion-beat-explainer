# 拍点、合并和无损修订

## 本地工具

需要 Node、npm 和 Remotion 处理画面，FFmpeg 处理音视频。Python 3.12 是已验证的版本。在该技能目录下，用当前项目的 Python 虚拟环境运行 `python -m pip install -r scripts/requirements.txt`。找不到命令时优先查工作区已有的工具；FFmpeg 可从 PATH、`FFMPEG` 环境变量或命令的 `--ffmpeg` 参数指定。新增封面要能调用 FFmpeg 的 `libx264` 和 `aac` 编码器。

校验助手针对 60 fps、48 kHz AAC 的交付格式，其他规格按实际时间基校验。封面无损拼接使用无 B 帧的 H.264 母版，新母版可在编码时用 `-bf 0`。托管 Agent 的文件和工具来自它的执行环境，把自己的主题、参考素材、配乐和批准版传到该环境。

## 拍点表

```bash
python scripts/analyze_beats.py "music.wav" --ffmpeg "path/to/ffmpeg" --fps 60 --output beats.json
```

优先看纯源。参考视频有居中旁白时，可试 `--channel side` 减少其对节拍检测的影响。侧声道近静音时切回 mono。已经量出 BPM 时用 `--bpm` 辅助跟踪。结果包含 BPM、每拍候选秒数、低频起音和最近视频帧。曲子有速度漂移或转段时，分段测并核对小节。按实际听感确认重拍。

至少保留这些字段，可用 JSON 或可读清单：

```json
{"id":"reveal","frame":384,"musicSourceSecond":6.4,"action":"切到发白脸","sfx":"无"}
```

字段中的 `frame` 是全片坐标。用 `round(seconds × fps)` 定帧，48 kHz / 60 fps 下一帧是 800 样本。片头、章节、标题卡各有独立长度时，记录全片位置和曲源位置的偏移。旧分镜修改按全片时间跨章节，不要拿分段播放器的 0:00 对照成片。

## 顺接排查

- 先对照原始曲源和批准版附近的听感、波形或相关性。转段的形状突然换位置可能已经发生在参考视频提取的混轨中。
- 选择跳段之前约半秒到一秒的可辨片段，在用户给的纯音轨中找同一乐句。反复乐句可能匹配多处，要看邻近几秒、音乐拍相和目标结尾。选定接点后，后段沿一段连续源时间播完。相差一两帧的强拍要在短试听里确认。
- 音轨连续优先于把所有转场硬压到拍上。确需改后段时保留已通过的前缀。直接串接各章成片容易让配乐反复从头播，合成时统一使用最终音轨。独立片头和片尾可以只混自己的合成音效。
- 兼顾实现层：锁定原始 AAC 音轨时优先 `-c:a copy`。拼接一个新音频区域时留意 AAC 1024 样本边界与解码器 priming。听两侧短段，并检查采样和时长，而不只看编辑软件的波形缩略图。

```bash
python scripts/match_music.py "approved.mp4" "clean-source.wav" --at 110.4 --window 0.75 --ffmpeg "path/to/ffmpeg"
```

结果按相关性给出纯源的候选秒数、与成片坐标的偏移和用于参考的音量匹配比例。重复乐句用 `--search-from` 与 `--search-to` 缩小范围，换邻近窗口再次核对。这个命令只分析时间，接点需结合原曲试听确认。

## 单点修订与封面脚本

```bash
python scripts/media_timing.py --ffmpeg "path/to/ffmpeg" copy-audio "approved.mp4" "revised-picture.mp4" "review.mp4"
python scripts/media_timing.py --ffmpeg "path/to/ffmpeg" verify "approved.mp4" "review.mp4" --decode-audio
python scripts/media_timing.py --ffmpeg "path/to/ffmpeg" cover-lead "approved-without-lead.mp4" "cover.png" "publish.mp4" --frames 6
```

`copy-audio` 用于分辨率和视频时间线不变的整条画面修订，自动校验输出。局部替换先按原帧插回整条画面再调用。可用帧边界裁剪，后半段流复制从对应 IDR 开始；在窗口之外找不到安全切点时，只多编码到下一关键帧。

添加新封面不要拿已经有片首封面的版本继续叠加。使用无封面头帧的 master 和同画幅 PNG。脚本只编码封面，后续画面保留 H.264 数据；音频帧顺延并检验解码样本逐个相同。扩展验收可以用 `verify --lead-frames 6 --exact-video --decode-audio`，然后检查第 0 帧和第 6 帧。封面独立图仍可用于支持自选封面的发布工具。

## 验收样例

线粒体科普发布版的封面占第 0–5 帧，第 6 帧进入原首镜。0.1 秒是该项目的用户决定。新项目从自己的时间线计算。对同长的字幕和图解修改，应比对原音轨 AAC 包和视频帧时间戳；对于增加首帧封面，应按新增帧数平移再校验，最终抽看边界两侧画面。本技能可用任意同规格的用户素材验证。
