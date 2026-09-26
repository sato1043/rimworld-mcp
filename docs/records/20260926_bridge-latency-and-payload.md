# ブリッジの遅延と応答サイズの計測

- 計測日: 2026-09-26（JST 09:22〜09:55）
- 対象: 開発機（Windows 11 Pro 10.0.26200）で起動中の RimWorld と MCP Mod の HTTP ブリッジ
  （`127.0.0.1:8080`）。セーブは 2 つ（下の「計測の条件」）
- 計測器: `tools/measure_bridge.py`。セーブ A は内容の SHA-256 先頭 12 桁
  `d645a6425092` の版で測った。その後、表の出力で `|` を置き換える修正と、ブリッジに
  届かないときの停止理由を直す修正を加え、セーブ B はその版（`0a949e69219f`）で測った。
  どちらの修正も計測値には影響しない
- 作業書: [TASK0005](../tasks/TASK0005_bridge-measurement.md)

確度の凡例:

- **A**: 本セッションで計測器を実行し、出力を直接観測した
- **B**: 利用者の申告による
- **C**: 推論。観測から導いたが、直接の裏付けを持たない

## 計測の条件

| 項目 | セーブ A（入植直後） | セーブ B（中盤以降） | 確度 |
|---|---|---|---|
| マップ | 250×250、温帯森林、冬 | 250×250、温帯森林、夏 | A |
| 入植者・動物・敵 | 2〜3・53・0 | 13・205・0 | A |
| 富 | 11,363 | 395,285 | A |
| 速度 | 一時停止（2 回）・速度 3（1 回） | 速度 1（1 回） | A |
| 有効な Mod | MCP と Harmony ほか。数は数えていない | Mod 一覧の項目 50 件 | A・B |
| fps | 未取得 | 未取得 | - |
| 共有秘密 | 未設定 | 未設定 | A |

- tick・速度・入植者数などは、各回の計測の前後に `/state` で取った
- 回数は系列ごとに 20 回。直前に捨てる 1 回を置く。拒否要求だけは 5 回（ゲームのログに
  `Refused a request ... (6 so far)` が出たことをセーブ B で確かめた）
- 読み込まれていた `MCP.dll` の版は確認していない。ガードが `Origin` 付きの要求を 403 で
  返したので、TASK0003 以降の版である（確度 C）
- セーブ B の計測中、tick は 2,114 進んだ。時間を計った要求の合計だけで 175 秒あるので、
  ゲームは速度 1 の目標（60 tick/秒）に対して **12 tick/秒以下**で進んでいた（確度 A の
  数値から導いた値）

## 計測器の較正

遅延が既知のスタブ（Python 標準ライブラリの `http.server`、HTTP/1.1 keep-alive）に当てた
（確度 A）。

| 注入した遅延 | 中央値 | p95 | 誤差 |
|---|---|---|---|
| 0 ms | 1.59 ms | 2.03 ms | +1.59 ms |
| 50 ms | 51.91 ms | 52.24 ms | +1.91 ms |

許容は 5 ms で、両方とも収まった。約 1.6 ms はスタブと計測器が自分で足す床である。
スタブを 10 ms 遅くすると較正は落ちた（破壊検査。作業書の検証を参照）。

## 観測（確度 A）

| 計測 | A: 停止 | A: 速度 3 | B: 速度 1 |
|---|---|---|---|
| ガードが拒否した要求（HTTP の受け付けだけ） | 1.3 ms | 1.0 ms | 0.9 ms |
| `/ping`（+ キューとゲームスレッド） | 6.9 ms | 6.5 ms | 170.6 ms |
| 状態を読む endpoint の中央値の中央値 | 6.86 ms | 6.74 ms | 168.61 ms |
| 同じく最小〜最大 | 6.7〜7.0 ms | 6.2〜8.5 ms | 165.5〜184.0 ms |
| `/fertility` | 19.5 ms | 22.1 ms | 188.0 ms |
| 応答の合計（`/ping` を除く成功した endpoint） | - | 24.5 KB | 157.0 KB |
| pawn の下位 13 パスの合計 | - | 6.7 KB | 9.9 KB |

「中央値の中央値」は、成功した keep-alive の系列から `/fertility` を除いた系列（`/ping` を
含む）の中央値を並べた中央値である。

- **セーブ A**: 停止時に 2 回測り、大半の系列で中央値の差は 0.5 ms 以内、応答サイズは全件
  一致した。速度 3 でも中央値はほぼ同じで、p95 が 1〜2 ms 伸びた
