# video-analyzer

動画から **MiniMax H3**（動画+音声生成モデル）用 / **LTX-2.5**（Lightricksの動画+音声同時生成モデル）用プロンプトを生成するツールと、そのためのプロンプトガイドのコレクション。

- `h3_video2prompt.py` — 動画を映像・音声解析し、H3の T2VA / I2VA / FL2VA / L2VA プロンプト（英語）または **LTX-2.5 の自然言語プロンプト**（`--mode LTX`）を生成。プロンプトなしの**映像の内容表示**（`--analysis-only`）にも対応
- `h3_video2prompt_frames.py` — 同じ出力を、Pass1(映像解析)の入力をffmpegフレーム抽出方式に差し替えて生成する別モード（本体は無変更、詳細は後述）
- `md/` — プロンプトガイド（H3ベース/Ref2VA、LTX-2.5ベース/IC-LoRA系）。`--analysis-only`以外の全モードで必須のため同梱

> **⚠️ どちらを使うか（重要）**: `h3_video2prompt.py` は動画をまるごと`video_url`としてLLMに送るため、
> **動画Vision（video input）に対応したエンドポイント（vLLM等でホストされたVideo-LLM）が必須**です。
> **`llama.cpp` / LM Studio 等、静止画（image_url）にしか対応していないバックエンドでは動きません。**
> その場合は代わりに `h3_video2prompt_frames.py`（動画をffmpegで静止画に分割して`image_url`配列で送る方式）を使ってください。
>
> **動画Vision対応LLMの例（2026-09時点、要最新確認）**:
> - ✅ Qwen3.6 / Qwen3.8 系（Qwen-VL系）
> - ✅ Gemma4 系
> - ❌ DeepSeek — `DeepSeek-V4-Flash-Vision-Exp`で画像Visionには対応したが、**動画は未対応**
>
> 上記以外のモデルも含め、使用するモデル・エンドポイントが動画Vision（`video_url`）に対応しているか事前に確認してください。非対応の場合は `h3_video2prompt_frames.py` を使用してください。

---

## 1. 概要

入力の mp4 動画を **OpenAI API 互換のビジョンLLM**（例: `http://192.168.11.100:8888/v1` / `qwen38-27b-dflash2`。`.env`で変更可、詳細は後述）で解析し、H3 が期待するプロンプト構造（`integrated_multimodal_description` / `overall_soundscape` / `non_diegetic_music` など）または LTX-2.5 の自然言語プロンプト（`--mode LTX`）に変換する。

処理パイプライン:

```
video.mp4
  ├─ ffprobe: 長さ・解像度・fpsの取得
  ├─ フェード検出: 先頭/末尾の黒（フェードイン・アウト）を blackdetect +
  │   フレーム平均輝度(YAVG)スキャンで検出し、実際の映像の範囲を特定
  │   （検出された場合、解析とキーフレームはこの範囲に対して行われる）
  ├─ ffmpeg: 解析用動画の作成（コンテンツ範囲をトリム / max side 480px以下 / h264）
  ├─ ffmpeg: キーフレーム抽出（元解像度 / 実際の映像開始・終了フレーム）
  ├─ ASR（mlx-whisper）: 音声があれば自動で文字起こし → transcript.txt
  │   （タイムスタンプ付き / セリフ・歌詞 / LLMの映像解析とプロンプト改写の正解データに使用）
  ├─ 音声タグ（PANNs/AudioSet）: 音声があれば音楽・楽器・環境音ラベル → audio_tags.txt
  │   （overall_soundscape や音楽記述を実際の音声に基づいて正確に書くためのデータ）
  ├─ LLM Pass1（映像解析）: 下書き動画 + 文字起こし + 音声タグ → 構造化 JSON（analysis.json）
  └─ LLM Pass2（改写）: 解析JSON + プロンプトガイド全文 → 最終プロンプト
       H3系: 3コアフィールド。キーフレームモードの画像アライメント指示行はLLMに書かせず、
       ガイドの固定テンプレートに従ってコード側で正確に付与する
       LTX系(--mode LTX): 自然言語1パラグラフ（マルチショットは時系列1段落+転換明示）
  （--analysis-only 指定時は Pass1 の保存までで終了し、内容サマリを表示してプロセス終了）
```

