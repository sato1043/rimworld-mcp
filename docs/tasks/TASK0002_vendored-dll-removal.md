---
task: TASK0002
status: frozen
features: []
requirements: []
relates-to:
 - TASK0001_build-path-override
user-reach: low
dev-reach: high
drive: high
irreversible: low
hazard: none
---

# 同梱 DLL をパッケージマネージャ経由の取得へ切り替える

## 目的

このリポジトリは upstream（`allenmonkey970/rimworld-mcp`）の fork であり、
`MCP/1.6/Assemblies/` に第三者がコミットしたバイナリ 3 件を抱えている。RimWorld が
読み込むのはこの DLL であって、レビューしたソースではない。素性を検証する仕組みを
持たないまま実行する経路を、**初回起動の前に**断つ。

取得元をパッケージフィードへ一本化し、固定の手段を検証可能な形（contentHash）へ移す。

## 目標

- `MCP/1.6/Assemblies/` の DLL 3 件を追跡から外し、ビルドで生成する運用へ移す
- `packages.lock.json` を導入し、浮動バージョン指定を contentHash つきで固定する
- `.gitignore` と `CONTRIBUTING.md` を切り替え後の実態へ合わせる

いずれも提供要求（SREQ）を採番しない。知覚ゲートを通らないためである ── 機能設計記述の
外部仕様に知覚項目を加えず、配布物の構成と依存の固定方法だけを変える。

## 非目標

- `README.md` の変更。ビルドを step 1 に置く手順は切り替え後も正しく、記述を変える
  必要が無い
- `MCP.pdb`。既存の `*.pdb` の行で除外済み
- upstream への働きかけ。追跡除外は upstream の明示方針と逆を向く fork 固有の判断で
  あり、送らない
- 依存パッケージそのものの更新（Harmony・Newtonsoft のバージョン変更）

## 問題

- **コミット済み DLL が事実上のロックとして働いている。** `Lib.Harmony 2.*` と
  `Newtonsoft.Json 13.*` は浮動指定で、ロックファイルが無い。DLL を外すだけだと、
  将来の restore が別バージョンを引いても気づく手段が消える
