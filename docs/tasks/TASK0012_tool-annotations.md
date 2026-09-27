---
task: TASK0012
status: planning
features: []
requirements: []
relates-to:
 - TASK0006_overview-and-lean-reads
user-reach: high
dev-reach: high
drive: high
irreversible: low
hazard: none
---

# 全ての tool に読み書きの性質を示す annotations を付ける

## 目的

MCP クライアントと LLM が、tool を呼ぶ前にそれがゲームを変えるかどうかを知れるようにする。

TASK0006 の CP6（攻撃者視点）で、ゲーム内の文字列（手紙のラベル・名前等）が状況把握の
出力に集まり、同じ文脈で書き込みの tool を呼べると指摘された。どの tool にも MCP の
annotations が無く、クライアントは読み出しと書き込みを区別して承認できない。TASK0006
では複合 tool にだけ `readOnlyHint` を付けた。

## 目標（起票時の案）

- 全ての tool を読み出しと書き込みに分け、MCP の annotations（`readOnlyHint`・
  `destructiveHint` 等）で示す
- 分類の規則を決め、新しい tool を足すときにも当てられる形にする

## 非目標

- tool の出力・引数の変更
- 書き込みの tool に確認の手順を足すこと

## 問題

- 85 の tool を 1 つずつ分類する必要がある。ブリッジの `GET` と `POST /command/...` の
  区別が手掛かりになるが、それだけで決まるかは確かめていない
- `destructiveHint`（取り消せない変化か）は、コマンドごとの判断を伴う（例: 解体・屠殺と、
  作業の優先度の変更）
- 付け忘れを検出する形（テスト等）が要る。TASK0006 のテストは複合 tool の 1 件だけを見る

## 裁定記録

- **起票**（2026-09-26・ユーザー）: TASK0006 の CP6 で起票と裁定された。85 の tool の
  分類が要り、TASK0006 の到達基準（3 つ以外の tool を変えない）の外にあたる
- **優先度**（2026-09-26・ユーザー）: `user-reach`・`dev-reach`・`irreversible`・
  `hazard` はエージェントの候補を承認した。`drive` は未判定
- **`drive`**（2026-09-26・ユーザー）: high と判定した

## stakeholder 未裁定の残課題

- `destructiveHint` を付ける基準（取り消せない変化の範囲）
- upstream へ送れる形にするか
