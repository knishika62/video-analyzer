#!/usr/bin/env python3
"""
h3_video2prompt.py — 動画 → MiniMax H3 プロンプト変換ツール

OpenAI API互換のビジョンLLM (既定: http://192.168.11.100:8888/v1,
モデル qwen38-27b-dflash2) を用いて動画を解析し、MiniMax H3 の
T2VA / I2VA / FL2VA / L2VA プロンプト（英語・ガイド準拠）を生成する。

流れ:
  1. ffprobe で動画情報を取得
  2. ffmpeg で解析用動画を下書き (max side 480px 既定)
  3. ffmpeg でキーフレーム抽出 (元解像度 / I2VA・FL2VA・L2VA用)
  4. LLM Pass1: 下書き動画 → 構造化解析 JSON
  5. LLM Pass2: JSON + H3ガイド → 3コアフィールド（英語）
     キーフレームモードの画像アライメント指示行は LLM に書かせず、
     ガイドの固定テンプレートに従ってコード側で正確に付与する
  6. 出力: prompt.txt / analysis.json / keyframes/ / analysis_downscaled.mp4

依存: Python 3.10+, requests, ffmpeg/ffprobe (PATHに存在すること)
"""

import argparse
import base64
import json
import os
import re
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path

import requests

# .env (cwd またはスクリプト同ディレクトリ) で変更可能な環境変数:
#   H3_API_BASE — OpenAI API互換エンドポイント (既定: http://192.168.11.100:8888/v1)
#   H3_MODEL    — モデル名 (既定: qwen38-27b-dflash2)
#   H3_API_KEY  — APIキー (既定: 設定なし、不要環境では空欄)
# 優先順位: CLI引数 > 環境変数/.env > 以下の既定値
DEFAULT_API_BASE = "http://192.168.11.100:8888/v1"
DEFAULT_MODEL = "qwen38-27b-dflash2"
KEYFRAME_MODES = ("I2VA", "FL2VA", "L2VA")
H3_MIN_DURATION, H3_MAX_DURATION = 4, 15
LTX_MIN_DURATION, LTX_MAX_DURATION = 6, 20
LTX_VALID_DURATIONS = (6, 8, 10, 12, 14, 16, 18, 20)


def load_env_file() -> None:
    """.env を読み込む (python-dotenv がある場合のみ / 既存の環境変数は上書きしない)"""
    try:
        from dotenv import load_dotenv
    except ImportError:
        return
    for candidate in (Path.cwd() / ".env", Path(__file__).resolve().parent / ".env"):
        if candidate.is_file():
            load_dotenv(candidate)


# ---------------------------------------------------------------------------
# ユーティリティ
# ---------------------------------------------------------------------------

def log(msg: str) -> None:
    print(f"[h3] {msg}", flush=True)


def die(msg: str) -> None:
    print(f"[h3][ERROR] {msg}", file=sys.stderr, flush=True)
    sys.exit(1)


def require_tool(name: str) -> str:
    path = shutil.which(name)
    if not path:
        die(f"{name} が PATH に見つかりません。インストールしてください。")
    return path


def run_cmd(cmd: list, desc: str) -> subprocess.CompletedProcess:
    log(f"実行: {' '.join(cmd)}")
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        die(f"{desc} 失敗 (returncode={proc.returncode}):\n{proc.stderr.strip()[-2000:]}")
    return proc


# ---------------------------------------------------------------------------
# ffmpeg / ffprobe
# ---------------------------------------------------------------------------

def probe_video(video: Path) -> dict:
    """動画の長さ(秒)/幅/高さ/fpsを取得"""
    out = run_cmd(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=width,height,avg_frame_rate",
         "-show_entries", "format=duration",
         "-of", "json", str(video)],
        "ffprobe",
    )
    data = json.loads(out.stdout)
    stream = data.get("streams", [{}])[0]
    duration = float(data.get("format", {}).get("duration", 0.0))
    if not stream.get("width") or not stream.get("height") or duration <= 0:
        die("動画ストリームまたは再生時間が取得できませんでした。")
    num, _, den = (stream.get("avg_frame_rate") or "30/1").partition("/")
    try:
        fps = float(num) / float(den)
    except (ValueError, ZeroDivisionError):
        fps = 0.0  # avg_frame_rate=0/0 等（VFRなど）
    if not (1.0 <= fps <= 240.0):
        fps = 30.0
    return {"duration": duration, "width": int(stream["width"]),
            "height": int(stream["height"]), "fps": fps}


# --- フェードイン/アウト（先頭・末尾の黒）検出 -------------------------------
# キーフレームを単純に 0.0s / 末尾から切ると、フェード付き動画では黒（Y=16）の
# フレームが抜けてしまう。そこで:
#   1) signalstats の YAVG（フレーム平均輝度）を低解像度で全フレーム計測
#   2) blackdetect で「全ピクセルが暗い」区間（黒 or フェードの暗い部分）を検出
#   3) 先頭の黒区間がある場合、YAVG が動画中央値の 90% 以上に達した最初のフレーム
#      を「映像の実際の開始」、末尾側は対称的に「実際の終了」として採用する

def scan_yavg(video: Path) -> list:
    """全フレームの平均輝度 (Y, リミテッドレンジ: 黒=16 白=235) を取得"""
    out = run_cmd(
        ["ffmpeg", "-i", str(video),
         "-vf", "scale=192:108,signalstats,metadata=print:key=lavfi.signalstats.YAVG",
         "-f", "null", "-"],
        "YAVGスキャン",
    )
    return [float(v) for v in re.findall(r"YAVG=([0-9.]+)", out.stderr)]


def black_intervals(video: Path, pix_th: float = 0.20, min_dur: float = 0.1) -> list:
    """全ピクセルが pix_th*255 以下の（ほぼ黒）区間 [(start, end), ...] を取得"""
    out = run_cmd(
        ["ffmpeg", "-i", str(video),
         "-vf", f"blackdetect=pix_th={pix_th}:black_min_duration={min_dur}",
         "-f", "null", "-"],
        "黒区間検出",
    )
    return [(float(a), float(b))
            for a, b in re.findall(r"black_start:([0-9.]+) black_end:([0-9.]+)", out.stderr)]


