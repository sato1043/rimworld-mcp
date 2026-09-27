---
task: TASK0029
status: frozen
features: []
requirements: []
relates-to:
 - TASK0012_tool-annotations
 - TASK0016_rimworld-play-skill
user-reach: high
dev-reach: low
drive: high
irreversible: low
hazard: none
---

# MCP のツール一覧とサーバーの案内で、スキル `rimworld-play` の存在を知らせる

## 目的

rimworld-mcp を使い始めた人とモデルが、遊び方の手順と攻略知識を持つスキル
`rimworld-play` の存在に気づき、使えるようにする。MCP だけでも遊べるが、まとまった
知識はスキルの側にある。

## 目標

- 入口の 3 個の tool（`get_game_state`・`ping`・`get_colony_overview`）の description の
  末尾に、スキルの案内を 1 文足す。tool 自体の説明を先に置く
- サーバーの `instructions`（initialize の応答）に同じ案内を置く。`instructions` を
  読まないクライアントには tool の description が届き、description を読み込む前の
  モデルには `instructions` が届く
- 案内は、スキルの名前と持つ知識・遊ぶときにセッションにあれば使うこと・スキルが
  リポジトリのどこに在るかを言う。外部の URL は書かない
- 案内の文面を 1 つの定数に置き、4 か所が同じ文面を使う

## 非目標

- upstream へ送ること。変更は fork 専用で、`mcp_server/main.py` に fork だけの差分を
  持つ（裁定記録）
- 案内を置く tool を 3 個より増やすこと・全 tool に置くこと
- tool の名前・引数・出力・annotations の変更と、案内以外の description の変更
- スキルの中身と置き場所の変更（TASK0016 の裁定のまま、リポジトリの `.claude/skills`）
- 外部の URL（公開先のリポジトリ等）へ誘導すること（裁定記録）
- `README.md` にスキルの案内を足すこと
- スキルをセッションへ自動で入れる仕組み（プラグイン化・`~/.claude/skills` への配置）

## 問題

- **Claude Code は tool の description を後から読み込む。** このリポジトリの 87 個の
  tool は、ToolSearch で読み込むまで名前しかモデルに届かない（2026-09-28 のセッションで
  観測）。description の案内は、モデルがその tool を使うと決めた時点で届く
- **`instructions` は tool より先に、毎セッション届く。** initialize の応答に入り、
  tools/list より前に取られる。Claude Code はシステムプロンプトへ入れる（同日、serena の
  案内で観測）。MCP は `--scope user` で登録されているので、RimWorld を使わない
  セッションにも入る
- **`instructions` を無視するクライアントがある。** OpenAI 系がそうだとユーザーが述べた
  （会話中の発言。一次情報は未確認）
- **tools/list にはサーバー全体の説明を置く欄が無い。** SDK の `ListToolsResult` が持つ
  のは `tools` と `nextCursor`（と汎用の `_meta`）だけである。tools/list で届けるには
  tool の description に書くしかない
- **全 tool に書くと嵩む。** description は 87 個で計 18,378 文字である（2026-09-28
  実測）。概要設計の文面の案は 273 文字で、全 tool なら 23,751 文字増えて 2.3 倍になる。
  3 個なら 819 文字（+4.5%）である
- **入口の 3 個を選ぶ根拠。** tools/list の先頭は `get_game_state`（登録順）で、その
  description は「Call this first」と言う。スキルの 1 サイクルは `ping` と
  `get_colony_overview` から始まる。この 3 個を読み込まずに別の tool から始めたモデル
  には description の案内は届かず、`instructions` が補う
- **スキルが見えるのはこのリポジトリを cwd にしたセッションだけである。** スキルは
  リポジトリの `.claude/skills` に在り、MCP は user スコープで登録されている。スキルが
  セッションに無いときは、名前とリポジトリの中の置き場所が手がかりになる
- **外部への誘導は規約違反とみなされうる。** tool の説明から公開先の URL へ導くことを
  ユーザーが退けた（会話中の発言。どの規約かは未確認）。案内は置き場所をリポジトリの中の
  相対パスで示すに留める
