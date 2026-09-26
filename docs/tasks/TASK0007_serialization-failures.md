---
task: TASK0007
status: frozen
features: []
requirements: []
relates-to:
 - TASK0005_bridge-measurement
user-reach: high
dev-reach: low
drive: high
irreversible: low
hazard: none
---

# 読み出しの直列化の失敗を直す

## 目的

ブリッジの読み出しが HTTP 500 で失敗し、LLM がその情報を得られない状態をなくす。

TASK0005 の実測（[記録](../records/20260926_bridge-latency-and-payload.md)）で、次の
3 つが 500 を返した。

| endpoint | 返した理由 | 起きたセーブ |
|---|---|---|
| `/world/sites` | `Self referencing loop detected`（型 `SurfaceTile+RoadLink`） | 入植直後・中盤の両方 |
| `/quests` | `Error getting value from 'Length' on 'Verse.TaggedString'` | 中盤 |
| `/pawn/{id}/psycasts` | `Object reference not set to an instance of an object` | 中盤 |

## 目標

- 上の 3 つの endpoint が、同じ状態で 200 と中身のある本文を返す
- 同じ型の値を持つ他の読み出しも、同じ直し方で失敗しなくなる（下の「問題」の潜在箇所）
- 読み出しが例外で失敗したとき、例外の全文（型・メッセージ・スタック）をゲームのログへ
  書く。応答の本文は今の形（`{"error": <メッセージ>}`）を保つ
- 計測器が応答の本文を保存できるようにし、修正の前後で全 endpoint の本文を比べられる
  ようにする

提供要求（SREQ）は採番しない。このリポジトリは要求一覧を持たない（TASK0003 の裁定）。

## 非目標

- 読み出しの出力の形を変えること。失敗していた値を、意味の通る素の値（文字列・整数）で
  返すところまでとする
- 失敗していない endpoint の出力の変更。共通の直し方が他の出力を変えてしまう場合は、
  その差を検出して裁定にかける（到達基準）
- TASK0006 が扱う tool（`get_animals`・`get_buildings`・`get_animal_training`・複合 tool）
  と、`mcp_server/main.py` の変更
- 通し番号付きのイベントログ（TASK0008）

## 問題

原因はいずれも仮説である。実装の段で一次情報（RimWorld 1.6 の型の定義と、例外の
スタック）を取って確かめる。

- **`/world/sites`（仮説）**: `tile = s.Tile` の `Tile` は、RimWorld 1.6 では整数でなく
  構造体（`PlanetTile`）である。Newtonsoft.Json は構造体をプロパティごとに辿り、
  地表のタイル（`SurfaceTile`）の道路の情報で循環参照に当たる。エラーの経路
  `[0].tile.Tile.potential...` はこの読みと合う
    - 潜在箇所: `GetCaravans` も `tile = c.Tile` を持つ。計測したセーブにキャラバンが
      無かったので、失敗が表に出ていない
- **`/quests`（仮説）**: `description = q.description` の型は `TaggedString`（ゲームの
  色付き文字列）である。中の文字列が null のとき、`Length` の取得で例外になる
    - 潜在箇所: `TaggedString` が null でなくても、Newtonsoft.Json はそれを文字列でなく
      プロパティを並べたオブジェクトとして出す可能性がある。letter の `Label` など、他の
      読み出しも同じ型を持ちうる。本文を保存して形を確かめる
- **`/pawn/{id}/psycasts`（原因不明）**: null 参照の箇所が分からない。今の実装は例外の
  メッセージしか応答へ載せず、スタックをどこにも残さない。例外の全文をログへ書く変更を
  先に入れ、中盤のセーブで再現させて箇所を特定する
- **Mod（C#）の変更は自動テストで確かめられない。** `GameStateReader` はゲームの型に
  依存し、テストのプロジェクト（ゲームを要さない）で compile できない。確かめるのは
  実機で、前後の本文の比較による
- **中盤のセーブは利用者の手元にある。** 再現と確認には、利用者にセーブを読み込んで
  もらう必要がある。キャラバンを持つ状態も要る
- 並行する TASK0006 は `mcp_server/` を変える。本作業は Mod と `tools/` だけを変えるので
  衝突しない

## 到達基準

- [x] 中盤のセーブで、`/world/sites`・`/quests` が 200 を返し、本文に `error` を持たない
      （計測器の失敗の一覧から消える）
- [x] Royalty が無効な環境で、`/pawn/{id}/psycasts` が 200 を返し、DLC が無効であることを
      述べる（2026-09-26 に改定。裁定記録を参照）
