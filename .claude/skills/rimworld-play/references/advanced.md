# 応用攻略とクリアの経路

対象は RimWorld 1.6・DLC なし。Defs のパスはインストール先の `Data/Core/Defs` からの
相対で、最初の項目は 2026-09-27 に 1.6.4871 で読んだ。後から足す項目で版が違うときは、
その項目の出典に版を添える。書式と書き足し方は [../SKILL.md](../SKILL.md)
「攻略知識を書き足す」に従う。語はゲームの日本語表示に合わせ、defName を添える。

## クリアの経路

DLC なしのクリアは、自分で宇宙船を建てて打ち上げるか、クエスト「宇宙への旅」で知らされた
宇宙船へ行って打ち上げるかの 2 つである。どちらも打ち上げの操作は tool に無い（TASK0017）
ので、その段になったら利用者に頼む。

### 自分で宇宙船を建てる

- 宇宙船の部品を作れるようにする研究は 15 件あり、基本コストの合計は 48,100 である。
  内訳は、電気工学 基礎（1600）・鍛冶（700）・精密工作機械（1000）・マイクロエレクトロニクス
  基礎（3000）・マルチアナライザー `MultiAnalyzer`（4000）・組立製造 `Fabrication`（4000）・
  先進組立製造 `AdvancedFabrication`（4000）・長距離鉱物探査スキャナー
  `LongRangeMineralScanner`（2000）・冬眠カプセル `Cryptosleep`（2000）・宇宙船 基礎工学
  `ShipBasics`（4000）・宇宙船 反応炉 `ShipReactor`（6000）・ジョンソン-タナカ ドライブ
  `ShipEngine`（6000）・AIコンピュータコア `ShipComputerCore`（3000）・宇宙船センサー
  `ShipSensorCluster`（4000）・耐圧冬眠カプセル `ShipCryptosleep`（2800）。既定のシナリオでは
  電気工学 基礎が始めから済んでいる（[basics.md](basics.md)「研究」）
  - 出典: Defs（`ResearchProjectDefs/`。前提をたどって足した）
  - 確度: 高
- ゲームの研究画面の表示コストは、技術レベルの差で基本値と違うことがある
  - 出典: 推論（`get_research` の応答で確かめていない）
  - 確度: 低
- 宇宙船の研究は、ハイテク研究卓 `HiTechResearchBench` と、それにつないだマルチアナライザー
  `MultiAnalyzer` を要する
  - 出典: Defs（`ResearchProjectDefs/ResearchProjects_5_Ship.xml` の
    `ShipResearchProjectBase`）
  - 確度: 高
- 部品は、船体骨格 `Ship_Beam`・耐圧冬眠カプセル `Ship_CryptosleepCasket`・コンピュータコア
  `Ship_ComputerCore`・反応炉 `Ship_Reactor`・核物質エンジン `Ship_Engine`・船殻センサー束
  `Ship_SensorCluster` の 6 種である
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Ship.xml`）
  - 確度: 高
- 耐圧冬眠カプセルは、頭の側を船体骨格につないで置く
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Ship.xml` の `PlaceWorker_HeadOnShipBeam`）
  - 確度: 高
- 打ち上げには、核物質エンジン 3 基と、ほかの部品を 1 つずつつないだ船が要る
  - 出典: https://rimworldwiki.com/wiki/Ship
  - 確度: 中
- 最小の船の資材は、鋼鉄 1,740・プラスチール 740・ウラン 294・先進部品 40・部品 12・
  金 74・AI人格コア 1 である。Wiki の値は、核物質エンジン 3 基と他の部品・船体骨格を
  1 つずつとして Defs の `costList` を足した値と全項目で一致する
  - 出典: https://rimworldwiki.com/wiki/Ship、Defs（`ThingDefs_Buildings/Buildings_Ship.xml`）
  - 確度: 中（部品の数の前提が Wiki による）
- AI人格コア `AIPersonaCore` はコンピュータコアの材料で、作業台では作れない。手に入れる
  道はクエストの報酬などで、商人は在庫に持たない見込みである
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Ship.xml`・`ThingDefs_Items/Items_Exotic.xml`）、
    推論（Defs の tradeability が Sellable で、売れるが買えない値と読んだ）
  - 確度: 中
- 建設の技能は、船体骨格が 5、ほかの部品が 8 以上要る
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Ship.xml` の
    `constructionSkillPrerequisite`）
  - 確度: 高
- 部品は 6 種とも屋根の下に置けない。建設地の屋根を先に確かめる
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Ship.xml` の
    `PlaceWorker_NotUnderRoof`）
  - 確度: 高
- 反応炉を起動すると 15 日かかり、その間は襲撃を招く。起動の前に防衛を固める
  - 出典: Defs（`ResearchProjectDefs/ResearchProjects_5_Ship.xml` の `ShipBasics` の
    知らせの文）、https://rimworldwiki.com/wiki/Ship
  - 確度: 高
- 打ち上げには、耐圧冬眠カプセルが 1 つ以上埋まっていればよい。連れて行く入植者と動物は、
  それぞれカプセルを 1 つずつ要する
  - 出典: https://rimworldwiki.com/wiki/Ship
  - 確度: 中

### クエスト「宇宙への旅」で脱出する

- クエスト `EndGame_ShipEscape` は、letter「宇宙への旅」（英語の表示は Journey offer・
  Ship to the Stars）で届き、隠された宇宙船の位置をワールドマップに示す。そこへ行って
  起動し、起動が終わるまで襲撃から守ってから打ち上げる。宇宙船の地点が無くなるか、
  反応炉が壊されると失敗する
  - 出典: Defs（`QuestScriptDefs/Script_EndGame_ShipEscape.xml`・
    `Storyteller/Incidents_World_Quests.xml`）
  - 確度: 高
- 宇宙船の地点へ行くにはキャラバンが要る。キャラバンの編成と出発は tool に無い
  （TASK0017）
  - 出典: 推論（宇宙船はワールドマップ上の別の地点に置かれる）
  - 確度: 中
- このクエストは、ゲームの開始から 20 日が経つと、どの語り手でも 1 回だけ届く
  - 出典: Defs（`Storyteller/Storytellers.xml` の `BaseStoryteller`・
    `Storyteller/Incidents_World_Quests.xml`）
  - 確度: 中（届く前にゲームの実装が課す条件は確かめていない）

## 応用

プレイで確かめたことを足していく。