- **セーブ B**: すべての endpoint が 165〜190 ms に揃った。`/ping` も同じなので、伸びたの
  は状態の読み出しでなく、キューに積まれてからゲームスレッドが処理するまでの待ちである
- **要求ごとに新しい接続を張る場合**
    - セーブ A: 中央値の keep-alive との差は −0.6〜+0.9 ms で、ほぼ変わらない。p95 は
      18〜32 ms で、keep-alive（7〜8 ms）の 2〜4 倍になった（3 回の計測・`/ping` と
      `/state` の 6 系列）
    - セーブ B: 差は `/ping` で +2.5 ms、`/state` で −25.1 ms だった。接続を張る時間の
      分だけ要求がフレームの途中に届くためと読む（確度 C）。170 ms の待ちの前では差が
      埋もれる
- **同時に送った要求**（セーブ B、10 本 × 10 回）: 10 の endpoint を順に送ると中央値
  1,689.9 ms、同時に送ると 181.9 ms だった。同時に送った要求は、ほぼ 1 回分の待ちで
  まとめて返る。計測は使い捨てのスクリプトで行った。`httpx.AsyncClient` で `/state`・
  `/pawns`・`/alerts`・`/colony`・`/threats`・`/weather`・`/power`・`/research`・
  `/messages`・`/zones` を、順に `await` する場合と `asyncio.gather` する場合で比べた
- **応答サイズ（セーブ B）**: 最大は `/animals` の 35.4 KB（約 8,900 トークン）、
  `/buildings` の 34.6 KB（約 8,700）、`/animals/training` の 29.7 KB（約 7,400）、
  `/room_assignments` の 12.1 KB（約 3,000）、`/pawns` の 5.8 KB（約 1,500）が続く。
  全 endpoint を 1 回ずつ読むと約 41,700 トークンになる。**トークン数はバイト数 ÷ 4 の
  概算**で、Claude のトークナイザーで数えた値ではない
- **失敗した endpoint**
    - `/world/sites` は両方のセーブで毎回 HTTP 500 を返した。本文は
      `Self referencing loop detected`（型 `RimWorld.Planet.SurfaceTile+RoadLink`）で、
      Newtonsoft.Json の直列化が循環参照で失敗している
    - `/quests` はセーブ B で HTTP 500 を返した。本文は
      `Error getting value from 'Length' on 'Verse.TaggedString'`
    - `/pawn/{id}/psycasts` はセーブ A でエラー本文 `Pawn is not a psycaster` を 200 で
      返した。サイキャスト能力を持たない入植者に対する想定どおりの応答である。セーブ B
      では HTTP 500（`Object reference not set to an instance of an object`）を返した

## 解釈

- **待ちの正体（確度 C）**: 拒否要求と `/ping` の差（セーブ A で約 5.5 ms、セーブ B で約
  170 ms）は、キューに積まれた要求が次の `GameComponentUpdate` を待つ時間と読む。順に
  送った要求は、前の応答を返したフレームの直後に積まれるので、ほぼ 1 フレーム分を待つ。
  この読みでは、セーブ A は 140 fps 前後、セーブ B は 6 fps 前後に当たる。fps を観測して
  いないので裏付けを欠くが、同時に送った 10 本が 1 回分の待ちで返ったこと、セーブ B の
  ゲームが 12 tick/秒以下でしか進んでいなかったことは、この読みと矛盾しない
- **状態の読み出しの費用（確度 C）**: 中盤のセーブでも、待ちに比べて小さい。`/fertility`
  だけが両方のセーブで 1 フレームを上回る

## 目的の 3 つの判断に対して

### 転送方式（REST から gRPC・WebSocket へ）

- 言えること: HTTP の受け付けの費用は 0.9〜1.3 ms で、セーブ B の 1 往復の 0.5% に
  すぎない。往復時間の大半はフレーム待ちであり、転送方式に依らない。方式を替えても往復は
  速くならない（確度 C。拒否要求の費用には HTTP 以外の処理も含むので、上限側に寄せた
  見積もり）
- 言えること: 接続を張り直す経路は、セーブ A で裾を 20 ms 以上悪くした。MCP サーバーの
  resource 2 箇所は、呼ぶたびに接続を張り直している（`mcp_server/main.py` の
  `_new_client()`）。フレームが重いセーブ B では差が埋もれる
- 言えないこと: サーバーからの push（出来事の通知）の価値。これは往復時間の問題でなく、
  LLM が出来事をどう受け取るかの設計の問題である

### 応答の絞り込み

