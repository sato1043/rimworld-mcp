---
task: TASK0035
status: planning
features: []
requirements: []
relates-to:
 - TASK0018_outer-play-loop
---

# 入植者の読み出しで、日本語の名前を引けるようにする

## 目的

LLM が入植者を画面と同じ名前で指定して読めるようにする。今は日本語の名前を渡すと
見つからず、ThingID を探し直す手間と、見つからないことの取り違えが起きる。

## 目標（起票時の案）

- `/pawn/<id>/...` の読み出し（`get_pawn_inventory` 等）が、日本語の名前でも入植者を引く
- 同じ形の経路（パスに名前や ID を載せる読み出し）を洗い出し、同じ扱いにそろえる

## 非目標

- 名前の照合の規則（大文字小文字・部分一致）の変更

## 問題

- **実機で見つからなかった。** TASK0018 の実機シナリオ（2026-09-29）で、サイクルが
  `get_pawn_inventory` に「鷹」を渡すと `Pawn '%E9%B7%B9' not found` が返った
  （サイクルの報告）
- **パスを復号していない。** ブリッジは `ctx.Request.Url.AbsolutePath` で経路を振り分け
  （`MCPHttpServer.cs`）、`RequestRouter.HandlePawnPath` はパスを切り出してそのまま
  照合する。Mod の `Uri.UnescapeDataString` は `Events/EventQuery.cs` が問い合わせの
  引数を復号する 2 か所だけで、パスは復号しない（grep で確かめた）。`%E9%B7%B9` は
  「鷹」の UTF-8 の百分率符号化と一致する。
  `AbsolutePath` は ASCII でない文字を百分率符号化のまま返す（.NET の仕様。推論で、
  このゲームの Mono で確かめていない）
- **同じ経路を使う読み出しがすべて当たる見込みである。** `/pawn/<id>/` の下の
  mood・inventory 等。`mcp_server/main.py` で `/pawn/{pawn_id}` へ GET を送る tool は
  14 個ある。命令（POST）は名前を JSON の本文で渡すので当たらない（推論）
- **送る側も符号化していない。** `main.py` は `pawn_id` を f 文字列でそのままパスへ
  入れる。`/`・`?`・`#` を含む値は、別の経路や問い合わせとして読まれうる（推論）
- upstream へ送れる変更である

## 裁定記録

- **起票**（2026-09-29・ユーザー）: TASK0018 の実機で見つかった tool の不具合 3 件を、
  それぞれ作業書として起票する。thought のラベルが null の件は TASK0031 が扱う

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