- [x] キャラバンを持つ状態で `/caravans` が 200 を返し、`tile` が整数である
- [x] 修正の前後で、全 GET endpoint の本文を同じセーブで比べ、変わった endpoint が
      意図したもの（上の 3 つと、同じ型を持つ潜在箇所）だけである。意図しない差は、
      一覧にして裁定にかける
- [x] 読み出しの例外が、型・メッセージ・スタックとともにゲームのログへ 1 回書かれる
      （わざと失敗させた状態で確かめる）。応答の本文は今の形のまま
- [x] `dotnet build` が 0 エラーで、警告の数が着手時から増えない（`--no-incremental`）
- [x] `dotnet test` が着手時と同じ件数で緑である
- [x] 実装のコミットが fork ローカルのファイル（`CONTRIBUTING.md`・`CLAUDE.md`・`docs/`・
      `tools/`）に触れていない（upstream へ送れる形である）
- [x] 第三者視点レビュー（CP6）の裁定を受けた（不要を提案し、不要と裁定された）

CP6 を不要と提案した根拠: 変更は Mod の直列化の数箇所と例外のログで、数十行の見込みで
ある。自動テストを持てない代わりに、全 endpoint の本文を前後で比べる検査が、意図しない
変更を機械的に拾う。

## 概要設計

### 直し方の選択

直し方は 2 つあり、実装の段で一次情報を見て選ぶ。

| 直し方 | 利点 | 欠点 |
|---|---|---|
| 各箇所で素の値へ変える（`s.Tile` → タイルの番号、`q.description` → 文字列） | 変更が局所的で、効果が箇所ごとに読める | 同じ型を持つ新しい箇所を足すたびに、同じ誤りを繰り返しうる |
| 直列化の設定に型ごとの変換（converter）を足す | 1 箇所で全 endpoint に効く | 失敗していない endpoint の出力も変えうる |

既定は前者とする。後者は、本文の比較で `TaggedString` がオブジェクトとして出ている
箇所が多数見つかった場合に、裁定を受けて採る。

### 例外のログ

`MCPGameComponent` が読み出しの例外を受け止める箇所で、ゲームスレッドのまま
`Log.Warning` へ例外の全文を書く。同じ例外が毎回の要求で繰り返し出るので、同じ
endpoint の同じ例外の型は 1 回だけ書く（ログを埋めないため）。

### 計測器の本文の保存

`tools/measure_bridge.py` に `--save-bodies <dir>` を足し、endpoint ごとに最後の応答の
本文をファイルへ書く。前後の比較は、2 つのディレクトリの差分で行う。計測器は fork
ローカルなので、作業書のブランチで変える。

### ブランチ

TASK0006 と同じく、作業書（と `tools/`）のブランチと、実装のブランチ
（`task/TASK0007-serialization-impl`）を分ける。実装のブランチは Mod のソースだけを変え、
upstream へ cherry-pick できる形に保つ。

## 実装計画

1. 計測器に `--save-bodies` を足す（作業書のブランチ）
2. 中盤のセーブで修正前の本文を保存する
3. 実装のブランチで、例外の全文をログへ書く変更を入れ、ビルドする
4. 中盤のセーブで `/pawn/{id}/psycasts` を再現させ、スタックから null 参照の箇所を特定する
5. RimWorld 1.6 の `PlanetTile` と `TaggedString` の定義を確かめ、3 つの endpoint と
   潜在箇所を直す
6. 中盤のセーブ（とキャラバンを持つ状態）で修正後の本文を保存し、前後を比べる
7. 記録へ結果を残す

## 工数概算

| ステップ | 内容 | 概算（実働）| 主な不確実性 |
|---|---|---|---|
| 1-2 | 計測器の本文の保存・修正前の保存 | 15〜30 分 | 利用者によるセーブの読み込みの待ち |
| 3-5 | 例外のログ・原因の特定・修正 | 30〜90 分 | psycasts の原因が Mod の組み合わせに依る場合の切り分け |
| 6-7 | 前後の比較と記録 | 20〜40 分 | キャラバンを持つ状態を作る待ち |
| 計 | | 65〜160 分 | 幅の主因: psycasts の原因と、利用者の操作の待ち |

- 前提: 実装はエージェント。ゲームの起動・セーブの読み込み・キャラバンの編成は利用者。
  ビルドした `MCP.dll` をゲームに読ませるには、ゲームの再起動が要る
