# MiniMax H3 プロンプトガイド（Ref2VA / フルリファレンスモード）

Ref2VA（完全参照モード）の改写（rewrite）出力のフォーマットと書き方。
出典: [MiniMax-AI/MiniMax-H3 — ref-en.txt](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/ref-en.txt)

> **重要**: 全6セクションは **英語** で書く。元の言語を保持するのは、`<d>` 内の対白と歌詞、およびシーン内に視覚的に存在するテキストのみ。
> ショット・カメラモーション・話者・対白・通常の音の基本フォーマットは [ベースモードガイド](./minimax-h3-prompt-guide-base.md) と共通。本ガイドはフルリファレンスモード固有の参照ラベル・解析セクション・フォーマット差分に焦点を当てる。
>
> **記述の詳細さ**: `detailed_description` は極力詳細で明示的にする。各ショットについて、現在の構図・被写体外見と位置・環境と照明・アクションと状態変化・カメラモーション・現在の音・参照コンテンツが実際に出現・発効するポイントを明確に確立。プロット要約や参照関係リストへの縮約を避ける。

---

## 1. 全体の構造（6セクションの固定順序）

| # | セクション | 目的 |
| --- | --- | --- |
| 1 | `subject_definitions` | 参照コンテンツとそれらの参照ラベルを定義 |
| 2 | `summary` | タスク種別・対象動画・主な参照関係を要約 |
| 3 | `retention_analysis` | 参照コンテンツが保持・転送・再利用される方法を記述 |
| 4 | `detailed_description` | 再生順でビジュアル・アクション・ショット・音・対白を記述 |
| 5 | `overall_soundscape` | 環境音と物理音を要約 |
| 6 | `non_diegetic_music` | 観客だけが聞こえるBGMを記述 |

---

## 2. 参照ラベルと定義（subject_definitions）

4種類のラベルで参照コンテンツのソースと役割を識別する:

| ラベル | 意味 |
| --- | --- |
| `<Subject N>` | 参照アセットから抽出され、対象動画で再利用・修正可能な視覚コンテンツ |
| `<Picture N>` | 具体的なターゲットフレームやショット企画のアンカーとして使う参照画像 |
| `<Video N>` | 編集ソース・継続の開始点・動画全体の時間構造を提供する参照動画 |
| `<Audio N>` | コピーまたは参照される音声信号 |

> ラベルを一度コンテンツに割り当てると、その意味は `subject_definitions`、`summary`、`retention_analysis`、`detailed_description`、音声セクションすべてで**一貫**する。

`subject_definitions` は、後で個別に追跡する必要がある参照コンテンツ（人物、環境、ソース動画の構造、オーディオトラックなど）を定義する。各項目に**1行**を与え、そのラベルが何を指すか、参照としての役割、追うべき主要特徴を説明。出典を明示する必要があれば対応するソースアセットを名乗る。
`<Picture N>` や `<Video N>` が別の参照項目のソースの識別だけを行い、後で個別に分析・使用されない場合は、その項目の定義内から引用するだけで**別途行を設けない**。
`retention_analysis` は各参照項目の出現箇所と、完全保持・部分保持・転送・再利用のいずれかを記録する。

### 2.1 `<Subject N>`

再利用可能な視覚コンテンツに使う:
- 人・動物・オブジェクト
- シーン・背景・環境
- 衣装・小道具・インターフェース・視覚効果
- スタイル・アクション・表情・ポーズ

「ソースファイルそのもの」ではなく、実際に対象動画で使われる**コンテンツ単位**を表す。1つの subject が複数アセットで定義され、1アセットが複数 subject を提供してもよい。

```text
<Subject 1> is the young woman in <Picture 1>, with long dark hair, a blue cardigan, and a thin silver necklace.
```

同一 subject が複数アセット由来の場合、ソースを結合し各アセットが何を提供するかを明記:

```text
<Subject 1> is the woman whose appearance comes from <Picture 1> and whose walking motion comes from <Video 1>.
```