- **`mcp_server/main.py` は upstream と共有のファイルである。** fork だけの差分を持つと、
  upstream の変更を取り込むときに、3 個の docstring の近くで衝突しうる
- **Claude Code が `instructions` の長さを制限するかは確かめていない。** 案内は数百文字に
  収める

## 到達基準

- [x] initialize の応答の `instructions` が案内の文面を持つ
- [x] 3 個の tool の description が、元の説明のあとに案内の文面で終わる。元の説明の
      部分は変更前と同じである
- [x] 残る 84 個の tool の description が変更前と同じで、案内の文面を含まない
- [x] 案内の文面が、スキル名 `rimworld-play`・遊ぶときにあれば使うこと・リポジトリの
      中の置き場所（`.claude/skills/rimworld-play`）を持つ。URL（`://` を含む語）を
      持たない
- [x] 上の 4 つを自動テストが確かめ、`pytest` の終了コードで合否が出る
- [x] 案内を 1 個の tool から外す・`instructions` から外す・別の tool へ付けると、
      対応するテストが落ちる（外して落ちることを確かめてから戻す）
- [x] stdio で起動したサーバーから、クライアントが `instructions` と 3 個の description を
      受け取れる
- [x] 名前・引数・出力の schema・annotations が変更前と同じである（前後の `list_tools` を
      比べる）
- [x] 既存のテストがすべて通る
- [x] CP6 の第三者視点レビューの実施の要否をユーザーが裁定した（不要と決まった）

CP6 は不要と提案する。変更は案内の定数 1 個とその参照 4 か所で、振る舞いは変わらない。
案内の有無と位置は自動テストと破壊で確かめられる。誤りが起きても、文面が誤る（読めば
分かる）か、案内が届かない（テストが落ちる）かのどちらかで、静かに危険な方へ倒れない。

## 概要設計

### 案内の文面

英語で書く（既存の description と同じ）。次を案とし、実装で長さを測って詰める。

> Companion skill: the Claude Code skill rimworld-play holds the play cycle,
> per-colony notes and strategy for RimWorld 1.6 without DLC. Use it when playing a
> colony, if this session has it. It is kept in .claude/skills/rimworld-play of the
> repository this server comes from.

- 「遊ぶとき」に限る。スキルは MCP の開発と tool の動作確認では使わないと宣言している
- 事実を述べる形で書き、モデルへの指示は「あれば使う」の 1 つに留める。利用者へ何かを
  伝えさせる指示と、外部の URL は置かない
- 入手の手順（どこへ置くか）は書かない。置き場所は利用者の選ぶことである

### 置き方

- 文面は `main.py` の定数 1 個に置く
- `instructions` は `RimWorldMCP(...)` の生成時にその定数を渡す
- 3 個の tool には、関数の定義の場所で読めるデコレータで付ける。デコレータは
  docstring の末尾へ定数を足すだけで、`@mcp.tool(...)` の下（先に適用される側）に置く。
  `add_tool` は `functools.wraps` で docstring を引き継ぐので、足した文面が description に
  入る。登録の関門（`RimWorldMCP.add_tool`）には手を入れない
- どの tool に付けたかは、デコレータの付いた定義を読めば分かる。一覧を別に持たない

### 検出の形

- `instructions` を in-memory のクライアントで取り、文面を含むことを見る
- 3 個の名前の集合をテストに持ち、description が文面で終わる tool の集合と一致する
  ことを見る。一致を見るので、付け忘れも、別の tool への付け間違いも落ちる
- 元の説明が変わっていないことは、description から文面を除いた部分を、デコレータを
  通さない関数の docstring と比べて見る
- 文面の中身（スキル名・置き場所・URL を持たないこと）は定数を見るテストで確かめる

### ブランチ

作業書と実装を 1 本のブランチ（`task/TASK0029-skill-notice`）に置く。実装も fork 専用で
upstream へ送らないので、分ける理由が無い。コミットは作業書とコードで分ける
（CONTRIBUTING.md「Commits」）。

## 実装計画

1. 案内の定数とデコレータを足し、`instructions` と 3 個の tool に付ける
2. テストを書く。案内を外す・付け替えると落ちることを確かめる
3. 前後の `list_tools` を比べる。stdio で起動したサーバーから `instructions` と
   description を受け取る
