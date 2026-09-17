# LTX-2.5 プロンプトガイド（ベースモード: T2V / I2V / A2V / マルチショット）

> Lightricks LTX-2.5（動画+音声同時生成モデル）向けプロンプト書きガイド（日本語まとめ）。
> 出典（2026年8月時点の公式情報）:
> - 公式Docs [Prompting Guide](https://docs.ltx.io/api-documentation/implementation-guides/prompting-guide)（.md版: 同URL＋`.md`）
> - 公式ブログ [LTX-2.5 Prompt Guide](https://ltx.io/blog/ltx-2-5-prompt-guide)（2026-08）
> - 公式ブログ [Prompting Guide for LTX-2](https://ltx.io/blog/prompting-guide-for-ltx-2)（2025-12 / LTX-2世代のTips。2.5でも大半は有効）
> - 公式Docs [LTX-2.5 モデル仕様](https://docs.ltx.io/models/ltx-2-5)
> IC-LoRA（Dub-It / Video Editing）固有のフォーマットは別ガイド [`ltx-prompt-guide-ic-lora.md`](ltx-prompt-guide-ic-lora.md) を参照。

---

## 0. モデル概要（プロンプト設計に影響する部分）

| 項目 | 内容 |
| --- | --- |
| 方式 | **動画と音声を1回で同時生成**（T2V / I2V / A2V） |
| 変種 | `ltx-2-5-fast`（速さ・低コスト / 最大4K）, `ltx-2-5-pro`（高忠実度 / 最大1080p） |
| 縦横比 | 横16:9・縦9:16 両対応（720p=1280x720/720x1280, 1080p=1920x1080/1080x1920, 1440p, 4Kはfastのみ） |
| 長さ | **6〜20秒**（6, 8, 10, 12, 14, 16, 18, 20。fast 24/25fps。高fps(48/50)は6/8/10まで。proは6/8/10） |
| マルチショット | **ネイティブ対応**（1回の生成でカット付き複数のショット。キャラ・景色・光・スタイル・声色が連続して維持される） |
| 音声 | プロンプトで音声を記述して生成。APIで `generate_audio: false` で無音可 |
| I2V | 先頭フレーム指定。`last_frame_uri`（末尾フレーム）も可能 |
| カメラ制御 | APIに `camera_motion` パラメータあり（プロンプト内のカメラ記述と併用可） |
| 自動長さ | `"duration": null` でプロンプト内容からモデルが長さを自動決定（`last_frame_uri` と併用不可） |
| 非対応 | retake / extend / reframe（これらはLTX-2.3 APIの機能） |

要点: **プロンプトは自然言語（英語）の1パラグラフ〜シナリオ体**。H3のような構造化フィールド（`integrated_multimodal_description` 等）や `<d>` 形式のラベルはない。**対白は二重クォート `"...")` で囲む**のが基本的な音声記述方式。

---

## 1. プロンプトに含めるべき6要素（Key Elements）

公式ガイドが挙げる中核。全要素を「始まりから終わりまで自然に流れる物語の完全な絵」として描く。

| # | 要素 | 内容 |
| --- | --- | --- |
| 1 | **Establish the Shot（ショットの提示）** | ジャンルに合った映画作りの語彙。ショットサイズ（wide/medium/close-up）やカテゴリ固有の特徴で視覚スタイルを絞る |
| 2 | **Set the Scene（シーンの設定）** | 照明、色パレット、表面テクスチャ、大気（雰囲気）でムードとトーンを設定 |
| 3 | **Describe the Action（アクション記述）** | コアアクションを、始まり→終わりまで明瞭に流れる自然な連続として書く |
| 4 | **Define the Character(s)（キャラクター定義）** | 年齢・髪型・服装・特徴的なディテール。**感情は抽象ラベル（"sad"等）ではなく身体的キュー**（姿勢・ジェスチャー・表情）で表現 |
| 5 | **Identify Camera Movement(s)（カメラワーク指定）** | いつ・どう移動するか。**移動後の被写体の見え方まで書くと、モデルがモーションを正確に完結させやすい** |
| 6 | **Describe the Audio（音声記述）** | 環境音・音楽・発話・歌唱を明記。**対白はクォート付き**、必要なら言語・アクセントを指定 |

---

## 2. プロンプトの構造（Structuring）

プロンプトは「1つの連続テイク」から「長いシナリオ風のシーン」まで幅があり、**描く内容に合わせて構造を選び、1つの形に強制しない**。
LTXは「明確なカメラ言語・一貫した照明・丁寧な音声記述を伴う映画的で被写体1つに焦点の絞れたシーン」に最も強く反応する。

### どの構造にも適用する原則
- **シーンを焦点化する** — 明確な少数のキャラとアクションが、混み合ったフレームより読みやすい
- **照明を一致させる** — 1ショットに1つの一貫した光ロジック。混在した光源は結果を乱す
- **シンプルに始めてレイヤーする** — コアショットから始めて、イテレーションで詳細を追加

### シンプル / シングルショット
1つの連続テイクには、短い流れの一文が最も効く:
- プロンプトは **1つの流れのあるパラグラフ**で書く
- アクション・移動は **現在形**の動詞
- 詳細度はショットサイズに合わせる（クローズアップはワイドより詳細を要する）
- カメラ移動は被写体に対する相対関係で記述
- 目安は **記述4〜8文**

### 長い / シナリオ風（Screenplay-Style）
対白・複数のビート・精密なタイミングを含むシーンは、シナリオ体で書く:
- シーンヘッダー（`INT. / EXT.` 形式）、キャラキュー（話者名+トーン注記）、クォート付き対白
-  fundamentals は同じ: 現在形・身体的感情キュー・対白はクォート
- 例: `Reporter (live):` / `Baker (whispering dramatically):` のような話者キュー

### 長さ
複雑度に合わせる（固定字数はない）。シンプルなシングルショットは4〜8文、シナリオ風は長くてもよいが、**各文が具体的な視覚/音声ディテールを追加していること**。

---

## 3. マルチショットプロンプト（LTX-2.5の目玉機能）

上記のシングルショット=1カメラテイク。LTX-2.5は **1プロンプト内で明示的なカットにより複数の異なるショットを繋いだマルチショットシーン** をネイティブに生成できる。

**書き方の基本: 全シーンを「時系列の1パラグラフ」（あるいは短い文の連続）で書く。**
ショットリスト・番号付きビート・シナリオのsluglineだけを使ってはいけない（カットをproseで説明する場合を除く）。

### マルチショットとシングルショットの差分

| | シングルショット | マルチショット |
| --- | --- | --- |
| カメラ | 1つの連続テイク | カットごとに新しい構図 |
| 転換 | カメラ移動のみ（pan, push-in等） | **編集を名付ける**: hard cut, match cut, dissolve等 |
| 連続性 | 同一空間・被写体が通し | 再登場する被写体を**再特定**。カットで何が続くかを明記 |
| 音声 | 1つの連続サウンドスケープ | **各カットで音楽/対白/環境音が継続するか変化するかを明記** |

### 各カット（cut）に入れるべきこと
1. **転換を自然言語で名付ける** — 例: 「A hard cut transitions to…」「The view cuts to a close-up of…」「A match cut connects…」「The image dissolves into…」
2. **新しいショットを再確立** — ショットサイズ、カメラアングル、フレーム内の被写体、照明（変われば）
3. **アイデンティティを一致させる** — 再登場する人・物は同じ視覚識別子を使い回す（"the woman in the red coat, earlier at the table, now…"）
4. **音声の連続性を明記** — 例: 「the piano score continues across the cut」「the dialogue drops; only wind remains.」

### 強いマルチショットを作るTips
- **1回あたり2〜4ショット**推奨。カットが増えるほど各ショットのビートは明確で短く
- 各ショットに明確な役割（establish → detail → reaction、wide → medium → close-up）
- アクションは時系列順（"Initially…" / "A moment later…" / "Simultaneously…"）
- シングルショットと同じルール適用: 現在形・身体的感情キュー・クォート対白・具体的カメラ言語
- カット間で地理の矛盾や説明のない衣装変化を避ける（意図的に時間/場所を飛ぶ場合はそう明記する）

### マルチショットの公式例（原文）

> A wide shot frames a rainy city intersection at dusk, neon signs reflecting on wet asphalt. A young woman in a yellow raincoat walks toward camera, gripping a folded newspaper, while cars hiss past behind her. Soft synth music and distant traffic fill the air. A hard cut transitions to a medium close-up of her face under the hood, raindrops catching the neon as she looks off-screen left; the synth score continues across the cut, traffic muffled. She whispers, "He's late." Another hard cut jumps to a low-angle shot of a man's scuffed boots stepping into a puddle at the curb; the music drops to a low drone. He lifts his head into frame — short dark hair, soaked jacket — and smiles toward her off-screen as a bus rumbles past.

（日本語要約: 夕暮れの雨の交差点のwide（黄色レインコートの女性がカメラへ歩く、合成音楽+交通音）→「hard cut」でhood下の彼女の顔のmedium close-up（スコア継続・交通音はミュート、囁き"He's late."）→「hard cut」で男性の磨き減った靴が水たまりに足を入れる低アングル（音楽は低いドローンに落ちる）、男性が顔を上げて画面外へ微笑む。）

### シングルショットで留める場合
- 途切れいないカメラモーション、親密な演技、**1つの構図でリップシンクを維持しなければならない対白**には連続テイクを
- 先頭フレームからのI2Vは、その開始画像から意図的に離れるカットを記述しない限り **連続テイクを優先**

---

## 4. 留意点（Keep in Mind — 未だ不器用な部分）

- **画面内テキスト**: LTX-2.5は短テキストの精度が以前より改善・細部保持も向上したが、**正確なスペルとフレーム間の一貫性は保証されない**。テキストは短く・大きくし、クリップ中ずっと確認し、重要なタイトル・ラベル・ロゴは**ポストで入れる**
- **複雑な物理**: 非常に混沌としたモーションは依然アーティファクトを生みうる。よりシンプル・妥当なモーションの方が信頼性が高い（ダンス等の日常モーションは問題ない）

---

## 5. 得意・不得意（LTX-2ブログより。2.5でも有効な大半）

### 得意（What Works Well）
- **映画的な構図**: 照明が考えられたwide/medium/close-up、浅い被写体深度、自然なモーション
- **感情のヒトの瞬間**: 単一被写体の感情表現、繊細なジェスチャー、 facial nuance
- **雰囲気と設定**: 霧・霞・黄金時間（golden hour）・柔らかな影・雨・反射・大気テクスチャがシーンを地に付ける
- **読みやすいカメラ言語**: 「slow dolly in」「handheld tracking」「over-the-shoulder」等の明確な指示が整合性を高める
- **スタイル化の美**: painterly / noir / アナログフィルム / ファッションエディトリアル / ピクセル化アニメ / スーリアル等。**プロンプトの早い段階で名乗る**と効く
- **照明とムードの制御**: バックライト、色パレット、柔らかなリム光、明滅するランプ。汎用的なムード語よりトーンを固定しやすい
- **声（Voice）**: 多言語での対話・歌唱が可能

### 避けるべき（What to Avoid）
- **内部状態のラベル**: "sad"「confused」等、視覚キューなしの感情ラベル → 姿勢・ジェスチャー・表情で
- **テキストとロゴ**: 可読で安定したテキスト生成には向かない（2.5でも短テキストは改善済みだが不保証）→ サイン・ブランド名・印刷物を避ける
- **複雑な物理・混沌したモーション**: 非線形・高速ねじれ（ジャンプ、ジャグリング等）はアーティファクト原因。ダンスは問題ない
- **シーンの複雑さ過多**: キャラ・アクション・オブジェクトの過剰は解像度と精度を下げる
- **照明ロジックの矛盾**: 「温かい夕日+冷たい蛍光灯」等、動機づけなき矛盾光源を避ける
- **過に複雑なプロンプト**: アクション/キャラ/指示を足すほど、一部が出力に反映されない確率が増す → **シンプルに始めてレイヤーする**

---

## 6. サンプルプロンプト（公式・原文）

### 例1: ニュース生中継（シナリオ風・単一テイクにカメラパン+カット風演出）

> EXT. SMALL TOWN STREET – MORNING – LIVE NEWS BROADCAST
> The shot opens on a news reporter standing in front of a row of cordoned-off cars, yellow caution tape fluttering behind him. The light is warm, early sun reflecting off the camera lens. The faint hum of chatter and distant drilling fills the air.
> The reporter, composed but visibly excited, looks directly into the camera, microphone in hand.
> Reporter (live):
> "Thank you, Sylvia. And yes — this is a sentence I never thought I'd say on live television — but this morning, here in the quiet town of New Castle, Vermont… black gold has been found!"
> He gestures slightly toward the field behind him.
> Reporter (grinning):
> "If my cameraman can pan over, you'll see what all the excitement's about."
> The camera pans right, slowly revealing a construction site surrounded by workers in hard hats. A beat of silence — then, with a sudden roar, a geyser of oil erupts from the ground, blasting upward in a violent plume.
> Workers cheer and scramble, the black stream glistening in the morning light. The camera shakes slightly, trying to stay focused through the chaos.
> Reporter (off-screen, shouting over the noise):
> "There it is, folks — the moment New Castle will never forget!"
> The camera catches the sunlight gleaming off the oil mist before pulling back, revealing the entire scene — the small-town skyline silhouetted against the wild fountain of oil.

（特徴: シーンヘッダー `EXT.`、話者キュー+ト注記（(live)/(grinning)/(off-screen)）、現在形、カメラ動作の明記（pans right / shakes / pulling back）、環境音の記述）

### 例2: 蛙ヨガ（アニメ風・対白・ビート）

> The camera opens in a calm, sunlit frog yoga studio. Warm morning light washes over the wooden floor as incense smoke drifts lazily in the air. The senior frog instructor sits cross-legged at the center, eyes closed, voice deep and calm. "We are one with the pond." All the frogs answer softly: "Ommm…" "We are one with the mud." "Ommm…" He smiles faintly. "We are one with the flies." A pause.
> The camera pans to the side towards one frog who twitches, eyes darting. Suddenly its tongue snaps out, catching a fly mid-air and pulling it into its mouth.
> The master exhales slowly, still serene. "But we do not chase the flies…" Beat. "not during class."
> The guilty frog lowers its head in shame, folding its hands back into a meditative pose. The other frogs resume their chant: "Ommm…" Camera holds for a moment on the embarrassed frog, eyes closed too tightly, pretending nothing happened.

（特徴: 照明・大気の記述、クォート対白、"Beat." の間表記、身体で出す感情（lowers his head in shame）、カメラ保持の明示）

### LTX-2時代の追加例（スタイル指定の参考）
- シングルアクション+カメラ: *"An action packed, cinematic shot of a monster truck driving fast towards the camera, the truck passes the camera, it pans left to follow the truck's reckless drive…"*
- 特定スタイル名乗: *"…pixar style acting and timing"* / *"sci-fi style cinematic scene"*

---

## 7. 補助語彙（Additional Helpful Terms）

結果の形を作るのに使える例示（網羅ではない）。

### カテゴリ（Categories）
- **Animation** — Stop-motion · 2D/3D animation · Claymation · Hand-drawn
- **Stylized** — Comic book · Cyberpunk · 8-bit pixel · Surreal · Minimalist · Painterly · Illustrated
- **Cinematic** — Period drama · Film noir · Fantasy · Epic space opera · Thriller · Modern romance · Experimental film · Arthouse · Documentary

### 視覚ディテール（Visual Details）
- **Lighting** — Flickering candles · Neon glow · Natural sunlight · Dramatic shadows
- **Textures** — Rough stone · Smooth metal · Worn fabric · Glossy surfaces
- **Color Palette** — Vibrant · Muted · Monochromatic · High contrast
- **Atmosphere** — Fog · Rain · Dust · Smoke · Particles

### 音と声（Sound and Voice）
- **Ambient Settings** — Coffeeshop noise · Wind and rain · Forest ambience with birds
- **Dialogue Style** — Energetic announcer · Resonant voice with gravitas · Distorted radio-style · Robotic monotone · Childlike curiosity
- **Volume** — Whisper · Mutter · Shout · Scream

### 技術スタイルマーカー（Technical Style Markers）
- **Camera Language** — Follows · Tracks · Pans across · Circles around · Tilts upward · Pushes in / pulls back · Overhead view · Handheld movement · Over-the-shoulder · Wide establishing shot · Static frame
- **Film Characteristics** — Film grain · Lens flares · Pixelated edges · Jittery stop-motion
- **Scale Indicators** — Expansive · Epic · Intimate · Claustrophobic
- **Pacing & Temporal Effects** — Slow motion · Time-lapse · Rapid cuts · Lingering shot · Continuous shot · Freeze-frame · Fade-in / fade-out · Seamless transition · Sudden stop
- **Visual Effects** — Particle systems · Motion blur · Depth of field

---

## 8. 本パイプラインの既定仕様（プロジェクト固有）

- **日本語の対白・歌詞はひらがなへ変換して出力する**（漢字・カタカナを含む表記は不可）。
  例: 「今日は六本木をブラブラしてるんだけどいいお店ないかな?」→「きょうはろっぽんぎをぶらぶらしてるんだけど いい おみせ ない かな?」
  - 変換は Pass2（改写）でLLMに行わせる。コード側はクォート内に漢字(U+4E00〜U+9FFF / U+3400〜U+4DBF)・
    カタカナ(U+30A0〜U+30FF)が残っていないかを検査し、混入時は実行ログに警告を出す
  - 他の言語の対白は原文のまま（LTXの一般的な仕様を変えるものではない）

## 9. 書き出しチェックリスト（要約）

0. [ ] **日本語の対白・歌詞はひらがなのみ**（漢字・カタカナなし: 「今日は六本木を…」→「きょうはろっぽんぎを…」）※本パイプラインの既定仕様。他言語は原文のまま
1. [ ] ジャンル/スタイルを早い段階で名乗っているか（cinematic / noir / animated / 8-bit…）
2. [ ] ショットサイズ+カメラアングルを最初に提示しているか
3. [ ] 照明・色・大気を1つの一貫したロジックで設定しているか
4. [ ] アクションは現在形で、始まり→終わりまで自然に流れているか
5. [ ] キャラは年齢・髪・服装・特徴で特定し、感情は身体キューで表現しているか
6. [ ] カメラ移動（+移動後の被写体の見え方）を書いているか
7. [ ] 音（環境音/音楽/対白/歌唱）を記述し、対白は `"..."` で囲んでいるか
8. [ ] マルチショットなら各カットで「転換名+新構図の再確立+アイデンティティ維持+音声連続性」を入れているか
9. [ ] 画面内テキストは短く・重要ならポスト前提か
10. [ ] 1回2〜4ショット・文数4〜8から開始し、シンプルにレイヤーしているか