ポイント:
- 映像解析には **フレーム分割しない下書きmp4をそのまま**渡す（`video_url` base64形式）
- キーフレーム（first/last）はLLMには渡さず**元解像度を維持**（H3 APIの参照画像用）
- **フェードイン/アウト対策**: 単純に0.0s/末尾からフレームを切ると黒フレームになるケースを避けるため、`blackdetect`（全ピクセル暗区間）と`signalstats`のフレーム平均輝度で「実際に映像が視える」先頭/末尾フレームを特定し、そこからキーフレームを切る。解析用動画もこの範囲にトリムされる
- プロンプト本文は**英語**、セリフ・歌詞・画面表示テキストのみ原文言語を保持

## 2. インストール / セットアップ

### 前提
- macOS (Apple Silicon) / Linux
- Python 3.10+（任意の仮想環境で可。以下は一例として`dev`という名前を使用）
- `ffmpeg` と `ffprobe` が PATH にあること

### 依存パッケージ

```bash
conda activate dev   # 任意の環境名でよい（venv等でも可）
pip install requests python-dotenv
pip install mlx-whisper          # ASR（セリフ・歌詞）
pip install panns-inference      # 音声タグ（音楽・環境音 / torch・torchlibrosa 付き）
```

> `panns-inference` は PyPI 公式パッケージ（`panns` パッケージはPython2構文で壊れているため使用しない）。
> `mlx-whisper` は初回実行時にモデル（`mlx-community/whisper-large-v3-turbo`）を HuggingFace から自動ダウンロードする。

### PC (CUDA) の場合

> 但し未確認（このリポジトリの開発・動作確認はmacOS環境のみで行っており、CUDA環境では未検証）。

`mlx-whisper` は Apple の MLX フレームワーク前提のため **Apple Silicon Mac専用** で、Windows/Linux (CUDA) 環境では動作しない。ASR (`h3_video2prompt.py` / `h3_video2prompt_frames.py` の `transcribe()`) を以下のいずれかに差し替えること。

```bash
pip install faster-whisper       # CTranslate2ベース。CUDA対応、速度面で推奨
# もしくは
pip install openai-whisper       # オリジナル実装。CUDA対応だが faster-whisper より低速
```

`transcribe()` は `{"segments": [{"start", "end", "text"}, ...], "text": ...}` の形を返せば後続処理（`format_transcript()` 等）は無改修で動く。`faster-whisper` での実装例:

```python
def transcribe(wav: Path, model: str, language: str | None) -> dict:
    from faster_whisper import WhisperModel
    m = WhisperModel(model, device="cuda", compute_type="float16")
    segments, info = m.transcribe(str(wav), language=language)
    segments = list(segments)  # ジェネレータなので先にリスト化
    return {
        "segments": [{"start": s.start, "end": s.end, "text": s.text} for s in segments],
        "text": "".join(s.text for s in segments),
        "language": info.language,
    }
```

`DEFAULT_ASR_MODEL`（既定 `mlx-community/whisper-large-v3-turbo`）も `faster-whisper` 用のモデル名（例: `large-v3-turbo`）に変更が必要。ASRなしで進める場合は `--no-asr`、既存の文字起こしがあれば `--transcript` で代替できる。

なお `panns-inference` (PyTorch) は OS/GPU非依存でそのままCUDA環境でも動作する（`device="cuda"` に変更すれば高速化も可能、既定は `device="cpu"`）。

### PANNs 重み
`.panns/Cnn14_mAP=0.431.pth`（約315MB）をこのディレクトリに配置。
無ければ初回実行時に自動ダウンロードされる（`thelou1s/panns-inference` から）。