### 2.2 `<Picture N>`

参照画像自体がショットの先頭フレーム・キーフレーム・末尾フレーム・編集キーフレーム・構図アンカーとして機能する場合は**独立した `<Picture N>`** を使う:

```text
<Picture 2> is the first frame of [Shot 1], showing a woman seated beside a café window.
```

画像がキャラクター・シーン・衣装・スタイルの定義にのみ使われる場合は独立した picture エントリを作らない。対応する `<Subject N>` の定義内で画像ソースを引用する。

ストーリーボードやショット企画の参照として使う場合は、どのショットにマッピングし、どんな企画情報を提供するかを明記:

```text
<Picture 3> is a storyboard reference for [Shot 1] and [Shot 2], defining their viewpoint, subject placement, and shot order.
```

### 2.3 `<Video N>`

動画全体との関係に専用:
- 元動画の編集
- 元動画の末尾からの継続
- 元動画のカメラモーション・カット・リズム・時間構造の参照

```text
<Video 1> is the source video for the target video edit.
```

参照動画から人物・オブジェクト・シーン・アクション・効果を視覚コンテンツとして再利用する場合は、それでも `<Subject N>` に属する。`<Video N>` はアセットや構造のソースを識別し、subject ラベルに置きかわらない。

### 2.4 `<Audio N>`

独立した音声アセット、または参照動画の有効化された同期オーディオトラックを表す。一般的な用途:
- 音声信号の全部または一部のコピー
- BGMスタイルの参照
- 話者の声の音色とdeliveryの参照
- 元音声の対白・歌詞・効果音の使用
- ビート・リズム・音響連続性の参照

`<Audio N>` が対象話者に明示対応する場合、その話者のグローバルIDを再利用する: speaker が定義済み subject にマッピングされるなら `<Subject N> (Sx)`、そうでないなら安定した声の記述の後に `(Sx)`。このIDは対象動画のグローバルな話者順序から来て、音声定義で独立割り当て・再番号付けはしない。

```text
<Audio 1> is the voice-timbre reference for <Subject 1> (S1).
```

1つの音声アセットが複数役割を持つ場合、追加の小セクションを作らず1つの自然な文でその役割を記述。

### 2.5 同一参照動画からの映像トラックと音声トラック

`<Video N>` と `<Audio N>` は**独立に番号付け**される。各インデックスは自分カテゴリ内のラベル順序のみを示し、2カテゴリ間のペアリングをエンコードしない。したがって同一参照動画が `<Video 1>` と `<Audio 2>` に対応することもあり、インデックスが違っても同一ソースアセット由来で問題ない。

- 通常の参照動画は、ファイルに音が含まれているからといって自動的に `<Audio N>` を作成しない。
- `<Audio N>` の定義は主に音声の役割を述べ、来源の `<Video N>` を名乗る必要はない。出典の曖昧さを解消する必要時のみ共有ソースを明記:

```text
<Video 1> is the source video for the target video edit.
<Audio 2> is the synchronized audio track of <Video 1> and is reused in the target video.
```

---

## 3. `summary`

対象動画とその参照関係を1つの短い英語段落で要約。**角括弧のタスク種別プレフィックス**から始める:

```text
[reference generation] ...
[video editing + reference generation + audio reuse] ...
```

各参照アセットが対象動画で実際に果たす役割に応じてタスク種別を選ぶ:

| タスク種別 | 使用時 |
| --- | --- |
| `keyframe completion` | 画像が対象動画の先頭フレーム・キーフレーム・末尾フレーム・編集キーフレーム、その他の具体的なフレームアンカーとして機能 |
| `reference generation` | 画像・動画・音声アセットがキャラクター・シーン・スタイル・アクション・カメラモーション・ストーリーボードなどの生成ガイダンスを提供し、具体的フレームでも編集・継続されるソース動画でもない |
| `video editing` | 既存のソース動画が直接修正される。画像の編集や静止キーフレーム間の生成はこれに属さない |
| `video continuation` | 新しいコンテンツが既存ソース動画から継続・延長・再開・転換 |
| `audio reuse` | 同一音声信号が全部または一部再利用される |
| `audio reference` | 音声信号が直接コピーされず、音楽スタイル・音色・対白/歌詞内容・効果音の質感・ビート・連続性のみ参照 |

