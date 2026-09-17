#!/usr/bin/env python3
"""video-analyzerHypit/analyze.py と同じ「ffmpegで等間隔にフレームを複数抽出し、
タイムスタンプ付き画像としてVision LLMに渡す」方式のPass1(映像解析)を、
video-analyzerV2の出力(H3 T2VA/I2VA/FL2VA/L2VA プロンプト / LTX-2.5プロンプト)に
適用する別モード。

**h3_video2prompt.py本体は一切変更していない**。このファイルは`import h3_video2prompt`
でその関数・定数をそのまま再利用するだけの、完全に別パスの新規スクリプト
(2026-09-17、ユーザー指示: 「video-analyzerHypit/はvideo-analyzerV2/を元にffmpeg式に
変えている。このffmpeg式をvideo-analyzerV2/にoptionで実装できますか？出力は
video-analyzerV2/準拠(H3 Prompt)。コードは別パスにして既存の触らない様に」)。

元(h3_video2prompt.py)との違いはPass1(映像解析)の入力方法だけ:
  元:     フェード除去・トリム・ダウンスケールした下書きmp4を、まるごと1本
          video_url(base64)として1回のメッセージで送る
  本ファイル: 同じ区間からffmpegで等間隔にNフレームをjpg抽出し、各フレームの前に
          「Frame at T.Ts」というタイムスタンプ見出しを添えたimage_url(base64)の
          配列として送る(video-analyzerHypit/analyze.pyと同じ方式)

Pass2(プロンプト改写)・フェード検出・キーフレーム抽出・ASR・音声タグ・CLI引数体系・
出力ファイル構成は元のh3_video2prompt.pyと共通(importして再利用)。

使い方:
  conda activate dev
  python h3_video2prompt_frames.py video.mp4 --mode T2VA
  python h3_video2prompt_frames.py video.mp4 --mode I2VA --duration 8 \
      --frame-fps 1.5 --max-frames 40
"""
from __future__ import annotations

import argparse
import base64
import json
import os
from pathlib import Path

import h3_video2prompt as v2  # 既存コードは一切変更せず、importで再利用するだけ


# ---------------------------------------------------------------------------
# Pass 1 (映像解析): フレーム抽出 + 複数画像でのLLM呼び出し
# ---------------------------------------------------------------------------

