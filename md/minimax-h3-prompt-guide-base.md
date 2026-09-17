# MiniMax H3 プロンプトガイド（ベースモード）

T2VA / I2VA / FL2VA / L2VA 用。MiniMax H3 の動画生成プロンプトを正しく書き、改写（rewrite）するためのリファレンス。
出典: [MiniMax-AI/MiniMax-H3 — base-en.txt](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt)

> **重要**: プロンプト本文（フィールド・セクション・記述）はすべて **英語** で書く。対白・歌詞・画面内の表示テキストのみ元の言語（日本語でも可）をそのまま保持する。

---

## 1. 4モードの違い

| モード | 入力の性質 | 書き方の要点 |
| --- | --- | --- |
| **T2VA** | テキストのみ | 音響+ビジュアルの完全なタイムラインをテキストから直接構築 |
| **I2VA** | テキスト + 先頭フレーム画像 | 先頭フレームをアンカーにして、そこから**前方へ発展**させる |
| **FL2VA** | テキスト + 先頭/末尾フレーム画像 | 先頭から末尾への**連続的なパス**を描く |
| **L2VA** | テキスト + 末尾フレーム画像 | 妥当な先行状態を推論し、末尾フレームへ**収束**させる |

- I2VA: T2VA本体 + 先頭フレーム指示 + 先頭フレームから前方発展するビジュアルパス
- FL2VA: T2VA本体 + 先頭/末尾フレーム指示 + 先頭フレームから末尾フレームへの連続パス
- L2VA: T2VA本体 + 末尾フレーム指示 + 妥当な先行状態から末尾フレームへ収束するパス

---

## 2. 最終プロンプトの構造

### 2.1 Part 1: 指示（画像アライメント指示）

**プロンプトの最初1行**に置き、その後に**1行のブランク**を挟んでコアフィールドから始める。

- **T2VA**: 画像アライメント指示は**不要**。3つのコアフィールドから直接始める。
- **I2VA**: 必ずこの固定文を使う:

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.
```

- **FL2VA**: 必ずこの形式を使う:

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot N) aligns with the S.SS-second mark of the target video.
```

- **L2VA**: 必ずこの形式を使う:

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot N]) aligns with the S.SS-second mark of the target video.
```

- `N` = 実際の最後のショットのインデックス
- `S.SS` = 実効的な動画の再生時間（**小数点以下2桁**でフォーマット。例: `8.00`, `6.00`）

### 2.2 Part 2: 3つのコアフィールド（この順番で）

```text
integrated_multimodal_description: [Shot 1] ...

overall_soundscape: ...

