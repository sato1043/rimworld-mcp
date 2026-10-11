---
task: TASK0039
status: planning
features: []
requirements: []
relates-to:
 - TASK0018_outer-play-loop
---

# 入植者の行動範囲の設定を効かせる

## 目的

`set_allowed_area` で入植者の行動範囲を決めたとき、ゲームでその範囲が実際に効くように
する。効かなかったときは、成功を返さずに理由を返す。

## 目標（起票時の案）

- `set_allowed_area` が、1.6 の入植者の行動範囲（`Pawn_PlayerSettings` の
  `AreaRestrictionInPawnCurrentMap`）を設定する。`area_id` に -1 を渡すと制限を外す
- 設定の後に読み直し、設定した範囲が返ることを確かめてから成功を返す。書けなかったら
  理由を返す
- 実機で、設定した範囲が `get_pawn_area` と画面の両方に現れる

## 非目標

- 範囲の区域そのものの作成・塗り（`create_allowed_area`・`area_paint`）の変更
- 複数のマップ・キャラバンでの範囲

## 問題

- **実機で効かなかった。** TASK0018 の実機（2026-09-30）で、サイクルが「`set_allowed_area`
  が成功を返すのに区域が効かない」と報告した。tool の不具合かは確かめていない（サイクルの
  報告。この作業書の起票時点で再現はしていない）
- **書く側が 1.6 に無い名前を引いている。** `CommandExecutor.SetAllowedArea` は
  `Pawn_PlayerSettings` のプロパティ `AreaRestriction` をリフレクションで探し、
  `?.SetValue` で書く。見つからなければ何もせずに `Ok` を返す。1.6 の
  `Assembly-CSharp.dll` の文字列には `AreaRestriction` 単独の名前が無く、
  `AreaRestrictionInPawnCurrentMap` だけがある（2026-09-30 に grep で確かめた）。
  したがって、書き込みは黙って空振りしている見込みが高い（推論。dll のメタデータの
  文字列から名前の不在を読んだだけで、実行して確かめていない）
- **読む側は正しい名前を使っている。** `GameStateReader` は
  `pawn.playerSettings?.AreaRestrictionInPawnCurrentMap` を直に読む（コンパイルが名前を
  確かめる）。書く側だけがリフレクションなので、名前の変化がビルドで見つからなかった
- **同じ形の黙った既定値がほかにもある。** `GameStateReader` の `TryGetOutfitLabel`・
  `TryGetFloat`・`TryGetList` は、名前が見つからないと `unknown`・0・空を返す。読み出しの
  誤りが「値が無い」の顔で出る。この作業で扱うかは決めていない
- upstream へ送れる変更である

## 裁定記録

- **起票**（2026-09-30・ユーザー）: TASK0018 の実機でサイクルが報告した
  `set_allowed_area` の件は、TASK0018 の範囲の外で扱う

## stakeholder 未裁定の残課題

- リフレクションで名前を引くほかの 3 か所（`TryGetOutfitLabel`・`TryGetFloat`・
  `TryGetList`）まで広げるか
- 書いた後の読み直しを、ほかの書き込みの命令にも揃えるか
