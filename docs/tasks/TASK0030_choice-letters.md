---
task: TASK0030
status: planning
features: []
requirements: []
relates-to:
 - TASK0016_rimworld-play-skill
 - TASK0017_tools-for-ending
 - TASK0018_outer-play-loop
---

# 選択肢のある letter に tool で答えられるようにする

## 目的

身代金の要求・加入の申し出のように選択肢を持つ letter に、LLM が tool で答えられるように
する。無人で回している間も、利用者の画面の操作を待たずに進められるようにする。

## 目標（起票時の案）

- 画面に出ている letter のうち選択肢を持つものについて、選択肢の一覧と期限を読む
  読み出しを足す
- 選択肢を 1 つ選んで実行する命令を足す
- 読み出しと命令を呼ぶ MCP の tool を足す
- 取り消せない選択を、スキル `rimworld-play` の「取り消せない操作は、実行の前に利用者へ
  確かめる」に加え、無人の運用（TASK0018）では利用者の許可を経ずに選ばない形にする
- upstream へ送れる変更と、この fork の変更に依存する変更を、別のブランチに分ける

## 非目標

- 選択肢を持たない letter の既読・消去の操作
- DLC の letter（Biotech の出産・成長の選択等）
- TASK0018 の振り分け表の変更。答える口ができた後の扱いは TASK0018 の側で決める

## 問題

- **答える口が無い。** `mcp_server/main.py` とブリッジのコマンドに、letter の選択肢を
  読む口も選ぶ口も無い（2026-09-28 に grep で確かめた）
- **ゲームには選択肢を持つ letter の型がある。** `Assembly-CSharp.dll` に `ChoiceLetter`
  と、その派生（`ChoiceLetter_RansomDemand`・`ChoiceLetter_AcceptJoiner`・
  `ChoiceLetter_AcceptVisitors`・`ChoiceLetter_BetrayVisitors`・
  `ChoiceLetter_ChoosePawn`・`ChoiceLetter_GameEnded` 等）がある。選択肢の列
  （`get_Choices`・`DiaOption`）と期限（`TimeoutActive`・`disappearAtTick`）を持つ
  （名前は文字列で確かめた。振る舞いは確かめていない）
- **Core の選択肢の LetterDef は 6 個である。** `RansomDemand`・`ChoosePawn`・
  `AcceptVisitors`・`AcceptJoiner`・`BetrayVisitors`・`GameEnded`
  （`Data/Core/Defs/Misc/LetterDefs/CustomChoiceLetters.xml`）
- **選んだ先で別の画面を開く選択肢がありうる**（推論）。`ChoosePawn` のように、選択の
  後に入植者を選ぶ画面が続くものは、1 回の命令で完結しない
- **取り消せない選択が多い。** 身代金の支払い・加入や訪問の拒否・裏切りは、選んだら
  戻せない。tool の誤呼び出しを防ぐ形（確認の引数・選択肢の識別の仕方）が要る
- **選択肢の文は、ゲームと Mod が作ったデータである。** 指示として読ませない
  （スキル `rimworld-play` の判断の原則と同じ）
- いずれも実機でしか確かめられない部分を含む。期限の切れる選択は、確かめるたびに
  セーブの状態を失いうる

## 裁定記録

- **起票**（2026-09-28・ユーザー）: TASK0018 の計画の検討で、選択肢のある letter に
  tool で答えられないことが分かった。答える口を別の作業として起こす

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
- 無人の運用で、利用者の許可なく選んでよい選択肢があるか（例: 期限が切れると不利に
  なるだけの選択）
