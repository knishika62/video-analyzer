# LTX-2.5 プロンプトガイド（IC-LoRA 系: Dub-It / Video Editing）

> LTX の IC-LoRA（video-to-video アダプタ）は、ベース生成（T2V/I2V）とは**別のプロンプト形式**を使う。
> 本ガイドは IC-LoRA 系ツールのプロンプティングパターンをまとめる。
> 出典（2026年8月時点の公式情報）:
> - 公式Docs [Prompting Guide › Prompting for Specific Capabilities › Dub-It](https://docs.ltx.io/api-documentation/implementation-guides/prompting-guide)
> - 公式Docs [Dub-It (IC-LoRA) Beta（機能ガイド全文）](https://docs.ltx.io/open-source-model/feature-guides/audio/dub-it-beta)
> - 公式ブログ [LTX-2.5 Prompt Guide](https://ltx.io/blog/ltx-2-5-prompt-guide)（Key Takeawaysに Video Editing IC-LoRA の形式）
> ベース生成の書き方は [`ltx-prompt-guide-base.md`](ltx-prompt-guide-base.md) を参照。

---

## 0. IC-LoRA とは

- 基盤モデルの生成を**既存動画から条件付け**して導くアダプタ（video-to-video）
- 通常、視覚コンテンツを変形するもの（Union Control / Motion Control / Relight 等）だが、
  **Dub-It は「音声の置き換え」に特化**した video-to-video ツール
- 各 IC-LoRA ツールには**専用のプロンプトフォーマット**があり、ベース生成の自然言語プロンプト流儀をそのまま使うと効かない

| IC-LoRA ツール | 用途 | プロンプトの性格 |
| --- | --- | --- |
| **Dub-It**（Speech Replacement） | 既存動画の発話を別/dialogueに置換（リップシンク再生成） | 固定テンプレート＋対白全文 |
| **Video Editing** | 既存動画の一部を編集（要素の変更・追加） | 1つの具体的・追加形（additive）指示 |
| （参考）Union Control / Motion Control | 構造化制御（キャラ置換、モーション指定等） | 制御パラメータ中心（本ガイド対象外） |

---

## 1. Dub-It（Speech Replacement / 発話置換）

### 何をするか
- 元動画の発話セグメントをプロンプト指定の新しいdialogueで再生成し、**リップシンクした出力**を生成
- 話者の**外見と声質（ボーカルアイデンティティ）を維持**
- リップ領域以外（動画全体）は保持
- 多言語吹替、または**元言語内での言い換え**に使える
- 実写・アニメ双方に対応
- ステータス: **LTX-2.3で検証済み / LTX-2.5対応は開発中**（beta）
- 検証済み言語: **英語・フランス語・スペイン語・ドイツ語・ロシア語**

### プロンプトテンプレート

```
[Speaker] is speaking [Language/Accent], saying: "[Dialogue]"
```

公式例:
```
A woman speaking in Russian saying: "Сегодня отличный день, чтобы протестировать рабочие процессы ComfyUI для дубляжа с использованием LTX."
```

- 感情・発話スタイルの詳細（トーン、速さ等）をテンプレートに追記可能
- 日本語例（構文上の例。検証済み言語外の使用は自己責任）:
  `A young woman speaking in Japanese saying: "こんにちは、今日はカフェにきました。"`

### 要件（Requirements）
1. **対白の全文を提供する** — モデルはプロンプトの内容をそのまま発話する。**翻訳はしない**（置き換える側のテキストを直接書く）
2. **ネイティブ文字を使う** — 対象言語の文字系で書く（ロシア語ならシリンル、中国語なら漢字等）
3. **単一話者** — beta IC-LoRA は複数話者を区別しない

### ベストプラクティス
- **音声長に合わせる** — 元dialogueと同じくらいのタイミング・モーラ（音節）数に保つ。**やや長めの方が短すぎるより良い**
  - 長すぎ: モデルが単語を飛ばす可能性
  - 短すぎ: 出力がゆっくりで不自然になる

### 実運用メモ
- 元動画の発話区間（ASR等でタイムスタンプ付き取得）と、置換後dialogueの長さ・モーラ数を照合してからプロンプトを作る
- ComfyUI/Pythonスクリプト両対応（2段階パイプライン: 低解像度生成→空間アップスケール→高解像度再生成）
- 参考: 負プロンプト `pc game, console game, video game, cartoon, childish, ugly`（公式ワークフロー既定）

---

## 2. Video Editing IC-LoRA（動画編集）

### 形式の要点（公式ブログ Key Takeaways 準拠）

> IC-LoRA tools (Dub-It, Video Editing) use their own formats: … **Video Editing works best with one concrete, additive-phrased instruction naming what changes and what stays.**

- **1つの具体的（concrete）な指示**で書く（複数命令の羅列を避ける）
- **追加形（additive phrasing）**: 「何を**加える/変える**か」を前向きに記述する
- **「何が変わり、何がそのまま残るか」を名指しする** —
  - 変わるもの（対象要素・変更内容）
  - 保持するもの（カメラワーク・構図・他の被写体・照明・音声 等）
- video-to-video であるため、元動画が条件付きになり、プロンプトは「差分の指示」に絞ると安定する

### 書き方のガイドライン（要点の具体化）
1. 変更対象を1つに絞る（例: 「女性のトップスを赤にする」「背景の雨を外す」）
2. 変更の**結果状態**を具体的・視覚的に書く（抽象命令ではなく見た目）
3. 明示的に「残すもの」を列挙して保持を強調（構図・カメラ・被写体のアイデンティティ・音声等）
4. ベース生成のような長いシーンプロンプトにしない（編集指示は短く）

> 注: 2026年8月時点で公式には Video Editing IC-LoRA 専用のフルガイドページは公開されていない。
> 上記は公式ブログ（LTX-2.5 Prompt Guide）の Key Takeaways と IC-LoRA 一般の設計思想から整理した要点。
> 公式の機能ページ（[editing-effects](https://docs.ltx.io/open-source-model/feature-guides/editing-effects/in-outpainting) 等）や更新されたブログが公開され次第、本節を更新する。

---

## 3. IC-LoRA 共通の注意点

- IC-LoRA 系は**元動画が条件**なので、プロンプトは「元動画との差分」を書く発想に切り替える（T2Vの「ゼロから絵を描く」ではない）
- 各IC-LoRAの**重み・強度パラメータ**（reference strength 等）が出力に強く効く。プロンプトとパラメータをセットで調整する
- ステータスを確認する（例: Dub-It は LTX-2.3検証済み・2.5は開発中）
- 検証済み言語・解像度・フレーム数の範囲を公式機能ガイドで確認してから使う