def detect_content_range(video: Path, duration: float, fps: float) -> tuple:
    """実際の映像コンテンツの範囲 (start, end) を返す。

    フェードイン/アウトが検出されなければ (0.0, duration)。
    3rd 要素は検出結果の説明。
    """
    yavg = scan_yavg(video)
    if len(yavg) < max(10, int(fps * 0.5)):
        return (0.0, duration, "動画が短い/フレーム不足のため検出をスキップ")

    med = statistics.median(yavg)
    if med < 24.0:
        log("動画全体がほぼ黒です — 検出をスキップ（元範囲を使用）")
        return (0.0, duration, "all-black")

    target = 0.9 * med
    intervals = black_intervals(video)
    # blackdetect の black_end は最後の黒フレームの pts なので、
    # 区間の実端は 1 フレーム分長い。末尾判定はそれに合わせて許容する。
    lead = next((iv for iv in intervals if iv[0] <= 0.05), None)
    trail = next((iv for iv in intervals if iv[1] + 1.0 / fps >= duration - 0.03), None)
    if not lead and not trail:
        return (0.0, duration, "黒区間なし（フェードなしと判断）")

    start, end = 0.0, duration
    notes = []
    max_advance = 3.0  # 黒区間の端から最長3秒まで先/後退を許容

    if lead:
        i0 = max(0, int(lead[0] * fps))
        for j in range(i0, len(yavg)):
            if yavg[j] >= target:
                start = min(j / fps, lead[1] + max_advance)
                notes.append(f"先頭フェード/黒 {lead[0]:.2f}s→{lead[1]:.2f}s "
                             f"=> コンテンツ開始 {start:.2f}s")
                break
        else:
            log("警告: 先頭黒区間以降に十分な輝度のフレームが見つからず、先頭は 0.0s のまま")
    if trail:
        i0 = min(len(yavg) - 1, int(trail[0] * fps))
        for j in range(i0, -1, -1):
            if yavg[j] >= target:
                end = max((j + 1) / fps, trail[0] - max_advance)
                notes.append(f"末尾フェード/黒 {trail[0]:.2f}s→{trail[1]:.2f}s "
                             f"=> コンテンツ終了 {end:.2f}s")
                break
        else:
            log("警告: 末尾黒区間以前に十分な輝度のフレームが見つからず、末尾は最後まで使用")

    if end - start < 0.5 * duration:
        log("警告: 検出されたコンテンツ範囲が動画の50%未満のため、元範囲に戻します")
        return (0.0, duration, "範囲が短すぎたためフォールバック")
    return (start, end, "; ".join(notes))


def make_analysis_video(src: Path, dst: Path, max_side: int,
                        start: float = 0.0, length: float | None = None,
                        info: dict | None = None) -> None:
    """[start, start+length] の範囲を max_side 以下に下書きした解析用 mp4 を作成 (音声なし / h264)

    info を渡さなければ内部で ffprobe を再実行する。"""
    info = info or probe_video(src)
    w, h = info["width"], info["height"]
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if length:
        cmd += ["-t", f"{float(length):.3f}"]
    cmd += ["-an"]

    if max(w, h) > max_side:
        if w >= h:
            scale = f"scale={max_side}:-2"
        else:
            scale = f"scale=-2:{max_side}"
        cmd += ["-vf", scale]
        log(f"下書き: {w}x{h} -> max side {max_side}")
    else:
        log(f"元解像度 {w}x{h} が max side {max_side} 以下のためスケーリングなし")

    cmd += ["-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", str(dst)]
    run_cmd(cmd, "解析用動画の作成")


def extract_keyframes(src: Path, out_dir: Path, fps: float,
                      first_at: float = 0.0, last_at: float | None = None) -> dict:
    """指定時刻のフレームを元解像度で jpg 抽出（last_at=None なら動画末尾）"""
    out_dir.mkdir(parents=True, exist_ok=True)
    first = out_dir / "first.jpg"
    last = out_dir / "last.jpg"
    run_cmd(["ffmpeg", "-y", "-v", "error", "-ss", f"{first_at:.3f}", "-i", str(src),
             "-frames:v", "1", "-q:v", "2", str(first)], "先頭フレーム抽出")
    if last_at is None:
        last_cmd = ["ffmpeg", "-y", "-v", "error", "-sseof", "-0.15", "-i", str(src),
                    "-frames:v", "1", "-q:v", "2", str(last)]
    else:
        # 最後のコンテンツフレームの先頭位置でシーク（そのフレームを抽出）
        seek = max(0.0, last_at - 1.0 / fps)
        last_cmd = ["ffmpeg", "-y", "-v", "error", "-ss", f"{seek:.3f}", "-i", str(src),
                    "-frames:v", "1", "-q:v", "2", str(last)]
    run_cmd(last_cmd, "末尾フレーム抽出")
    return {"first": str(first), "last": str(last)}


# ---------------------------------------------------------------------------
# LLM
# ---------------------------------------------------------------------------

class LLMClient:
    def __init__(self, api_base: str, model: str, temperature: float = 0.2, api_key: str = ""):
        self.url = api_base.rstrip("/") + "/chat/completions"
        self.model = model
        self.temperature = temperature
        self.api_key = api_key

    def _headers(self) -> dict:
        headers = {"Content-Type": "application/json"}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"
        return headers

    def chat(self, messages: list, max_tokens: int, retries: int = 2,
             timeout: tuple = (15, 900)) -> str:
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature,
            "max_tokens": max_tokens,
        }
        last_err = None
        for attempt in range(1, retries + 1):
            try:
                log(f"LLM 呼び出し中... (試行 {attempt}/{retries})")
                t0 = time.time()
                resp = requests.post(self.url, json=payload, headers=self._headers(), timeout=timeout)
                # 4xx（429を除く）= 認証/パラメータ等で再試行しても同じく失敗する想定 → 即失敗
                if 400 <= resp.status_code < 500 and resp.status_code != 429:
                    die(f"LLM エンドポイントが HTTP {resp.status_code} を返しました (リトライなし):\n{resp.text[:500]}")
                if 500 <= resp.status_code < 600:
                    raise requests.HTTPError(f"HTTP {resp.status_code}: {resp.text[:500]}")
                resp.raise_for_status()
                data = resp.json()
                content = data["choices"][0]["message"]["content"]
                log(f"LLM 応答受信: {time.time() - t0:.1f} 秒, {len(content)} 文字")
                return content
            except (requests.RequestException, KeyError, json.JSONDecodeError) as e:
                last_err = e
                log(f"応答エラー: {e}")
                if attempt < retries:
                    time.sleep(3)
        die(f"LLM 呼び出しが {retries} 回失敗しました: {last_err}")


