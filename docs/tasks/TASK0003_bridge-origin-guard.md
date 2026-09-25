---
task: TASK0003
status: frozen
features: []
requirements: []
relates-to:
 - TASK0002_vendored-dll-removal
user-reach: high
dev-reach: low
drive: high
irreversible: low
hazard: none
---

# HTTP ブリッジをブラウザ由来の要求から守る

## 目的

Mod の HTTP ブリッジは全応答に `Access-Control-Allow-Origin: *` を付け、認証を持たない。
その結果、プレイ中に開いた**任意の Web ページ**からブリッジを読み書きできる。

- GET は ACAO `*` のおかげで cross-origin から応答本文を読める。コロニーの状態が漏れる
- POST は `Content-Type: text/plain` にすれば preflight の要らない simple request になり、
  `JObject.Parse` は Content-Type を見ないので `/command/*` がそのまま実行される。
  ポーズ・時間加速・建物の解体指定・ゾーン削除などが外部サイトから可能になる

実害はゲーム内に閉じるが、塞ぐ費用は小さい。初回起動の前に塞ぐ。

## 目標

- 応答から `Access-Control-Allow-Origin` の付与をやめる
- ブラウザが送った要求を拒否する。判定はブラウザが必ず付け JS から消せないヘッダ
  （`Origin` と `Sec-Fetch-Site`）の有無で行う
- `Host` がループバックを名乗らない要求を拒否する（DNS rebinding を塞ぐ）
- 共有秘密が設定されていればそれを照合する。設定が無ければ照合しない（任意）
- 判定をゲームの型に依存しない純粋関数へ切り出し、自動テストを成果物として残す
- Python 側が秘密を持っていればヘッダへ載せる

いずれも提供要求（SREQ）を採番しない。知覚ゲートを通らないためである ── 機能設計記述の
外部仕様に知覚項目を加えず、既存の経路の入口に判定を足す作業である。

## 非目標

初回レビューで挙げた他の指摘は本作業で扱わない。扱うかどうかは未裁定で、下の残課題に置く。

- 指摘 B（同一マシンの他プロセスからの到達）。トークンを**必須**にすれば塞がるが、
  RimWorld 起動前のユーザー環境変数の設定が要る。裁定済みで、本作業では任意に留める
- 指摘 C（キュー無制限・ボディサイズ無制限によるゲームの停止）
- 指摘 D（タイムアウト済みの要求がセーブのロード後に実行される）
- 指摘 E（`HandleContext` の未処理例外と 503 経路の競合）
- 指摘 F（`Stop()` がデッドコード・ポート 8080 固定）
- 指摘 G（Python 側で `pawn_id` を URL エスケープしていない）
- 秘密の受け渡し経路の自動化（ファイル生成・自動共有）。環境変数で与える形に留める

## 問題

- **ブリッジは RimWorld のプロセス内で動く。** 判定ロジックをゲームの型に依存させると、
  単体で実行できずテストが書けない
- **`Origin` の無いブラウザ要求が残る。** `no-cors` の GET（`<img>` 等）は `Origin` を
  送らない。ただし応答を読めず副作用も無いため、実害は無い。`Sec-Fetch-Site` を併せて
  見れば現代のブラウザではこれも落ちる
- 既存の `OPTIONS` → 204 の分岐は CORS preflight のためだけに在る。CORS をやめる以上、
  この枝も同じ変更で外す必要がある
- **判定を通らなかった要求をゲームスレッドへ渡してはいけない。** キューはメインスレッドが
  1 フレームずつ処理するため、拒否をキューの先で行うと指摘 C を悪化させる

## 到達基準

- [x] `RequestGuard` が RimWorld・Unity の型に依存せず、単独でコンパイルできる
- [x] 自動テストが判定の真理値表を覆い、`dotnet test` の終了コードで合否が出る
- [x] **ガードの各条件を 1 つずつ外すと、対応するテストが落ちる**（外して落ちることを
      確かめてから戻す）