- 参照クラス: `docs/records/effort-anchors.md`。利用者の操作を挟む作業（TASK0005）は、
  待ちが壁時計の大半を占めた
- 実績（完了時）: 壁時計 約 50 分（作業書のブランチの作成 15:13 から、キャラバンの確認と
  完了の記入 16:02 まで。数え方はブランチの reflog と時計で、TASK0008 の起票と利用者の
  操作の待ちを含むため実働の上限にあたる）。見積もり 65〜160 分の下限を割った。幅の主因に
  置いた psycasts の原因は、足したログのスタックと型の属性で 1 回で特定できた。利用者の
  操作（セーブの読み込み 3 回・ジャンクションの張り替え・キャラバン）の待ちが大半を
  占めた

## 検証

### 概要

中盤のセーブ（入植者 13・動物 205・Mod 一覧 50 件、Royalty は無効）で、修正前と修正後の
全 GET endpoint の本文を保存し、JSON の形（キーの経路と値の型）で比べた（2026-09-26）。
値はゲームが進むと変わるので、比べるのは形である。原因は RimWorld 1.6 の
`Assembly-CSharp.dll` をリフレクションで読み、ゲームのログのスタックと合わせて確かめた。
Royalty が有効な環境での `psycasts` は、この機械に Royalty が無いため確かめていない。

### 検証項目（チェックリスト）

- [x] 修正前: 54 系列のうち失敗 3（`/quests`・`/world/sites`・`/pawn/{id}/psycasts` の
      500）。`/incidents` の `label` が `{"RawText","Length","StrippedLength"}` の
      オブジェクトで出ていた
- [x] 修正後: 54 系列のうち 500 は 0。失敗として数えられる 1 件は `psycasts` のエラー本文
      「Royalty DLC is not active」（200）で、改定した基準どおり。13 人の全員で同じ
- [x] 形の差: 51 本文のうち 4。`/incidents`（`label` が文字列へ）・`/quests`（エラーから
      一覧へ）・`/world/sites`（エラーから一覧へ、`tile` は整数）は意図した差。
      `/designations` は修正前が空の配列で、修正後に要素が入った。ゲームの状態の差で、
      読み出しのコードは変えていない
- [x] わざと 3 回失敗させて（`POST /command/pause` に `{"paused": "abc"}`）、500 を 3 回
      受け、ゲームのログへの記録は 1 回（スタックつき）だった
- [x] `dotnet build --no-incremental` が 0 エラー / 0 警告（着手時の `develop` も 0 警告。
      TASK0004 の記録）
- [x] `dotnet test` が 58 件緑（着手時と同じ件数）
- [x] 実装のブランチの差分は `MCP/Source/MCP/` の 2 ファイルだけ（`git diff --stat`）
- [x] 計測器の本文の保存を、ゲームを要さない 6 件の確認と、既存の破壊検査 11 件で確かめた
- [x] キャラバンを持つ状態の `/caravans` が 200 で、`tile` が整数（`111597`）だった。
      キャラバンがワールドに出てから現れる（マップで集合している間は空の配列）

### 検証手順

#### 自動

```sh
dotnet build MCP/Source/MCP/MCP.csproj --no-incremental
dotnet test MCP/Tests/MCP.Tests.csproj
uv run --project mcp_server python tools/measure_bridge.py --calibrate
```

Mod の読み出しは自動テストを持たない（ゲームの型に依存するため）。前後の形の比較に
使ったスクリプトはリポジトリに残していない（保存した 2 つのディレクトリの JSON を
キーの経路と値の型の集合へ落として比べるもの）。

#### 実機

- **修正の前後の本文の比較**
    - 目的: 失敗していた読み出しが直り、他の読み出しの形が変わっていないことを確かめる
    - 前提条件: 中盤のセーブ。修正前は `Mods\MCP` のジャンクションが主チェックアウトを、
      修正後は実装の worktree を指す（手順は TASK0003 の「前提: Mod の配置と設定」）
    - 期待結果: 修正後に 500 が 0 件。形の差が意図した endpoint だけ
    - 観察方法: `tools/measure_bridge.py --save-bodies <dir>` を修正前と修正後で実行し、
      2 つのディレクトリの JSON の形を比べる
    - 復元手順: `develop` へ統合した後、ジャンクションを主チェックアウトへ張り直す