non_diegetic_music: ...
```

| フィールド | 内容 |
| --- | --- |
| `integrated_multimodal_description` | タイムラインに沿ったビジュアル・アクション・ショット・話者・対白・歌・ディー제ティック音（世界内音）の記述。**本文（本体）** |
| `overall_soundscape` | 動画全体にわたる環境音・物理アクション音・非言語的人間音の要約 |
| `non_diegetic_music` | 登場人物は聞こえず**観客だけが聞こえる**BGMの記述 |

---

## 3. キーフレームの取り込み方（integrated_multimodal_description 内）

### 3.1 I2VA: 画像から始まり前方へ発展

`<Picture 1>` は 0.00秒の実際の先頭フレームであり `[Shot 1]` に属する。
まず画像内のスタイル・被写体・構図・シーンアンカーを確立し、**その次に**次のアクションを記述する。
キャラクターの同一性・衣装・色・主要オブジェクト・空間関係は一貫性を保つこと。

推奨構造: **先頭フレームアンカー → アクション開始 → 連続的な発展 → 結果または反応**

### 3.2 FL2VA: 先頭/末尾フレーム間のパスを記述

Picture 1 が開始、Picture 2 が終了。被写体の移動・ポーズ変化・オブジェクト操作・構図の進化・シーン/照明の転換に焦点を当てる。

- FL2VAは原則**シングルショット**が望ましい（先頭フレームから末尾フレームへ連続補間するため）。複数ショットは明示指定時のみ。
- 末尾フレームは動画の終わりに最後の `[Shot N]` で到達しなければならない。

推奨構造: **先頭フレームの状態 → 観測可能な中間変化 → 段階的に狭まる差分 → 末尾フレームの状態**

### 3.3 L2VA: 開始を推論し、末尾で画像に着地

`<Picture 1>` は動画の**末尾フレーム**であり最後の `[Shot 1]`…ではなく最後の `[Shot N]` に属する（Shot 1 に属するわけではない）。
ユーザーの意図と末尾フレームから妥当な先行状態を推論し、キャラクター・オブジェクト・カメラ・シーンが参照画像に徐々に近づく過程を記述する。

推奨構造: **妥当な先行状態 → 明示的なアクションと転換パス → 最終ショットでの漸進的収束 → 末尾フレームへの着地**

---

## 4. 3つのコアセクションの書き方

### 4.1 タイムラインに沿って展開する（integrated_multimodal_description）

すべての詳細は視覚的に見えたり、耳に届いたりするものに対応させること: ビジュアルスタイル、初期構図、被写体の外見と位置、シーンと主要プロップ、アクションと反応、ショット変更、発話言語、同期するディージティック音。

`[Shot 1]` の冒頭で全体のスタイルと初期構図を明記する。
一般的なスタイル: `Cinematic`, `live-action`, `2D-animated`, `3D CG`, `claymation`, `watercolor`, `vintage film`。
キーフレームタスクでは参照画像からスタイルを導出し、T2VA ではユーザーのテキストから選ぶ。

```text
[Shot 1] Live-action, cinematic, a medium-wide shot frames...
```

> 可読性上の既定仕様（本パイプライン）: **各 `[Shot N]`（`[Shot 1]`を含む）の直前に改行を入れる**。
> `integrated_multimodal_description:` ラベルの直後に説明文が入るケースでも、`[Shot 1]` は必ず改行の先頭に来る（説明文はラベル行に残る）。
> 生成時はコード側の後処理（`format_shot_breaks`）が確実に挿入するので、LLM出力の改行の有無は問わない。

### 4.2 ショットとカット

- 最初のショットには**タイムスタンプを書かない**。
- 以降のショットは連番のショット番号を使い、**動画の長さ以内**で厳密に増加していくカット時刻から始める:

```text
[Shot 2] At 00:03.500, the camera cuts to...
```

- 通常のカットは `the camera cuts to` / `the shot cuts to` / `the shot transitions to` / `the shot changes to` / `the shot switches to` を使う。クロスディ졸ブ・フェード・ワイプはユーザーが明示要求した場合のみ。
- カットは被写体・空間・状態・視点（viewpoint）・時間のいずれかについて**新しい情報**を持ち込むこと。距離や軽いアングルの変化のみならカメラモーションを優先。

### 4.3 カメラモーション: 運動タイプ + 振幅 + 速度

完全なカメラモーション表現は3次元: **運動タイプ**（カメラがどう動くか）/ **振幅**（構図変化の範囲）/ **速度**（変化のペース）。
振幅と速度は意味がある場合のみ付加。中程度の振幅・通常速度は通常省略。

| 次元 | 表現 | 意味 |
| --- | --- | --- |
| 運動タイプ | `Zoom In / Zoom Out` | カメラ本体は固定で焦点距離が変わる |
| 運動タイプ | `Push In / Pull Out` | カメラが前進 / 後退 |
| 運動タイプ | `Pan Left / Pan Right` | 位置固定でレンズを水平に振る |
| 運動タイプ | `Truck Left / Truck Right` | カメラが水平方向に移動 |
| 運動タイプ | `Tilt Up / Tilt Down` | 位置固定でレンズを垂直に振る |
| 運動タイプ | `Pedestal Up / Pedestal Down` | カメラ全体が上昇 / 下降 |
| 運動タイプ | `Arc Shot` | 被写体の周りを弧に移動 |
| 運動タイプ | `Tracking Shot` | 動く被写体を追従 |
| 運動タイプ | `Static Shot` | カメラ位置とレンズが静止 |
| 運動タイプ | `Shake Slightly / Shake Strongly` | 軽い / 強いカメラシェイク |
| 運動タイプ | `POV` | 被写体の視点 |
| 運動タイプ | `Roll Clockwise / Roll Counterclockwise` | レンズ軸周りで時計回り / 反時計回りにロール |
| 振幅 | `with small amplitude` | 小範囲の変化 |
| 振幅 | `with large amplitude` | 大範囲の変化 |
| 速度 | `at slow speed` | 低速の移動 |
| 速度 | `at fast speed` | 高速の移動 |

文の末尾にラベルを積み上げるのではなく、**ショット内の自然な英語のアクションとして**書く:

```text
The camera pushes in with small amplitude at slow speed toward the folded letter in her hands.
The camera pans right with large amplitude at fast speed, revealing the open doorway.
The camera holds a static shot as the runner exits the frame.
```

### 4.4 話者・対白・歌

発話・歌唱・画面外の人間の声を発する被写体には `(S1)` `(S2)` などの安定IDを使う。
複数の番号済み話者が一緒に話す/歌う場合は `(S1,S2)` の複合ID。
話者はショット間で同じIDを維持。発声しないキャラクターには話者IDを付与しない。

話者が**初めて**登場する際は、安定したアイデンティティを確立するために視覚・音声コンテキストから十分な情報を与える（キャラクター種別、年齢、性別、画面上にあるか、ピッチ、音色、話速、アクセントなど）。
話者の識別フレーズ・ID・アクション・納品（delivery）は `<d>` の外に置く。`<d>` の内には言語タグとユーザー指定の発話内容のみを含める。元の言葉と句読点をそのまま保持し、翻訳や書き換えをしない。

```text
The young woman with a quiet, breathy voice (S1) says: <d>[English] I get off at the next station.</d>
The two children (S1,S2) shout together, <d>[English] Wait for us!</d>
```

**ナレーション（voiceover）**: 正確なフレーズ `says in an off-screen voiceover` を使い、voiceover の `<d>` ブロック直後に画面上のキャラクターの唇が閉じたままであることを明記する。

```text
The man (S1) says in an off-screen voiceover: <d>[English] I still remember that road.</d> while his lips remain completely closed.
```

**カットをまたぐ対白/歌詞**: 接続点の両方で `<scenetrans>` を使い、音声がカットを越えて継続することを明示。
動画の終わりで発話が途切れる場合は `<cutoff>` を使う。
連続性の表現例: `continues seamlessly across the cut` / `continues uninterrupted into the next shot` / `carries over from the previous shot` / `remains audible across the transition`

### 4.5 画面内のテキスト（On-Screen Text）

画面に実際に表示されるバナー・看板・ラベル・字幕・ネオン文字は**英語のダブルクォーテーション**で囲む。元のテキストと句読点をそのまま保持し、翻訳しない。

```text
A red neon sign reading "营业中" glows above the doorway.
```

### 4.6 overall_soundscape

1〜4文の英語を**1つの連続した段落**で、動画全体の環境音・物理アクション音・非言語的人間音を要約（風、雨、交通、足音、布の動き、衝突、呼吸、笑い、息切れなど）。
対白・歌唱・ディージティック音楽は multimodal description に既に含まれるので**ここで繰り返さない**。
`N/A` を使うのは、ユーザーが完全に無音の動画を明示要求した場合のみ。

```text
overall_soundscape: Steady rain taps against the café windows while low room ambience continues underneath. The entrance bell rings once, followed by wet footsteps and the soft scrape of a chair.
```

### 4.7 non_diegetic_music

1〜3文の英語で、登場人物は聞こえず観客だけが聞こえるBGMを記述。
楽器編成・速度・リズム・ダイナミック変化に焦点を当て、抽象的なムード語やスコアの感情的機能の説明は使わない。
キャラクターに聞こえる歌・楽器・ラジオ・テレビ・スマートフォンの音楽はディージティックイベントなので multimodal description に書く。
ノーディージティック音楽が無い場合は `N/A`。

```text
non_diegetic_music: Sparse piano notes at a slow tempo, joined by sustained low strings that gradually increase in volume before fading out.
```

---

## 5. 完全な例（4モード）

### Case 1: T2VA

参照画像なし。テキストから完全なタイムラインを直接構築。ユーザーの意図と整合するシーン・キャラクター・アクション・音の詳細を追加してよい。

```text
integrated_multimodal_description: [Shot 1] Live-action, cinematic, a medium-wide shot frames a baker opening the shutters of a small street bakery before sunrise. The camera pushes in with small amplitude at slow speed as the middle-aged baker with a calm, slightly raspy voice (S1) places a fresh loaf on the wooden counter and says: <d>[English] First batch of the morning.</d> [Shot 2] At 00:05.000, the camera cuts to a close-up of steam rising from the sliced bread while the baker's final words carry over from the previous shot.