### LLM エンドポイント（.env）

LLMのエンドポイントとモデル名は `.env` で変更できます:

```bash
cp .env.example .env   # サンプルから .env を作成
```

```ini
# .env
H3_API_BASE=http://192.168.11.100:8888/v1
H3_MODEL=qwen38-27b-dflash2
```

読み込み優先順位: **CLI引数（`--api-base` / `--model`）> `.env` / 環境変数 > スクリプト内既定値**
（`cwd/.env` とスクリプト同ディレクトリの `.env` の両方を参照。先に読んだ側が優先、既存の環境変数は上書きしない）
実行開始時に使用したエンドポイントがログに表示される。

## 3. 使い方

```bash
conda activate dev   # 上でセットアップした環境を使う（環境名は任意）

# テキスト生成のみ（キーフレーム不要）
python h3_video2prompt.py video.mp4 --mode T2VA

# キーフレーム付きモード
python h3_video2prompt.py video.mp4 --mode I2VA --duration 8
python h3_video2prompt.py video.mp4 --mode FL2VA --duration 8
python h3_video2prompt.py video.mp4 --mode L2VA --duration 8

# LTX-2.5 用プロンプト（自然言語1パラグラフ / 長さ6〜20秒・妥当値にスナップ）
python h3_video2prompt.py video.mp4 --mode LTX

# 同じ解析でH3+LTX両方（2回目はPass1=LLM解析をスキップ）
python h3_video2prompt.py video.mp4 --mode T2VA
python h3_video2prompt.py video.mp4 --mode LTX --reuse-analysis

# 映像の内容だけ知りたい（プロンプト生成しない: 解析JSON+文字起こし+音声タグ+サマリ表示）
python h3_video2prompt.py video.mp4 --analysis-only
```

### フレーム抽出方式（`h3_video2prompt_frames.py`）

Pass1（映像解析）の入力方法だけを、動画まるごと`video_url`で渡す方式から、ffmpegで
複数フレームをjpg抽出し`image_url`の配列（各画像にタイムスタンプ付き）で渡す方式に
差し替えた別モード。**`h3_video2prompt.py`本体は変更していない**（`import`で再利用する
だけの独立ファイル）。使い方・出力・Pass2以降は本体と同じ:

```bash
python h3_video2prompt_frames.py video.mp4 --mode T2VA
python h3_video2prompt_frames.py video.mp4 --mode I2VA --duration 8 \
  --frame-fps 1.5 --max-frames 40 --frame-max-side 768
```

追加オプション: `--frame-fps`（フレーム抽出fps、既定1.0）/ `--max-frames`（抽出上限、既定32）/
`--frame-max-side`（各フレームの最大辺px、既定768）。出力に`frames/`（解析に渡したjpg）が
加わる以外は本体と同じ構成。詳細・検証記録は`AGENTS.md`参照。

### オプション