複数関係が同時に成り立つ場合は ` + ` でタスク種別を結合し、種別の重複をしない。
例: ソース動画から継続しつつ画像を末尾フレームにする → `[video continuation + keyframe completion]`。ソース動画を編集しつつ元音声を保持 → `[video editing + audio reuse]`。

- 動画や音声の単なる存在が自動的に対応タスク種別を作るわけではない。参照動画がカメラモーション・カット・リズムのみを提供する場合は、通常 `reference generation` に属する。`video editing` / `video continuation` はその動画が直接編集・継続される場合のみ。
- ソース動画を編集する際、元の音声が聞こえ続けると `audio reuse` も使う。ソース動画から直接音声信号をコピーせずに継続する場合、新しい音声が元のトラックの聴覚的特性のみ継続するなら `audio reference` を使う。
- `summary` は `subject_definitions` で定義済みラベルを用いて主要被写体・ショットの流れ・参照アセットの役割を記述する。**このセクションで新しい参照ラベルを導入しない**。
- 動画編集タスクでは、タスク種別プレフィックス直後に次を始める:

```text
The target video is an edited version of <Video 1>.
```

---

## 4. `retention_analysis`

各参照コンテンツが対象動画内で保存・転送・コピー・参照される方法を記述。各参照ラベルに1行を使い、`subject_definitions` で確立した意味を維持する。

### 4.1 視覚コンテンツの関係マーカー

`<Subject N>`、`<Picture N>`、`<Video N>` は以下を使う（出力フォーマット内の**固定英語値**）:

| マーカー | 意味 |
| --- | --- |
| `fully_preserved` | 定義された役割が完全に保持される |
| `partially_preserved` | 参照コンテンツは使われるが、定義された特徴の一部が変更または部分的保持 |
| `attribute_transfer` | 参照特徴が別の識別可能な対象 subject に転送される |
| `weak_reference` | スタイル・カテゴリ・構図・雰囲気での広範な類似のみ保持 |

エントリの形式:

```text
<Subject 1> (appears in [Shot 1], [Shot 3]): fully_preserved - ...
<Picture 2> ([Shot 1] first frame): fully_preserved - ...
<Video 1> (cut and pacing structure): weak_reference - ...
```

### 4.2 音声の関係マーカー

`<Audio N>` は以下を使う:

| マーカー | 意味 |
| --- | --- |
| `fully_copy` | 完全なソース音声が対象動画の完全な最終オーディオトラックとして機能 |
| `partially_copy` | タイムラインの一部または選択されたオーディオ層のみコピー、またはコピー後に音の追加・削除・置換 |
| `reference` | 信号は直接コピーされず、音色・リズム・音楽スタイル・対白内容・音の質感のみ参照 |
| `weak_reference` | カテゴリや雰囲気での広範な類似のみ保持 |

```text
<Audio 1>: fully_copy - <Audio 1> is reused 1:1 as the target video's complete final audio track.

<Audio 2>: reference - the target speaker follows <Audio 2>'s voice timbre and measured delivery without copying the original signal.
```

- 各マーカーは、そのラベルに対して `subject_definitions` で既に定義された参照役割の範囲内で**のみ**選ぶ。対象動画に新たに追加されたアクション・背景・プロットイベントを、参照忠実度の喪失として扱わない。

---

## 5. `detailed_description`

フルリファレンス改写の本体。対象動画の再生順でショット単位にビジュアル・アクション・音・対白を記述し、該当处で参照ラベルを挿入する。

### 5.1 基本フォーマット

