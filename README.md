# Meeting Audio Notes

[![skills.sh](https://skills.sh/b/bystander563/meeting-audio-notes-skill)](https://skills.sh/bystander563/meeting-audio-notes-skill)

面向中文会议录音的 Agent Skill：本地转写、结构化纪要、时间戳证据和后续细节追问。

它不是功能最多的通用转写 CLI。它解决的是另一个问题：让 Agent 在总结后仍然保留可核查的会议记忆，而不是只输出一段容易丢失细节的摘要。

## 特点

- 使用 `faster-whisper` 在本地转写，支持 NVIDIA CUDA 和 CPU 回退。
- 自动处理 Windows NVIDIA wheel 的 DLL 搜索路径。
- 中文繁体识别结果规范化为简体，同时在 JSON 中保留 `raw_text`。
- 生成持久化会议包：JSON、Markdown、TXT、SRT 和媒体元数据。
- 结构化提取结论、决策、待办、负责人、截止时间、风险和重要数字。
- 使用时间戳证据回答后续问题，并区分原文、推断和未提及。
- 模糊检索可容忍少量 ASR 错字，并返回命中片段的上下文。

## 与通用转写 Skill 的区别

| 能力 | Meeting Audio Notes | 基础 Whisper Skill | 高级 faster-whisper Skill |
|---|---:|---:|---:|
| 本地转写 | 是 | 是 | 是 |
| 中文繁转简并保留原文 | 是 | 通常无 | 通常无 |
| 持久化会议证据包 | 是 | 无 | 部分 |
| 纪要、决策和待办工作流 | 是 | 通常无 | 通常无 |
| 基于上下文的后续追问 | 是 | 通常无 | 关键词搜索 |
| Windows CUDA wheel 自动加载 | 是 | 依赖环境 | 依赖实现 |
| 说话人分离 | 尚未内置 | 无 | 部分实现支持 |
| 批量、URL、丰富字幕格式 | 基础 | 基础 | 更强 |

因此，本项目的优势范围是“中文会议纪要与可追问证据链”，不是所有语音转写场景。

## 安装 Skill

使用 Agent Skills CLI：

```bash
npx skills add bystander563/meeting-audio-notes-skill --skill meeting-audio-notes
```

也可以手动安装。将 `meeting-audio-notes` 目录放入 Agent 的 skills 目录，例如：

```text
~/.codex/skills/meeting-audio-notes
```

在 Windows 上安装运行环境：

```powershell
cd meeting-audio-notes
.\scripts\setup.ps1 -Gpu
```

Linux 或 macOS：

```bash
cd meeting-audio-notes
./scripts/setup.sh
```

## 使用

在支持 Agent Skills 的客户端中调用：

```text
$meeting-audio-notes 转写这个录音，生成中文会议纪要，并保留后续追问所需的时间戳证据。
```

随后可以继续问：

```text
谁负责演示版本？
预算是多少？
供应商风险在哪一段提到？
最终决定和前面的提议有没有冲突？
```

直接运行转写脚本：

```powershell
& "$HOME\.codex\skill-runtimes\meeting-audio-notes\Scripts\python.exe" `
  .\scripts\transcribe_audio.py meeting.m4a `
  --output-dir .\meeting-packages\meeting `
  --model large-v3 `
  --language zh
```

## 输出

```text
meeting-packages/meeting/
├── meeting.json
├── transcript.md
├── transcript.txt
├── transcript.srt
├── audio-info.json
└── minutes.md
```

`meeting.json` 是后续问答的事实来源。摘要不能覆盖或替代它。

## 验证

```powershell
python -m unittest discover -s tests -v
```

项目已在 Windows 11、Python 3.13、RTX 4070 SUPER、CUDA 推理路径上完成端到端测试。

## 限制

- 当前没有内置说话人分离，不能仅凭发言顺序推断真实姓名。
- 默认 Whisper 模型并不保证在所有普通话、方言或行业词汇上优于 FunASR/SenseVoice。
- 首次运行需要下载模型；`large-v3` 占用数 GB 空间。
- 纪要质量取决于 Agent 对转写证据的遵守程度。

## License

MIT