- **upstream の明示方針と逆を向く。** upstream の `.gitignore` には
  「Assemblies/*.dll are committed on purpose: they are the distributable mod.」と
  ある。upstream が DLL を更新するたび、同期でコンフリクトが出る
- **clone しただけでは動かなくなる。** 「クローンして symlink すれば遊べる」という
  upstream の性質を失う。ビルドを挟む前提になる
- 切り替えで配布物の中身が変わってはいけない。変わったなら、それは素性の違いである

## 到達基準

- [x] `git ls-files` に `MCP/1.6/Assemblies/` 配下の DLL が 1 件も出ない
- [x] `MCP/Source/MCP/packages.lock.json` が追跡下にあり、Lib.Harmony と
      Newtonsoft.Json を `resolved` と `contentHash` つきで固定している
- [x] `dotnet restore --locked-mode` が成功する
- [x] ロックファイルを意図的に壊すと `--locked-mode` の restore が失敗する
      （ガードが効いていることの確認。確認後に復元する）
- [x] ビルドで `MCP/1.6/Assemblies/` に DLL 3 件が生成される
- [x] 生成された `0Harmony.dll` と `Newtonsoft.Json.dll` が、削除前のコミット済み
      バイナリと **SHA-256 が一致**する（切り替えで配布物の中身が変わらないことの証明）
- [x] ビルド後に `git status` が clean（`.gitignore` が生成物を覆っている）
- [x] `CONTRIBUTING.md` が、生成物を追跡しないこと・upstream と乖離していること・
      同期時にコンフリクトが出ることを述べている
- [x] CP6 の第三者視点レビューを実施するかをユーザーが裁定する

## 概要設計

3 つの変更を、行き先の違いで 2 つのブランチに割る。

**upstream 行き** — 依存の固定。誰にとっても再現性の改善であり、fork 固有の判断を
含まない。

- `MCP.csproj` に `<RestorePackagesWithLockFile>true</RestorePackagesWithLockFile>`
- 生成された `MCP/Source/MCP/packages.lock.json` を追跡下に置く

**fork 固有** — 生成物の追跡除外。upstream の明示方針と逆を向くため送らない。

- `git rm --cached` で DLL 3 件を index から外す（作業ツリーのファイルは残す）
- `.gitignore` に `MCP/1.6/Assemblies/*.dll` を足し、既存のコメント
  （「committed on purpose」）を実態へ書き換える
- `CONTRIBUTING.md` のビルド節を書き換える。現在の「tracked な生成物なので惰性で
  stage するな」は、切り替え後は誤りになる

順序が要る。**固定を先に入れ、除外を後に置く。** 逆にすると、ロックが無い状態で
バイト単位の固定も失われる窓ができる。

ハッシュの照合は削除の前に採る必要がある。TASK0001 の検証中に採取済みで、記録
（`docs/records/20260925_dev-environment-and-branch-migration.md`）に残っている。
本作業の検証では、削除前にもう一度採り直してから照合する。

## 実装計画

1. `RestorePackagesWithLockFile` を有効にし、`packages.lock.json` を生成して
   コミットする（upstream 行きブランチ）
2. `--locked-mode` の restore が通ること、ロックを壊すと落ちることを確かめる
3. 削除前のコミット済み DLL 3 件の SHA-256 を採る
4. `git rm --cached` で 3 件を外し、`.gitignore` と `CONTRIBUTING.md` を直す
   （fork 固有ブランチ）
5. ビルドして 3 件が生成されること、`git status` が clean であること、
   第三者由来の 2 件が手順 3 のハッシュと一致することを確かめる

## 工数概算

| ステップ | 内容 | 概算（実働）| 主な不確実性 |
|---|---|---|---|
| 1-2 | ロックファイルの導入と破壊検証 | 20〜40 分 | ロックの壊し方の当て所 |
| 3-5 | 追跡除外・規約更新・照合 | 20〜40 分 | `.gitignore` の書き方 |
| 計 | | 40〜80 分 | 幅の主因: 破壊検証が素通りした場合の切り分け |

- 参照クラス: TASK0001（実働 約 90 分）。あちらは環境不備の切り分けを含んだため、
  それを除いた正味は本作業と同程度と見る
- 実績（完了時）: 壁時計 11 分（計画コミット 19:17 から検証完了 19:28 まで。数え方は
  コミット時刻の差で、ユーザーの裁定待ちを含むため実働の上限にあたる）。見積もり
  40〜80 分に対し大幅な下振れ。主因は、幅の主因に置いた「破壊検証が素通りした場合の
  切り分け」が実際に 2 件起きたにもかかわらず、どちらも数分で片付いたこと

## 検証

### 概要

ロックの固定・ロックを壊したときの失敗・切り替え後のビルドによる再生成・生成物の
ハッシュ照合を実測した。実機（RimWorld に読み込ませての動作）は未検証。この作業は
取得経路だけを変え、生成される IL に影響しないため。

照合は期待を先に宣言する器で行った（`hash_compare.py` に「一致を期待するファイル名」を
引数で渡し、期待と観測が食い違ったら非零終了する）。一致した事実だけを眺める形にすると、
`MCP.dll` が偶然一致した場合も「問題なし」に見えてしまうため。

### 検証項目（チェックリスト）

- [x] `packages.lock.json` が Lib.Harmony 2.4.2 / Newtonsoft.Json 13.0.4 /
      Microsoft.NETFramework.ReferenceAssemblies 1.0.3 を `contentHash` つきで固定
- [x] `dotnet restore --locked-mode --force` が exit 0
- [x] ロックの `resolved` を `2.4.2` から `2.4.1` へ書き換えると `NU1403`
      （コンテンツハッシュ検証の失敗）で exit 1
- [x] 書き戻した後に再度 exit 0。さらに削除して再生成したロックと**差分なし**
- [x] `git rm --cached` 後、`git ls-files MCP/1.6/` が 0 件
- [x] 退避した 3 件を消した状態からビルドし、`0Harmony.dll` / `MCP.dll` /
      `Newtonsoft.Json.dll` が再生成される。0 エラー / 13 警告で、警告は既存コードの
      nullable 由来
- [x] 生成された `0Harmony.dll` と `Newtonsoft.Json.dll` が退避分と SHA-256 一致。
      `MCP.dll` は不一致（ビルドメタデータ由来として期待どおり）
- [x] ビルドと restore の後も `git status` が本変更の差分だけを示す。生成された DLL 3 件は
      `git check-ignore` が `.gitignore:18` で覆っていると報告する
- [ ] 実機での読み込み（未検証。上記の理由により不要と判断）

### 検証手順

自動:

```sh
dotnet restore MCP/Source/MCP/MCP.csproj --locked-mode --force
dotnet build MCP/Source/MCP/MCP.csproj -p:RimWorldDir="<RimWorld の導入先>"
git ls-files MCP/1.6/
```

`--force` は必須。復元済みのプロジェクトでは restore が up-to-date 判定で短絡し、
ロックの検証を行わないまま exit 0 を返す。

実機: なし。

## 作業記録

- **破壊検証が 1 度素通りした。** ロックの `resolved` を書き換えても
  `dotnet restore --locked-mode` が exit 0 を返した。破壊が当たっていないことを先に疑って
  ファイルを確認したところ、書き換えは効いていた。原因は restore 側にあり、復元済みの
  プロジェクトでは up-to-date 判定で短絡して検証そのものを行わない。`obj/` を消すか
  `--force` を付けると `NU1403` で落ちた。この落とし穴は upstream にも当たるので
  `MCP.csproj` のコメントと `CONTRIBUTING.md` の両方に残した
- **同じ型の誤測が改行の調査でも起きた。** `grep -c` のパターンがシェルの unescape で
  壊れており、CR の件数として誤った値を返した。`git -c core.autocrlf=false status` が
  clean を返したのも、git の stat キャッシュが一致して内容比較を省いたためで、やはり
  何も測っていなかった。較正済みのスクリプトで測り直し、index が LF・作業ツリーが CRLF で
  あることを確定させた
- 上記から `.gitattributes` を足し、`packages.lock.json` を `text` と宣言した。これが
  無いと restore 後に dirty になるかどうかが各開発者の `core.autocrlf` に依存する
- 退避は削除でなく移動で行った（scratchpad へ `mv`）。再生成が失敗した場合に戻せる形を
  保つため

## 機能への反映

特記なし。

## 裁定記録

- **同梱 DLL をパッケージ取得へ切り替えるか**（2026-09-25・ユーザー）: 切り替える
    - 根拠: コミットされた第三者バイナリを検証なしに実行するのは危険であり、初回起動の
      前に断つべきである
- **`MCP.dll` だけを外すか、3 件とも外すか**（2026-09-25・ユーザー）: 3 件とも外す
    - 根拠: 当初は「`MCP.dll` は再生成できるので外し、第三者の 2 件はロック代わりに
      残す」案を採ったが、残す案は第三者バイナリを実行し続けることを意味する。
      ロックの役割は `packages.lock.json` が引き受けられる
- **浮動バージョン指定を固定するか**（2026-09-25・ユーザー）: 固定する
    - 根拠: コミット済み DLL を外すとバイト単位の固定が消える。代替が無いまま外せない
- **CP6 の第三者視点レビューを実施するか**（2026-09-25・ユーザー）: 不要

## stakeholder 未裁定の残課題

なし（2026-09-25 検分。到達基準・裁定記録・非目標を見た）
