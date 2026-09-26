---
task: TASK0004
status: frozen
features: []
requirements: []
relates-to:
 - TASK0001_build-path-override
user-reach: low
dev-reach: high
irreversible: low
hazard: none
---

# Mod のビルドから nullable 警告をなくす

## 目的

`MCP.csproj` は `<Nullable>enable</Nullable>` で nullable 参照型の解析を有効にしている。
しかし既存コードの型注釈が実態に追従しておらず、ビルドのたびに 10 件の警告が出る。

- 警告は既知の雑音として読み飛ばされる。新しく入った警告、つまり本物の null 参照の
  可能性が同じ一覧に埋もれる
- 差分ビルドではコンパイルが省かれると警告が出ない。件数が回ごとに変わって見えるので、
  「増えた」ことに気づく手がかりが無い

型の宣言を実態に合わせて警告を 0 にし、以後の警告を意味のある信号として扱えるようにする。

## 目標

- `dotnet build --no-incremental` の警告を 10 件から 0 件にする。抑止（`#pragma`・
  `!` 演算子・`<NoWarn>`）でなく、型の宣言を実態に合わせて解消する
- 実行時の挙動を変えない

いずれも提供要求（SREQ）を採番しない。知覚ゲートを通らないためである ── 機能設計記述の
外部仕様に知覚項目を加えず、既存コードの型の宣言を直す作業である。

## 非目標

- nullable 以外の警告・コードの整理。着手時点で他種の警告は 0 件である
- テストプロジェクト（`MCP/Tests/`）の変更。警告の出ている 3 ファイルはどれもテストへ
  共有されていない
- 警告を以後エラーとして扱うゲートの導入。導入するかは未裁定で、残課題に置く

## 問題

- **`required` 修飾子は使えない。** CS8618 のメッセージは `required` を勧めるが、C# 11 の
  機能である。本プロジェクトは `LangVersion 9` に固定している（`MCP.Tests.csproj` も
  同じ版に揃えている）
- **`init` アクセサも使えない。** C# 9 の機能だが、`net472` には
  `System.Runtime.CompilerServices.IsExternalInit` が無く、自前の型の追加が要る
- **`FindColonist` の戻り値を `Pawn?` にすると、呼び出し側へ波及する。**
  `GameStateReader` の 14 箇所と、`CommandExecutor.Colonist` 経由の 12 箇所である。
  着手前に grep で確かめた範囲では、すべて直後の行で null を検査している。検査していない
  箇所があれば新しい警告（CS8602）として現れ、それは本物の欠陥の候補である

## 到達基準

- [x] `dotnet build --no-incremental` が 0 エラー / 0 警告
- [x] `#pragma warning`・null 許容の抑止演算子（`!`）・`<NoWarn>` を足していない
- [x] `dotnet test MCP/Tests/MCP.Tests.csproj` が着手時と同じ件数で緑
- [x] `PendingRequest` の生成箇所が 4 つの文字列を名前付き引数で渡している
- [x] 解消した注釈を 1 つ戻すと、対応する警告が再び出る（戻して確かめてから元に戻す）
- [x] 実機確認を行うかをユーザーが裁定し、行うなら結果を検証の節へ記録する
- [x] 第三者視点レビュー（CP6）の裁定を受けた（不要を提案）
    - 根拠: 変更は型の宣言と 1 つのコンストラクタに閉じ、想定は 4 ファイル・20 行前後で
      ある。正否はコンパイラの警告件数が判定し、注釈を戻す破壊確認がそれを裏づける

## 概要設計

### 基準値（2026-09-26・`develop` の `2fce55d`）

`dotnet build --no-incremental` で 0 エラー / 10 警告。

| 警告 | 件数 | 箇所 |
|---|---|---|
| CS8618 | 5 | `PendingRequest.cs:7-11` |
| CS8600 | 4 | `CommandExecutor.cs:74,189,373,606` |
| CS8603 | 1 | `GameStateReader.cs:761` |

### `PendingRequest`

生成時に必ず与える 4 項目（`Method`・`Path`・`QueryString`・`Body`）はコンストラクタで
受け、`readonly` にする。生成後に書き換える箇所は無い。コンストラクタで受ければ、
与え忘れをコンパイラが検出する。

