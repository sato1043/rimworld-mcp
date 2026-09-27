---
task: TASK0028
status: planning
features: []
requirements: []
relates-to:
 - TASK0012_tool-annotations
 - TASK0016_rimworld-play-skill
 - TASK0022_blueprint-footprint
---

# スキルの操作知識から、`place_blueprint` の説明文と重なる記述を除く

## 目的

スキル `rimworld-play` の操作知識が、tool の説明文と同じ事実を二重に持たないようにする。
片方だけが直って食い違うことを防ぐ。

## 目標（起票時の案）

- `references/tools.md`「命令の癖」のうち、直した `place_blueprint` の説明文と重なる
  2 項を、説明文に無い使い方だけへ絞る
- 重なる記述を出典に挙げる TASK0022 の非目標の書き方を合わせて改める

## 非目標

- `place_blueprint` の説明文の変更（TASK0012 で直した）
- 「命令の癖」の他の項の見直し

## 問題

- **スキルは「tool の説明文に無い使い方だけを書く」と定める**（`tools.md` の冒頭）。
  TASK0012 で `place_blueprint` の説明文へ、床とゾーンを置けないこと、向きと素材が既定へ
  倒れること、応答の `rotation` と `stuff` で結果が分かることを書いた。「命令の癖」の
  次の 2 項がこれと重なる
    - 「`place_blueprint` が置けるのは建物（ThingDef）だけである」
    - 「`place_blueprint` は、向きと素材の誤りを黙って既定へ倒す」
- **TASK0022 の非目標が前者を出典に挙げる。** 「床とゾーンを置くこと（`place_blueprint`
  の非対応。TASK0016 の `tools.md` に記載）」。項を削るなら、出典を説明文へ改める
- 「応答の `rotation` と `stuff` で結果を確かめる」は、説明文の事実を前提にスキルが
  どう動くかにあたるので、残す候補である

## 裁定記録

- **起票**（2026-09-27・ユーザー）: TASK0012 の未裁定の残課題（スキルと説明文の重なり）を
  起票する

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