def extract_json(text: str) -> dict:
    """LLM応答からJSONオブジェクトを抽出する (コードフェンス対応)"""
    text = text.strip()
    m = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if m:
        text = m.group(1)
    else:
        start, end = text.find("{"), text.rfind("}")
        if start == -1 or end <= start:
            raise ValueError("JSON ブロックが見つかりません")
        text = text[start:end + 1]
    return json.loads(text)


# ---------------------------------------------------------------------------
# Pass 1: 映像解析
# ---------------------------------------------------------------------------

ANALYSIS_JSON_SCHEMA = """{
  "style": "live-action, cinematic, ...",
  "shots": [
    {"index": 1, "time_range": "0.0s-3.5s",
     "composition": "shot size / framing / subject position",
     "subjects": "appearance, clothing, objects, spatial relations",
     "actions": "what happens, in order",
     "camera_motion": "e.g. push in with small amplitude at slow speed; 'static shot' if still",
     "environment": "scene, lighting, props"}
  ],
  "speakers": [{"id": "S1", "description": "age, gender, on/off-screen, pitch, timbre, rate, accent"}],
  "dialogue": [{"time": "~2.0s", "speaker": "S1", "text": "...", "language": "English",
                 "confidence": "low"}],
  "on_screen_text": ["exact visible text, verbatim"],
  "sounds": "ambient / physical / non-verbal human sounds heard or implied"
}"""

ANALYSIS_PROMPT = """あなたは動画生成プロンプト向けの映像解析専門家です。
添付の動画を細かく観察し、後段のプロンプト生成のためだけに使える構造化JSONを出力してください。

ルール:
- JSONの値はすべて英語で記述すること（on_screen_text と dialogue.text は画面に表示された/聞こえた原文の言語のまま保持）
- ショットは再生順で分割し、カットがあるごとに index を振る。time_range は動画内の絶対秒数
- camera_motion は「運動タイプ + (意味がある場合)振幅 + 速度」で記述。静止なら "static shot"
- 話者は S1, S2... で安定IDを付ける。画面に映っていないナレーションも含める
- 音声は推測できないため、dialogue.text は映像（口の動き・字幕・状況）からの最善推定とし、
  confidence を "low" / "medium" でマークする。字幕が読める場合は字幕を優先し confidence "medium"
- 見切れている・不明瞭な対白は推測せず省略するか [unclear] とする
- 出力はコードフェンスなしのJSON本体のみ

JSONスキーマ（これに完全に従うこと）:
""" + ANALYSIS_JSON_SCHEMA


# ---------------------------------------------------------------------------
# ASR (mlx-whisper) — 音声から対白・歌詞の文字起こし
# ---------------------------------------------------------------------------

DEFAULT_ASR_MODEL = "mlx-community/whisper-large-v3-turbo"


def has_audio_stream(video: Path) -> bool:
    """音声ストリームの有無"""
    out = run_cmd(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv", str(video)],
        "ffprobe(音声)",
    )
    return bool(out.stdout.strip())


def extract_audio(src: Path, dst: Path, start: float, length: float,
                  sample_rate: int = 16000) -> None:
    """[start, start+length] の音声を指定レート・モノ WAV に抽出"""
    dst.parent.mkdir(parents=True, exist_ok=True)
    cmd = ["ffmpeg", "-y", "-v", "error"]
    if start > 0:
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src), "-t", f"{float(length):.3f}",
            "-vn", "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(dst)]
    run_cmd(cmd, "音声抽出")


def transcribe(wav: Path, model: str, language: str | None) -> dict:
    """mlx-whisper で文字起こし。segments と全文を返す"""
    import mlx_whisper
    log(f"ASR実行中: {model} (初回はモデルダウンロードに時間がかかります)")
    t0 = time.time()
    result = mlx_whisper.transcribe(str(wav), path_or_hf_repo=model,
                                    language=language)
    log(f"ASR完了: {time.time() - t0:.1f} 秒")
    return result


def format_transcript(result: dict) -> str:
    """セグメントをタイムスタンプ付きテキストに変換 ([start-end] 形式)"""
    def ts(sec: float) -> str:
        m, s = divmod(float(sec), 60)
        return f"{int(m):02d}:{s:06.3f}"

    lines = []
    for seg in result.get("segments", []):
        text = seg.get("text", "").strip()
        if text:
            lines.append(f"[{ts(seg.get('start', 0))}-{ts(seg.get('end', 0))}] {text}")
    return "\n".join(lines)


# --- 音声タグ (PANNs / AudioSet) — 音楽・楽器・環境音のラベル ----------------

PANNS_WEIGHTS = Path(__file__).resolve().parent / ".panns" / "Cnn14_mAP=0.431.pth"
PANNS_WEIGHTS_URL = ("https://huggingface.co/thelou1s/panns-inference/"
                     "resolve/main/Cnn14_mAP%3D0.431.pth")
DEFAULT_TAG_THRESHOLD = 0.05
DEFAULT_TAG_MAX = 12


def _ensure_panns_weights() -> Path:
    if PANNS_WEIGHTS.is_file() and PANNS_WEIGHTS.stat().st_size > 3e8:
        return PANNS_WEIGHTS
    PANNS_WEIGHTS.parent.mkdir(parents=True, exist_ok=True)
    # 部分DLをそのまま確定ファイルにしないため、.part に落としてサイズ検証後に原子移動する
    part = PANNS_WEIGHTS.parent / (PANNS_WEIGHTS.name + ".part")
    log(f"PANNs重みのダウンロード中 (約315MB): {PANNS_WEIGHTS}")
    import urllib.request
    urllib.request.urlretrieve(PANNS_WEIGHTS_URL, part)
    size = part.stat().st_size
    if size <= 3e8:
        part.unlink(missing_ok=True)
        raise RuntimeError(f"PANNs重みのダウンロードが不完全 ({size} bytes, 300MB超を期待)")
    part.replace(PANNS_WEIGHTS)
    return PANNS_WEIGHTS


