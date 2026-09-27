# 開発環境の構築と develop メインラインへの移行

- 作業日: 2026-09-25（2026-09-26 に「ターゲットフレームワーク net472 の妥当性」を、
  2026-09-27 に「worktree の置き場所の移し替え」を追記）
- 対象: 開発機（Windows 11 Pro 10.0.26200 / Git Bash）と `sato1043/rimworld-mcp`（fork）
- 位置づけ: **fork の所有者による変更の記録**。upstream（`allenmonkey970/rimworld-mcp`）の
  判断・方針ではない

確度の凡例:

- **A**: 本セッションでコマンドを実行し、出力を直接観測した（一次相当）
- **B**: 利用者の申告による。打鍵の瞬間は観測していない
- **C**: 推論。観測から導いたが直接の裏付けを持たない

## 環境セットアップ

利用者が実行したコマンド（確度 B）:

```sh
winget install Microsoft.DotNet.SDK.8
winget install astral-sh.uv
uv python install 3.14
gh repo clone sato1043/rimworld-mcp
```

結果として観測した状態（確度 A、2026-09-25 時点）:

| 項目 | 観測値 | 確認コマンド |
|---|---|---|
| .NET SDK | 8.0.425（`C:\Program Files\dotnet`） | `dotnet --version` |
| uv | 0.11.28 | `uv --version` |
| uv 管理の CPython | 3.14.6 | `uv python list --only-installed` |
| システムの Python | 3.13.4 | `python --version` |
| GitHub CLI | 認証済み。アカウント `sato1043`、git は SSH | `gh auth status` |
| 作業ツリー | `C:/Users/sato1043/projects/rimworld-mcp` | `git worktree list` |

`mcp_server/pyproject.toml` は `requires-python = ">=3.14"` を宣言する。システムの Python は
3.13.4 なので、`uv run` が uv 管理の 3.14.6 を選ぶ前提で成り立っている（確度 A）。

2026-09-26 の観測（確度 A）: 上の表の .NET SDK は古くなっている。2026-09-25 23:07 に
SDK 10.0.401 が加わり（`sdk/10.0.401` の作成時刻）、`dotnet --version` は 10.0.401 を
返す。`global.json` は無く、最新の SDK が選ばれるため、MOD 本体（net472）のビルドも
SDK 10 が担う。導入は winget で行った（利用者の申告、確度 B）。`winget list` は
`Microsoft.DotNet.SDK.10` 10.0.401 と `Microsoft.DotNet.SDK.8` 8.0.425 を、ソース
winget として報告する（確度 A）

## develop メインラインへの移行（段階 1）

動機: `main` は upstream のブランチと見なし、fork 側のメインラインを `develop` に置く。

前セッションで提示した手順（確度 C。利用者が「段階 1 を実施した」と申告したが、実際に打った
コマンド列は観測していない。観測できるのは下記の移行後の状態だけである）:

```sh
git fetch --all --prune
git switch -c develop
git push -u origin develop
gh repo edit sato1043/rimworld-mcp --default-branch develop
git remote set-head origin -a
git branch -d main
```

移行後に観測した状態（確度 A、2026-09-25）:

```
$ git branch -avv
* develop                18c41f3 [origin/develop] fix: use GitHub CDN URL for demo video and remove local copy
  remotes/origin/HEAD    -> origin/develop
  remotes/origin/develop 18c41f3 fix: use GitHub CDN URL for demo video and remove local copy
  remotes/origin/main    18c41f3 fix: use GitHub CDN URL for demo video and remove local copy
  remotes/upstream/HEAD  -> upstream/main
  remotes/upstream/main  18c41f3 fix: use GitHub CDN URL for demo video and remove local copy
```

- ローカル `main` は存在しない
- `origin/HEAD` が `origin/develop` を指す。GitHub 側の既定ブランチ変更が反映されている
- `origin/main` と `upstream/main` は残置されている
- `develop` / `origin/develop` / `origin/main` / `upstream/main` はすべて `18c41f3` で、
  この時点で内容差は無い
- worktree は主チェックアウトの 1 本のみ。作業用の worktree は未作成

ローカル `main` を持たないまま fork の `main` を upstream へ追随させる手順は
[CONTRIBUTING.md](../../CONTRIBUTING.md) が正本として持つ。

## この機械に固有の罠

いずれも確度 A、2026-09-25 時点の観測。