- 言えること: 中盤のセーブでは、全 endpoint を 1 回ずつ読むと約 41,700 トークン（概算）に
  なる。`/animals`・`/buildings`・`/animals/training` の 3 つで約 25,000 トークンを占め、
  絞り込みの効果はこの 3 つに集中する
- 言えないこと: LLM が実際にどの endpoint をどれだけ呼ぶか。利用の記録を持たない

### tool の束ね方

- 言えること: 順に送る要求は、1 本ごとに 1 フレームを待つ。同時に送れば、10 本でも
  1 回分の待ちで返る（セーブ B で 1,690 ms → 182 ms）。状況把握のための複数の読み出しを
  1 つの tool に束ね、その中で同時に送れば、Mod を変えずに待ちを 1 フレームへ縮められる
- 言えること: tool を 1 回呼ぶごとに、ブリッジは少なくとも 1 フレームを足す。重いセーブ
  では 170 ms 前後になる。LLM の推論 1 回（秒単位）よりは小さい（確度 C。LLM の推論時間は
  本作業では測っていない）
- 言えないこと: どの組み合わせで呼ばれることが多いか。利用の記録を持たない

## 生データ

中央値と p95 の単位は ms。生の JSON は追跡していない（計測器を再実行すれば同じ形で出る）。

### セーブ A: 停止時（1 回目）と速度 3

応答サイズは速度 3 のときの値。

| path | mode | 停止 中央値 | 停止 p95 | 速度3 中央値 | 速度3 p95 | bytes（速度3）| 失敗 |
|---|---|---|---|---|---|---|---|
| `/ping` | refused | 1.3 | 1.5 | 1.0 | 1.2 | 70 |  |
| `/ping` | keep-alive | 6.9 | 7.1 | 6.5 | 7.6 | 17 |  |
| `/state` | keep-alive | 6.8 | 7.5 | 7.1 | 8.1 | 174 |  |
| `/pawns` | keep-alive | 6.8 | 7.4 | 6.7 | 8.0 | 1195 |  |
| `/animals` | keep-alive | 6.7 | 7.7 | 6.7 | 8.9 | 8822 |  |
| `/enemies` | keep-alive | 6.9 | 7.4 | 6.7 | 8.1 | 2 |  |
| `/fertility` | keep-alive | 19.5 | 24.7 | 22.1 | 40.3 | 5780 |  |
| `/things` | keep-alive | 6.8 | 7.4 | 7.1 | 9.4 | 1399 |  |
| `/buildings` | keep-alive | 6.9 | 7.3 | 7.0 | 7.7 | 40 |  |
| `/research` | keep-alive | 6.9 | 7.1 | 7.1 | 7.5 | 2502 |  |
| `/weather` | keep-alive | 6.9 | 7.5 | 7.0 | 9.6 | 88 |  |
| `/designations` | keep-alive | 6.9 | 7.3 | 7.0 | 9.2 | 2 |  |
| `/power` | keep-alive | 6.9 | 7.1 | 6.9 | 8.4 | 153 |  |
| `/rooms` | keep-alive | 6.8 | 7.6 | 7.2 | 8.8 | 2 |  |
| `/zones` | keep-alive | 6.9 | 7.1 | 6.6 | 8.1 | 30 |  |
| `/prisoners` | keep-alive | 6.8 | 7.3 | 6.7 | 8.1 | 2 |  |
| `/colony` | keep-alive | 6.7 | 7.3 | 6.7 | 8.3 | 970 |  |
| `/threats` | keep-alive | 6.9 | 7.3 | 6.7 | 8.2 | 109 |  |
| `/traders` | keep-alive | 6.8 | 7.3 | 6.7 | 8.2 | 40 |  |
| `/quests` | keep-alive | 6.9 | 7.4 | 6.9 | 7.7 | 35 |  |
| `/ideology` | keep-alive | 6.8 | 7.1 | 7.2 | 9.6 | 823 |  |
| `/animals/training` | keep-alive | 6.8 | 7.1 | 6.8 | 8.0 | 320 |  |
| `/caravans` | keep-alive | 6.8 | 7.4 | 6.7 | 8.7 | 2 |  |
| `/world/factions` | keep-alive | 6.9 | 7.4 | 6.4 | 8.4 | 691 |  |
| `/world/sites` | keep-alive | 5.3 | 5.3 | 14.0 | 14.0 | 193 | HTTP 500 |
| `/messages` | keep-alive | 6.9 | 7.4 | 6.3 | 8.6 | 2 |  |
| `/alerts` | keep-alive | 6.9 | 7.5 | 7.2 | 8.4 | 214 |  |
| `/medical` | keep-alive | 6.9 | 7.2 | 6.9 | 8.0 | 2 |  |
| `/production` | keep-alive | 7.0 | 7.1 | 6.7 | 8.2 | 2 |  |
| `/apparel` | keep-alive | 6.9 | 7.5 | 6.7 | 8.3 | 237 |  |
| `/areas` | keep-alive | 6.8 | 7.5 | 6.4 | 8.4 | 425 |  |
| `/social` | keep-alive | 6.7 | 11.9 | 6.7 | 8.5 | 116 |  |
| `/stockpiles` | keep-alive | 6.9 | 7.2 | 6.8 | 9.0 | 2 |  |
| `/corpses` | keep-alive | 6.8 | 8.9 | 8.5 | 10.7 | 2 |  |
| `/drug_policies` | keep-alive | 6.9 | 7.3 | 6.7 | 9.8 | 281 |  |
| `/room_assignments` | keep-alive | 6.9 | 7.4 | 6.7 | 8.1 | 2 |  |
| `/mechs` | keep-alive | 6.8 | 7.5 | 6.5 | 8.0 | 2 |  |
| `/incidents` | keep-alive | 6.9 | 7.2 | 6.7 | 8.5 | 2 |  |
| `/pawn/{id}` | keep-alive | 6.9 | 7.2 | 6.2 | 8.6 | 415 |  |
| `/pawn/{id}/health` | keep-alive | 6.7 | 7.4 | 6.8 | 8.3 | 254 |  |
| `/pawn/{id}/needs` | keep-alive | 6.9 | 7.2 | 6.4 | 8.0 | 558 |  |
| `/pawn/{id}/mood` | keep-alive | 6.8 | 7.3 | 6.9 | 9.3 | 262 |  |
| `/pawn/{id}/inventory` | keep-alive | 6.8 | 7.7 | 6.5 | 8.1 | 239 |  |
| `/pawn/{id}/backstory` | keep-alive | 6.9 | 7.4 | 6.9 | 8.5 | 817 |  |
| `/pawn/{id}/capacities` | keep-alive | 6.9 | 7.1 | 6.9 | 8.0 | 839 |  |
| `/pawn/{id}/psycasts` | keep-alive | 6.0 | 6.0 | 9.8 | 9.8 | 67 | error body |
| `/pawn/{id}/genes` | keep-alive | 6.9 | 7.5 | 7.1 | 8.2 | 198 |  |
| `/pawn/{id}/area` | keep-alive | 7.0 | 7.4 | 6.6 | 8.2 | 73 |  |
| `/pawn/{id}/traits` | keep-alive | 6.8 | 7.3 | 6.4 | 8.1 | 76 |  |
| `/pawn/{id}/relations` | keep-alive | 6.9 | 8.0 | 6.7 | 10.0 | 262 |  |
| `/pawn/{id}/work` | keep-alive | 6.8 | 7.2 | 6.5 | 7.9 | 1749 |  |
| `/pawn/{id}/schedule` | keep-alive | 6.8 | 7.5 | 6.5 | 12.7 | 1002 |  |
| `/ping` | new-connection | 7.8 | 31.5 | 7.4 | 30.6 | 17 |  |
| `/state` | new-connection | 7.2 | 26.5 | 7.7 | 21.0 | 175 |  |

