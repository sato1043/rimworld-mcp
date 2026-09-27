# 基本攻略

対象は RimWorld 1.6・DLC なし。Defs のパスはインストール先の `Data/Core/Defs` からの
相対で、最初の項目は 2026-09-27 に 1.6.4871 で読んだ。後から足す項目で版が違うときは、
その項目の出典に版を添える。書式と書き足し方は [../SKILL.md](../SKILL.md)
「攻略知識を書き足す」に従う。tool で行えない操作は [tools.md](tools.md)「tool に無い操作」
を見て、利用者に頼む。語はゲームの日本語表示に合わせ、研究には defName を添える。

## 着地した直後

- 着地したら、まずゲームを止めてから状況を見る
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 最初の夜までに、ベッドを入れた木造の部屋（7×7 程度）を 1 つ建てる
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 持ち込んだ物資は屋外で傷むので、屋根の下の倉庫ゾーンへ早く入れる
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 「優先順位」画面で、消火・瀕死・病人・雑用を全員 1 にする
  - 出典: https://rimworldwiki.com/wiki/Basics、Defs（`WorkTypeDefs/WorkTypes.xml`）
  - 確度: 中（仕事の種類の日本語表示は言語ファイルの `labelShort` による）

## 食料

- 収穫物は常温で、米が 40 日、トウモロコシが 60 日、ジャガイモが 30 日で腐り始める
  - 出典: Defs（`ThingDefs_Items/Items_Resource_RawPlant.xml` の `daysToRotStart`）
  - 確度: 高
- 冬が来る前に、食料を 1000 単位ほど蓄える
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 冷凍庫は、扉 1 枚の部屋に冷却器を置き、冷える側を室内へ向けて 0°C 未満（-5°C 程度）に
  設定する
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 生の食材をそのまま食べると気分が下がるので、簡単な食事を作らせる
  - 出典: https://rimworldwiki.com/wiki/Basics
  - 確度: 中

## 研究

- 既定のシナリオの入植者は、電気工学 基礎 `Electricity`・空調設備 `AirConditioning`・
  栄養補給ペースト `NutrientPaste`・ストーンカッター `Stonecutting` 等を済ませた状態で始まる。
  研究の道筋に入れる前に `get_research` で済んでいるかを見る
  - 出典: Defs（`FactionDefs/Factions_Player.xml`・`ResearchProjectDefs/`）
  - 確度: 中（タグ `ClassicStart` は Defs で確かめた。タグの付いた研究を済ませる働きは
    ゲームの実装にある）
- 序盤の研究の前提とコスト（基本値）は次のとおり
  - 電気工学 基礎 `Electricity`（1600）→ バッテリー `Batteries`（400）・太陽光発電
    `SolarPanels`（600）・水力発電 `WatermillGenerator`（700）・空調設備 `AirConditioning`
    （500）・水耕栽培器 `Hydroponics`（700）・栄養補給ペースト `NutrientPaste`（400）
  - 鍛冶 `Smithing`（700）と電気工学 基礎 → 精密工作機械 `Machining`（1000）→ ガンスミス
    `Gunsmithing`（500）
  - ストーンカッター `Stonecutting`（300）は前提を持たない
  - マイクロエレクトロニクス 基礎 `MicroelectronicsBasics`（3000）は電気工学 基礎だけを
    前提にする。これより先の多くはハイテク研究卓 `HiTechResearchBench` を要する
  - 出典: Defs（`ResearchProjectDefs/ResearchProjects_1.xml`・
    `ResearchProjectDefs/ResearchProjects_2_Electricity.xml`・
    `ResearchProjectDefs/ResearchProjects_3_Microelectronics.xml`）
  - 確度: 高
- 定石の順は、太陽光発電とバッテリー → 鍛冶 → 精密工作機械で、すぐ使える研究を先にする。
  マイクロエレクトロニクス 基礎（3000）は重いので後に回す
  - 出典: https://rimworldwiki.com/wiki/Basics
  - 確度: 中
- 木の壁は燃えるので、石材の壁へ置き換える。屋根の崩落を避けるため、少しずつ置き換える
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中

## 電力

- 薪発電機は 1000 W を出し、燃料の木材を食う。太陽光発電機の定格は 1700 W、風力発電機は
  2300 W である
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Power.xml` の `basePowerConsumption`）
  - 確度: 高
- 太陽光と風力の実際の出力は、日照と風で定格より下がる
  - 出典: 推論（Defs の値は定格で、変動の式はゲームの実装にある）
  - 確度: 中
- 電池は 1 台で 600 Wd を蓄える。冷却器は 200 W、ヒーターは 175 W を使う
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Power.xml`・
    `ThingDefs_Buildings/Buildings_Temperature.xml`）
  - 確度: 高

## 温度

- 居室は 21°C 前後に保つ。寒いと不満が出て、さらに下がると低体温症や凍傷になる
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 室温を調整できるのは、壁で囲まれ屋根のある部屋である。電力の前は焚き火で暖める
  - 出典: https://rimworldwiki.com/wiki/Basics
  - 確度: 中

## 防衛

- 土嚢とバリケードの `fillPercent` は 0.55、壁は 1 である。Wiki が挙げる遮蔽の 55% と
  一致する
  - 出典: Defs（`ThingDefs_Buildings/Buildings_Security.xml`・
    `ThingDefs_Buildings/Buildings_Structure.xml`）、https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 高
- 射手は土嚢の後ろに徴兵して並べ、近づかれたら近接の入植者が当たる
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中
- 序盤はタレットより、壁と位置取りに資材を使う
  - 出典: https://rimworldwiki.com/wiki/Basics
  - 確度: 中
- 爆発する動物（ブーマロープ・ブームラット）、捕食者、群れの動物は狩らない。反撃や火災を
  招く
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中

## 医療

- 打撲や小さな切り傷は薬なしで手当てし、薬は病気と重い出血へ回す
  - 出典: https://rimworldwiki.com/wiki/Quickstart_Guides
  - 確度: 中

## 気分と時間割

- 「時間割」は既定の「なんでも」を基本にする。「仕事の時間」だけで埋めると欲求を満たせず、
  精神崩壊へ近づく
  - 出典: https://rimworldwiki.com/wiki/Basics
  - 確度: 中

## 火災

- 建物の周りの草を刈っておく。乾いた雷雨では、入植者を徴兵して手動で消火させる
  - 出典: https://rimworldwiki.com/wiki/Basics
  - 確度: 中
