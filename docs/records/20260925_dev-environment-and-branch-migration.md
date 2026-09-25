# 開発環境の構築と develop メインラインへの移行

- 作業日: 2026-09-25
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