- **例外のログ**
    - 目的: 読み出しの例外が、スタックつきで 1 回だけ記録されることを確かめる
    - 前提条件: 実装のビルドでゲームを起動した直後。他の Mod のエラーでゲームのログが
      上限に達すると、以後は何も書かれない
    - 期待結果: 同じ要求を 3 回失敗させて、500 を 3 回受け、`Player.log` の
      `[MCP] POST /command/pause failed` が 1 行
    - 観察方法: `POST /command/pause` に `{"paused": "abc"}` を 3 回送り、`Player.log` を
      grep する。値の読み取りで例外になり、一時停止の処理へは届かない
    - 復元手順: なし（ゲームの状態を変えない）
- **キャラバンのタイル**
    - 目的: `/caravans` の `tile` が整数で返ることを確かめる
    - 前提条件: キャラバンを 1 つ出した状態。確認の後にセーブしない
    - 期待結果: 200 で、各キャラバンの `tile` が整数
    - 観察方法: `GET /caravans`
    - 復元手順: セーブせずにゲームを終了するか、キャラバンを戻す

## 作業記録

- 原因は 3 つとも一次情報で確かめた
    - `/world/sites`: `WorldObject.Tile` は構造体 `PlanetTile`（`tileId`・`layerId`）で、
      プロパティ `Tile` が地表のタイルへ進み、道路の隣接で循環する。エラーの経路
      `[0].tile.Tile.potentialRoads[0].neighbor.Tile...` と一致した
    - `/quests`: `Quest.description` は構造体 `TaggedString`。中身が null のとき
      `Length` が null 参照の例外を投げ、`RawText` と `ToString()` は null を返す（値を
      作って試した）
    - `/pawn/{id}/psycasts`: 足したログのスタックが `MaxEntropy`
      （`Pawn_PsychicEntropyTracker`）→ `StatExtension.GetStatValue` を指した。
      `StatDefOf.PsychicEntropyMax` は `MayRequireRoyalty` で、Royalty が無効だと null に
      なる。エントロピーの管理そのものは Royalty が無くても作られる
- 同じ型を持つ潜在箇所として、`/caravans` の `tile` と、`/messages`・`/incidents` の
  letter の `label`（`TaggedString`）を直した。他の `Label` はすべて `string` だった
  （リフレクションで確かめた）
- 直し方は各箇所で素の値へ変える側を採った。`TaggedString` が漏れていたのは 3 箇所に
  限られ、直列化の設定へ変換を足す理由は無かった
- `psycasts` の基準は、原因が分かる前に「本文に `error` を持たない」と書いていた。
  Royalty が無効な環境では DLC が無効と答えるのが正しいので、改定の裁定を受けた
- 最初の実機ではゲームのログが上限（`Reached max messages limit`）に達していて、13 人分の
  失敗のうち 1 件しか記録されなかった。再起動の直後に、わざと失敗させて確かめ直した

## 機能への反映

特記なし。

## 裁定記録

- **作業の取り決め（目的・目標・非目標・到達基準）**（2026-09-26・ユーザー）: 承認
- **upstream へ送るか**（2026-09-26・ユーザー）: 送れる形にしておく。実装のブランチを
  作業書のブランチから分ける
- **CP6 の第三者視点レビューを実施するか**（2026-09-26・ユーザー）: 不要
- **優先度の `drive`**（2026-09-26・ユーザー）: high
- **psycasts の到達基準の改定**（2026-09-26・ユーザー）: 「200 を返し、本文に `error` を
  持たない」から「Royalty が無効な環境で 200 を返し、DLC が無効であることを述べる」へ
    - 根拠: 原因が Royalty の無効な環境に固有と分かった。その環境で返せる正しい答えは
      DLC が無効であることで、元の基準は偽になっていた
- **`/caravans` の確かめ方**（2026-09-26・ユーザー）: 実機でキャラバンを出して確かめる

## stakeholder 未裁定の残課題

- Royalty が有効な環境での `psycasts` の振る舞い。この機械に Royalty が無く、確かめて
  いない
- コマンドの本文を読む `Parse` が、JSON を読めないと例外を握って空のオブジェクトを返す。
  本文が壊れた `POST /command/pause` は、既定値の「一時停止する」で実行される
- 他の Mod が大量のエラーを出す環境では、ゲームのログが上限に達し、例外の記録も書かれ
  なくなる。中盤のセーブでは、読み込みから数分で上限に達した
- `TaggedString` を `RawText` で返すので、色などのタグ（`<color=...>`）は残る。LLM へ
  渡す前に取り除くか
- `/incidents` の `typeLabel` が、中盤のセーブで全件 `unknown` だった（letter の定義の
  `label` が null）
