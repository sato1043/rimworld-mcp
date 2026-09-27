---
task: TASK0017
status: planning
features: []
requirements: []
relates-to:
 - TASK0016_rimworld-play-skill
 - TASK0018_outer-play-loop
---

# クリアに要る操作を tool へ足す

## 目的

DLC なしのエンディング（宇宙船の打ち上げ・ジャーニーオファー）まで、LLM が tool だけで
到達できるようにする。

## 目標（起票時の案）

- 宇宙船を打ち上げる tool を足す
- ゲームをセーブする tool を足す
- キャラバンを編成し、目的地へ出発させる tool を足す
- upstream へ送れる変更と、この fork の変更に依存する変更を、別のブランチに分ける
- スキル `rimworld-play` の `references/tools.md`「tool に無い操作」と
  `references/advanced.md` から、足した操作を「tool に無い」とする記述を消す
  （fork ローカルの変更として分ける）

## 非目標

- DLC のエンディング
- キャラバンの交易・戦闘・ワールドマップ上の操作全般
- スキル（TASK0016）と外側のループ（TASK0018）の変更

## 問題

- **打ち上げ・セーブ・キャラバンの出発を行う tool が無い。** `mcp_server/main.py` の
  87 tool と `MCP/Source/MCP` を grep して確かめた（2026-09-27）。`get_caravans` は
  読み出しだけである
- **宇宙船の部品と研究は Defs で確かめた。** 部品は `Ship_Beam`・
  `Ship_CryptosleepCasket`・`Ship_ComputerCore`・`Ship_Reactor`・`Ship_Engine`・
  `Ship_SensorCluster` の 6 種（`ThingDefs_Buildings/Buildings_Ship.xml`）。研究は
  `ShipBasics` を前提に `ShipCryptosleep`・`ShipReactor`・`ShipEngine` が続く
  （`ResearchProjectDefs/ResearchProjects_5_Ship.xml`）。反応炉の起動から打ち上げが
  可能になるまでの条件は、ゲームの実装（`Assembly-CSharp`）で確かめる必要がある
  （未確認）
- **打ち上げは取り消せない。** ゲームの終わりにあたる。tool の誤呼び出しを防ぐ形
  （確認の引数・前提の検査）が要る
- **セーブは上書きになりうる。** 名前の付け方と、既存のセーブを上書きするかを決める
- **キャラバンの編成はゲームの UI（`Dialog_FormCaravan`）に寄る部分が多い**（推論）。
  UI を通さずに編成できる API があるかを確かめる必要がある
- いずれも実機でしか確かめられない。打ち上げは確かめるたびにセーブの状態を失う

## 裁定記録

- **起票**（2026-09-27・ユーザー）: クリアまで眺めるための論点のうち、tool が足りない点を
  1 本の作業書で扱う。TASK0016 の作業の分割の裁定による

## stakeholder 未裁定の残課題

- 優先度の 4 軸と `drive`
- 3 つの操作を 1 本の作業書で扱うか、操作ごとに分けるか
- セーブの上書きの扱い
- 打ち上げの誤呼び出しを防ぐ形