### セーブ B: 速度 1

約トークンはバイト数 ÷ 4 の概算。

| path | mode | 中央値 | p95 | bytes | 約トークン | 失敗 |
|---|---|---|---|---|---|---|
| `/ping` | refused | 0.9 | 1.1 | 70 | 18 |  |
| `/ping` | keep-alive | 170.6 | 207.0 | 17 | 4 |  |
| `/state` | keep-alive | 172.0 | 175.4 | 177 | 44 |  |
| `/pawns` | keep-alive | 170.8 | 209.4 | 5806 | 1452 |  |
| `/animals` | keep-alive | 171.2 | 206.0 | 35414 | 8854 |  |
| `/enemies` | keep-alive | 171.2 | 206.6 | 2 | 0 |  |
| `/fertility` | keep-alive | 188.0 | 200.2 | 5801 | 1450 |  |
| `/things` | keep-alive | 172.4 | 214.4 | 4779 | 1195 |  |
| `/buildings` | keep-alive | 176.6 | 239.7 | 34609 | 8652 |  |
| `/research` | keep-alive | 170.2 | 189.9 | 51 | 13 |  |
| `/weather` | keep-alive | 165.9 | 175.1 | 89 | 22 |  |
| `/designations` | keep-alive | 168.1 | 207.6 | 805 | 201 |  |
| `/power` | keep-alive | 169.6 | 212.4 | 173 | 43 |  |
| `/rooms` | keep-alive | 167.4 | 234.3 | 2644 | 661 |  |
| `/zones` | keep-alive | 167.8 | 179.0 | 3543 | 886 |  |
| `/prisoners` | keep-alive | 170.2 | 202.8 | 2 | 0 |  |
| `/colony` | keep-alive | 170.0 | 215.1 | 993 | 248 |  |
| `/threats` | keep-alive | 166.5 | 199.8 | 109 | 27 |  |
| `/traders` | keep-alive | 167.1 | 170.9 | 40 | 10 |  |
| `/quests` | keep-alive | 167.6 | 167.6 | 70 | 18 | HTTP 500 |
| `/ideology` | keep-alive | 166.0 | 218.6 | 819 | 205 |  |
| `/animals/training` | keep-alive | 166.6 | 209.3 | 29687 | 7422 |  |
| `/caravans` | keep-alive | 166.6 | 212.7 | 2 | 0 |  |
| `/world/factions` | keep-alive | 167.5 | 198.7 | 712 | 178 |  |
| `/world/sites` | keep-alive | 186.8 | 186.8 | 193 | 48 | HTTP 500 |
| `/messages` | keep-alive | 184.0 | 250.7 | 2 | 0 |  |
| `/alerts` | keep-alive | 169.6 | 216.5 | 222 | 56 |  |
| `/medical` | keep-alive | 166.2 | 171.4 | 2 | 0 |  |
| `/production` | keep-alive | 167.4 | 205.9 | 5155 | 1289 |  |
| `/apparel` | keep-alive | 169.0 | 207.8 | 601 | 150 |  |
| `/areas` | keep-alive | 169.9 | 204.4 | 1029 | 257 |  |
| `/social` | keep-alive | 167.6 | 175.7 | 1713 | 428 |  |
| `/stockpiles` | keep-alive | 176.3 | 199.4 | 3106 | 776 |  |
| `/corpses` | keep-alive | 169.5 | 237.5 | 2007 | 502 |  |
| `/drug_policies` | keep-alive | 172.3 | 206.8 | 755 | 189 |  |
| `/room_assignments` | keep-alive | 170.7 | 208.8 | 12149 | 3037 |  |
| `/mechs` | keep-alive | 167.4 | 176.5 | 2 | 0 |  |
| `/incidents` | keep-alive | 166.6 | 204.5 | 3986 | 996 |  |
| `/pawn/{id}` | keep-alive | 166.8 | 193.3 | 429 | 107 |  |
| `/pawn/{id}/health` | keep-alive | 166.4 | 210.9 | 369 | 92 |  |
| `/pawn/{id}/needs` | keep-alive | 166.4 | 180.3 | 558 | 140 |  |
| `/pawn/{id}/mood` | keep-alive | 165.8 | 173.3 | 668 | 167 |  |
| `/pawn/{id}/inventory` | keep-alive | 170.2 | 208.7 | 766 | 192 |  |
| `/pawn/{id}/backstory` | keep-alive | 173.4 | 215.5 | 114 | 28 |  |
| `/pawn/{id}/capacities` | keep-alive | 167.3 | 207.0 | 843 | 211 |  |
| `/pawn/{id}/psycasts` | keep-alive | 168.2 | 168.2 | 64 | 16 | HTTP 500 |
| `/pawn/{id}/genes` | keep-alive | 167.4 | 176.7 | 190 | 48 |  |
| `/pawn/{id}/area` | keep-alive | 165.5 | 168.9 | 74 | 18 |  |
| `/pawn/{id}/traits` | keep-alive | 168.7 | 209.0 | 218 | 54 |  |
| `/pawn/{id}/relations` | keep-alive | 169.0 | 208.7 | 783 | 196 |  |
| `/pawn/{id}/work` | keep-alive | 168.6 | 207.5 | 3873 | 968 |  |
| `/pawn/{id}/schedule` | keep-alive | 168.1 | 175.9 | 1051 | 263 |  |
| `/ping` | new-connection | 173.2 | 231.1 | 17 | 4 |  |
| `/state` | new-connection | 146.9 | 149.7 | 177 | 44 |  |

## 要裁定の判断点

- `/world/sites`・`/quests`・`/pawn/{id}/psycasts` の HTTP 500 を直すか。製品の不具合で、
  本作業の非目標（製品コードの変更）の外にある。TASK0005 の残課題へ置いた
- 状況把握の読み出しを 1 つの tool に束ね、同時に送る形を採るか。TASK0005 の残課題
  （どの後続作業を起こすか）へ置いた