ベースガイド（T2VA 等）に準ずる:
- 本文は英語。対白・歌詞・表示テキストは元の言語を保持。
- `[Shot 1]` は開始ショットでタイムスタンプなし。以降のショットは `[Shot N] At MM:SS.mmm, ...` でカット時刻を記す。
- カメラモーションは現在のショット内の自然な英語で、必要に応じて運動タイプ・振幅・速度を含める。
- 発声源に安定した `(S1)` `(S2)` 等のID。対白・歌詞は `<d>[Language] ...</d>`。
- カットをまたぐ対白・動画終わりで途切れる発話・ショット間を越える連続音に `<scenetrans>`、`<cutoff>`、対応する連続性記述を使う。

### 5.2 フルリファレンスモードの差分

| 次元 | T2VA | フルリファレンスモード |
| --- | --- | --- |
| 主要フィールド | `integrated_multimodal_description` | `detailed_description` |
| スタイル冒頭 | `[Shot 1]` の後に書く | `[Shot 1]` **より前に**1〜2文の英語で確立 |
| 参照情報 | フルリファレンスラベルを使わない | `<Subject N>`、`<Picture N>`、`<Video N>`、`<Audio N>` を初出現時と役割が適用される場所に挿入 |
| 音響関係 | 対象動画自身の音を記述 | 対応ショットまたは音声フェーズで `<Audio N>` を引用し、信号がコピーされるか参照されるかを明記 |

冒頭例:

```text
The target video is in a cinematic, literary music-video style with soft lighting and a slightly desaturated color palette.
[Shot 1] The scene opens in a crowded urban street...
[Shot 2] At 00:09.000, the shot cuts to an extreme close-up...
```

- 生成タスクでは `detailed_description` は通常 **350〜500語の英語**。対白の多いコンテンツでは、機械的な語数到達より**完全な発話タイムラインの収容を優先**。
- 動画編集の記述はソース動画の複雑さに比例し、生成タスクの範囲に従う必要はない。
- シングルショットだからといって記述が短くてよいわけではない。情報量に応じて複数ショットに詳細を配分する。

### 5.3 ショット内での参照ラベルの使い方

重要な `<Subject N>` が明確に初めて出現した際は、ショット内で実際に見えている範囲内で、参照された特徴・フレーム内位置・現在のアクションを記述する。以降のショットではラベルを再定義せず同じラベルを使い続ける。

具体的なフレームアンカーには自然な言い回しを使う:

```text
the shot begins from <Picture 1>
the shot's keyframe corresponds to <Picture 2>
the shot ends on <Picture 3>
```

元動画の編集・継続では、ソース状態・構造・継続関係が適用される場所に `<Video N>` を自然に引用。`<Audio N>` は音響関係が有効なショットまたは意味フェーズで引用。

### 5.4 話者・音声源・対白

基本の話者IDと `<d>` フォーマットは T2VA に従う。参照 subject が実際に発声する場合は、視覚参照ラベルと話者IDの**両方**を保持:

```text
<Subject 2> (S1) turns toward the woman and says, <d>[English] Last summer, I went to my grandfather's house. He talked about you.</d>
```

- `<Subject N>` は参照 subject を、`(Sx)` は実際の発声者を識別。subject が発声する場合は `<Subject N> (Sx)` と書く。同一 subject が画面外で発声する場合も同じ形式を維持し `off-screen` とマーク。話者が定義済み subject に対応しない場合は、安定した声の記述の後に `(Sx)` を使う。
- 発話コンテンツが直接再利用されるBGMや完全サントラの**クエ（手がかり）のみ**で、人・キャラクター・ナレータその他の独立した発声源が物理的に発音していない場合は、`<Audio N>` を可聴源として使い、追加の `(Sx)` を発明しない。逆に具体的な人・キャラクター・ナレータ等の独立した発声源が声を発している場合は、その源に `(Sx)` を割り当て再利用する:

```text
When <Audio 1> reaches the phrase <d>[English] I'm lonely lonely lonely lonely lonely I'm lonely</d>, <Subject 1> performs the corresponding hand gesture without becoming a separate speaker source.
```

