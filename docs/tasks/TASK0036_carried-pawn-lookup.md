---
task: TASK0036
status: planning
features: []
requirements: []
relates-to:
 - TASK0018_outer-play-loop
---

# 運ばれている最中の入植者を読めるようにする

## 目的

救助で運ばれている入植者の容体を、LLM が運ばれている間も読めるようにする。今は
見つからないと返り、倒れた入植者がどこへ行ったのかを取り違えうる。

## 目標（起票時の案）

- 運ばれている最中の入植者を、ThingID でも名前でも、入植者の読み出しで引ける
- 引いた結果が、運ばれている最中であること（誰が運んでいるか）を示す

## 非目標

- キャラバンで移動中の入植者（マップの外）の読み出し

## 問題

- **実機で見つからなかった。** TASK0018 の実機シナリオ（2026-09-29）で、運ばれている
  最中の入植者を ThingID で引くと not found が返った（サイクルの報告）
- **マップに出現している入植者だけから引いている。** `GameStateReader.FindColonist` は
  `mapPawns.FreeColonistsSpawned` から探す。運ばれている入植者は運ぶ側の手に持たれ、
  出現していない（spawned でない）ので、この一覧に入らない（推論。運ぶ仕組みの
  `Pawn_CarryTracker` を確かめていない）
- **同じ探し方の呼び出し元が多い。** `FindColonist` は `GameStateReader` の読み出しの
  14 か所と、`CommandExecutor` の `Colonist()` を通した命令の 10 か所が使う。命令の側まで
  広げるかは、運ばれている最中に命令が意味を持つかで決める
- upstream へ送れる変更である

## 裁定記録

- **起票**（2026-09-29・ユーザー）: TASK0018 の実機で見つかった tool の不具合 3 件を、
  それぞれ作業書として起票する。thought のラベルが null の件は TASK0031 が扱う

## stakeholder 未裁定の残課題

- 命令の側（`FindColonist` を使う命令）まで広げるか
- 優先度の 4 軸と `drive`