4. 自己レビュー（`/code-review`）
5. 統合の後、Claude Code の新しいセッションで案内が届くことを見る（実機。到達基準の
   外）

## 工数概算

| ステップ | 内容 | 概算（実働）| 主な不確実性 |
|---|---|---|---|
| 1 | 定数・デコレータ・4 か所 | 10〜20 分 | 文面を詰める回数 |
| 2 | テストと破壊 | 15〜30 分 | |
| 3 | 前後比較と stdio | 10〜20 分 | TASK0012 の手順を流用できるか |
| 4 | 自己レビュー | 10〜20 分 | |
| 計 | | 45〜90 分 | 幅の主因: 文面の裁定の往復 |

- 前提: 実装はエージェント。ゲームの起動は要らない
- 参照クラス: `docs/records/effort-anchors.md` の TASK0012（Python 側で tool の
  宣言と description を変えた。ステップ 1〜4 は 69〜82 分）。本作業は触る tool が 3 個で、
  CP6 を不要と提案している

実績（確度 B。作業したセッションの記録の時刻から導いた。区間はユーザーの発言で切った）:

| 区間 | 起点 → 終点（UTC） | 壁時計 |
|---|---|---|
| 分析・計画 | 依頼（09-28 01:17）→ 着手の承認（01:54） | 37 分 |
| ステップ 1〜4 と記録 | → 作業書の記録（02:20 ごろ） | 約 26 分 |

- ステップ 1〜4 は概算 45〜90 分の下限を割った。文面は計画の段で裁定を受け終えていて、
  幅の主因に置いた往復が実装の段に残らなかった
- 分析・計画の壁時計はユーザーの返答を待つ間を含む。空きを除いた値は測っていない

## 検証

### 概要

自動テストと破壊で案内の有無・位置・文面を確かめた。stdio で起動したサーバーの
initialize と tools/list は、変更の前後で比べた。Claude Code の新しいセッションで案内が
届くことは統合の後に見るので、未検証である。

### 検証項目（チェックリスト）

- [x] `pytest` が 155 件すべて通る（新しい 7 件を含む。skip・xfail・警告なし）
- [x] 破壊 8 件のうち、狙った 7 件は対応するテストを落とす。守りの側を弱めた 1 件
      だけが素通りする（作業記録）
- [x] stdio の前後比較: 87 個の名前と並びは同じで、変わったのは 3 個の `description`
      だけである。3 個とも、変更前の description が変更後の先頭にそのまま残る。
      `instructions` は None から案内の文面になった。description の合計は 823 文字増えた
- [x] 自己レビュー（`/code-review` medium、`568de46`）の所見は 0 件
- [ ] Claude Code の新しいセッションで案内が届く（統合の後に見る。未検証）

### 検証手順

#### 自動

- テスト: `uv run --directory mcp_server pytest -q`
- 前後比較: 変更前と変更後の worktree で、stdio のクライアントからサーバーを起動し、
  initialize の `instructions` と tools/list の全項目を JSON へ落として比べる。
  使ったスクリプトはセッションのスクラッチパッドにあり、追跡していない
  （`dump_tools.py`・`compare.py`。比較は問題があれば終了コード 1）

#### 実機

- **Claude Code の新しいセッションで案内が届く**
    - 目的: 統合した後のサーバーの案内が、実際のクライアントでモデルに届くか
    - 前提条件: develop へ統合し、user スコープの `rimworld` を本体のチェックアウトで
      起動する。セッションの cwd はこのリポジトリの外にする（スキルが見えない状態）
    - 期待結果: システムプロンプトの MCP の案内に rimworld の文面が出る。ToolSearch で
      `get_game_state` を読み込むと、description の末尾に同じ文面が出る
    - 観察方法: 新しいセッションを起こし、システムプロンプトの「MCP Server
      Instructions」を読む。続けて ToolSearch で `get_game_state` を読み込み、
      description を読む
    - 復元手順: なし（状態を残さない）

## 作業記録

### 2026-09-28 実装と検証（ステップ 1〜4）