| オプション | 既定 | 説明 |
| --- | --- | --- |
| `--mode` | `T2VA` | `T2VA` / `I2VA` / `FL2VA` / `L2VA`（H3）/ `LTX`（LTX-2.5） |
| `--duration N` | 動画長をクランプ | 対象動画の長さ（秒）。H3: 4〜15 / LTX: 6〜20（6,8,10,...20にスナップ） |
| `--max-side N` | `480` | 解析用動画の最大辺px。大きいほど正確だが遅い |
| `--max-seconds N` | 動画全体 | 解析対象の長さ上限（長い動画の冒頭N秒だけ解析） |
| `--keep-fade` | 無効 | フェード検出・トリミングをしない（0.0s〜末尾のまま） |
| `--content-start S` / `--content-end S` | 自動検出 | コンテンツ範囲を手動指定（検出が合わない動画向け） |
| `--no-asr` | 無効 | 音声文字起こし(ASR)をしない（既定: 音声があれば自動実行） |
| `--asr-model` | `mlx-community/whisper-large-v3-turbo` | mlx-whisperのモデル（例: `.../whisper-medium-mlx` で軽量に） |
| `--asr-language` | 自動検出 | ASRの言語コード（例: `ja`, `en`） |
| `--no-audio-tags` | 無効 | 音声タグ(PANNs)算出をしない（既定: 音声があれば自動実行） |
| `--tags-threshold` / `--tags-max` | `0.05` / `12` | 音声タグの信頼度閾値 / 出力タグの最大数 |
| `--transcript f.txt` | なし | セリフの文字起こしを直接指定（ASRの上書き） |
| `--reuse-analysis [path]` | なし | LLM Pass1（映像解析）をスキップし既存の `analysis.json` を再利用（引数なし: `out/<動画名>/analysis.json`）。H3/LTXを同じ解析で出す際にPass1のLLM呼び出しを省く |
| `--analysis-only` | 無効 | LLM Pass1（映像解析）までで終了。プロンプトは生成せず、`analysis.json` / `transcript.txt` / `audio_tags.txt` と内容サマリを表示する（agent skill `video-content` がこれを使う） |
| `--guide file.md` | H3系: `md/minimax-h3-prompt-guide-base.md` / LTX: `md/ltx-prompt-guide-base.md` | 改写用ガイド |
| `--out DIR` | `out/` | 出力先ディレクトリ |
| `--api-base` / `--model` | `.env`の `H3_API_BASE` / `H3_MODEL`（なければ既定値） | LLMエンドポイント・モデル名 |
| `--temperature` | `0.2` | LLMの温度 |

### 出力（`out/<動画名>/` に）

| ファイル | 内容 |
| --- | --- |
| `prompt.txt` | 最終的なプロンプト（H3系: 3コアフィールド / LTX: 自然言語1パラグラフ。`--analysis-only` 時は生成されない） |
| `analysis.json` | Pass1 の映像解析 JSON（手直し・デバッグ用。`--reuse-analysis` の再利用源） |
| `keyframes/first.jpg` / `last.jpg` | 元解像度の先頭/末尾フレーム（H3キーフレームモード I2VA/FL2VA/L2VA のみ） |
| `analysis_downscaled.mp4` | LLMに渡した下書き動画（再解析用） |
| `transcript.txt` | ASR文字起こし（音声がある場合。手直しして `--transcript` で再実行できる） |
| `audio_tags.txt` | 音声タグ（PANNs/AudioSet: 音楽・楽器・環境音のラベル+信頼度） |

## 4. モードの選び方

### MiniMax H3

| モード | H3に渡すもの | 使いどころ |
| --- | --- | --- |
| T2VA | プロンプトだけ | テキストからゼロで生成したい |
| I2VA | プロンプト + 先頭フレーム1枚 | 先頭を元の動画に一致させて続きを生成 |
| FL2VA | プロンプト + 先頭/末尾2枚 | 元の動画の両端を再現して間を生成 |
| L2VA | プロンプト + 末尾フレーム1枚 | 末尾フレームに収束する動画を生成 |

### LTX-2.5

| モード | LTXに渡すもの | 使いどころ |
| --- | --- | --- |
| LTX | 自然言語プロンプト（1パラグラフ〜シナリオ風） | LTX-2.5のT2Vで生成。マルチショット（2〜4カット）の動画を作る場合はカットを時系列1段落で記述 |

- LTXはH3と違い **構造化フィールドやアライメント行がない**（自然言語プロンプトのみ）
- 動画長は **6〜20秒**（6,8,10,...,20にスナップ）。既定では解析対象動画長を妥当値に丸める
- セリフは**二重クォート `"...")`**。日本語のセリフ・歌詞は**ひらがなへ変換して出力**（漢字・カタカナ禁止。他言語は原文のまま）
- キーフレーム抽出・アライメント行付与は行わない（I2V相当は別途対応）
- 詳細は [`md/ltx-prompt-guide-base.md`](md/ltx-prompt-guide-base.md) / [IC-LoRA系](md/ltx-prompt-guide-ic-lora.md)