- [x] 応答ヘッダに `Access-Control-Allow-Origin` を設定する箇所がソースに無い
- [x] `OPTIONS` → 204 の分岐が削除されている
- [x] 拒否がキューへの投入より前で起き、拒否された要求がゲームスレッドへ渡らない
- [x] POST は `Content-Type: application/json` を要求し、他の媒体型は 415 で落ちる
- [x] 秘密が未設定のとき、Python 側は従来どおり動く（ヘッダを載せない）
- [x] 秘密が設定されているとき、Python 側が `X-MCP-Token` を載せる
- [x] `dotnet build` が 0 エラー
- [x] 著者が実機確認の手順を用意する
- [x] 利用者が実機で確認し、結果を検証の節へ記録する
- [x] CP6 の第三者視点レビューを実施するかをユーザーが裁定する
- [x] CP6 の第三者視点レビューを実施し、各指摘の disposition をユーザーが裁定する

## 概要設計

### 判定を純粋関数へ切り出す

`MCP/Source/MCP/RequestGuard.cs` を新設する。`using Verse` を持たず、文字列だけを受ける。

```csharp
internal static class RequestGuard
{
    public static string? RefusalReason(string? origin, string? secFetchSite,
                                        string? hostHeader, string? expectedToken,
                                        string? presentedToken)
    public static bool IsAcceptedContentType(string? contentType)
}
```

`RefusalReason` は拒否の理由を返し、通すときは null を返す。真偽値と `out` 引数の組に
しないのは、「拒否するときに限り理由がある」ことを 1 つの値で表し、呼び出し側の
コンパイラに照合させるためである。

判定は 5 段で、先に当たったものが理由になる。1〜4 段は `RefusalReason` が受け持ち、
403 を返す。

1. `origin` が空でない → 拒否。ブラウザは cross-origin の fetch/XHR と全 POST に必ず付け、
   JS からは消せない
2. `secFetchSite` が空でない → 拒否。`Origin` の無い `no-cors` GET もここで落ちる
3. `hostHeader` のホスト名部が許可リストに無い → 拒否。許可は `127.0.0.1` と `localhost`
   の 2 つで、等号で照合する。ただし実機では Mono の `HttpListener` が、受付先
   `127.0.0.1` と一致しない Host（`localhost` を含む）をこの判定より前に 400 で返す。
   この段は受付先を広げたときの備えとして残す（裁定記録を参照）
4. `expectedToken` が空でなく `presentedToken` と一致しない → 拒否。比較は固定時間で行う
5. POST の `Content-Type` の媒体型が `application/json` でない → 415 で拒否する。
   `IsAcceptedContentType` が受け持つ（`charset` 等の引数は見ない）。ブラウザの form は
   この媒体型を送れず、`fetch` で指定すると preflight が先に飛んで 1 段で落ちる。
   ブラウザが `Origin` を付けなくても、ページからコマンドへ届かない（裁定記録を参照）

許可リストで書くのは、拒否リストが書き手の語彙を先回りできないため。照合を等号で書けるので
そちらを採る。

### 呼び出し側

`MCPHttpServer.HandleContext` で、**キューへ投入する前に**判定する。拒否は 403 と
JSON の理由で返す。あわせて `Access-Control-Allow-Origin` の付与を削除する。

`RequestRouter.Handle` の `OPTIONS` → 204 の枝を削除する。CORS を廃止する以上、
preflight に応える意味が無い。削除後、`OPTIONS` は既定の 405 に落ちる。

秘密は `RIMWORLD_MCP_TOKEN` 環境変数から起動時に読む。未設定なら段 4 を行わない。

### Python 側

`main.py` の `httpx.AsyncClient` 生成が 3 箇所に散っているので `_new_client()` に集約し、
`RIMWORLD_MCP_TOKEN` があれば `X-MCP-Token` を載せる。`import os` が増える。

`uv run mcp dev main.py` の Inspector は、ブラウザから Inspector 自身を叩く構成である。
ブリッジを叩くのは Python プロセスで、httpx は `Origin` も `Sec-Fetch-*` も送らない。
したがってこの変更で壊れない。

### テスト

`MCP/Tests/` に net8.0 のテストプロジェクトを置き、`RequestGuard.cs` を
`Compile Include` で共有する。xunit を採るのは、検査ごとに名前が付き、落ちた 1 件が
集計から消えないため。自作のコンソールハーネスでも終了コードは出せるが、名前と件数の
管理を自前で持つことになる。

## 実装計画