- 文面は概要設計の案のまま実装した（273 文字）
- 区切りの空行は、docstring の末尾の改行の有無で 1 行か 2 行を足して作る。
  `ping` の docstring は 1 行で末尾に改行が無く、ほかの 2 個は改行で終わる
- 元の説明の比較には、`main.py` の関数の定義からデコレータと本体を除いてコンパイルした
  docstring を使う。Python 3.13 以降のコンパイラは docstring の字下げを除くので、
  コンパイルした値でないと description と比べられない（`requires-python` は 3.14）
- 到達基準の「残る 84 個が変更前と同じ」は、はじめは前後比較でしか見ていなかった。
  自動テストで確かめるという基準に届かないので、テストを 1 本足した（`3859af6`）
- 破壊の結果（落ちたテスト）
    - `ping` から案内を外す: 集合の一致と `ping` の位置のテスト
    - `get_weather` に付ける: 集合の一致と、残る tool の docstring のテスト
    - `instructions` から外す: `instructions` のテスト
    - 案内を説明の前に置く: 位置のテスト 3 件
    - 空行を 1 行にする: `ping` の位置のテスト
    - 説明の中身を書き換える: 位置のテスト 3 件
    - 文面に URL を入れる: 文面のテスト
    - 比較の相手をソースでなくデコレータの後の docstring にしてから説明を書き換える:
      どれも落ちない。元の説明を守っているのが、ソースから取る比較の相手だと分かる
- 最初に当てた「説明の前後の空白を除く」破壊は、空行の検査で落ちていて、元の説明の
  比較まで届いていなかった。説明の中身を書き換える破壊に替えた

### 2026-09-28 上位 2 層の導出

`frozen` を立てた後に `spec-derive` を走らせた。本作業の目標 4 件は「新規候補（SREQ
未採番）」に出た。要求一覧が無いので採番しない（要求一覧を起こすかは TASK0006 の残課題で
裁定待ち）。整合性違反・照合の食い違い・必須欄の未記入はいずれも 0 件である。

## 機能への反映

特記なし。

## 裁定記録

- **起票**（2026-09-28・ユーザー）: ツールの一覧の description にスキルの存在を載せ、
  MCP を使いたい人がスキルに気づいて使えるようにする
- **置き場所**（2026-09-28・ユーザー）: tools/list の description と `instructions` の
  両方に置く。tools/list で届く時点を重く見る。`instructions` は OpenAI 系が無視するので
  それだけには頼らず、description を読み込む前のモデルのために残す
- **文面の位置**（2026-09-28・ユーザー）: description の末尾に置く。tool 自体の説明が
  先に来る
- **upstream との関係**（2026-09-28・ユーザー）: 案内を常に出す fork 専用の変更にする。
  upstream へは送らない。エージェントは、スキルのディレクトリが在るときだけ案内を出す形を
  推奨した
- **外部の URL**（2026-09-28・ユーザー）: 公開先の URL を書かない。外部への誘導は規約
  違反とみなされうる。エージェントの案（fork の GitHub の URL と「利用者へ伝える」指示）を
  退けた

- **入口の tool**（2026-09-28・ユーザー）: `get_game_state`・`ping`・
  `get_colony_overview` の 3 個とするエージェントの提案を承認した
- **置き場所の文**（2026-09-28・ユーザー）: 文面の最後の文（リポジトリの中の置き場所）を
  残すエージェントの推奨を承認した
- **ブランチ**（2026-09-28・ユーザー）: 作業書と実装を 1 本のブランチに置くエージェントの
  提案を承認した
- **CP6**（2026-09-28・ユーザー）: 不要と裁定した（エージェントの提案どおり）
- **優先度**（2026-09-28・ユーザー）: `user-reach` high・`dev-reach` low・
  `irreversible` low・`hazard` none はエージェントの候補を承認した。`drive` は high と
  判定した
- **着手の承認**（2026-09-28・ユーザー）: CP4 で目的・目標・非目標・到達基準を承認した

## stakeholder 未裁定の残課題

なし（2026-09-28 検分。起票から着手の承認までの会話で出た論点を、裁定記録と照合した）