- **RimWorld は Steam 版**が `C:\Program Files (x86)\Steam\steamapps\common\RimWorld` にある。
  GOG 版は存在しない。`Assembly-CSharp.dll` と `UnityEngine.CoreModule.dll` は同ディレクトリの
  `RimWorldWin64_Data\Managed\` に在る
- **現状この機械では C# 側をビルドできない。** `MCP/Source/MCP/MCP.csproj` の `HintPath` が
  `C:\GOG Games\RimWorld\` 固定で、そのパスは存在しない
- **この機械でこの Mod はまだ起動していない。** Steam の `Mods\` には
  `Place mods here.txt` しか無く、README が指示する `Mods\MCP` の symlink は張られていない
- `.serena/` が未追跡のまま作業ツリーに残っている。`.gitignore` には記載が無い。一方
  `.idea/` は `.gitignore:21` に既出で、`git check-ignore -v .idea/` が無視を報告する

### 2026-09-25 後刻の更新

同日の後半に状況が動いた。いずれも確度 A。

- **ビルド不可は解消した。** TASK0001 で `RimWorldDir` プロパティを導入し、Steam の
  導入先を与えてコンパイルが通ることを確認した（0 エラー / 13 警告。警告はすべて既存
  コードの nullable 由来）
- **別の障害が 1 つ在った。** 利用者レベルの `NuGet.Config` の `<packageSources>` が
  空で、パッケージフィードが 1 つも登録されていなかった（NU1100）。マシンレベル・
  リポジトリ内の設定も無し。nuget.org への疎通は正常（http 200）。利用者が
  `dotnet nuget add source` で nuget.org を登録して解消した。当該 `NuGet.Config` の
  更新時刻は 2026-08-28 で、2026-09-25 に入れた dotnet SDK より古い
- **コミット済みの同梱バイナリ 2 件は改変されていない。** NuGet から取得して再ビルド
  した `0Harmony.dll` と `Newtonsoft.Json.dll` は、コミット済みのものとハッシュが一致
  した（Lib.Harmony 2.4.2 / Newtonsoft.Json 13.0.4）。初回レビューで「公式配布物との
  ハッシュ照合は未実施」として残していた項目が、これで埋まった
- **`MCP.dll` は再ビルドでハッシュが変わる。** サイズは同一（254,464 バイト）で、
  TASK0001 は C# ソースに触れていない。差分はビルドごとに変わるメタデータ（MVID・
  タイムスタンプ）と見られる（確度 C。IL を逐次比較してはいない）

## ターゲットフレームワーク net472 の妥当性

調査日 2026-09-26。問いは「`MCP/Source/MCP/MCP.csproj` の
`<TargetFramework>net472</TargetFramework>` は古い版に見えるが、問題は無いか」である。

### net472 と SDK の関係

- `net472` は TFM（Target Framework Moniker。成果物が動くランタイムの種類と版を表す）で、
  .NET Framework 4.7.2 を指す。dotnet SDK の版ではない
- この機械の SDK は 8.0.425 と 10.0.401 の 2 本である（`dotnet --list-sdks`、確度 A）。
  net472 向けのビルドには NuGet キャッシュの参照アセンブリ
  `microsoft.netframework.referenceassemblies.net472` 1.0.3 を使う（確度 A）
- テストプロジェクト `MCP/Tests/MCP.Tests.csproj` は `net10.0` を採る。RimWorld に
  読み込まれないためで、理由は同ファイルのコメントが持つ

### 読み込む側の観測

Steam 版 RimWorld の導入先で観測した（確度 A）。DLL は
`RimWorldWin64_Data\Managed\` 配下。

| 項目 | 観測値 | 確認方法 |
|---|---|---|
| RimWorld | 1.6.4871 rev590 | `Version.txt` |
| Unity | 2022.3.35f1 | `RimWorldWin64_Data\globalgamemanagers` 内の版文字列 |
| Mono | 導入先の直下に `MonoBleedingEdge\` が在る | ディレクトリ一覧 |
| `mscorlib.dll` | 4.0.0.0 | `AssemblyName.GetAssemblyName` |
| `netstandard.dll` | 2.1.0.0 | 同上 |
| `System.Runtime.dll` | 4.1.0.0 | 同上 |
| `Assembly-CSharp.dll` | 文字列 `mscorlib` を 3 件、`netstandard` を 1 件含む | バイト列の grep |

- `Assembly-CSharp.dll` に `.NETFramework,Version=` の文字列は見つからなかった。参照表の
  解析はしていないので、ゲーム本体の TFM は特定できていない
- MOD の DLL はゲームのランタイム（Unity 同梱の Mono と見る。確度 C）へ読み込まれる。
  TFM を決めるのは読み込む側で、MOD 側は選べない
- `net10.0` でビルドした DLL は `System.Runtime` 10.0.0.0 を参照する。導入先の
  `System.Runtime.dll` は 4.1.0.0 で版が足りず、読み込みに失敗すると見る（確度 C。実機では
  試していない）
- RimWorld の MOD を net472 でビルドするのは慣例である（確度 C。慣例の出典を本調査では
  確認していない）

### サポート期限

出典: [Lifecycle FAQ - .NET Framework](https://learn.microsoft.com/en-us/lifecycle/faq/dotnet-framework)
（ページの `updated_at` は 2025-11-24。2026-09-26 に取得。確度 A）

- 4.5.2 以降は Windows の構成要素として扱われ、インストール先の OS のライフサイクルに
  従う。4.7.2 に単独の終了日は無い
- 4.5.2・4.6・4.6.1 は 2022-04-26 に終了した（SHA-1 署名の廃止に伴う）
- 4.7.2 の対象 OS の一覧に Windows 11 は無い。Windows 11 は 4.8 / 4.8.1 の対象で、FAQ は
  4.6.2 以降を先行版の in-place 更新（互換を保つ置き換え）と位置づける
- この MOD が動くのは Microsoft の .NET Framework でなく Mono の上なので、上の期限は直接
  効かない（確度 C）。効くのは RimWorld と Unity の対応状況である。RimWorld の版上げで
  TFM が変わったら、`MCP.csproj` の `TargetFramework` と `OutputPath`
  （`1.6\Assemblies`）を合わせて見直す

### C# 9 と net472 の組み合わせ

- `LangVersion` は 2 つのプロジェクトとも 9 に固定されている
- 参照アセンブリの `mscorlib.dll` は `IsExternalInit`・`ModuleInitializerAttribute`・
  `SkipLocalsInitAttribute` を含まない（grep で 0 件）。RimWorld 同梱の `mscorlib.dll` も
  `IsExternalInit` を含まない。同じ grep で既存の型 `ExtensionAttribute` と
  `TupleElementNamesAttribute` はそれぞれ 1 件当たり、検査が効くことを確かめた（確度 A）
- したがって `init` アクセサと `record` は、型を自前で定義しないとコンパイルできないと見る
  （確度 C。コンパイルは試していない）。現行の `MCP/Source/` はどちらも使っていない
  （`git grep` で当たるのはコメント中の英単語 record だけ。確度 A）
- テストを `net10.0` で走らせても、この差はテストで塞がらない。`LangVersion` の固定が
  揃えるのは構文の版だけで、ランタイムの API の差は MOD のビルドで初めて現れる（確度 C）

この節の調査は新しい判断点を立てない（2026-09-26 検分。本節の全項）。

## worktree の置き場所の移し替え

2026-09-27。置き場所を、利用者の Claude Code 設定が持つ WorktreeCreate hook の規則
（`$HOME/worktrees/<repo>/<name>`）へ揃えた。裁定は「要裁定の判断点」の節が持つ。

動機: 旧い形では、エージェントは `git worktree add` の後に `EnterWorktree(path=...)` で
移る。この移動のたびに、リポジトリ外の worktree への permission-root の移し替えの確認が
出ていた（利用者の申告、確度 B）。

主チェックアウトから `EnterWorktree(name=worktree-location)` を呼んで観測した（確度 A）:

- worktree は `C:/Users/sato1043/worktrees/rimworld-mcp/worktree-location` に作られた
- 作られた直後の HEAD は `54044ec` で、`develop` と一致した。ブランチは付かない
  （detached）。`git switch -c task/worktree-location` で切れた
- linked worktree の中では `git rev-parse --show-toplevel` がその worktree のパスを返す。
  hook はこの値の basename をリポジトリ名に使うので、worktree の中から起動すると置き場所が
  その worktree の名前の下へずれる（確度 C。hook を読んで導いた。起動しては試していない）
- この時点の linked worktree は 3 本（旧い置き場所の `event-log`・`event-log-impl` と
  本件）で、hook の上限の既定値 3 に達している。旧い置き場所の 2 本は移していない

## 要裁定の判断点

いずれも作業書を介さず、fork の所有者が本セッションで直接裁定した。そのため行頭に仰ぎ先の
作業 ID を持たない。裁定の内容は [CONTRIBUTING.md](../../CONTRIBUTING.md) と `.gitignore` が
正本として持つ。

- worktree の置き場所を `../rimworld-mcp.worktrees/<slug>` と `../rimworld-mcp-<slug>` の
  どちらにするか（裁定 2026-09-25。前者を採る）
- 作業ブランチを `develop` へ統合する方法を PR 経由と直接 squash merge のどちらにするか
  （裁定 2026-09-25。直接 squash merge を採る）
- `.serena/` を `.gitignore` へ加えるか（裁定 2026-09-25。加える。`.idea/` は既出のため変更なし）
- 浮動バージョン指定（`Lib.Harmony 2.*` / `Newtonsoft.Json 13.*`）を `packages.lock.json` で
  固定するか（裁定 2026-09-25。固定する。TASK0002 で扱う）
- 同梱 DLL 3 件を追跡から外し、パッケージマネージャ経由の取得へ切り替えるか
  （裁定 2026-09-25。切り替える。TASK0002 で扱う）
- worktree の置き場所を、利用者の Claude Code 設定の WorktreeCreate hook の規則
  （`$HOME/worktrees/<repo>/<name>`）へ揃えるか（再裁定 2026-09-27。揃える。2026-09-25 の
  候補は sibling の 2 形だけで、この形を比べていなかった）
- 計測用の一時の木 `git worktree add ../before`（`tools/measure_tool_output.py` の説明と
  TASK0009 の記録）を上の規則へ揃えるか（裁定 2026-09-27。揃えない。規則が対象にするのは
  作業ブランチを載せる worktree で、計測用の木は任意の版に detached で置いてすぐ外す。
  hook は版を受け取れないので `EnterWorktree` の形は当てはまらない）