1. `RequestGuard.cs` を新設する
2. `MCP/Tests/` を作り、真理値表のテストを書く。**各条件を外して落ちることを確かめる**
3. `MCPHttpServer` から ACAO を外し、キュー投入前に判定を挟む
4. `RequestRouter` から `OPTIONS` の枝を外す
5. `main.py` のクライアント生成を集約し、ヘッダを載せる
6. `README.md` と `CONTRIBUTING.md` に秘密の与え方を書く
    - `CONTRIBUTING.md` 側（テストの回し方）は、実装のブランチでなく作業書のブランチに
      置いた。`CONTRIBUTING.md` は fork ローカルである。upstream 行きのブランチに置くと
      squash で実装と溶接され、upstream へ出せるコミットが残らない（`CONTRIBUTING.md`
      「One purpose per branch」）
7. ビルドとテストを通し、実機の確認手順を用意する

## 工数概算

| ステップ | 内容 | 概算（実働）| 主な不確実性 |
|---|---|---|---|
| 1-2 | 判定の切り出しとテスト・破壊検証 | 20〜40 分 | テストプロジェクトの初期化 |
| 3-5 | 呼び出し側と Python 側の差し替え | 15〜30 分 | 少ない |
| 6-7 | ドキュメントと検証 | 15〜30 分 | 実機確認は利用者の操作を要する |
| 計 | | 50〜100 分 | 幅の主因: 環境と道具の不確実性（下記） |

- 参照クラス: `docs/records/effort-anchors.md` の 2 件。どちらもずれの主因は実装量でなく
  環境と道具の不確実性だった。本作業ではテストプロジェクトの初期化がその位置に当たる
- 実績（完了時）: 壁時計 238 分（計画コミット 19:39 から `develop` への統合 23:37 まで。
  数え方はコミット時刻の差で、裁定待ちを含むため実働の上限にあたる）。見積もり
  50〜100 分に対し上振れ。最初の実装の完了（20:26）までは 47 分でレンジ内に収まった。
  主因は残る 191 分で、実機確認・CP6 の第三者視点レビュー・その反映が占める。いずれも
  概算の表に行を持たなかった

## 検証

### 概要

自動テスト・破壊検査・実機確認・CP6 の第三者視点レビューを実施した（2026-09-25）。

下のチェックリストの数値は、`develop` へ統合した `a580d35` に対する実測である。出典は
統合時の引き継ぎメモ（追跡外）で、作業書のブランチでは測り直していない（このブランチは
ドキュメントだけを変える）。破壊検査のスクリプトはリポジトリに残していない。

### 検証項目（チェックリスト）

- [x] `dotnet build` が 0 エラー / 10 警告（着手時 13 警告）
- [x] `dotnet test` が 58 件緑（`net10.0`）
- [x] 破壊検査 3 本（`ablate.py` / `ablate_notices.py` / `reorder.py`）が緑
- [x] コミット規約の検査で、実装ブランチの 16 本に違反 0 件
- [x] 実機で 8 観測が期待と一致する（下記「実機確認の結果」）
- [x] CP6 の第三者視点レビューの指摘 189 件を束ね、各束の disposition をユーザーが裁定した
      （裁定記録を参照）

### 検証手順

自動（手順の正本は `CONTRIBUTING.md`「Tests」）:

```sh
dotnet test MCP/Tests/MCP.Tests.csproj
dotnet restore MCP/Tests/MCP.Tests.csproj --locked-mode --force
```

実機:

#### ブラウザを名乗る要求が落ちること

- 目的: 任意の Web ページからブリッジを操作できる経路が塞がったことを、動いている
  ゲームに対して確かめる
- 前提条件: RimWorld が起動しセーブを読み込んでいる。Mod が有効。ブリッジが
  `127.0.0.1:8080` で待ち受けている。配置と設定は下の「前提: Mod の配置と設定」に従う
- 期待結果: 素の要求は 200 を返す。`Origin` / `Sec-Fetch-Site` を付けた要求は 403 を
  返し、理由が本文に入る。`Host` を偽装した要求は `HttpListener` が 400
  `Invalid host` で返し、ガードへ届かない。秘密を設定した場合、不一致の要求は 403 を返す
- 観察方法: `curl` の応答コードと本文。あわせて RimWorld のログに Mod の例外が出ていない
  ことを見る
- 復元手順: 下の「復元」に従う

##### 手順の約束

PowerShell で実行する。curl は PowerShell 5.1 では Invoke-WebRequest の別名なので
`curl.exe` と書く。`-i` は応答ヘッダも表示する指定。各コマンドは 1 行で、連結していない。