def extract_frames(video: Path, out_dir: Path, start: float, length: float,
                    fps: float, max_side: int, max_frames: int) -> list[tuple[Path, float]]:
    """[start, start+length]区間から等間隔にjpgフレームを抽出する
    (video-analyzerHypit/analyze.pyと同じ方式: fpsサンプリング+アスペクト比維持の縮小)。
    戻り値は (フレームパス, 動画内絶対秒数) のリスト。
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    for p in out_dir.glob("frame_*.jpg"):
        p.unlink()
    vf = (f"fps={fps},scale='min({max_side},iw)':'min({max_side},ih)'"
          ":force_original_aspect_ratio=decrease")
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(video), "-t", f"{length:.3f}", "-vf", vf,
            "-frames:v", str(max_frames), "-q:v", "3", str(out_dir / "frame_%04d.jpg")]
    v2.run_cmd(cmd, "フレーム抽出")
    paths = sorted(out_dir.glob("frame_*.jpg"))
    if not paths:
        v2.die("フレーム抽出に失敗しました(0枚)。--frame-fps / --max-frames を見直してください")
    # フレーム間隔は1/fps秒刻み(ffmpeg fpsフィルタの仕様通り)。start起点で絶対秒数を割り当てる。
    return [(p, start + i / fps) for i, p in enumerate(paths)]


def run_analysis_frames(client: "v2.LLMClient", frames: list[tuple[Path, float]],
                         transcript: str | None, tags: list | None = None) -> dict:
    """h3_video2prompt.run_analysis()のPass1相当。動画まるごとの代わりに、
    タイムスタンプ付き複数フレーム画像を渡す。
    """
    text = v2.ANALYSIS_PROMPT
    text += (
        "\n\n[入力形式についての注記]\n"
        f"動画そのものではなく、時系列順に抜き出した{len(frames)}枚のフレーム画像が"
        "添付されています。各画像の直前に「Frame at T.Ts」という見出しでその画像の"
        "動画内絶対秒数が付いています。ショットの境界・time_rangeの判定はこのタイムスタンプを"
        "手がかりにしてください(フレームとフレームの間の内容は補間・推測せず、実際に見えている"
        "フレームの範囲だけを根拠にすること)。"
    )
    if transcript:
        text += (
            "\n\n[文字起こし（対白・歌詞の正解データ）]\n"
            "以下のタイムスタンプ付き文字起こしが提供されています（セリフまたは歌唱歌詞）。\n"
            "dialogue の text / language / time はこの文字起こしに合わせ、confidence は \"high\" にしてください。\n"
            "歌唱の歌詞も dialogue として扱うこと。\n"
            + transcript
        )
    if tags:
        text += (
            "\n\n[音声タグ（実際の音声から算出: PANNs/AudioSet, 信頼度付き）]\n"
            "以下の音楽・楽器・声・環境音のラベルが実際の音声から検出されています。\n"
            "sounds フィールドと、音楽・歌唱に関する記述はこのタグと整合させてください。\n"
            + "\n".join(tags)
        )

    content: list[dict] = [{"type": "text", "text": text}]
    for path, t in frames:
        b64 = base64.b64encode(path.read_bytes()).decode()
        content.append({"type": "text", "text": f"Frame at {t:.2f}s"})
        content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}})

    messages = [{"role": "user", "content": content}]
    raw = client.chat(messages, max_tokens=8192)
    try:
        return v2.extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        v2.log(f"JSON 解析失敗 ({e})。LLM に修正を要求中...")
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user",
             "content": "上記出力は有効なJSONではありません。スキーマに従った有効なJSONのみを再出力してください。コードフェンスは不要です。"},
        ]
        raw2 = client.chat(retry_messages, max_tokens=8192)
        return v2.extract_json(raw2)


# ---------------------------------------------------------------------------
# CLI (h3_video2prompt.parse_args()と同じ体系 + フレーム抽出用オプション)
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="動画 → MiniMax H3 / LTX-2.5 プロンプト変換 (ffmpegフレーム抽出方式)")
    p.add_argument("video", type=Path, help="入力動画 (mp4 等)")
    p.add_argument("--mode", choices=["T2VA", "I2VA", "FL2VA", "L2VA", "LTX"], default="T2VA",
                   help="T2VA/I2VA/FL2VA/L2VA = MiniMax H3, LTX = LTX-2.5 (自然言語プロンプト)")
    p.add_argument("--duration", type=float, default=None,
                   help="対象動画の長さ(秒)。H3: 4-15 / LTX: 6-20(妥当値にスナップ)。既定: 解析対象動画をクランプ")
    p.add_argument("--frame-fps", type=float, default=1.0,
                   help="フレーム抽出のfps (既定 1.0 = 1秒に1枚)")
    p.add_argument("--max-frames", type=int, default=32,
                   help="抽出フレーム数の上限 (既定 32)")
    p.add_argument("--frame-max-side", type=int, default=768,
                   help="各フレームの最大辺px (既定 768)")
    p.add_argument("--max-seconds", type=float, default=None,
                   help="解析対象の動画長上限(秒)。既定=動画全体")
    p.add_argument("--keep-fade", action="store_true",
                   help="先頭/末尾のフェード(黒)検出・トリミングをしない (0.0s〜末尾のまま)")
    p.add_argument("--content-start", type=float, default=None,
                   help="コンテンツ開始時刻(秒)を手動指定 (自動検出を上書き)")
    p.add_argument("--content-end", type=float, default=None,
                   help="コンテンツ終了時刻(秒)を手動指定 (自動検出を上書き)")
    p.add_argument("--no-asr", action="store_true",
                   help="音声の文字起こし(ASR)をしない (既定: 音声があれば自動実行)")
    p.add_argument("--asr-model", default=v2.DEFAULT_ASR_MODEL,
                   help="mlx-whisperモデル (既定: " + v2.DEFAULT_ASR_MODEL + ")")
    p.add_argument("--asr-language", default=None,
                   help="ASRの言語コード (既定: 自動検出。例: ja, en)")
    p.add_argument("--no-audio-tags", action="store_true",
                   help="音声タグ(PANNs)算出をしない (既定: 音声があれば自動実行)")
    p.add_argument("--tags-threshold", type=float, default=v2.DEFAULT_TAG_THRESHOLD,
                   help="タグの信頼度閾値 (既定 0.05)")
    p.add_argument("--tags-max", type=int, default=v2.DEFAULT_TAG_MAX,
                   help="出力タグの最大数 (既定 12)")
    p.add_argument("--transcript", type=Path, default=None,
                   help="対白の文字起こしテキストファイル (あれば対白精度が上がる)")
    p.add_argument("--guide", type=Path, default=None,
                   help="プロンプトガイド md ファイル (既定: H3系=md/minimax-h3-prompt-guide-base.md, "
                        "LTX=md/ltx-prompt-guide-base.md)")
    p.add_argument("--reuse-analysis", nargs="?", const="__default__", default=None,
                   help="LLM Pass1（映像解析）をスキップし既存の analysis.json を再利用する。"
                        "引数なしなら <out>/<動画名>/analysis.json、パスを指定ならそのファイル")
    p.add_argument("--analysis-only", action="store_true",
                   help="LLM Pass1（映像解析）まで実行して終了（プロンプト生成しない）。"
                        "analysis.json / transcript.txt / audio_tags.txt と内容サマリを表示")
    p.add_argument("--out", type=Path, default=Path("out"), help="出力先ディレクトリ (既定 out/)")
    p.add_argument("--api-base", default=None,
                   help="OpenAI API互換エンドポイント (既定: .env の H3_API_BASE / 上記既定値)")
    p.add_argument("--model", default=None,
                   help="モデル名 (既定: .env の H3_MODEL / 上記既定値)")
    p.add_argument("--temperature", type=float, default=0.2)
    return p.parse_args()


def main() -> None:
    v2.load_env_file()
    args = parse_args()
    api_base = args.api_base or os.environ.get("H3_API_BASE") or v2.DEFAULT_API_BASE
    model = args.model or os.environ.get("H3_MODEL") or v2.DEFAULT_MODEL
    api_key = os.environ.get("H3_API_KEY", "") or ""
    v2.log(f"LLM: {model} @ {api_base}" + (" (API key: 設定済み)" if api_key else "")
           + " [フレーム抽出方式]")
    video: Path = args.video
    if not video.is_file():
        v2.die(f"動画が見つかりません: {video}")
    v2.require_tool("ffmpeg")
    v2.require_tool("ffprobe")

    out_dir = args.out / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = out_dir / "keyframes"
    frames_dir = out_dir / "frames"

    # --- ffmpeg 準備 (元のmain()と共通ロジック、v2をそのまま呼ぶ) -----------------
    info = v2.probe_video(video)
    v2.log(f"入力動画: {info['width']}x{info['height']}, {info['duration']:.2f} 秒, {info['fps']:.2f} fps")

    if args.content_start is not None or args.content_end is not None:
        start = args.content_start if args.content_start is not None else 0.0
        end = args.content_end if args.content_end is not None else info["duration"]
        if not (0.0 <= start < end <= info["duration"] + 0.03):
            v2.die(f"--content-start/--content-end が無効です "
                   f"(0 <= start < end <= 動画長 {info['duration']:.2f}s): "
                   f"start={start:.2f}s, end={end:.2f}s")
        v2.log(f"コンテンツ範囲を手動指定: {start:.2f}s〜{end:.2f}s")
    elif args.keep_fade:
        start, end = 0.0, info["duration"]
        v2.log("フェード検出をスキップ (--keep-fade)")
    else:
        start, end, note = v2.detect_content_range(video, info["duration"], info["fps"])
        v2.log(f"コンテンツ範囲: {start:.2f}s〜{end:.2f}s ({note})")

    analysis_start = start
    analysis_len = (end - start) if args.max_seconds is None else min(end - start, args.max_seconds)
    if analysis_len <= 0.2:
        v2.die("解析対象範囲が短すぎます (--max-seconds を見直してください)")

    if args.analysis_only:
        duration = None
        v2.log(f"モード: analysis-only / 解析対象: {analysis_len:.2f} 秒 (プロンプト生成なし)")
    else:
        duration = v2.resolve_duration(args.mode, args.duration, analysis_len)
        v2.log(f"対象動画長: {duration:.2f} 秒 ({args.mode})")

    keyframe_paths = {}
    if not args.analysis_only and args.mode in v2.KEYFRAME_MODES:
        keyframe_paths = v2.extract_keyframes(video, keyframes_dir, info["fps"],
                                              first_at=analysis_start,
                                              last_at=analysis_start + analysis_len)
        v2.log(f"キーフレーム: {keyframe_paths['first']} / {keyframe_paths['last']}")

    guide_text = None
    if not args.analysis_only:
        default_guide = ("ltx-prompt-guide-base.md" if args.mode == "LTX"
                         else "minimax-h3-prompt-guide-base.md")
        guide_path = args.guide or (Path(__file__).parent / "md" / default_guide)
        if not guide_path.is_file():
            v2.die(f"プロンプトガイドが見つかりません: {guide_path} (--guide で指定)")
        guide_text = guide_path.read_text(encoding="utf-8")

    # --- 文字起こし・音声タグ (元のmain()と共通ロジック) -------------------------
    transcript = None
    audio_present = v2.has_audio_stream(video)
    if args.transcript:
        if not args.transcript.is_file():
            v2.die(f"--transcript: ファイルが見つかりません: {args.transcript}")
        transcript = args.transcript.read_text(encoding="utf-8")
        v2.log(f"文字起こしを読み込み: {args.transcript}")
    elif not args.no_asr and audio_present:
        wav = out_dir / "audio_16k.wav"
        v2.extract_audio(video, wav, analysis_start, analysis_len)
        try:
            result = v2.transcribe(wav, args.asr_model, args.asr_language)
        except ImportError:
            v2.log("警告: mlx_whisper がimportできないためASRをスキップ "
                   "(conda activate dev で実行 / --no-asr)")
        except Exception as e:
            v2.log(f"警告: ASRに失敗したためスキップ ({e})。--no-asr で省略できます")
        else:
            transcript = v2.format_transcript(result)
            if transcript:
                (out_dir / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")
                v2.log(f"文字起こしを保存: {out_dir / 'transcript.txt'}")
            else:
                v2.log("ASR: 発話(セリフ/歌詞)が検出されませんでした")
                transcript = None
    elif args.no_asr:
        v2.log("ASRをスキップ (--no-asr)")

    tag_lines: list[str] = []
    if args.no_audio_tags:
        v2.log("音声タグをスキップ (--no-audio-tags)")
    elif audio_present:
        wav32k = out_dir / "audio_32k.wav"
        v2.extract_audio(video, wav32k, analysis_start, analysis_len, sample_rate=32000)
        try:
            tags = v2.audio_tags(wav32k, args.tags_threshold, args.tags_max)
        except Exception as e:
            v2.log(f"警告: 音声タグの算出に失敗したためスキップ ({e})。--no-audio-tags で省略できます")
        else:
            if tags:
                tag_lines = [f"{conf:.3f}  {label}" for label, conf in tags]
                (out_dir / "audio_tags.txt").write_text("\n".join(tag_lines) + "\n",
                                                        encoding="utf-8")
                v2.log(f"音声タグを保存: {out_dir / 'audio_tags.txt'} "
                       f"(top3: {', '.join(l.split('  ')[1] for l in tag_lines[:3])})")
            else:
                v2.log("音声タグ: 閾値を超えるタグがありません")

    client = v2.LLMClient(api_base, model, args.temperature, api_key=api_key)
    analysis = None
    if args.reuse_analysis is not None:
        reuse_path = (out_dir / "analysis.json" if args.reuse_analysis == "__default__"
                      else Path(args.reuse_analysis))
        if not reuse_path.is_file():
            v2.die(f"--reuse-analysis: {reuse_path} が見つかりません "
                   "(まず --reuse-analysis なしで1回実行してください)")
        try:
            analysis = json.loads(reuse_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            v2.die(f"--reuse-analysis: {reuse_path} が有効なJSONではありません: {e}")
        if not isinstance(analysis, dict) or "shots" not in analysis:
            v2.die(f"--reuse-analysis: {reuse_path} が analysis.json のスキーマに見えません "
                   "(shots キーを含む JSONオブジェクトが必要です)")
        v2.log(f"既存の解析を再利用: {reuse_path} (Pass 1 スキップ)")
    else:
        # --- ここだけ元のmain()と異なる: 動画をvideo_urlで丸ごと送る代わりに、
        # フレームを複数枚image_urlとして送る ---
        frames = extract_frames(video, frames_dir, analysis_start, analysis_len,
                                fps=args.frame_fps, max_side=args.frame_max_side,
                                max_frames=args.max_frames)
        v2.log(f"フレーム抽出: {len(frames)}枚 ({frames_dir})")
        analysis = run_analysis_frames(client, frames, transcript, tags=tag_lines)

    (out_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    v2.log("解析 JSON を保存: " + str(out_dir / "analysis.json"))

    if args.analysis_only:
        v2.print_analysis_summary(analysis, info, tag_lines)
        v2.log(f"完了 (analysis-only)。出力先: {out_dir}/")
        v2.log(f"  - analysis.json       映像解析の構造化 JSON")
        v2.log(f"  - frames/             解析に渡したフレーム画像")
        if transcript:
            v2.log(f"  - transcript.txt        ASR文字起こし (対白・歌詞)")
        if tag_lines:
            v2.log(f"  - audio_tags.txt        音声タグ (音楽・楽器・環境音)")
        return

    # --- LLM Pass 2: 改写 (元のmain()と共通ロジック、v2をそのまま呼ぶ) -----------
    prompt_text = v2.run_rewrite(client, args.mode, duration, analysis, guide_text,
                                 transcript, tags=tag_lines)
    alignment = v2.build_alignment_line(args.mode, duration)
    if alignment:
        prompt_text = alignment + "\n\n" + prompt_text
        v2.log(f"アライメント行を付与: {alignment[:60]}...")
    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt_text + "\n", encoding="utf-8")

    print("\n" + "=" * 60)
    print(f"モード: {args.mode} / 対象動画長: {duration:.2f} 秒 [フレーム抽出方式]")
    print("=" * 60)
    print(prompt_text)
    print("=" * 60)
    v2.log(f"完了。出力先: {out_dir}/")
    v2.log(f"  - prompt.txt          最終プロンプト")
    v2.log(f"  - analysis.json       映像解析の中間 JSON (手直し用)")
    if keyframe_paths:
        v2.log(f"  - keyframes/first.jpg, keyframes/last.jpg  (元解像度 / H3 API 用)")
    v2.log(f"  - frames/             解析に渡したフレーム画像 ({args.frame_fps} fps)")
    if transcript:
        v2.log(f"  - transcript.txt        ASR文字起こし (対白・歌詞)")
    if tag_lines:
        v2.log(f"  - audio_tags.txt        音声タグ (音楽・環境音)")


if __name__ == "__main__":
    main()
