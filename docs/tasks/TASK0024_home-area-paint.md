---
task: TASK0024
status: planning
features: []
requirements: []
relates-to:
 - TASK0016_rimworld-play-skill
 - TASK0023_fire-locations
---

# 居住エリアを tool で塗れるようにする

## 目的

LLM が、消火・掃除・修理の範囲である居住エリア（ホームエリア）を、利用者に頼まずに
広げたり狭めたりできるようにする。

TASK0016 の実機シナリオの途中（2026-09-27）で、LLM は大深度ドリルの小屋 2 か所の火災に
誰も消しに行かなかったと報告し、居住エリアの外だったためと推測した。居住エリアを塗る
tool が無いことを、困った操作の 1 つに挙げた。

## 目標（起票時の案）

- 居住エリアへ矩形のマスを足す・外すを指示できるようにする
- upstream へ送れる変更と、この fork の変更に依存する変更を、別のブランチに分ける
- スキル `rimworld-play` の `references/tools.md`「tool に無い操作」から居住エリアの
  塗り分けを消す（fork ローカルの変更として分ける）

## 非目標

- 屋根エリア（屋根を作る・作らない範囲）の塗り分け
- 許可エリアの操作の変更（`area_paint` の既存の範囲）

## 問題

- **`area_paint` は許可エリアしか受けない。** `CommandExecutor.AreaPaint` は、対象を
  `as Area_Allowed` で絞り、それ以外には「must be a mutable allowed area」を返す
  （2026-09-27 に読んだ）。居住エリアは `list_areas` に出るが、塗れない
- **既存の tool を広げるか、別の tool にするかを決める。** `area_paint` に居住エリアを
  許すと、同じ tool の意味が広がる。`list_areas` の `mutable` の意味との関係も見直す
- **入植者が自分から消すのは、居住エリアの中の火災だけである**（推論。1.6 で
  確かめていない）。TASK0023（火災の場所）と合わせると、場所を見て居住エリアへ足す、
  という手順が組める

## 裁定記録

- **起票**（2026-09-27・ユーザー）: TASK0016 の実機シナリオで LLM が挙げた「tool に
  無くて困った操作」のうち、居住エリアを塗ることを起票すると指示した

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
- `area_paint` を広げるか、別の tool にするか