パスのうち次の 2 つは環境ごとに置き換える。RimWorld のパスは Steam の既定の
インストール先で書く。GOG 版など別の場所なら、そこへ置き換える。

- `<worktree>`: 実装を載せたブランチの worktree（例: `task/TASK0003-guard-impl` の
  worktree）
- `<主チェックアウト>`: `develop` を持つ主チェックアウト

##### 前提: Mod の配置と設定

`Mods\MCP` が `<worktree>` の `MCP` フォルダを指していること。

RimWorld は `Mods\<フォルダ>\About\About.xml` を持つフォルダだけを Mod として読む。
`Mods` 直下へ DLL を直接置いても読まれない。リンク先は `<worktree>` にする。主チェック
アウトの `MCP.dll` はガードを含まない別のビルドである。ジャンクション（ディレクトリ
リンク）を使うので管理者権限は要らない。RimWorld を終了してから実行する。

`Mods` 直下へ直接置いた DLL 3 件があれば取り除く。

```powershell
Remove-Item "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\MCP.dll"
Remove-Item "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\0Harmony.dll"
Remove-Item "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\Newtonsoft.Json.dll"
```

`Mods\MCP` をジャンクションとして作る。

```powershell
New-Item -ItemType Junction -Path "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\MCP" -Target "<worktree>\MCP"
```

`About.xml` と `MCP.dll` がジャンクション越しに見えることを確かめる。

```powershell
Get-ChildItem "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\MCP\About"
Get-ChildItem "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\MCP\1.6\Assemblies"
```

RimWorld を起動し、メインメニューの Mods で「MCP」を有効にする。再起動を求められたら
従う。オプション → 一般 の「バックグラウンドで実行」をオンにする（オフだとターミナルへ
移った時点でゲームの更新が止まり、要求は 15 秒後に 503 `Game thread timeout` になる）。
セーブを読み込んでからケース 1 へ進む。

##### ケース 1: 素の要求は通る

```powershell
curl.exe -i http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 200 OK` / 本文 `{"status":"pong"}`
- 併せて見る: 応答ヘッダに `Access-Control-Allow-Origin` が無いこと

##### ケース 2: `Origin` を付けた要求は落ちる

```powershell
curl.exe -i -H "Origin: https://example.test" http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 403 Forbidden`
- 本文: `{"error":"Origin header present: this bridge does not serve browsers"}`

##### ケース 3: `Sec-Fetch-Site` を付けた要求は落ちる

```powershell
curl.exe -i -H "Sec-Fetch-Site: cross-site" http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 403 Forbidden`
- 本文: `{"error":"Sec-Fetch-Site header present: this bridge does not serve browsers"}`

##### ケース 4: `Host` を偽装した要求は落ちる

```powershell
curl.exe -i -H "Host: evil.test:8080" http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 400 Bad Request`
- 本文: `<h1>Bad Request (Invalid host)</h1>`

拒否するのはガードでなく `HttpListener` である。受付先 `127.0.0.1` と一致しない Host は、
`localhost` も含めてガードへ届く前に 400 で返る。したがって `Player.log` に Refused の行は
出ない。ガードの Host 判定は受付先を広げたときの備えで、判定そのものは単体テストが
確かめる。

##### ケース 5: 共有秘密

任意機能。試すなら RimWorld を終了してから設定し、起動し直す。

秘密を設定する。この行だけは現在の PowerShell セッションにしか効かないので、RimWorld を
同じセッションから起動すること。

```powershell
$env:RIMWORLD_MCP_TOKEN = "choose-your-own-value"
```

Steam から起動すると秘密は届かない（ゲームは Steam 本体の環境変数を受け継ぐ）。同じ
PowerShell から exe を直接起動する。インストール先に `steam_appid.txt` が在るので Steam
経由の再起動は起きない。Steam 本体は起動したままにしておく。

```powershell
& "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\RimWorldWin64.exe"
```

秘密が届いたことをログで確かめる。

```powershell
Select-String -Path "$env:USERPROFILE\AppData\LocalLow\Ludeon Studios\RimWorld by Ludeon Studios\Player.log" -Pattern "\[MCP\]"
```

- 期待: `[MCP] Requests must carry the shared secret in X-MCP-Token.`
- `[MCP] No shared secret configured.` が出たら秘密は届いていない。以降の結果は無効

