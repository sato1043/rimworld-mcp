---
task: TASK0026
status: planning
features: []
requirements: []
relates-to:
 - TASK0016_rimworld-play-skill
---

# 加工の繰り返し方を tool で指定し、読めるようにする

bill（作業台の「加工」タブに並ぶ指示）は、ゲームの日本語表示に合わせて「加工」と呼ぶ。

## 目的

LLM が、加工を「在庫 X 個まで繰り返す」「無制限」でも出せるようにし、既存の加工が
どの繰り返し方かを読めるようにする。

TASK0016 の実機シナリオの途中（2026-09-27）で、LLM は先進機械部品の加工を足すとき、
既存の加工の回数を tool で読めないため、それを残したまま回数を指定した加工を別に
足した。

## 目標（起票時の案）

- `add_bill` で、繰り返し方（X 回繰り返す・在庫 X 個まで繰り返す・無制限）と目標の個数を
  指定できるようにする
- `get_production` で、各加工の繰り返し方・回数・目標の個数を読めるようにする
- upstream へ送れる変更と、この fork の変更に依存する変更を、別のブランチに分ける
- スキル `rimworld-play` の `references/tools.md`「命令の癖」から `add_bill` の行を消し、
  `get_production` の読み方を合わせて直す（fork ローカルの変更として分ける）

## 非目標

- 加工の細かい設定（材料の制限・技能の範囲・置き場所）
- 既存の加工を書き換える tool（要るかは計画で決める）

## 問題

- **`add_bill` は回数しか設定しない。** `CommandExecutor.AddBill` は
  `new Bill_Production(recipe)` を作り、`repeatCount` に `count` を入れるだけである
  （2026-09-27 に読んだ）
- **`get_production` は繰り返し方を返さない。** 加工ごとに `label`・`recipe`・
  `suspended` だけを返す（`GameStateReader.GetProduction`）。同じ作業台に同じレシピの
  加工が重なっても、呼ぶ側は見分けられない
- **繰り返し方はゲームの型が持つ**（推論。`Bill_Production.repeatMode` と
  `BillRepeatModeDefOf` の Forever・TargetCount・RepeatCount、目標の個数は `targetCount`。
  1.6 で確かめていない）。日本語表示は「X 回繰り返す」「在庫 X 個まで繰り返す」「無制限」
  （言語ファイル `BillRepeatModeDefs.xml`）
- 定石では料理の加工を「在庫 X 個まで繰り返す」にする（TASK0016 の `basics.md` の出典の
  Wiki）。今は利用者に頼むしかない

## 裁定記録

- **起票**（2026-09-27・ユーザー）: TASK0016 の実機シナリオで LLM が挙げた「tool に
  無くて困った操作」のうち、請求書の「X 個になるまで」を起票すると指示した
- **用語**（2026-09-27・ユーザー）: bill の訳は「請求書」でなく、ゲームの日本語表示の
  「加工」とする

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
- 既存の加工を書き換える tool も足すか
