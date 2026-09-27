---
task: TASK0027
status: planning
features: []
requirements: []
relates-to:
 - TASK0012_tool-annotations
---

# 5 つの書き込みの tool が同じ呼び出しの 2 回目で何をするかを確かめる

## 目的

クライアントが再試行を安全かどうか判断できるよう、`idempotentHint` を推測でなく
ゲームの振る舞いで決める。

## 目標（起票時の案）

- 次の 5 つの tool について、同じ引数の 2 回目がゲームに何をするかを確かめる
    - `place_blueprint`・`equip_item`（今は false。安全側へ倒した）
    - `draft_pawn`・`set_pause`・`assign_bed`（今は true。ゲーム本体の同値の扱いに依る）
- 確かめた結果と宣言が食い違えば、宣言・`main.py` の理由・テストの表・TASK0012 の表を直す

## 非目標

- 5 つ以外の tool の宣言の見直し
- Mod（C#）に 2 回目を止める分岐を足すこと（振る舞いを変えるのでなく、宣言を振る舞いへ
  合わせる）

## 問題

- **Mod 側に 2 回目を止める分岐は無い。** `CommandExecutor` の 5 つの実装は、ゲーム本体の
  メソッドをそのまま呼ぶ。2 回目の振る舞いは次のメソッドが決める（TASK0012 で読んだ）
    - `GenConstruct.CanPlaceBlueprintAt`（`place_blueprint`）
    - `Pawn_EquipmentTracker.AddEquipment`（`equip_item`）
    - `Pawn_DraftController.Drafted` の setter（`draft_pawn`）
    - `TickManager.Pause()`（`set_pause`。再開の側は代入で冪等）
    - `CompAssignableToPawn.TryAssignPawn`（`assign_bed`）
- **この機械にはデコンパイラが無い。** ゲームの Def は `Data` の XML で読めるが、C# の
  振る舞いは読めない。確かめる道は、デコンパイラ（ilspycmd 等）を入れて読むか、実機で
  同じ呼び出しを 2 回送るかである
- **true の側の誤りは危うい向きに倒れる。** `idempotentHint=true` は再試行を安全と
  伝える。ブリッジは 15 秒で 503 を返しても要求を後で実行するので、再試行は実際に
  2 回目の実行になる

## 裁定記録

- **起票**（2026-09-27・ユーザー）: TASK0012 の未裁定の残課題 2 件（`place_blueprint`・
  `equip_item` と、`draft_pawn`・`set_pause`・`assign_bed` の 2 回目の振る舞い）を、
  1 本の作業書で扱う。確かめ方が同じだからである

## stakeholder 未裁定の残課題

- 確かめ方（デコンパイラを入れるか、実機で送るか）
- 優先度の 4 軸と `drive`
