# LTX API 連携メモ（設計メモ・未実装）

> 本ツールは現状 **プロンプト生成まで**（`--mode LTX` → `prompt.txt`）。
> 実際の動画生成（api.ltx.io 呼び出し）は未実装。ここに「実装するならこうやる」設計メモを置く。
> 出典: [LTX-2.5モデル仕様](https://docs.ltx.io/models/ltx-2-5) / [async jobs](https://docs.ltx.io/async-jobs) /
> [text-to-video API](https://docs.ltx.io/api-documentation/api-reference/async-video-generation/submit-text-to-video) /
> [pricing](https://docs.ltx.io/pricing) / [llms.txt](https://docs.ltx.io/llms.txt)（2026年8月時点）

## 1. エンドポイントとモデル

- 生成は **async（V2）API** を前提にする（sync版も存在するが長時間処理なのでpolling方式が本番向け）:
  1. `POST /v2/text-to-video`（または image-to-video / audio-to-video）でジョブ提出 → job ID
  2. `GET .../jobs/{id}` で状態をポーリング（status値・保留ポリシーは async-jobs ドキュメント参照）
  3. 完了時に出力URL
- LTX-2.5 の利用可能エンドポイント: **text-to-video / image-to-video / audio-to-video** のみ
  （`retake` / `extend` / `reframe` は **LTX-2.5非対応** = LTX-2.3の機能）
- モデル変種: `ltx-2-5-fast`（最大4K・速い・安価）/ `ltx-2-5-pro`（最大1080p・高忠実度）

### サポート値（T2V/I2V）

| 変種 | 解像度 | FPS | 長さ(秒) |
| --- | --- | --- | --- |
| fast | 720p / 1080p | 24, 25 | 6〜20（6,8,10,12,14,16,18,20） |
| fast | 720p / 1080p | 48, 50 | 6, 8, 10 |
| fast | 1440p / 4K | 全fps | 6, 8, 10 |
| pro | 720p / 1080p | 24, 25, 50 | 6, 8, 10 |

- 縦横比: 16:9（1280x720 / 1920x1080 / 2560x1440 / 3840x2160）と 9:16（720x1280 等）のみ。
  **非標準アスペクト（例: 1920x1104）は最も近い標準解像度に落とす**（例: 1920x1080）—実装時の方針要確定
- 自動長さ: `"duration": null`（promptの内容からモデルが決定。`last_frame_uri`と併用不可）

## 2. 本ツールの出力 → APIフィールドのマッピング

| 本ツールの出力 | APIフィールド | 備考 |
| --- | --- | --- |
| `out/<video>/prompt.txt`（`--mode LTX`生成） | `prompt` | 自然言語プロンプトそのまま |
| 対象動画長（6〜20妥当値スナップ済み） | `duration` | または `null`（自動長さ） |
| 解像度（元動画の横/縦判定から） | `resolution` | 16:9 / 9:16 基準で割当 |
| 元動画fps | `fps` | 24/25 に丸め（fast） |
| キーフレーム `keyframes/first.jpg` | I2V `image_uri` | 事前アップロード（uploadエンドポイント）またはpublic URL が必要 |
| キーフレーム `keyframes/last.jpg` | I2V `last_frame_uri` | 指定すると末尾が固定→durationは固定値必須（自動長さ不可） |
| `analysis.json` の `camera_motion` | `camera_motion` | **APIのenum値へのマッピング要調査**（OpenAPI参照: docs.ltx.io/openapi.json） |
| 音声不要の場合 | `generate_audio: false` | 無音動画 |
| LTX用プロンプトの対白 | —（prompt内） | 音声はprompt記述から同時生成される（別途TTS不要） |

## 3. 呼び出し例（公式docsのcurlをそのまま）

```bash
curl -X POST https://api.ltx.io/v2/text-to-video \
  -H "Authorization: Bearer $LTX_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "model": "ltx-2-5-fast",
    "prompt": "<prompt.txtの内容>",
    "duration": 14,
    "resolution": "1920x1080",
    "fps": 24
  }'
```

（公式の自動長さ例: `"duration": null`。課金は実生成長で計算、prepaidは最大長分を先に確保）

## 4. 実装候補（`ltx_generate.py` あるいは `h3_video2prompt.py` への `--generate`）

1. 引数: `--api-key`（または `.env` の `LTX_API_KEY`）/ `--model ltx-2-5-fast|pro` / `--resolution` / `--fps`
2. `prompt.txt`（`--mode LTX`実行の出力）+ 必要なら `keyframes/` を読み込み
3. async提出 → job ID取得 → `--poll` 間隔でポーリング（完了まで。保留期限・失敗コードは async-jobs/errors ドキュメント準拠）
4. 出力動画URLを `out/<video>/generated.mp4` としてダウンロード
5. 設計上の判断点:
   - 生成呼び出しも **バックグラウンドジョブ** で（LLMと同様にサーバー占有注意は不要だが長時間）
   - `camera_motion` のenum値は OpenAPI（docs.ltx.io/openapi.json）で確認してから決める
   - I2Vの `image_uri` には upload エンドポイント（create-upload）経由のURLを使う想定

## 5. 未確認・要調査

- [ ] `LTX_API_KEY` の取得（console.ltx.io / 無料APIキー）—**ユーザー側で必要**
- [ ] `camera_motion` のenum値一覧（openapi.json）
- [ ] 非標準アスペクト動画の解像度割当ルール（cropかletterboxか、APIの挙動確認）
- [ ] I2V の入力画像制約（input-formats: フォーマット・サイズ・枚数）
- [ ] audio-to-video の制約（解像度・fps・長さの別テーブル）
- [ ] 課金（per-second単価、fast/pro差）— 実行前に pricing を確認