セーブを読み込む。

起動後、秘密を載せない要求が落ちること。

```powershell
curl.exe -i http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 403 Forbidden`
- 本文: `{"error":"Missing or wrong X-MCP-Token"}`

違う秘密も落ちること。

```powershell
curl.exe -i -H "X-MCP-Token: wrong-value" http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 403 Forbidden`

正しい秘密は通ること。

```powershell
curl.exe -i -H "X-MCP-Token: choose-your-own-value" http://127.0.0.1:8080/ping
```

- 期待: `HTTP/1.1 200 OK` / 本文 `{"status":"pong"}`

##### 全ケース共通で併せて見るもの

RimWorld のログ（開発者モードのログウィンドウ、または `Player.log`）に次の行が出ている
こと。ケース 5 では 2 行目が別の行になる。

```text
[MCP] HTTP bridge listening on http://127.0.0.1:8080/
[MCP] No shared secret configured. ...
```

拒否したケースでは理由ごとに 1 度だけ次の行が出る。同じ理由の 2 度目以降はログに出ない
（ページが叩き続けたときにログを埋めないため）。

```text
[MCP] Refused a request. <理由>
```

Mod の例外（赤字）が出ていないことも見る。

##### 復元

ゲームを終了する。ケース 5 で環境変数を設定した場合は PowerShell を閉じれば消える。
ゲーム側の状態は読み取り系の確認しかしていないので、セーブへの変更は無い。

`Mods\MCP` のジャンクションは `<worktree>` を指したまま残る。TASK0003 を `develop` へ
統合した後に `<主チェックアウト>` へ張り直す。1 行目はリンクだけを消し、リンク先の中身には
触れない。

```powershell
(Get-Item "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\MCP").Delete()
New-Item -ItemType Junction -Path "C:\Program Files (x86)\Steam\steamapps\common\RimWorld\Mods\MCP" -Target "<主チェックアウト>\MCP"
```

#### 実機確認の結果（2026-09-25）

- 環境: Steam 版 RimWorld 1.6。`Mods\MCP` を `TASK0003-guard-impl` の worktree へ
  junction で接続した。確認したビルドの `MCP.dll` の SHA-256 は `ebf262eb…` で、
  worktree のビルド出力と一致する
- 実行: 利用者が curl.exe を打鍵し、出力を会話へ貼った（確度 B）。`Player.log` は
  エージェントが直接読んだ（確度 A）

| ケース | 観測 | 期待との一致 |
|---|---|---|
| 素の要求 | 200 `{"status":"pong"}`。`Access-Control-Allow-Origin` 無し | 一致 |
| `Origin` つき | 403、理由が本文に入る | 一致 |
| `Sec-Fetch-Site` つき | 403、理由が本文に入る | 一致 |
| `Host: evil.test:8080` | 400 `Bad Request (Invalid host)`（HTML） | 一致（改訂後の期待） |
| `Host: localhost:8080` | 400 `Bad Request (Invalid host)`（HTML） | 仮説の確認に追加 |
| 秘密を設定し、ヘッダ無し | 403 `Missing or wrong X-MCP-Token` | 一致 |
| 秘密を設定し、違う値 | 403 `Missing or wrong X-MCP-Token` | 一致 |
| 秘密を設定し、正しい値 | 200 `{"status":"pong"}` | 一致 |

- `Player.log`: 拒否の行は理由ごとに 1 行だけ出た。同じ理由を 2 回拒否したケースでも
  2 行目は出ていない。`Host` のケースの行は出ていない（リスナーが止めたため）。例外は
  0 件（今回と前回の起動の 2 ファイル）
- 当初の期待（`Host` の偽装は 403）は実機で偽だった。改訂の経緯は裁定記録を参照
- 確認の途中で次の 2 つの前提が要ると分かった。いずれも本作業の変更とは関係なく、
  upstream から続く振る舞いである
    - 「バックグラウンドで実行」がオフだと、ターミナルへフォーカスを移した時点で
      ゲームの更新が止まる。そのため要求は 15 秒後に 503 `Game thread timeout` になる
    - 秘密の環境変数は、Steam から起動したゲームには届かない。同じ PowerShell から
      `RimWorldWin64.exe` を直接起動する（`steam_appid.txt` が在るため再起動は起きない）

## 作業記録

