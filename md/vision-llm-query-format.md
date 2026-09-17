# video-analyzer の Vision LLM への投げ方（Pass 1 映像解析）

`h3_video2prompt.py` が OpenAI 互換用の vision LLM に何を、どう送っているかの仕様メモ。
他の AI / エージェントが同様の呼び出しを再現する用途のためにまとめている。

## 1. エンドポイント

| 項目 | 値 |
|---|---|
| URL | `http://192.168.11.100:8888/v1/chat/completions` |
| モデル | `qwen38-27b-dflash2` |
| 認証 | 不要（keys なし。後継 key 認証に戻る場合は `Authorization: Bearer <key>` を付与） |
| ケーパセット | OpenAI 互換 chat completions API |
| temperature | 0.2 |
| max_tokens | 8192 |

この LLM は `content` 配列の `video_url`（データ URI 形式 MP4）にネイティブ対応している。
`image_url` のみのサーバー（video_url ネイティブな非対応）では 422 になることが確認済み。

## 2. パイプラインの事前準備

送る前にパイプラインが次の処理を行う（いずれも LLM には含まない）:

1. ffprobe で動画の幅・高さ・FPS・長さを取得
2. blackdetect + signalstats（YAVG スキャン）でフェード（黒ive部分）を除外し、コンテンツ範囲を特定
3. コンテンツ範囲を ffmpeg で **480px 最大辺**にscaleして `analysis_downscaled.mp4` を生成
   - `scale=-2:480`（縦長）または `scale=480:-2`（横長）
   - libx264 `-preset veryfast -crf 23 -pix_fmt yuv420p`、音声なし
4. 16kHz 単一チャネル wav を抽出し mlx-whisper（whisper-large-v3-turbo）で ASR
5. 32kHz 単一チャネル wav を抽出し PANNs（Cnn14）サブプロセスで音声タグ
6. `analysis_downscaled.mp4` を base64 化（`data:video/mp4;base64,...`）

## 3. リクエスト本体

POST `http://192.168.11.100:8888/v1/chat/completions`

```json
{
  "model": "qwen38-27b-dflash2",
  "messages": [
    {
      "role": "user",
      "content": [
        {"type": "text", "text": "<プロンプト＋オプションの文字起こし＋オプションの音声タグ>"},
        {"type": "video_url",
         "video_url": {"url": "data:video/mp4;base64,<analysis_downscaled.mp4 の base64>"}}
      ]
    }
  ],
  "temperature": 0.2,
  "max_tokens": 8192
}
```

### text パーツの組み立て順

1. **メインプロンプト**（日本語）:
   「動画生成プロンプト向けの映像解析専門家として、添付動画を細かく観察し、構造化 JSON を出力せよ」という指示と
   - 値はすべて英語（on_screen_text と dialogue.text は原文言語を保持）
   - ショットは再生順に分割、カットごとに index、time_range は動画内の絶対秒数
   - camera_motion は「運動タイプ + 振幅 + 速度」、静止なら "static shot"
   - 話者は S1, S2... で安定 ID（画面外のナレーションも包含）
   - dialogue.text は映像（口の動き・字幕・状況）からの最善推定、confidence を low/medium
   - 字幕が読める場合は字幕を優先、confidence medium
   - 見切れている対白は推測せず、省略または [unclear]
   - **出力はコードフェンスなしの JSON 本体のみ**
   - 末尾に JSON スキーマをそのまま提示

2. **[文字起こし（対白・歌詞の正解データ）]**（ASR があれば追加）:
   タイムスタンプ付き文字起こしを付与。「dialogue の text / language / time はこの文字起こしに合わせ、
   confidence は "high" にしてください」「歌唱の歌詞も dialogue として扱うこと」の指示と文字起こし本体

3. **[音声タグ（PANNs/AudioSet, 信頼度付き）]**（タグがあれば追加）:
   信頼度付きのラベル行（`0.851  Speech` のような `conf  label` 形式）と
   「sounds フィールドと、音楽・歌唱に関する記述はこのタグと整合させてください」の指示

### JSON スキーマ（LLM にそのまま提示）

```json
{
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
}
```

## 4. レスポンスの扱い

- `choices[0].message.content` が応答テキスト
- 助記コードフェンス ```json ... ``` Umumów、または JSON ブロック（最期の `{`〜`}`）を抽出
- JSON パース失敗の場合、**1回だけ**再試行:
  過去の応答を assistant メッセージとして残し、
  「上記出力は有効な JSON ではありません。スキーマに従った有効な JSON のみを再出力してください。コードフェンスは不要です。」
  と user メッセージで追加入力し、再チャット
- LLM HTTP 4xx（429 除外）は再試行せず即 fail、5xx はリトライ（既定 2 回、3 秒(interval)）

## 5. 留意点

- video_url は **ネイティブ対応の vision LLM でないと 422** になる。image_url のみ対応のサーバー（tabbyAPI 上の Qwen に系）では動画ベースの HP を通せないため、フレームを image_url 配列に変換して投げ直すか、video input 対応の LLM を使う必要がある
- 動画は 480px dummy に下書きしてから 1 リクエストでまとめて送る。10〜15 秒動画で MemoryStream がだいたい 1〜2 MB（base64 化）になる
- temperature は 0.2。JSON 生成の安定性を最優先
- .env の `H3_API_BASE` / `H3_MODEL`（任意 `H3_API_KEY`）が上書き可能。CLI `--api-base` / `--model` が最優先