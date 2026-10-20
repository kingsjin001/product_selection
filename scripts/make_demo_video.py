"""用实际页面截图和验收数据制作 3 分 04 秒字幕讲解视频，不冒充实时录屏。"""

import json
import subprocess
from pathlib import Path

import imageio_ffmpeg
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]


def wrap(text, font, width):
    """按实际像素宽度换行，避免中文字符被挤出画布。"""
    lines, current = [], ""
    for character in text:
        if character == "\n" or font.getlength(current + character) > width:
            lines.append(current)
            current = "" if character == "\n" else character
        else:
            current += character
    if current:
        lines.append(current)
    return lines


def main():
    """从已保存结果读取数字，保留准确的测试范围和限制。"""
    font_path = "C:/Windows/Fonts/msyh.ttc"
    title = ImageFont.truetype(font_path, 36)
    body = ImageFont.truetype(font_path, 25)
    small = ImageFont.truetype(font_path, 18)
    results = json.loads((ROOT / "evals/compare-results.json").read_text(encoding="utf-8"))
    summary = results["summary"]
    scenes = [
        ("选品研究项目演示",
         ["从中文合成资料导入，到可核验的研究报告。",
          "保留 Deep Agents 和 Milvus；API 在本机 Python 环境启动。",
          "字幕讲解版：实际页面截图与验收记录，非实时录屏。"],
         "docs/acceptance/phase-5-workbench.png"),
        ("数据和执行链路",
         ["CSV / JSONL → PostgreSQL 证据与 outbox",
          "Embedding → 规则 / 评论两个 Milvus 集合",
          "FastAPI → Celery / Redis → LangGraph",
          "报告、检查点、调用账本和事件回到 PostgreSQL。"], None),
        ("三种研究方式",
         ["A：把冻结资料交给一次模型调用。",
          "B：固定检索评论与规则，再做一次综合。",
          "C：自主调用工具，按需委派两个专项。",
          "默认使用 B；多规格或冲突问题可选择 C。"], None),
        ("成本由代码计算",
         ["成本输入必须完整，使用 Decimal 避免浮点误差。",
          "演示假设：基准贡献利润 7.25 USD。",
          "保守 5.15 USD；乐观 9.35 USD。",
          "缺成本就显示缺失，不自动填零，也不把贡献利润称作净利润。"], None),
        ("后台任务与失败恢复",
         ["相同幂等键复用任务；发送后崩溃允许重投。",
          "租约、心跳与 epoch 阻止迟到 Worker 覆盖结果。",
          "真实子进程退出后，从 PG 检查点恢复。",
          "刷新页面，按事件序号补发完整时间线。"],
         "docs/acceptance/phase-4-workbench.png"),
        ("报告不可静默改写",
         ["页面、Markdown、JSON 和 Word 使用同一报告源。",
          "追问单独保存，报告 hash 保持不变。",
          "售价从 25 改为 26：新报告利润 8.09，旧报告仍为 7.25。",
          "新任务保留父报告编号和证据快照。"],
         "docs/acceptance/phase-5-workbench.png"),
        ("实测结果与判断边界",
         [f"A / B / C 各完成 {summary['A']['completed']} / 3 个生成对照。",
          "引用可解析 43/43；完整成本情景数值 18/18 一致。",
          "16 条留出检索查询三种方法均命中 16/16。",
          "本组 C 没有委派；尚不能证明子 Agent 或融合检索改善质量。"], None),
        ("面试展示与待核验项",
         ["六期代码保存在独立本地 Git 分支，README 提供运行入口。",
          "原始结果、故障脚本、模型用量和历史失败都保留。",
          "Word 数值与引用已检查；缺少渲染器，打印版式未验收。",
          "人工引用支持率尚未完成，费用需按账户单价补算。"], None),
    ]
    folder = ROOT / "docs/demo"
    folder.mkdir(exist_ok=True)
    (ROOT / "exports").mkdir(exist_ok=True)
    output = folder / "selection-demo.mp4"
    writer = subprocess.Popen([
        imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", "1280x720", "-pix_fmt", "rgb24", "-r", "12", "-i", "-",
        "-an", "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
        "-pix_fmt", "yuv420p", "-movflags", "+faststart", str(output),
    ], stdin=subprocess.PIPE, stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
    fps, seconds = 12, 23
    try:
        for index, (heading, paragraphs, screenshot) in enumerate(scenes):
            canvas = Image.new("RGB", (1280, 720), "#f3f6f5")
            draw = ImageDraw.Draw(canvas)
            draw.text((60, 38), f"选品研究工作台 / {index + 1:02d}", font=small, fill="#286e61")
            draw.text((60, 90), heading, font=title, fill="#24343d")
            width = 735 if screenshot else 1120
            y = 178
            for paragraph in paragraphs:
                for line in wrap(paragraph, body, width):
                    draw.text((60, y), line, font=body, fill="#344b44")
                    y += 40
                y += 20
            if screenshot:
                image = Image.open(ROOT / screenshot).convert("RGB")
                image.thumbnail((360, 590))
                canvas.paste(image, (850 + (360 - image.width) // 2, 60))
            draw.text((60, 650), "字幕讲解版 · 合成资料演示 · 详见 docs/evaluation.md",
                      font=small, fill="#687c74")
            canvas.save(ROOT / "exports" / f"demo-scene-{index + 1}.png")
            for frame in range(fps * seconds):
                image = canvas.copy()
                progress = ImageDraw.Draw(image)
                ratio = (index * fps * seconds + frame + 1) / (len(scenes) * fps * seconds)
                progress.rectangle((0, 708, int(1280 * ratio), 719), fill="#286e61")
                writer.stdin.write(image.tobytes())
        writer.stdin.close()
        error = writer.stderr.read().decode("utf-8", errors="replace")
        if writer.wait() != 0:
            raise RuntimeError(error[-1500:])
    except BaseException:
        writer.kill()
        writer.wait()
        raise
    # 解码一遍确认时长和尺寸，不能仅以文件存在作为成功标准。
    reader = imageio_ffmpeg.read_frames(str(output), pix_fmt="rgb24")
    metadata = next(reader)
    first = next(reader)
    reader.close()
    assert metadata["size"] == (1280, 720)
    assert abs(metadata["duration"] - len(scenes) * seconds) < 1
    preview = ROOT / "exports/demo-first-frame.png"
    preview.parent.mkdir(exist_ok=True)
    Image.frombytes("RGB", (1280, 720), first).save(preview)
    (ROOT / "docs/acceptance/video-results.json").write_text(json.dumps({
        "path": str(output.relative_to(ROOT)), "seconds": metadata["duration"],
        "size": metadata["size"], "audio": False, "kind": "实际截图与验收数据的字幕讲解版",
        "bytes": output.stat().st_size,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"video": str(output), "seconds": metadata["duration"]}))


if __name__ == "__main__":
    main()