## 5. プロンプトガイド（md/）

> `--analysis-only` 以外の全モードで実行に必須のため、このリポジトリに同梱しています。

### H3（MiniMax）

| ファイル | 内容 |
| --- | --- |
| [`md/minimax-h3-prompt-guide-base.md`](md/minimax-h3-prompt-guide-base.md) | T2VA/I2VA/FL2VA/L2VA のプロンプト書き方（4モードの完全なサンプル付き） |
| [`md/minimax-h3-prompt-guide-ref2va.md`](md/minimax-h3-prompt-guide-ref2va.md) | Ref2VA（フルリファレンス）の6セクション改写フォーマット（ラベル体系・完全な例付き） |

出典: [MiniMax-AI/MiniMax-H3](https://github.com/MiniMax-AI/MiniMax-H3)（`skills/h3-prompt-writing/`）。
このリポジトリのガイドは、その `base-en.txt` / `ref-en.txt` / `SKILL.md` を日本語解説付きでまとめたもの。

### LTX-2.5（Lightricks）

| ファイル | 内容 |
| --- | --- |
| [`md/ltx-prompt-guide-base.md`](md/ltx-prompt-guide-base.md) | T2V/I2V/A2V・マルチショット（ネイティブ2〜4カット）のプロンプト書き方（6要素・構造・語彙・サンプル・チェックリスト付き） |
| [`md/ltx-prompt-guide-ic-lora.md`](md/ltx-prompt-guide-ic-lora.md) | IC-LoRA系（Dub-It発話置換 / Video Editing）の専用プロンプトフォーマット |
| [`md/ltx-25-api-notes.md`](md/ltx-25-api-notes.md) | LTX API（api.ltx.io）連携の設計メモ（未実装: エンドポイント・モデル・パラメータマッピング） |

出典: [公式Docs Prompting Guide](https://docs.ltx.io/api-documentation/implementation-guides/prompting-guide)（`.md`版）/ [LTX-2.5 Prompt Guide（ブログ）](https://ltx.io/blog/ltx-2-5-prompt-guide) / [LTX-2 Prompting Guide（ブログ）](https://ltx.io/blog/prompting-guide-for-ltx-2) / [LTX-2.5モデル仕様](https://docs.ltx.io/models/ltx-2-5) / [Dub-It機能ガイド](https://docs.ltx.io/open-source-model/feature-guides/audio/dub-it-beta)。
元HTML/MDの保存先: `.ltx-refs/`。

## 6. トラブルシューティング

- **LLM応答が遅い/タイムアウト**: `--max-side 360` や `--max-seconds` を小さくして解析対象を軽くする
- **セリフが不正確**: `--transcript` で文字起こしを渡す。歌唱の歌詞はWhisperの精度限界で推測混じりになるため、`out/<動画>/transcript.txt` を手直しして `--transcript` で再実行するのが確実
- **音声タグが壊れた（numbaキャッシュエラー）**: PANNsはASRと同じプロセス内で走らせると numba が壊れるため、内部でサブプロセス分離している。それでも失敗したら `--no-audio-tags` で省略
- **ガイドがないエラー**: H3系は `--guide md/minimax-h3-prompt-guide-base.md`、LTXは `--guide md/ltx-prompt-guide-base.md` を指定
- **LTXの長さが想定と違う**: LTXモードは 6〜20秒の妥当値（6,8,10,...,20）にスナップされる（H3の4〜15秒とは別ロジック）。`--duration` で固定可
- **フェード検出が合わない**: `--content-start` / `--content-end` で手動指定、または `--keep-fade` で無効化
- **`Operation not permitted`（パッケージ/モデルの書込）**: conda環境やホームディレクトリへの書込が必要な場合（pip install、モデルDL）、サンドボックス外の権限で実行すること
