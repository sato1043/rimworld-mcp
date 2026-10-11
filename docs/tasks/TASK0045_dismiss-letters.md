---
task: TASK0045
status: planning
features: []
requirements: []
relates-to:
 - TASK0008_event-log
 - TASK0018_outer-play-loop
 - TASK0030_choice-letters
---

# 対応を終えた letter を tool で閉じられるようにする

## 目的

LLM が、対応を終えた letter を画面の letter の列から閉じられるようにする。

無人で回している間（TASK0018）、letter は画面に積もり続ける。2026-10-10 の回し直しでは、
家畜の死亡の letter だけで 24 回のサイクルが起き、どの回も対応は不要と判断したが、
letter は画面に残った。利用者が画面へ戻ったとき、対応の済んだものとまだのものが
見分けられない（利用者の要望からのエージェントの読み）。

## 目標（起票時の案）

- 画面に出ている letter を 1 つずつ指して閉じる命令と、それを呼ぶ MCP の tool を足す
- letter を指せるよう、letter の読み出しに識別子を持たせる
- 選択肢を持つ letter は閉じない（答える口は TASK0030 が持つ）
- スキル `rimworld-play` の 1 サイクルに、対応を終えた letter を閉じる手順を足す。無人の
  運用でどこまで閉じてよいかを決める
- upstream へ送れる変更と、この fork の変更に依存する変更を、別のブランチに分ける

## 非目標

- 選択肢のある letter に答えること（TASK0030）
- 画面の上に流れる短い通知（message）の消去
- 閉じた letter を画面へ戻すこと

## 問題

- **閉じる口が無い。** Mod のソースが letter の列に触れるのは読み出しの
  `GameStateReader.GetMessages`（`Find.LetterStack.LettersListForReading` の先頭 30 件）
  だけで、`mcp_server/main.py` にも閉じる tool は無い。2026-10-10 に読んで確かめた
- **letter を指す識別子が無い。** `get_messages` の応答は `label`・`type`・`typeDef`
  だけを持つ。同じラベルの letter が並ぶと指せない。出来事の記録（`get_events`）の項目も
  letter の列の項目と結び付いていない
- **閉じる API の候補は `LetterStack.RemoveLetter` である**（推論。`Assembly-CSharp.dll`
  にその名前の文字列が在り、実在しない名前は 0 件であることだけを 2026-10-10 に
  確かめた。振る舞いは実装の段で確かめる）
- **選択肢を持つ letter を閉じると、選ぶ機会を失いうる**（推論）。閉じられない letter も
  ありうる（`CanDismissWithRightClick` の名前が DLL に在る）。型で分ける必要がある
- **閉じても出来事の記録は残るはずである**（推論）。記録は Archive への追加から取って
  いる（`ArchiveAddPatch.cs`）。監視スクリプトは記録を読むので、合図には効かない見込みで
  ある。Archive から消える経路（`ArchiveRemovePatch.cs`）との関わりは確かめていない
- **「対応を終えた」の判定は LLM が行う。** 誤って閉じると、利用者が画面で気づく手がかりを
  失う。ゲームの「履歴」から読み返せるかは確かめていない
- 実機でしか確かめられない部分を含む（閉じた後の画面・セーブと読み込みをまたいだ状態）

## 裁定記録

- **起票**（2026-10-10・ユーザー）: TASK0018 の 8g の回し直しの後に、処置の済んだ
  letter を閉じる MCP の tool が欲しいと述べた。TASK0030 は選択肢を持たない letter の
  既読・消去を非目標にしているので、別の作業として起こす（エージェントの判定）

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
- 無人の運用で、サイクルが利用者の許可なく閉じてよい letter の範囲（例: 対応が不要と
  判断した良い出来事と家畜の死亡だけ・脅威の letter は残す）
- 識別子を `get_messages` へ足すか、`get_events` の項目へ足すか