- 参照音声の対白・ナレーション・歌詞を直接再利用するか、入力プロンプトが再パフォーマンスを明示要求する場合、`<d>` 内で正確なソース語と元の言語を保持。聞き取れないスパンは推測やパラフレーズ代りに `[unclear]` と書く。句読点は文を表現するために必要な基本書き記号（`,` `.` `?` `!`）に標準化し、重複したチルダ・絵文字・箇条書き・装飾的句読点を削除。完全な文・疑問文・感動文はそれぞれ `.`, `?`, `!` で `</d>` の前に閉じる。
- 音色・リズム・感情・deliveryのみ参照する場合は、参照音声の元の対白を対象動画に持ち込まない。
- `(Sx)` は対象動画内の**実際の発声イベントの順序**で一度だけ割り当て。`detailed_description` 内のすべての実際の発声イベントで対応IDを再利用する。`subject_definitions` で対象話者にバインドされた `<Audio N>` 定義も同じ `(Sx)` を再利用するが、独立に新しい `(Sx)` を割り当てない。`retention_analysis` には `(Sx)` を書かない。

---

## 6. `overall_soundscape` と `non_diegetic_music`

2つの音のカテゴリの定義はベースガイドに従う。

- `overall_soundscape` は動画全体の環境音と物理音を要約。対白・歌唱・特定ショットに同期した音イベントは `detailed_description` に残す。

```text
overall_soundscape: Quiet indoor room tone and a low ventilation hum continue throughout the video.
```

- `non_diegetic_music` は登場人物には聞こえず観客にだけ聞こえるBGM。音楽がある場合は楽器編成・テンポ・ダイナミクス展開を記述。

```text
non_diegetic_music: A restrained solo-piano score at a slow tempo, with sustained low cello underneath and no swell.
```

- 参照音声を使う場合は、コピー/参照関係を**可聴レイヤーに一致するセクションでのみ**記述: 環境音と効果音は `overall_soundscape`、観客限定スコアは `non_diegetic_music`。同一音声が両方の種類の内容を提供する場合、各セクションで対応関係を記述:

```text
overall_soundscape: The copied ambience layer from <Audio 1> continues throughout the target video.
non_diegetic_music: <Audio 2> is directly reused as the complete audience-only score.
```

- 完全な対白・歌詞は `detailed_description` 内の `<d>` でのみ書き、この2セクションで繰り返さない。

---

## 7. 完全な例（Ref2VA）

