---
task: TASK0009
status: planning
features: []
requirements: []
relates-to:
 - TASK0006_overview-and-lean-reads
user-reach: high
dev-reach: high
irreversible: low
hazard: none
---

# tool の出力から JSON の字下げを除く

## 目的

LLM が tool の出力に払うトークンを、中身を変えずに減らす。

TASK0006 の計測（[記録](../records/20260926_tool-output-size.md)）で、FastMCP が tool の
戻り値を 2 桁字下げの JSON にしていると分かった。整えた後の 3 つの出力を字下げと区切りの
空白を除いた JSON にすると、36〜40% 縮む（`dict` を返す 2 つは実際の出力とほぼ同じ量で
測った）。字下げは全ての tool に付いている。

## 目標（起票時の案）

- 全ての tool の出力を、字下げと区切りの空白を除いた JSON にする
- 出力の中身（キーと値）は変えない
- 変更の前後の出力の大きさを実測し、記録へ残す（記録層）

## 非目標

- 出力の中身を絞ること（TASK0006 が扱った）
- Mod（C#）の変更
- resource の出力（すでにブリッジの本文をそのまま返している）

## 問題

- **FastMCP の変換は戻り値の型で分かれる。** `dict` は 1 つのテキストブロック、`list` は
  要素ごとのブロック、`str` はそのまま渡る（`mcp` 1.27.1 の `func_metadata.py` の
  `_convert_to_content`）。文字列にして返すと、`list` を返す tool のブロックの分け方も
  変わる
- **戻り値の型注釈が合併型だと、structured content として同じ結果をもう一度送る。**
  TASK0006 の `get_animals` がこれに当たり、`structured_output=False` で塞いだ。全 tool を
  文字列にする形なら、出力スキーマの扱いも同時に決まる
- 85 の tool に一律に効かせるので、個別に書き換えるより、FastMCP の変換の手前で 1 箇所に
  寄せる形が要る。upstream へ送れる形にするかは計画時に決める
- `list` を返す tool の実際の出力に対する割合は測っていない（TASK0006 の記録の注記）

## 裁定記録

- **起票**（2026-09-26・ユーザー）: TASK0006 の計測で字下げの割合が分かり、「削って
  ほしい」と裁定された。TASK0006 に混ぜず別の作業書で扱う
- **優先度**（2026-09-26・ユーザー）: `user-reach`・`dev-reach`・`irreversible`・
  `hazard` はエージェントの候補を承認した。`drive` は未判定

## stakeholder 未裁定の残課題

- upstream へ送れる形にするか（全 tool に効く変更で、upstream の出力も変える）
- `list` を返す tool を 1 つのテキストブロックにまとめてよいか。要素ごとのブロックを
  前提にしたクライアントがあれば振る舞いが変わる