def _panns_tag_worker(wav_32k: str, threshold: float, max_tags: int) -> None:
    """サブプロセス側の処理: PANNsタグを計算しstdoutにJSONで出力する"""
    import tempfile
    os.environ.setdefault("MPLCONFIGDIR", tempfile.gettempdir())
    os.environ.setdefault("NUMBA_CACHE_DIR", tempfile.gettempdir())
    import wave
    import numpy as np
    import torch
    from panns_inference.models import Cnn14
    from panns_inference.config import labels, classes_num

    weights = _ensure_panns_weights()
    model = Cnn14(sample_rate=32000, window_size=1024, hop_size=320,
                  mel_bins=64, fmin=50, fmax=14000, classes_num=classes_num)
    ckpt = torch.load(str(weights), map_location="cpu")
    model.load_state_dict(ckpt["model"])
    model.eval()

    with wave.open(wav_32k, "rb") as w:
        data = np.frombuffer(w.readframes(w.getnframes()),
                             dtype=np.int16).astype(np.float32) / 32768.0
    audio = torch.from_numpy(data).unsqueeze(0)
    with torch.no_grad():
        out = model(audio, None)["clipwise_output"]

    probs = out.squeeze(0).numpy()
    order = np.argsort(probs)[::-1]
    tags = [[labels[i], float(probs[i])] for i in order if probs[i] >= threshold][:max_tags]
    print(json.dumps(tags))


def audio_tags(wav_32k: Path, threshold: float = DEFAULT_TAG_THRESHOLD,
               max_tags: int = DEFAULT_TAG_MAX) -> list:
    """PANNs Cnn14 (AudioSet 527クラス) で音声タグを取得 [(label, confidence), ...]

    同一プロセスでASR(mlx_whisper)の後に走るとnumbaキャッシュが壊れる
    ("no locator available")ため、サブプロセスで隔離して実行する。
    """
    log("音声タグ算出中 (PANNs, サブプロセス)...")
    t0 = time.time()
    script_dir = str(Path(__file__).resolve().parent)
    code = (
        f"import sys; sys.path.insert(0, {script_dir!r}); "
        f"import h3_video2prompt as _m; "
        f"_m._panns_tag_worker({str(wav_32k)!r}, {float(threshold)!r}, {int(max_tags)})"
    )
    proc = subprocess.run([sys.executable, "-c", code],
                          capture_output=True, text=True, timeout=600)
    if proc.returncode != 0:
        raise RuntimeError(proc.stderr.strip()[-800:] or "unknown error")
    out_lines = [l for l in proc.stdout.splitlines() if l.strip()]
    if not out_lines:
        raise RuntimeError("サブプロセスから出力がありませんでした")
    tags = [tuple(t) for t in json.loads(out_lines[-1])]
    log(f"音声タグ算出: {time.time() - t0:.1f} 秒")
    return tags


def run_analysis(client: LLMClient, video_b64: str, transcript: str | None,
                 tags: list | None = None) -> dict:
    """LLM Pass 1 (映像解析)。tags はフォーマット済み行リスト ("conf  label" 文字列の list)"""
    text = ANALYSIS_PROMPT
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
    messages = [{
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            {"type": "video_url",
             "video_url": {"url": f"data:video/mp4;base64,{video_b64}"}},
        ],
    }]
    raw = client.chat(messages, max_tokens=8192)
    try:
        return extract_json(raw)
    except (ValueError, json.JSONDecodeError) as e:
        # 1回だけJSON修正を要求して再試行
        log(f"JSON 解析失敗 ({e})。LLM に修正を要求中...")
        retry_messages = messages + [
            {"role": "assistant", "content": raw},
            {"role": "user",
             "content": "上記出力は有効なJSONではありません。スキーマに従った有効なJSONのみを再出力してください。コードフェンスは不要です。"},
        ]
        raw2 = client.chat(retry_messages, max_tokens=8192)
        return extract_json(raw2)


# ---------------------------------------------------------------------------
# Pass 2: H3 プロンプト改写
# ---------------------------------------------------------------------------

def build_alignment_line(mode: str, duration: float) -> str | None:
    """モード別の画像アライメント指示行（ガイドの固定テンプレート）をコード側で生成する"""
    dur = f"{duration:.2f}"
    if mode == "I2VA":
        return ("For the target video, at 0.00 seconds into the target video, "
                "<Picture 1> (from [Shot 1]) is fully referenced.")
    if mode == "FL2VA":
        return (f"How the reference pictures align with the target video — "
                f"Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; "
                f"Picture 2 (from Shot 1) aligns with the {dur}-second mark of the target video.")
    if mode == "L2VA":
        return (f"How the reference pictures align with the target video — "
                f"<Picture 1> (from [Shot 1]) aligns with the {dur}-second mark of the target video.")
    return None  # T2VA