```text
subject_definitions:
<Subject 1> is the coffee-shop environment in <Picture 1>, featuring an exposed brick wall, an orange tufted sofa with patterned pillows, a neon sign, and a wooden coffee table.
<Subject 2> is the fluffy white Samoyed in <Picture 2>, <Picture 3>, and <Picture 4>, with thick white fur, pointed ears, a dark nose, and a curved tail.
<Subject 3> is the young blonde woman in <Video 1>, with long blonde hair and a light-pink button-down shirt with rolled-up sleeves.
<Subject 4> is the young man in <Video 2>, with short wavy brown hair and a dark-grey hoodie with drawstrings.
<Audio 1> is the voice-timbre reference for <Subject 3> (S1), containing a spoken English vocal layer.

summary:
[reference generation + audio reference] The target video shows <Subject 3> eating a cookie in <Subject 1>. <Subject 4> enters with <Subject 2>, which lunges toward the cookie. The three-shot exchange uses <Audio 1> as the voice-timbre reference for <Subject 3> and ends with a canned audience laugh.

retention_analysis:
<Subject 1> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - the exposed brick wall, orange tufted sofa, patterned pillows, neon sign, and wooden coffee table are retained.
<Subject 2> (appears in [Shot 1], [Shot 2]): fully_preserved - the Samoyed's thick white fur, pointed ears, dark nose, and curved tail are retained.
<Subject 3> (appears in [Shot 1], [Shot 2], [Shot 3]): fully_preserved - the blonde woman's identity, long hair, and light-pink shirt are retained.
<Subject 4> (appears in [Shot 1], [Shot 2]): fully_preserved - the young man's short wavy brown hair and dark-grey hoodie are retained.
<Audio 1>: reference - its vocal timbre guides the dialogue delivery of <Subject 3> without copying the original signal.

detailed_description:
The target video uses a realistic multi-camera sitcom style with warm indoor lighting.
[Shot 1] A medium shot establishes <Subject 1>, the coffee shop with its exposed brick wall, orange tufted sofa, patterned pillows, neon sign, and wooden coffee table. <Subject 3> (S1), the young woman with long blonde hair and a light-pink button-down shirt with rolled-up sleeves, sits on the sofa holding a chocolate-chip cookie. From the left, <Subject 4>, the young man with short wavy brown hair and a dark-grey hoodie with drawstrings, enters holding the leash of <Subject 2>, the thick-furred white Samoyed with pointed ears, a dark nose, and a curved tail. The dog lunges toward the cookie and pulls the leash taut. <Subject 3> (S1) jerks her hand back and, using the clear youthful voice timbre referenced from <Audio 1>, exclaims with light annoyance, <d>[English] Hey! Watch your dog!</d> She closes her lips and guards the cookie while <Subject 4> pulls the dog back.
[Shot 2] At 00:03.000, the shot cuts to a close-up of <Subject 4> (S2), the young man in the dark-grey hoodie from Shot 1, sitting beside <Subject 3> on the sofa and holding <Subject 2> securely in his arms. <Subject 4> (S2) says in a casual young male voice with a playful tone and an easy conversational pace, <d>[English] He just likes cookies more than me.</d> He closes his mouth into an apologetic smile and strokes the dog's thick white fur.
[Shot 3] At 00:05.000, the shot cuts to a close-up of <Subject 3> (S1), the blonde woman in the light-pink shirt from Shot 1. Her annoyance softens as she looks toward the Samoyed. <Subject 3> (S1) replies in the same clear youthful voice referenced from <Audio 1> with an amused cadence, <d>[English] Well, he has good taste at least.</d> She smiles and raises the cookie in a small toast-like gesture. A classic canned audience laugh begins immediately after the line and continues through the final frame.

overall_soundscape:
Soft indoor coffee-shop room tone continues throughout the scene.

non_diegetic_music:
N/A
```

---

## 8. ワークフローまとめ（SKILL.md 準拠）

1. 入力モードの特定: T2VA / I2VA / FL2VA / L2VA / Ref2VA（フルリファレンス）
2. ベース（テキスト/キーフレーム）モード: [base-en.txt](https://github.com/MiniMax-AI/MiniMax-H3/blob/main/skills/h3-prompt-writing/references/base-en.txt)（= このリポジトリの `minimax-h3-prompt-guide-base.md`）の最終プロンプト構造に従う
3. フルリファレンスモード: 本ガイド（`ref-en.txt`）の6セクション改写フォーマットに従う
4. 選択したガイドの**正確なフィールド名・セクション順序・ラベル・タイミング表記**を保持

### 出力ルール
- 改写セクションは英語で書く。対白・歌詞・画面内表示テキストは元の言語を保持。
- 各ショットは構図・被写体・環境・アクション・カメラ・音、参照コンテンツが出現する正確なポイントを記述。
- プロット要約、未解決の参照ラベル、要求時間と一致しないタイミングを避ける。

### 良い結果のためのTips
- 記述の総再生時間は要求された動画長（**4〜15秒**）と一致させる。
- 参照ラベル（`<Picture 1>`、`<Video 1>`、`<Audio 1>` など）は全セクションで一貫させる。
- "cinematic" "beautiful" 等の抽象語より具体的なビジュアル/オーディオ詳細を優先。
- キーフレーム（I2VA / FL2VA / L2VA）を使う場合、先頭/末尾フレームがタイムラインにどう接続されるかを明確に記述。
