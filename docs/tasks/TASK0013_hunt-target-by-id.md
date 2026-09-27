---
task: TASK0013
status: planning
features: []
requirements: []
relates-to:
 - TASK0006_overview-and-lean-reads
user-reach: high
dev-reach: low
drive: high
irreversible: low
hazard: none
---

# 狩りの標的を ThingID でだけ選ぶ

## 目的

`hunt_animal` が、意図しない動物（とくに飼育動物）を狩りの対象にしないようにする。

## 目標（起票時の案）

- ブリッジの狩りの指示が、標的を ThingID でだけ選ぶ。または、ラベルで選ぶ場合に飼育
  動物を除く
- 選び方の規則をゲームの型に依存しない形で切り出し、自動テストを残せるかを計画時に決める

## 非目標

- 他のコマンドの標的の選び方の変更（同じ形があれば計画時に範囲を決める）

## 問題

- **ブリッジの `Hunt` は、ラベルの一致でも標的を選ぶ。** `CommandExecutor.Hunt` は地図上の
  動物から、`ThingID` が一致するか `LabelShort` が大文字小文字を無視して一致する最初の
  1 頭を選ぶ。陣営で絞らないので、飼育動物も候補に入る
- **TASK0006 で、既定の出力から野生動物の ID が消えた。** `get_animals` の既定の出力は
  野生動物を種ごとの頭数にまとめる。ID を引くには `race` を渡す必要があり、LLM が種名を
  そのまま `hunt_animal` へ渡すと、名前の無い飼育動物に当たりうる（未実測の推論。TASK0006
  の CP6 の攻撃者視点の指摘）
- ラベルでの選択に頼っている利用者がいるかは分からない。変えると `hunt_animal` の
  振る舞いが変わる

## 裁定記録

- **起票**（2026-09-26・ユーザー）: TASK0006 の CP6 で起票と裁定された。Mod 側の変更で、
  TASK0006 の非目標にあたる
- **優先度**（2026-09-26・ユーザー）: `user-reach`・`dev-reach`・`irreversible`・
  `hazard` はエージェントの候補を承認した。`drive` は未判定
- **`drive`**（2026-09-26・ユーザー）: high と判定した

## stakeholder 未裁定の残課題

- ラベルでの選択をやめるか、ラベルで選ぶときに飼育動物を除くだけにするか