`Response` はゲームスレッドが後から書くので、生成時には値が無い。`string?` にする。
読む側は既に `pending.Response ?? "{}"` で null を受けている。

生成箇所（`MCPHttpServer`）は名前付き引数で渡す。4 つとも `string` なので、位置で渡すと
順序の入れ違いをコンパイラが検出できない。

`= ""` の既定値で黙らせる案は採らない。与え忘れが空文字の要求として素通りし、警告が
検出していたものを消すためである。

### `CommandExecutor` の局所変数

4 箇所とも、null で初期化して条件付きで代入する局所変数である。宣言を `Thing?`・
`ThingDef?`・`Area?`・`Area_Allowed?` にする。使う側は既に null を検査しているか、
null を許す RimWorld の API へ渡している。

### `FindColonist`

戻り値を `Pawn?` にする。同じ値を返す `CommandExecutor.Colonist` も `Pawn?` にする
（しないと CS8603 がそこへ 1 件移るだけになる）。呼び出し側の `var` は `Pawn?` と
推論され、直後の null 検査で非 null へ絞られる。

## 実装計画

1. 実装用のブランチ `task/TASK0004-nullable-impl` と worktree を `develop` から切る
2. `PendingRequest` と生成箇所を直す
3. `CommandExecutor` の局所変数 4 箇所を直す
4. `FindColonist` と `Colonist` の戻り値を直す
5. 全量ビルドで 0 警告を確かめ、注釈を 1 つ戻して警告が再び出ることを確かめる
6. テストを回す
7. 実機確認（裁定しだい）

作業書はこのブランチ（`task/TASK0004-nullable-warnings`）に置き、実装と分ける。実装は
upstream のコードだけを変えるので、fork ローカルのドキュメントと同じブランチに置くと
squash で溶接される（`CONTRIBUTING.md`「One purpose per branch」）。

## 工数概算

| ステップ | 内容 | 概算（実働）| 主な不確実性 |
|---|---|---|---|
| 1-4 | ブランチの用意と宣言の修正 | 10〜20 分 | 呼び出し側から新しい警告が出たときの切り分け |
| 5-6 | 全量ビルド・注釈を戻す確認・テスト | 5〜10 分 | 少ない |
| 7 | 実機確認 | 0〜15 分 | 実施の裁定と利用者の操作 |
| 計 | | 15〜45 分 | 幅の主因: 実機確認の有無と、新しい警告が出た場合の対応 |

- 参照クラス: `docs/records/effort-anchors.md` の TASK0002（ビルド構成の変更・11 分）と
  TASK0003 の最初の実装（47 分）。本作業は TASK0002 に近い規模である
- CP6 の第三者視点レビューは行を置いていない。提案が「不要」のため。実施と裁定されたら
  行を足す（TASK0003 ではレビューと反映が実装の約 4 倍を占めた）
- 実績（完了時）: 壁時計 8 分（計画コミット 09:14 から実機確認の完了 09:22 まで。
  数え方はコミット時刻と確認時刻の差で、承認待ちを含むため実働の上限にあたる。
  `develop` への統合は含まない）。見積もり 15〜45 分に対し下振れ。呼び出し側から
  新しい警告が 1 件も出ず、幅の主因に置いた切り分けが起きなかった

## 検証

### 概要

全量ビルド・テスト・注釈を戻す破壊確認・実機確認を実施した（2026-09-26）。数値は
実装ブランチの `4bc4e48` に対する実測である。

### 検証項目（チェックリスト）

- [x] `dotnet build --no-incremental` が 0 エラー / 0 警告（着手時 10 警告）
- [x] 追加行に `#pragma`・`NoWarn`・抑止演算子 `!` が 0 件（`git diff develop` の追加行を
      grep）
- [x] `dotnet test` が 58 件緑・失敗 0・スキップ 0（`net10.0`。TASK0003 の記録と同数）
- [x] 破壊確認: 次の 4 つを同時に戻して全量ビルドし、4 つとも元の位置で警告が出た。
      戻した後は再び 0 警告
    - `FindColonist` の `?` → CS8603（`GameStateReader.cs:761`）
    - `Response` の `?` → CS8618（`PendingRequest` のコンストラクタ）
    - コンストラクタの `Body` への代入 → CS8618 と CS0649
    - `Area_Allowed` の `?` → CS8600（`CommandExecutor.cs:606`）
