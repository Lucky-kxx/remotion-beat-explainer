# Remotion Beat Explainer

一个用 Remotion 制作卡点科普视频的 Agent Skill。把配乐测拍、动作音效和逐帧修订放进同一条时间线，让分镜改得动，原有卡点接得住。

## 作品示例

[《你练的不是运动员，是耗材》原版视频](https://github.com/Lucky-kxx/remotion-beat-explainer/releases/download/showcase-v1/mitophagy-explainer.mp4) · 1920×1080 · 60 fps · 中文字幕 · 0.1 秒封面

示例展示了「能量 → 适应 → 训练」的三段主线、跟随画面的图解标注，以及分章节修订时如何保留原有音乐与音效。仓库提供通用创作技能，品牌素材与专用动画模板独立保留。

## 安装与调用

1. 下载或克隆本仓库。
2. 把 [skills/remotion-beat-explainer](skills/remotion-beat-explainer) 整个目录复制到 Agent 能读取的技能目录。Codex 和本地 Cursor 可用项目中的 `.agents/skills/`，Claude Code 可用 `.claude/skills/`。
3. Codex 用 `$remotion-beat-explainer`，支持斜杠命令的 Agent 用 `/remotion-beat-explainer`。也可以直接让 Agent 先读 [SKILL.md](skills/remotion-beat-explainer/SKILL.md)。

> 用这个技能按我提供的主题、资料和配乐制作一个 10 秒横屏样片，先测 BPM 和重拍。后续修订请保留已经通过的音乐卡点。

## 可复用工具

- `analyze_beats.py` 给出 BPM 和低频起音候选，供试听确认。
- `match_music.py` 在纯源中寻找同一乐句，定位一次顺接的候选点。
- `media_timing.py` 复制已通过的音轨，校验音画时间戳，或增加定长封面。

本地分析脚本使用 Python 3.12 和 FFmpeg，依赖见 [requirements.txt](skills/remotion-beat-explainer/scripts/requirements.txt)。渲染用 Node.js 和 Remotion。逐帧操作与完整命令见 [拍点和修订说明](skills/remotion-beat-explainer/references/timing.md)。
