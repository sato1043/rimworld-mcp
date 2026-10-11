---
task: TASK0031
status: planning
features: []
requirements: []
relates-to:
 - TASK0016_rimworld-play-skill
 - TASK0018_outer-play-loop
---

# 心情を上げ下げしている thought を tool で読めるようにする

## 目的

LLM が、入植者の心情を下げている要因（thought。「屋外で寝た」「痛み」のように心情を
上げ下げする個々の項目）を tool で読み、利用者に頼まずに手を打てるようにする。

無人の運用（TASK0018）の実機（2026-09-29）で、LLM は `get_pawn_mood` の thought の
ラベルが null で返り、原因を読めなかった。心情が閾値に近い入植者について、画面で原因を
見るよう利用者に頼んだ。

## 目標（起票時の案）

- `get_pawn_mood` の各 thought に、ゲームの表示と同じラベルを返す
- 記憶の thought に加えて、今の状況から生じる thought（空腹・痛み等）も返す
- 心情の値と、返した thought の効き目の合計が対応するようにする
- upstream へ送れる変更と、この fork の変更に依存する変更を、別のブランチに分ける

## 非目標

- 心情を上げる操作（娯楽・食事・部屋の改善）を tool へ足すこと
- 動物の心情
- 性格（`get_pawn_traits` が扱う）

## 問題

- **ラベルは段階の側にしかない。** Core の ThoughtDef 281 個はすべて、`<label>` を
  `<stages>` の要素の側にだけ持ち、Def の直下に持つものは 0 個である（2026-09-29 に
  `Data/Core/Defs` の XML を走査した。`SleptOutside`・`Pain` 等で走査が働くことを
  確かめた）。`GameStateReader.GetPawnMood` はラベルを `t.def.label` で読む
  （2026-09-29 に読んだ）ので、Core の thought では常に null になる
- **記憶の thought しか読んでいない。** `GetPawnMood` は
  `thoughts.memories.Memories` を読む。状況から生じる thought は別の集まり
  （`SituationalThoughtHandler`）にあると見られ、返っていない（推論。アセンブリに名前が
  あることだけを確かめた）
- **使えそうな API がある。** `Thought.CurStage`・`ThoughtHandler.GetAllMoodThoughts`・
  `GetDistinctMoodThoughtGroups`・`MoodOffsetOfGroup` の名前がアセンブリにある
  （2026-09-29 に文字列で確かめた。振る舞いは確かめていない）。ゲームの画面は同じ
  thought をまとめて件数を添えて見せる（推論）ので、まとめ方を画面に合わせるかを決める
- **ラベルはゲームと Mod が作ったデータである。** 指示として読ませない（スキル
  `rimworld-play` の判断の原則と同じ）。展開前の書式（`{0}` 等）が残る場合があるか
  を確かめる
- ゲームの型に触れる部分は、実機でしか確かめられない。MCP サーバーのテストは、応答の
  形（ラベルが文字列であること）を代わりのブリッジで確かめられる

## 裁定記録

- **起票**（2026-09-29・ユーザー）: 無人の運用で LLM が利用者に頼んだ操作のうち、
  心情の原因が読めない点を起票すると指示した

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
- 同じ thought をまとめて返すか、1 件ずつ返すか