- [x] 実機で 3 観測が期待と一致する（下記「実機確認の結果」）

### 検証手順

自動:

```sh
dotnet build MCP/Source/MCP/MCP.csproj --no-incremental "-p:RimWorldDir=<RimWorld の導入先>"
dotnet test MCP/Tests/MCP.Tests.csproj
```

`--no-incremental` は省かない。差分ビルドはコンパイルを省いた回に警告を出さず、0 警告と
区別できない。

実機:

#### ブリッジの要求と入植者の検索が変わらず動くこと

- 目的: `PendingRequest` のコンストラクタ経由の要求と、`FindColonist` の null・非 null の
  両経路が、動いているゲームで従来どおり応答することを確かめる
- 前提条件: `Mods\MCP` が実装の worktree の `MCP` フォルダを指すジャンクションである。
  張り替えた後に RimWorld を起動し、セーブを読み込んでいる。張り替えの手順は
  TASK0003 の「前提: Mod の配置と設定」と同じ
- 期待結果: `GET /ping` が 200 `{"status":"pong"}`。`GET /pawn/no-such-pawn` が 200
  `{"error":"Pawn 'no-such-pawn' not found"}`。実在する入植者の `GET /pawn/<id>` が
  200 でその入植者を返す
- 観察方法: `curl` の応答コードと本文。`Player.log` の作成時刻がジャンクションの
  張り替えより後であること（読み込んだのが実装のビルドである証拠）と、例外が無いこと
- 復元手順: `develop` へ統合した後、ジャンクションを主チェックアウトへ張り直す
  （TASK0003 の「復元」と同じ手順）。読み取りの要求だけなので、セーブへの変更は無い

#### 実機確認の結果（2026-09-26）

- ジャンクションの張り替え 09:20、`Player.log` の作成 09:21:03。実装のビルドで起動した
- `GET /ping` → 200 `{"status":"pong"}`（利用者が実行）
- `GET /pawn/no-such-pawn` → 200 `{"error":"Pawn 'no-such-pawn' not found"}`
- `GET /pawn/Human888` → 200、入植者 Liam を返した（`/pawns` から id を得た）
- `Player.log` に `exception` を含む行は 0 件

## 作業記録

- 実装は `task/TASK0004-nullable-impl` の 1 コミット（`4bc4e48`）。作業書はこの
  ブランチに置き、実装と分けた
- 呼び出し側から新しい警告（CS8602）は出なかった。`FindColonist` と `Colonist` の
  呼び出し 26 箇所は、着手前の grep のとおりすべて null を検査していた
- 破壊確認は、戻した注釈 4 つの警告位置が互いに重ならないので、1 回のビルドへまとめた。
  `Body` の代入を外した側は、想定の CS8618 に加えて CS0649 も出た
- この環境の worktree 隔離セッションは、引数に空白を含む `-p:RimWorldDir=...` を
  「検証できない構文」として拒否した。引数全体を引用符で括ると通った

## 機能への反映

特記なし。

## 裁定記録

- **作業の取り決めで着手するか**（2026-09-26・ユーザー）: 承認
- **第三者視点レビュー（CP6）を実施するか**（2026-09-26・ユーザー）: 不要
    - 根拠: 変更は型の宣言と 1 つのコンストラクタに閉じ、正否はコンパイラの警告件数が
      判定する。注釈を戻す破壊確認がそれを裏づける
- **実機確認を行うか**（2026-09-26・ユーザー）: 軽く行う（`/ping` と存在しない入植者の
  `/pawn/<id>`）。実在する入植者の `/pawn/<id>` は、非 null の経路を通すために
  エージェントが 1 本足した

## stakeholder 未裁定の残課題

- nullable 警告を以後エラーとして扱うか
  （`<WarningsAsErrors>nullable</WarningsAsErrors>`）。0 件を保つにはゲートが要る。
  ただし upstream のビルドの振る舞いを変えるので、本作業では扱わない
- 本作業を upstream へ送るか