def build_rewrite_prompt(mode: str, duration: float, analysis: dict,
                         guide_text: str, transcript: str | None,
                         tags: list | None = None) -> str:
    dur_s = f"{duration:.2f}"
    shots = analysis.get("shots", [])
    single_shot = len(shots) <= 1
    is_ltx = (mode == "LTX")

    if is_ltx:
        mode_rule = (
            "Mode: LTX (LTX-2.5 text-to-video). Output ONE natural-language prompt in English, following the LTX guide.\n"
            "There are NO structured fields (no integrated_multimodal_description / overall_soundscape / non_diegetic_music) "
            "and NO image-alignment line — output ONLY the prompt body.\n"
            "Structure: a single flowing paragraph for a continuous take, or screenplay-style (scene header, character cues, "
            "quoted dialogue) for dialogue / multi-beat / multi-shot content. Aim for roughly 4-8 descriptive sentences.\n"
            "Cover the guide's key elements: (1) establish the shot (genre + shot scale), (2) set the scene "
            "(lighting, color palette, textures, atmosphere), (3) describe the action as a natural sequence in PRESENT TENSE, "
            "(4) define the character(s) with concrete features and express emotion through physical cues, not labels, "
            "(5) identify camera movement and how subjects appear AFTER it, (6) describe the audio "
            "(ambient sound, music, speech/singing — spoken lines in double quotation marks, with language/accent if needed).\n"
            "If the analysis has multiple shots, write 2-4 shots as ONE chronological paragraph, naming each cut in plain language "
            "(hard cut / match cut / dissolve), re-establishing the new framing, keeping re-appearing subjects' identity consistent, "
            "and stating whether audio continues or changes across each cut.\n"
            "Japanese dialogue/lyrics must be written in HIRAGANA ONLY (no kanji, no katakana), e.g. "
            "\"今日は六本木をブラブラしてる\" -> \"きょうはろっぽんぎをぶらぶらしてる\". Other languages stay verbatim."
        )
    elif mode == "T2VA":
        mode_rule = (
            "Mode: T2VA (text only). Output the three core fields in this exact order:\n"
            "1. integrated_multimodal_description: [Shot 1] ...\n"
            "2. overall_soundscape: ...\n"
            "3. non_diegetic_music: ...\n"
            "There is no image-alignment line in T2VA; start directly with integrated_multimodal_description."
        )
    elif mode == "I2VA":
        mode_rule = (
            "Mode: I2VA. The user will supply <Picture 1> as the actual first frame of the target video.\n"
            "Output ONLY the three core fields (integrated_multimodal_description / overall_soundscape / non_diegetic_music) in that order, "
            "separated by one blank line. Do NOT output the image-alignment instruction line — the tool adds it automatically.\n"
            "Content rule: Shot 1 must start from the state shown in <Picture 1> (establish style, subjects, composition, scene anchors first) and develop forward. "
            "Keep character identity, clothing, colors, key objects, and spatial relations consistent with the reference."
        )
    elif mode == "FL2VA":
        mode_rule = (
            "Mode: FL2VA. The user will supply Picture 1 (first frame) and Picture 2 (last frame).\n"
            "Output ONLY the three core fields in that order. Do NOT output the image-alignment instruction line — the tool adds it automatically.\n"
            "Content rule: write a single continuous shot describing the motion path from Picture 1 to Picture 2: "
            "first-frame state -> observable intermediate changes -> progressively narrowing differences -> last-frame state. "
            "Do not repeat two static image descriptions; supply the connecting motion. The last frame must be reached at the end of the shot."
        )
    else:  # L2VA
        mode_rule = (
            "Mode: L2VA. The user will supply <Picture 1> as the actual LAST frame of the target video.\n"
            "Output ONLY the three core fields in that order. Do NOT output the image-alignment instruction line — the tool adds it automatically.\n"
            "Content rule: write a single shot that infers a plausible preceding state, then lets actions, object states, and composition "
            "gradually converge and land exactly on <Picture 1> in the final moment: "
            "plausible preceding state -> explicit action and transition path -> gradual convergence -> last-frame landing."
        )

    extra = ""
    if transcript:
        if is_ltx:
            extra += (
                "\n## Ground-truth transcript (with timestamps)\n"
                "Use this transcript for the spoken words and sung lyrics. Put each line in double quotation marks "
                "inside the prompt, preserving its exact words and original language, and place each line at its "
                "timestamp position in the timeline. For Japanese, write each line in hiragana only (no kanji, no katakana):\n"
                + transcript + "\n"
            )
        else:
            extra += (
                "\n## Ground-truth transcript (with timestamps)\n"
                "Use this transcript for the spoken words and sung lyrics inside <d>. "
                "Preserve its exact words and language, and place each line at its timestamp position in the timeline:\n"
                + transcript + "\n"
            )
    if tags:
        if is_ltx:
            extra += (
                "\n## Audio tags (from the actual audio: PANNs/AudioSet, with confidence)\n"
                "The following music / instrument / voice / ambience labels were detected in the real audio. "
                "Use them to make the prompt's audio description (ambient sound, music, voice) accurate and consistent "
                "(instrumentation, genre, crowd/ambience). Do not invent music that these tags contradict:\n"
                + "\n".join(tags) + "\n"
            )
        else:
            extra += (
                "\n## Audio tags (from the actual audio: PANNs/AudioSet, with confidence)\n"
                "The following music / instrument / voice / ambience labels were detected in the real audio. "
                "Use them to make overall_soundscape and any diegetic-music description accurate and consistent "
                "(instrumentation, genre, crowd/ambience). Do not invent music that these tags contradict:\n"
                + "\n".join(tags) + "\n"
            )

    if is_ltx:
        return f"""You are writing an LTX-2.5 video-generation prompt.
Read the LTX prompt-writing guide below, then use the video analysis JSON to produce the FINAL prompt.

## Target parameters
- Mode: LTX (LTX-2.5 text-to-video)
- Target video duration: {duration:.2f} seconds (keep every action/cut inside this duration)
- Shot plan from analysis: {len(shots)} shot(s)

## Mode rule (must follow exactly)
{mode_rule}

{extra}
## LTX prompt-writing guide
{guide_text}

## Video analysis JSON (from vision LLM; dialogue marked "low" confidence is an inference — use it if it fits, and you may drop it if implausible; "high"/"medium" should be kept)
{json.dumps(analysis, ensure_ascii=False, indent=2)}

## Output rules
1. Write the prompt in English: ONE flowing paragraph for a single continuous take, or screenplay-style (scene header, character cues, quoted dialogue) for dialogue / multi-beat / multi-shot content.
2. No markdown fences, no commentary, no explanations before or after the prompt.
3. No structured field names, no image-alignment instruction lines — output ONLY the prompt body.
4. Use present tense for actions/movement; express emotion through physical cues, not abstract labels.
5. Dialogue / lyrics / singing go in double quotation marks in the original language; specify language/accent when needed.
   Japanese lines must be in HIRAGANA ONLY (no kanji, no katakana).
6. If there are multiple shots (2-4), keep them in one chronological paragraph with explicit transition language at each cut and stated audio continuity.
7. Do not invent on-screen text, brands, or logos. If the source has readable text, keep it short.
8. If there is no dialogue, no singing, and no on-screen speaking source, do not invent any.
"""

    return f"""You are writing a MiniMax H3 video-generation prompt.
Read the H3 prompt-writing guide below, then use the video analysis JSON to produce the FINAL prompt.

## Target parameters
- Mode: {mode}
- Target video duration: {duration:.2f} seconds (every cut time must be strictly inside this duration; format the alignment line with the duration to exactly two decimal places)
- Shot plan from analysis: {len(shots)} shot(s){" -> keep as a single shot" if single_shot and mode in ("FL2VA", "L2VA") else ""}

## Mode rule (must follow exactly)
{mode_rule}

{extra}
## H3 prompt-writing guide
{guide_text}

## Video analysis JSON (from vision LLM; dialogue marked "low" confidence is an inference — use it if it fits, and you may drop it if implausible; "high"/"medium" should be kept)
{json.dumps(analysis, ensure_ascii=False, indent=2)}

## Output rules
1. Write ONLY the three core fields, in English, separated by one blank line, in the order required by the mode rule above.
2. No markdown fences, no commentary, no explanations before or after the fields.
3. Preserve the exact field names: integrated_multimodal_description, overall_soundscape, non_diegetic_music.
4. Never output the image-alignment instruction line ("For the target video..." or "How the reference pictures align...") — the tool adds it.
5. For keyframe modes, reference <Picture 1>/Picture 2 in the shot descriptions.
6. Dialogue inside <d>[Language] ... </d> must keep the original language verbatim.
7. If there is no dialogue, no singing, and no on-screen speaking source, do not invent any <d> blocks.
8. overall_soundscape: 1-4 sentences; non_diegetic_music: 1-3 sentences or "N/A".
9. For overall_soundscape, infer plausible ambient/physical/non-verbal sounds from the visual content (weather, locations, actions, crowds). Use "N/A" only when the scene truly has no plausible sound source.
"""