- 実装は `task/TASK0003-guard-impl` で 16 コミットに分けて進め、squash して `develop` の
  `a580d35` へ統合した。作業書はこのブランチ（`task/TASK0003-bridge-origin-guard`）に
  置き、実装と分けた。fork ローカルのドキュメントを upstream 行きのブランチへ混ぜない
  ためである
- **実装ブランチへ `CONTRIBUTING.md` を 1 度入れ、取り出し直した。** squash すると
  upstream へ出せないコミットになると気づき、「Tests」節を `git am` で作業書のブランチへ
  移した（実装計画 6）
- **実機確認で `Host` の期待値が偽だと分かった。** Mono の `HttpListener` は受付先
  `127.0.0.1` と一致しない Host を、`localhost` も含めてガードより前に 400 で返す。
  期待値を改め、ガードの `Host` 判定を残す理由をソースに書いた（裁定記録を参照）
- CP6 の第三者視点レビューは指摘 189 件を返した。機序ごとに束ね、再評価層の指摘した
  食い違い 11 件を全て採ったうえで、束ごとの disposition をユーザーの裁定にかけた。
  今対応の束は実装ブランチで反映してから統合した

## 機能への反映

特記なし。

## 裁定記録

- **秘密を必須にするか任意にするか**（2026-09-25・ユーザー）: 任意
    - 根拠: 指摘 A は `Origin` / `Sec-Fetch-Site` / `Host` のガードだけで塞がる。秘密が
      追加で塞ぐのは指摘 B（同一マシンの他プロセス）に限られる。必須にすると RimWorld
      起動前のユーザー環境変数の設定が要り、導入の摩擦でガードごと無効化される方が危ない
- **判定のテストを成果物として残すか**（2026-09-25・ユーザー）: 残す
    - 根拠: セキュリティ判定は退行が静かに起きる。真理値表が残れば、条件を 1 つ緩めた
      変更が自動で落ちる
- **CP6 の第三者視点レビューを実施するか**（2026-09-25・ユーザー）: 実施する
    - 根拠: セキュリティ修正であり、判定を 1 段でも読み違えると穴が残る。TASK0001 /
      TASK0002 と違って免除に倒せない
- **`Host` 偽装の実機の期待値を改めるか**（2026-09-25・ユーザー）: 改める。400 を
  リスナーが返し、ガードへ届かないことを期待値とする
    - 根拠: 実機で `evil.test` も `localhost` も 400 `Invalid host` になった。成り立たない
      期待値を残すと、後から読む者が誤る
- **実機で届かないガードの `Host` 判定を残すか**（2026-09-25・ユーザー）: 残す。
  残す理由をソースのコメントに書く
    - 根拠: 受付先を `+` や `localhost` へ広げる変更が入れば、この判定が DNS rebinding に
      対する唯一の守りになる。残しても失うものが無い
- **README の `localhost` の記述を直すか**（2026-09-25・ユーザー）: 直す。本作業が
  書いた許可の説明は本作業のブランチで、upstream 由来の疎通確認と図は README の
  ブランチ（`task/readme-run-in-background`）で直す
    - 根拠: `localhost` で到達できると読める記述は、動く環境で疎通確認を失敗させる
- **`Host` の実機確認を CP6 の他の指摘の反映より先に行うか**（2026-09-25・ユーザー）:
  先に行う
    - 結果: Mono の `HttpListener` が受付先と一致しない Host を 400 で返すことが確定し、
      レビュー時点では推論だった前提が一次情報になった
- **POST に `Content-Type: application/json` を必須にするか**（2026-09-25・ユーザー）:
  必須にする。到達基準を 1 つ増やす作業の取り決めの変更として承認した
    - 根拠: ブラウザはこの媒体型を simple request で送れず、`fetch` で付ければ
      preflight が `Origin` の検査に先に当たる。Fetch Metadata を送らないブラウザから
      も、原理的にコマンドへ届かなくなる。Python 側は全呼び出しが `json=` を使うので
      変更が要らない
    - 裁定の対象は `/command/*` だった。ブリッジの POST はすべて `/command/*` なので、
      実装は POST 全体に当てている
- **拒否理由をどこまで開示するか**（2026-09-25・ユーザー）: 現状維持。4 種の理由を 403 の
  本文で返す
    - 根拠: 実装は公開され、理由は固定の集合で、診断の価値が上回る。理由が同一マシンの
      他プロセスへ追加で与えるのは「秘密が設定済みか」だけで、そのプロセスは環境変数を
      直接読める。DNS rebinding の経路では実機で 400 が先に返るので、403 の本文は届かない
