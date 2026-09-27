---
task: TASK0015
status: planning
features: []
requirements: []
relates-to:
 - TASK0007_serialization-failures
 - TASK0008_event-log
user-reach: high
dev-reach: low
drive: high
irreversible: low
hazard: none
---

# `/incidents` が説明どおり最近の letter を返すようにする

## 目的

`get_incidents` を呼んだ LLM が、tool の説明どおりに最近の letter を、書式タグの無い
ラベルで受け取れるようにする。

## 目標（起票時の案）

- `/incidents` が、記録にある letter のうち最も新しい 30 件を返す
- ラベルを `/events` と同じ取り方にそろえ、書式タグを含めない
- upstream へ送れる変更と、このフォークの変更に依存する変更を、別のブランチに分ける

## 非目標

- 応答のキー（`label`・`type`・`typeLabel`）の変更
- `get_incidents` と `get_events` の統合や、`get_incidents` の廃止
- `/messages` の変更

## 問題

- **`/incidents` は最も古い 30 件を返す。** ゲームの記録（`Find.Archive`）は古い順に
  並ぶ（TASK0008 で一次情報から確かめた）。`GameStateReader.GetIncidents` はその先頭から
  `Take(30)` で取る。tool の説明は「Recent archived game letters (up to 30)」で、
  `get_events` の説明も `get_incidents` が最近の letter を示すと書く。upstream の
  `upstream/main` も同じ `Take(30)` である
- **ラベルが書式タグを含むことがある。** 同じセーブで `/incidents` の 30 件と `/events` の
  letter を比べると、1 件だけ `/incidents` が `(*Name)…(/Name)` を含んだ（TASK0008 の
  残課題）。`/incidents` は `Label.RawText` で取り、`/events` は `ArchivedLabel` で取る
- **ラベルの変更は upstream へそのまま送れない。** `RawText` は TASK0007（`3483efc`）が
  1.6 の型の直列化の失敗を直すために入れたもので、upstream は `l.Label` を返す
- **並び順を決める必要がある。** 末尾から 30 件を取るとき、古い順のまま返すか新しい順で
  返すかで、呼ぶ側の読み方が変わる
- `GameStateReader` はゲームの型に依存し、自動テストで確かめられない。取り出す規則を
  純粋関数へ切り出すか（TASK0008 の `EventQuery` と同じ形）を計画で決める

## 裁定記録

- **起票**（2026-09-27・ユーザー）: TASK0008 の残課題 2 件（最も古い 30 件・書式タグ）を、
  1 本の作業書で直す。直す箇所と実機での確かめ方（同じセーブで前後の応答を比べる）が
  同じだからである。upstream へ送れるかはブランチで分ける
- **優先度**（2026-09-27・ユーザー）: `user-reach: high`（LLM が説明と逆の古い出来事を
  読む）・`dev-reach: low`・`irreversible: low`・`hazard: none` はエージェントの候補を
  承認した。`drive` は high と判定した

## stakeholder 未裁定の残課題

- 返す 30 件の並び順（古い順のまま・新しい順）
- 優先度の 4 軸と `drive`
- 決着（2026-09-27）: 上の優先度は、ユーザーが候補を承認し `drive` を判定した（裁定記録）