def format_shot_breaks(text: str) -> str:
    """可読性仕様: 各 [Shot N]（1つ目を含む）の直前に「改行1つ」を揃える（幂等・空白正規化）。
    'integrated_multimodal_description:' ラベルの直後に説明文が入るケースでも、
    [Shot 1] は必ず改行の先頭に来る（説明文はラベル行に残る）。
    LLM が既に改行（空白行つき含む）を入れていても、改行1つに正規化される。
    """
    label = "integrated_multimodal_description:"
    idx = text.find(label)
    if idx < 0:
        return text
    head, rest = text[: idx + len(label)], text[idx + len(label):]
    rest = re.sub(r"\s*(\[(?:Shot|shot) \d+\])", r"\n\1", rest)
    return head + rest


def strip_alignment_line(text: str) -> str:
    """LLM が指示行を先頭に書いてきた場合、除去して3フィールド本文だけ残す"""
    lines = text.split("\n")
    i = 0
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and (
        lines[i].startswith("For the target video,")
        or lines[i].startswith("How the reference pictures align")
    ):
        lines[i] = ""
    return "\n".join(lines).lstrip("\n")


def strip_stray_tags(text: str) -> str:
    """H3仕様にない <token> マーカ混入（例: <scenetrans>）を除去する。
    残すのは <d>...</d> と <Picture N>（参照画像マーカー）のみ。"""
    def _keep(m: "re.Match") -> str:
        tag = m.group(0)
        if tag.startswith("</"):
            return tag if tag == "</d>" else ""
        return tag if re.fullmatch(r"<(d|Picture \d+)>", tag) else ""
    return re.sub(r"</?[a-zA-Z][a-zA-Z0-9 _-]*>", _keep, text)


def run_rewrite(client: LLMClient, mode: str, duration: float, analysis: dict,
                guide_text: str, transcript: str | None,
                tags: list | None = None) -> str:
    """LLM Pass 2 (プロンプト改写)。tags はフォーマット済み行リスト ("conf  label" 文字列の list)"""
    prompt = build_rewrite_prompt(mode, duration, analysis, guide_text, transcript,
                                  tags=tags)
    messages = [{"role": "user", "content": prompt}]
    raw = client.chat(messages, max_tokens=8192)
    # コードフェンスを除去
    m = re.search(r"```(?:text|prompt)?\s*(.*?)\s*```", raw, re.DOTALL)
    if m:
        raw = m.group(1)
    raw = raw.strip()
    if mode == "LTX":
        # LTX は自然言語プロンプト1本: 3フィールド不要。極端に短い/空出力だけ検出する
        if len(raw.split()) < 20:
            die(f"LLM 出力が短い(LTXプロンプトとして不適切)です。再実行してください。\n---\n{raw[:800]}")
        # 仕様: 日本語対白はひらがなのみ。クォート内に漢字/カタカナが残っていれば警告
        # （単一クォート・日本語「」も拾って検出漏れを減らす）
        quoted = (re.findall(r'"([^"]*)"', raw)
                  + re.findall(r"'([^']*)'", raw)
                  + re.findall(r"「([^」]*)」", raw))
        bad = [q for q in quoted if re.search(r"[\u30A0-\u30FF\u3400-\u4DBF\u4E00-\u9FFF]", q)]
        if bad:
            log(f"警告: LTX対白に漢字/カタカナが混入しています(仕様: ひらがなのみ): {bad[:3]}")
        return raw
    # H3系: LLM が万一アライメント行を先頭に書いてきた場合、除去する
    raw = strip_alignment_line(raw)
    raw = strip_stray_tags(raw)  # <scenetrans> 等の仕様外タグ混入を除去
    # 3コアフィールドの存在確認 + 固定順序の確認（仕様: 順序固定）
    fields = ("integrated_multimodal_description", "overall_soundscape",
              "non_diegetic_music")
    positions = []
    for field in fields:
        pos = raw.find(field + ":")
        if pos < 0:
            die(f"LLM 出力に '{field}:' が見つかりません。再実行してください。\n---\n{raw[:800]}")
        positions.append(pos)
    if positions != sorted(positions):
        die(f"LLM 出力の 3コアフィールドの順序が不正です (pos={positions})。再実行してください。\n---\n{raw[:800]}")
    # 可読性仕様: 2つ目以降の [Shot N] 前に改行（LLMに書かせずコードで確実に挿入）
    raw = format_shot_breaks(raw)
    return raw


def print_analysis_summary(analysis: dict, info: dict, tag_lines: list | None = None) -> None:
    """--analysis-only: 映像解析の結果を表示する"""
    print("\n" + "=" * 60)
    print(f"映像解析  ({info['width']}x{info['height']}, {info['duration']:.2f} 秒, "
          f"{info['fps']:.2f} fps)")
    print("=" * 60)
    style = analysis.get("style", "")
    if style:
        print(f"\n[スタイル] {style}")
    shots = analysis.get("shots", [])
    if shots:
        print(f"\n[ショット] 全{len(shots)}個")
        for s in shots:
            print(f"\n--- Shot {s.get('index', '?')} ({s.get('time_range', '')}) ---")
            for key in ("composition", "subjects", "actions", "camera_motion", "environment"):
                v = s.get(key)
                if v:
                    print(f"  {key}: {v}")
    speakers = analysis.get("speakers", [])
    if speakers:
        print(f"\n[話者] 全{len(speakers)}名")
        for sp in speakers:
            print(f"  {sp.get('id', '?')}: {sp.get('description', '')}")
    dialogue = analysis.get("dialogue", [])
    if dialogue:
        print(f"\n[発話/歌詞] 全{len(dialogue)}行 (confidence=low は推定)")
        for d in dialogue:
            conf = d.get("confidence", "")
            note = f" [low]" if conf == "low" else ""
            print(f"  {d.get('time', '')} {d.get('speaker', '')} "
                  f"[{d.get('language', '')}]{note}: {d.get('text', '')}")
    ost = analysis.get("on_screen_text", [])
    if ost:
        print("\n[画面内テキスト]")
        for t in ost:
            print(f"  - {t}")
    sounds = analysis.get("sounds", "")
    if sounds:
        print(f"\n[環境音] {sounds}")
    if tag_lines:
        print("\n[音声タグ: PANNs/AudioSet]")
        for line in tag_lines:
            print(f"  {line}")
    print("=" * 60)