overall_soundscape: Wooden shutters scrape open over a quiet street as trays clink softly inside the bakery. The doorbell rings once, followed by light footsteps and the crisp sound of bread being sliced.

non_diegetic_music: A soft acoustic-guitar pattern at a moderate tempo, joined by sparse upright-bass notes and a gentle fade at the end.
```

### Case 2: I2VA

先頭フレーム指示を先に書き、その後 Picture 1 の被写体・構図・シーンを Shot 1 の出発点としてからシーンの展開を記述。

```text
For the target video, at 0.00 seconds into the target video, <Picture 1> (from [Shot 1]) is fully referenced.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, the young woman shown in <Picture 1> remains beside the rain-covered train window, preserving her appearance, clothing, seat position, and the carriage layout. The camera trucks right with small amplitude at slow speed as she lifts her gaze from the folded letter toward the passing city lights. Her reflection moves across the glass while the quiet, breathy young woman (S1) says: <d>[English] I get off at the next station.</d> She folds the letter along its existing crease.

overall_soundscape: The train wheels produce a steady metallic rhythm beneath a low ventilation hum. Rain ticks against the window while paper rustles softly in her hands.

non_diegetic_music: Sustained cello notes at a slow tempo with widely spaced piano tones, gradually decreasing in volume.
```

### Case 3: FL2VA

2枚の画像がそれぞれ開始と終了をアンカー。本文では2枚の静的な画像記述を繰り返さず、両者を結ぶ**運動パス**を与える。（例は8秒のシングルショット）

```text
How the reference pictures align with the target video — Picture 1 (from Shot 1) aligns with the 0.00-second mark of the target video; Picture 2 (from Shot 1) aligns with the 8.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a rain-soaked cyclist begins in the position and framing established by Picture 1, holding a closed black umbrella beside a silver bicycle. The camera pulls out with small amplitude at slow speed as she releases the bicycle handle, raises the umbrella above her shoulder, and presses the runner upward until the canopy opens. Water rolls from the expanding fabric while she steps beneath it, rotates the handle into the final angle, and settles into the pose, spacing, and composition established by Picture 2 at the end of the shot.