- **テストプロジェクトを `net10.0` へ移すか**（2026-09-25・ユーザー）: 移す。Mod 側は
  `net472` のまま
    - 根拠: `net8.0` のサポート終了は 2026-11-10。.NET 10 は LTS で 2028-11-14 まで
- **README の「Run in background」の段落**（2026-09-25・ユーザー）: `develop` 側の文を
  採る。実装ブランチ側の文が持っていた機序（すべての要求がゲームスレッドを待つため）は
  足さない。あわせて、この段落だけ折り返しの書式が他と違う点も揃えない。どちらも受容
- **CP6 の第三者視点レビューの disposition**（2026-09-25・ユーザー）: 束ごとに次のとおり
    - 今対応: 束 A・B・C・E・F（README の記述の精度）・G・H・I・M（`CONTRIBUTING.md`
      と `LangVersion` の固定）・O・P・Q・T（記述品質）・U・V。P は本作業書の修正に
      当たり、他は `a580d35` に入った。束 D は実機確認で決着した。束 J・N・S は上の個別の
      裁定が決めた
    - 起票: 6 件。行き先は下の「stakeholder 未裁定の残課題」
    - 受容: 次の 3 件と、上の「Run in background」の 2 件
        - 束 K2（`OPTIONS` の削除で未知のメソッドが 1 往復する）。ブラウザは `Origin` の
          検査に先に当たり、非ブラウザの未知メソッドは想定外の利用である
        - 束 R の現在の重複（言語をまたぐ定数）。実測で一致している
        - 改行コードの検査が NG を返したこと。index は LF である。検査器は作業ツリーを
          読むが、規約が縛るのはコミットの内容である
- **起票 6 件をどこへ置くか**（2026-09-26・ユーザー）: 本作業書の残課題へ置き、新しい
  作業書は今は起こさない
    - 根拠: 起票は決定の先送りで、作業書を起こすには設計が要る。残課題の節は
      `task-triage` が走査するので埋もれない
- **上位 2 層（要求一覧・機能設計記述）を新設するか**（2026-09-26・ユーザー）: 今は
  新設しない
    - 根拠: 本作業は `features` も `requirements` も持たず、提供要求を採番しないと目標で
      宣言している。導出されるものが無い。新設するなら TASK0001〜0003 を遡って起こす
      別の作業になる

## stakeholder 未裁定の残課題

- 初回レビューで挙げた指摘 C・D・E・F・G を扱うか、扱うならいつか。本作業では非目標に
  置いたが、扱わないという裁定は下っていない。CP6 のレビューから 2 件を起票してここへ
  寄せた
    - C・D へ: 受理経路の資源制御（キューの長さ・本文の長さ・1 フレームで処理する量）。
      キューの予算制御は新しい設計を要する
    - F へ: ブリッジの生涯管理（`Start` が失敗したときの復帰・`Stop` を呼ぶ経路）
- 指摘 B（同一マシンの他プロセスからの到達）を塞ぐため、秘密を必須へ切り替えるか
- ポート 8080 を先に掴んだプロセスへ、Python 側が秘密を渡してしまう（CP6 から起票）。
  クライアントが相手のサーバを確かめる仕組みは新しい設計を要する
- テストを回す CI（CP6 から起票）。現在は `CONTRIBUTING.md`「Tests」の手順を手で回す
- 秘密を入れ替える仕組み（CP6 から起票）。現在は両側の環境変数を手で揃え、両方を
  起動し直す
- 言語をまたぐ定数の機械照合（CP6 から起票）。`X-MCP-Token`・`RIMWORLD_MCP_TOKEN`・
  `application/json` を C# と Python の両方が知っている。前の 2 つは両側とも定数で、
  媒体型は httpx が暗黙に送るので Python 側に定数が無い。現在の値が一致していることは
  受容した（裁定記録を参照）
- CP6 のレビューが挙げた差分外の既存項目 3 件の disposition。`RequestRouter` の culture
  依存・LLM 由来の値の URL パスへの埋め込み・記録ファイルの絶対パスである。レビューの
  推奨は受容だが、ユーザーの裁定は記録されていない
