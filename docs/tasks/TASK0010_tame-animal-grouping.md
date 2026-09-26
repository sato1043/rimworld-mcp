---
task: TASK0010
status: planning
features: []
requirements: []
relates-to:
 - TASK0006_overview-and-lean-reads
user-reach: high
dev-reach: low
irreversible: low
hazard: none
---

# 飼育動物を種ごとにまとめる

## 目的

飼育動物が多いコロニーで、`get_animals` の既定の出力を小さくする。

TASK0006 は野生動物を種ごとの頭数にまとめたが、飼育動物は 1 頭ずつ残した。中盤のセーブ
では 205 頭のうち 135 頭が飼育動物で、`get_animals` の縮小は 3 つの tool の中で最も小さい
（-51.7%。[記録](../records/20260926_tool-output-size.md)）。既定の出力は飼育動物の頭数に
比例したままである。

## 目標（起票時の案）

- `get_animals` の既定の出力で、飼育動物を種ごとにまとめる
- 個体として扱う理由のある動物（名前の付いたペット・絆のある動物等）の扱いを決める
- 個体の一覧は、`race` か `detail=True` で引けることを保つ

## 非目標

- Mod（C#）の変更
- `get_animal_training` の出力の変更（こちらは訓練の状態を個体ごとに持つ）

## 問題

- **どの動物を個体として残すかは判断を伴う。** 名前の付いたペットや、入植者と絆のある
  動物は、頭数に畳むと LLM が名前で指せなくなる。ブリッジの `/animals` が持つ項目だけで
  見分けられるかは確かめていない
- 既定の出力の形を変えると、TASK0006 で変えた形をもう一度変えることになる。README の
  「Upgrading from an earlier version」も合わせて直す

## 裁定記録

- **起票**（2026-09-26・ユーザー）: TASK0006 の CP6 で起票と裁定された（性能効率性の
  指摘）。名前の付いたペットの扱いの設計が要るため、TASK0006 の内側で扱わない
- **優先度**（2026-09-26・ユーザー）: `user-reach`・`dev-reach`・`irreversible`・
  `hazard` はエージェントの候補を承認した。`drive` は未判定

## stakeholder 未裁定の残課題

- 個体として残す飼育動物の基準（名前の有無・絆・訓練の状態等）