overall_soundscape: Rain falls steadily on the pavement, followed by the metallic click of the umbrella runner and the soft snap of the canopy opening. Water drips from the bicycle frame as distant traffic passes.

non_diegetic_music: N/A
```

### Case 4: L2VA

画像は最後の瞬間のみをアンカー。先に互換性のある先行状態を確立し、アクション・オブジェクト状態・構図が最終ショットで Picture 1 へ段階的に着地させる。（例は6秒のシングルショット）

```text
How the reference pictures align with the target video — <Picture 1> (from [Shot 1]) aligns with the 6.00-second mark of the target video.

integrated_multimodal_description: [Shot 1] Live-action, cinematic, a close shot begins with an intact drinking glass near the edge of a dark wooden table, while the same hand and sleeve visible in <Picture 1> approach from the right. The camera pushes in with small amplitude at slow speed as the fingertips strike the rim. The glass tips, falls, and hits the floor with a sharp impact; cracks spread through it as fragments slide outward. Toward the end, the moving pieces lose momentum and settle into the exact broken arrangement, hand position, camera angle, lighting, and final composition established by <Picture 1>.

overall_soundscape: Fingertips tap the glass before it scrapes across the tabletop, falls, and breaks with a sharp crash. Small fragments scatter and gradually stop sliding across the floor.

non_diegetic_music: A low electronic pulse at a slow tempo, ending immediately after the glass breaks.
```

---

## 6. 書き方のTips（良い結果のために）

- 記述の**総再生時間は要求された動画長（4〜15秒）と一致**させること。
- 参照ラベル（`<Picture 1>`、`<Video 1>`、`<Audio 1>` など）は全セクションで一貫させる。
- "cinematic" や "beautiful" のような抽象語より、**具体的なビジュアル/オーディオの詳細**を優先。
- キーフレーム（I2VA / FL2VA / L2VA）を使う場合は、先頭/末尾フレームがタイムラインにどう接続されるかを明確に記述する。

## 7. 出力ルール（SKILL.md 準拠）

- 改写セクションは英語で書く。対白・歌詞・画面内表示テキストは元の言語を保持。
- 各ショットは構図・被写体・環境・アクション・カメラ・音、参照コンテンツが出現する正確なポイントを記述する。
- プロット要約、未解決の参照ラベル、要求時間と一致しないタイミングは避ける。