# ---------------------------------------------------------------------------
# main
# ---------------------------------------------------------------------------

def resolve_duration(mode: str, requested: float | None, effective_len: float) -> float:
    """モード別の対象動画長を解決する。
    H3: 4〜15秒。指定なしなら動画長を丸めてクランプ / 指定時は範囲チェック。
    LTX: 6〜20秒の妥当値 (6,8,10,...,20) にスナップ。
    """
    if mode == "LTX":
        raw = round(effective_len) if requested is None else requested
        if not (LTX_MIN_DURATION <= raw <= LTX_MAX_DURATION):
            die(f"LTXモードでは --duration は 6〜20 秒で指定してください (実際: {requested})")
        return float(min(LTX_VALID_DURATIONS, key=lambda v: abs(v - raw)))
    # H3
    dur = min(H3_MAX_DURATION, max(H3_MIN_DURATION, round(effective_len))) if requested is None else requested
    if not (H3_MIN_DURATION <= dur <= H3_MAX_DURATION):
        die(f"--duration は {H3_MIN_DURATION}〜{H3_MAX_DURATION} 秒で指定してください (実際: {requested})")
    return float(dur)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description="動画 → MiniMax H3 / LTX-2.5 プロンプト変換")
    p.add_argument("video", type=Path, help="入力動画 (mp4 等)")
    p.add_argument("--mode", choices=["T2VA", "I2VA", "FL2VA", "L2VA", "LTX"], default="T2VA",
                   help="T2VA/I2VA/FL2VA/L2VA = MiniMax H3, LTX = LTX-2.5 (自然言語プロンプト)")
    p.add_argument("--duration", type=float, default=None,
                   help="対象動画の長さ(秒)。H3: 4-15 / LTX: 6-20(妥当値にスナップ)。既定: 解析対象動画をクランプ")
    p.add_argument("--max-side", type=int, default=480,
                   help="解析用動画の最大辺px (既定 480)")
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
    p.add_argument("--asr-model", default=DEFAULT_ASR_MODEL,
                   help="mlx-whisperモデル (既定: " + DEFAULT_ASR_MODEL + ")")
    p.add_argument("--asr-language", default=None,
                   help="ASRの言語コード (既定: 自動検出。例: ja, en)")
    p.add_argument("--no-audio-tags", action="store_true",
                   help="音声タグ(PANNs)算出をしない (既定: 音声があれば自動実行)")
    p.add_argument("--tags-threshold", type=float, default=DEFAULT_TAG_THRESHOLD,
                   help="タグの信頼度閾値 (既定 0.05)")
    p.add_argument("--tags-max", type=int, default=DEFAULT_TAG_MAX,
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
    load_env_file()
    args = parse_args()
    api_base = args.api_base or os.environ.get("H3_API_BASE") or DEFAULT_API_BASE
    model = args.model or os.environ.get("H3_MODEL") or DEFAULT_MODEL
    api_key = os.environ.get("H3_API_KEY", "") or ""
    log(f"LLM: {model} @ {api_base}" + (" (API key: 設定済み)" if api_key else ""))
    video: Path = args.video
    if not video.is_file():
        die(f"動画が見つかりません: {video}")
    require_tool("ffmpeg")
    require_tool("ffprobe")

    out_dir = args.out / video.stem
    out_dir.mkdir(parents=True, exist_ok=True)
    keyframes_dir = out_dir / "keyframes"

    # --- ffmpeg 準備 -------------------------------------------------------
    info = probe_video(video)
    log(f"入力動画: {info['width']}x{info['height']}, {info['duration']:.2f} 秒, {info['fps']:.2f} fps")

    # コンテンツ範囲（フェードイン/アウトの黒部分を除く実際の映像の範囲）
    if args.content_start is not None or args.content_end is not None:
        start = args.content_start if args.content_start is not None else 0.0
        end = args.content_end if args.content_end is not None else info["duration"]
        # 末尾判定の許容幅 (0.03s) を end の上限に加える
        if not (0.0 <= start < end <= info["duration"] + 0.03):
            die(f"--content-start/--content-end が無効です "
                f"(0 <= start < end <= 動画長 {info['duration']:.2f}s): "
                f"start={start:.2f}s, end={end:.2f}s")
        log(f"コンテンツ範囲を手動指定: {start:.2f}s〜{end:.2f}s")
    elif args.keep_fade:
        start, end = 0.0, info["duration"]
        log("フェード検出をスキップ (--keep-fade)")
    else:
        start, end, note = detect_content_range(video, info["duration"], info["fps"])
        log(f"コンテンツ範囲: {start:.2f}s〜{end:.2f}s ({note})")

    # 解析対象範囲 = コンテンツ範囲 ∩ [0, max_seconds]
    analysis_start = start
    analysis_len = (end - start) if args.max_seconds is None else min(end - start, args.max_seconds)
    if analysis_len <= 0.2:
        die("解析対象範囲が短すぎます (--max-seconds を見直してください)")

    analysis_video = out_dir / "analysis_downscaled.mp4"
    make_analysis_video(video, analysis_video, args.max_side,
                        start=analysis_start, length=analysis_len, info=info)

    if args.analysis_only:
        duration = None
        log(f"モード: analysis-only / 解析対象: {analysis_len:.2f} 秒 (プロンプト生成なし)")
    else:
        duration = resolve_duration(args.mode, args.duration, analysis_len)
        log(f"対象動画長: {duration:.2f} 秒 ({args.mode})")

    keyframe_paths = {}
    if not args.analysis_only and args.mode in KEYFRAME_MODES:
        keyframe_paths = extract_keyframes(video, keyframes_dir, info["fps"],
                                           first_at=analysis_start,
                                           last_at=analysis_start + analysis_len)
        log(f"キーフレーム: {keyframe_paths['first']} / {keyframe_paths['last']}")

    # --- LLM Pass 1: 解析 ---------------------------------------------------
    guide_text = None
    if not args.analysis_only:
        default_guide = ("ltx-prompt-guide-base.md" if args.mode == "LTX"
                         else "minimax-h3-prompt-guide-base.md")
        guide_path = args.guide or (Path(__file__).parent / "md" / default_guide)
        if not guide_path.is_file():
            die(f"プロンプトガイドが見つかりません: {guide_path} (--guide で指定)")
        guide_text = guide_path.read_text(encoding="utf-8")

    # --- 文字起こし (対白・歌詞) --------------------------------------------
    transcript = None
    audio_present = has_audio_stream(video)  # ffprobeは1回で済ませる (ASR/音声タグの判定で共有)
    if args.transcript:
        if not args.transcript.is_file():
            die(f"--transcript: ファイルが見つかりません: {args.transcript}")
        transcript = args.transcript.read_text(encoding="utf-8")
        log(f"文字起こしを読み込み: {args.transcript}")
    elif not args.no_asr and audio_present:
        wav = out_dir / "audio_16k.wav"
        extract_audio(video, wav, analysis_start, analysis_len)
        try:
            result = transcribe(wav, args.asr_model, args.asr_language)
        except ImportError:
            log("警告: mlx_whisper がimportできないためASRをスキップ "
                "(conda activate dev で実行 / --no-asr)")
        except Exception as e:
            log(f"警告: ASRに失敗したためスキップ ({e})。--no-asr で省略できます")
        else:
            transcript = format_transcript(result)
            if transcript:
                (out_dir / "transcript.txt").write_text(transcript + "\n", encoding="utf-8")
                log(f"文字起こしを保存: {out_dir / 'transcript.txt'}")
            else:
                log("ASR: 発話(セリフ/歌詞)が検出されませんでした")
                transcript = None
    elif args.no_asr:
        log("ASRをスキップ (--no-asr)")

    # --- 音声タグ (音楽・楽器・環境音) -----------------------------------------
    tag_lines = []
    if args.no_audio_tags:
        log("音声タグをスキップ (--no-audio-tags)")
    elif audio_present:
        wav32k = out_dir / "audio_32k.wav"
        extract_audio(video, wav32k, analysis_start, analysis_len, sample_rate=32000)
        try:
            tags = audio_tags(wav32k, args.tags_threshold, args.tags_max)
        except Exception as e:
            log(f"警告: 音声タグの算出に失敗したためスキップ ({e})。--no-audio-tags で省略できます")
        else:
            if tags:
                tag_lines = [f"{conf:.3f}  {label}" for label, conf in tags]
                (out_dir / "audio_tags.txt").write_text("\n".join(tag_lines) + "\n",
                                                       encoding="utf-8")
                log(f"音声タグを保存: {out_dir / 'audio_tags.txt'} "
                    f"(top3: {', '.join(l.split('  ')[1] for l in tag_lines[:3])})")
            else:
                log("音声タグ: 閾値を超えるタグがありません")

    client = LLMClient(api_base, model, args.temperature, api_key=api_key)
    analysis = None
    if args.reuse_analysis is not None:
        reuse_path = (out_dir / "analysis.json" if args.reuse_analysis == "__default__"
                      else Path(args.reuse_analysis))
        if not reuse_path.is_file():
            die(f"--reuse-analysis: {reuse_path} が見つかりません "
                "(まず --reuse-analysis なしで1回実行してください)")
        try:
            analysis = json.loads(reuse_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            die(f"--reuse-analysis: {reuse_path} が有効なJSONではありません: {e}")
        if not isinstance(analysis, dict) or "shots" not in analysis:
            die(f"--reuse-analysis: {reuse_path} が analysis.json のスキーマに見えません "
                "(shots キーを含む JSONオブジェクトが必要です)")
        log(f"既存の解析を再利用: {reuse_path} (Pass 1 スキップ)")
    else:
        video_b64 = base64.b64encode(analysis_video.read_bytes()).decode()
        log(f"解析用動画: {analysis_video.stat().st_size / 1e6:.2f} MB (base64化して送信)")
        analysis = run_analysis(client, video_b64, transcript, tags=tag_lines)

    (out_dir / "analysis.json").write_text(
        json.dumps(analysis, ensure_ascii=False, indent=2), encoding="utf-8")
    log("解析 JSON を保存: " + str(out_dir / "analysis.json"))

    if args.analysis_only:
        print_analysis_summary(analysis, info, tag_lines)
        log(f"完了 (analysis-only)。出力先: {out_dir}/")
        log(f"  - analysis.json       映像解析の構造化 JSON")
        if transcript:
            log(f"  - transcript.txt        ASR文字起こし (対白・歌詞)")
        if tag_lines:
            log(f"  - audio_tags.txt        音声タグ (音楽・楽器・環境音)")
        return

    # --- LLM Pass 2: 改写 ---------------------------------------------------
    prompt_text = run_rewrite(client, args.mode, duration, analysis, guide_text,
                              transcript, tags=tag_lines)
    alignment = build_alignment_line(args.mode, duration)
    if alignment:
        prompt_text = alignment + "\n\n" + prompt_text
        log(f"アライメント行を付与: {alignment[:60]}...")
    prompt_path = out_dir / "prompt.txt"
    prompt_path.write_text(prompt_text + "\n", encoding="utf-8")

    # --- 結果表示 -----------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"モード: {args.mode} / 対象動画長: {duration:.2f} 秒")
    print("=" * 60)
    print(prompt_text)
    print("=" * 60)
    log(f"完了。出力先: {out_dir}/")
    log(f"  - prompt.txt          最終プロンプト")
    log(f"  - analysis.json       映像解析の中間 JSON (手直し用)")
    if keyframe_paths:
        log(f"  - keyframes/first.jpg, keyframes/last.jpg  (元解像度 / H3 API 用)")
    log(f"  - analysis_downscaled.mp4  解析に渡した下書き動画")
    if transcript:
        log(f"  - transcript.txt        ASR文字起こし (対白・歌詞)")
    if tag_lines:
        log(f"  - audio_tags.txt        音声タグ (音楽・環境音)")


if __name__ == "__main__":
    main()
