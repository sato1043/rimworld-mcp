---
task: TASK0006
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

# 状況把握の tool を束ね、重い 3 つの tool の出力を絞る

## 目的

LLM が RimWorld の状況を把握するのに要する、待ちとトークンを減らす。

TASK0005 の実測（[記録](../records/20260926_bridge-latency-and-payload.md)）から次が
分かった。

- ブリッジへの要求は、順に送ると 1 本ごとに 1 フレームを待つ。重いセーブでは 1 本
  170 ms 前後になる。同時に送れば、10 本でも 1 回分の待ちで返る（1,690 ms → 182 ms）
- 中盤のセーブでは、`/animals`・`/buildings`・`/animals/training` の 3 つが、全 endpoint
  の応答の約 6 割を占める

## 目標

- 状況把握用の複合 tool を 1 つ足す。中で複数の読み出しを同時に送り、1 回分の待ちで返す
- 複合 tool は、読み出しの 1 つが失敗しても残りを返し、失敗した節にはブリッジが述べた
  理由を載せる
- `get_animals` の既定の出力を、野生動物は種ごとの頭数に、飼育動物は個体ごとの一覧にする。
  個体ごとの全件と、1 つの種の個体一覧は、引数で選べるようにする
- `get_buildings` の既定の出力で、電力を使う建物を個体の一覧から種類ごとの集計に変える。
  個体の一覧は引数で選べるようにする
- `get_animal_training` の出力から重複を除く。訓練項目ごとの `defName`・`label`・
  `learned`・`wanted` を、習得済みの項目名と習得待ちの項目名の 2 つの一覧にする
- 出力の形を整える処理を Python 側の純粋関数へ切り出し、自動テストを成果物として残す
- 変更の前後の出力の大きさを中盤のセーブで実測し、記録へ残す（記録層）

提供要求（SREQ）は採番しない。このリポジトリは要求一覧を持たない（TASK0003 の裁定）。
LLM から見える tool の外部仕様を変えるので、要求一覧を起こすかは残課題に置く。

## 非目標

- Mod（C#）の変更。ブリッジの応答の形は変えず、Python 側で整える
- 上の 3 つ以外の tool の出力の変更
- 通し番号付きのイベントログ、HTTP 500 を返す 3 つの endpoint の修正、resource 2 箇所の
  共有クライアント化。いずれも TASK0005 の残課題にあり、本作業では扱わない
- トークン数の厳密な計数。大きさはバイト数と文字数で比べる

## 問題

- **Python 側で整えても、ブリッジの直列化と転送の費用は減らない。** TASK0005 で、直列化の
  費用はフレーム待ちに埋もれると測った（`/fertility` を除く）。減らしたいのは LLM へ渡る
  トークンなので、Python 側で足りる
- **既定の出力から野生動物の個体を外すと、狩りの指示に要る id が見えなくなる。**
  `hunt_animal` は `target_id` を取る。種を指定して個体一覧を引ける引数が要る
- **ブリッジの失敗は、`_raise_with_reason` が例外として投げる。** 同時に送る読み出しの
  1 つが失敗すると、既定の `asyncio.gather` は全体を失敗させる。例外を節ごとに受け止める
  必要がある
- **ゲームの表示言語が日本語で、ラベルが UTF-8 で 1 字 3 バイトになる。** TASK0005 の
  「バイト数 ÷ 4」はトークン数を少なく見積もっている可能性がある。本作業では前後の比を
  バイト数と文字数の両方で出す
- **中盤のセーブの実データが手元に無い。** 大きさの実測には、利用者にセーブを読み込んで
  もらう必要がある。自動テストは実データと同じフィールドを持つ合成データで書く
- `mcp_server` は自動テストを持たない。pytest を開発用の依存として足す

## 到達基準

- [x] 複合 tool の往復時間が、中盤のセーブで `/ping` の中央値の 2 倍以下である。順に送れば
      読み出しの本数倍になるので、同時に送れていることを見分けられる
- [x] 複合 tool は、読み出しの 1 つが 500 を返しても残りの節を返し、失敗した節にブリッジの
      理由を載せる（自動テスト）
- [x] `get_animals` の既定の出力が、野生動物の頭数でなく種の数に比例する。同じ種の野生
      動物を 1 頭から 100 頭へ増やしても、出力の大きさが頭数の分だけ増えない（自動テスト）
- [x] `get_animals` で、1 つの種の個体を id つきで引ける（自動テスト）
- [x] `get_buildings` の既定の出力が、電力を使う建物の個数でなく種類数に比例する
      （自動テスト）
- [x] `get_animal_training` の出力が、習得済みと習得待ちの区別を失わない（自動テスト）
- [x] 形を整える規則を 1 つずつ外すと、対応するテストが落ちる（外して落ちることを確かめて
      から戻す）
- [x] 中盤のセーブで、3 つの tool の既定の出力と複合 tool の出力の大きさを前後で実測し、
      バイト数と文字数で記録へ残す
- [x] 3 つ以外の tool は、変えた tool を名指す説明の文言と、ID の入手先の案内を実態に
      合わせる説明の文言だけが変わる（差分で確かめる）
- [x] 第三者視点レビュー（CP6）の裁定を受けた（実施を提案し、実施と裁定された）
- [x] CP6 の第三者視点レビューを実施し、各指摘の disposition をユーザーが裁定する
- [x] 実装のコミットが fork ローカルのファイル（`CONTRIBUTING.md`・`CLAUDE.md`・`docs/`・
      `tools/`）に触れていない（upstream へ送れる形である）

CP6 の実施を提案した根拠: LLM から見える tool の外部仕様（既定の出力・引数・新しい
tool）を変える。Python 側の変更と新しいテストで、差分は数百行の見込みである。

## 概要設計

### 置き場

- 形を整える関数は、新しいモジュール `mcp_server/shaping.py` に置く。FastMCP の文脈を
  持たない純粋関数なので、単独でテストできる
- tool の定義は `mcp_server/main.py` に残し、`shaping.py` の関数を呼ぶ
- テストは `mcp_server/tests/` に置く。複合 tool は `httpx.MockTransport` で、ブリッジの
  応答（500 を含む）を差し込んで確かめる

### 複合 tool

名前は `get_colony_overview` とする。次の読み出しを `asyncio.gather` で同時に送る。

| 節 | 読み出し | 中盤のセーブの大きさ（TASK0005） |
|---|---|---|
| state | `/state` | 177 B |
| alerts | `/alerts` | 222 B |
| threats | `/threats` | 109 B |
| colony | `/colony` | 993 B |
| weather | `/weather` | 89 B |
| power | `/power` | 173 B |
| messages | `/messages` | 2 B |
| colonists | `/pawns` を整えたもの | 5,806 B（整える前） |

- `colonists` は、入植者ごとに id・名前・健康・徴兵・ダウン・現在の仕事だけを残す。技能と
  情熱は `get_pawns` で引く
- `asyncio.gather(..., return_exceptions=True)` で受け、失敗した節は
  `{"error": "<理由>"}` に置き換える。畳むのは読み出しの失敗（HTTP の失敗、JSON でない
  本文、整形できない形の応答）だけで、それ以外の例外は伝播させる。理由の文言が空の例外
  （タイムアウト）は型の名前を理由にする
- 整形は節の読み出しの内側で行う。応答の形が想定と違っても、その節だけが失敗する
- 8 つの節がすべて失敗したら、最初の失敗を例外として送出する。何も読めていないので、
  他の tool と同じく呼び出しを失敗させる（ブリッジに届かない・トークンを拒まれた等）
- 節ごとの読み出しは、応答を受けたら自分で `raise_for_status()` を呼ぶ。この fork の
  クライアントは失敗の応答を受けた時点で理由つきの例外を投げる（TASK0003 の
  `_raise_with_reason`）が、upstream のクライアントは投げない。どちらの上でも失敗を節へ
  畳めるようにするためである。**ブリッジが述べた理由が節に載るのは fork のクライアントの
  上だけで、upstream のクライアントでは HTTP の状態だけが載る**（CP6 で実測）
- MCP の tool annotations で読み出し専用（`readOnlyHint`）と示す

### upstream へ送れる形

- 実装は作業書と別のブランチ（`task/TASK0006-overview-impl`）で行い、fork ローカルの
  ファイルに触れない。`develop` へ squash した後、`upstream/main` へ cherry-pick できる
- ただし `develop` の `mcp_server/main.py` は TASK0003 の変更（クライアントの生成の集約・
  失敗の理由の取り出し）を含む。upstream へ送るときは TASK0003 の変更が先に要るか、
  cherry-pick で衝突する。送る順は残課題に置く

### 3 つの tool の既定の出力

| tool | 既定 | 引数で選べるもの |
|---|---|---|
| `get_animals` | 飼育動物は個体ごと、野生動物は `(種, 頭数)` の集計 | `race` で 1 つの種の個体一覧、`detail=True` で全件（従来の形） |
| `get_buildings` | 種類ごとの集計・損傷した建物・電力を使う建物の種類ごとの集計（台数・稼働数・出力の合計） | `detail=True` で従来の形 |
| `get_animal_training` | 動物ごとに id・名前・種・習得済みの項目名（`learned`）・習得待ちの項目名（`pending`）・絆の相手 | `detail=True` で従来の形（CP6 で追加） |

- `race` はゲームの表示言語の種のラベル（既定の出力の `race` 欄の値）と照合する。空文字は
  未指定として扱う（他の tool の省略可能な文字列引数と同じ）。一致が 0 件なら、地図上の
  種の一覧を添えて失敗させる。空の成功応答では「その種はいない」と区別できないため
- `race` と `detail=True` を同時に渡したら `race` を優先する

## 実装計画

1. 実装のブランチと worktree を `develop` から切る
2. pytest を開発用の依存として足し、`shaping.py` とテストを書く。規則を外して落ちることを
   確かめる
3. 3 つの tool を `shaping.py` の関数へつなぎ、引数を足す
4. 複合 tool を足し、失敗の扱いを MockTransport で確かめる
5. 中盤のセーブで前後の大きさと複合 tool の往復時間を測り、記録へ書く
6. CP6 の第三者視点レビューを回し、指摘の disposition の裁定を受けて反映する
7. `CONTRIBUTING.md` の「Tests」に Python のテストの回し方を足す（作業書のブランチで。
   fork ローカルのファイルなので実装のブランチに入れない）

## 工数概算

| ステップ | 内容 | 概算（実働）| 主な不確実性 |
|---|---|---|---|
| 2 | pytest の導入・`shaping.py`・テスト・破壊確認 | 30〜60 分 | テストの基盤を初めて置く |
| 3-4 | 3 つの tool の差し替え・複合 tool | 20〜40 分 | FastMCP の tool の引数の扱い |
| 5 | 実機の計測と記録 | 20〜40 分 | 利用者によるセーブの読み込みの待ち |
| CP6 | 第三者視点レビューと反映 | 60〜180 分 | 指摘の量（TASK0003 では実装の約 4 倍） |
| 計 | | 130〜320 分 | 幅の主因: CP6 の指摘の量と、利用者の操作の待ち |

- 前提: 実装はエージェント。CP6 は実施の提案どおりなら行を持つ
- レビュー（CP5 の `/code-review`・CP6 の fan-out）のトークンは、計画の時点で行を
  持たなかった（CP6 の指摘）。実績は下の「実績」に置いた
- 参照クラス: `docs/records/effort-anchors.md` の 5 件。CP6 を実施した作業（TASK0003）は
  レビューと反映が実装の約 4 倍を占めた。利用者の操作を挟む作業（TASK0005）は、待ちが
  壁時計の大半を占めた

### 実績

確度 B（コミット時刻の差から導いた壁時計。裁定待ちを含む実働の上限）。計画コミットより
前の分析・計画は数えていない。

| 区間 | 起点 → 終点 | 壁時計 |
|---|---|---|
| 実装・計測・CP5 の反映 | `29865a8`（15:07）→ 記録 `149743e`（15:31） | 24 分 |
| CP6 のレビューと反映 | 15:31 → `0c6bbf8`（16:12） | 41 分 |
| 計 | 15:07 → 16:12 | 65 分 |

- 見積もり（130〜320 分）の下限を割った。CP6 は実装より長いが、TASK0003 の約 4 倍に
  対して約 1.7 倍だった。作業書と記録への反映・完了処理はこの表に入っていない
- CP6 のサブエージェント 14 体（観点計画 1・観点 12・再評価 1）のトークンは計
  1,681,256（完了通知の値の和）。メインの文脈の消費は測っていない

## 検証

### 概要

形を整える関数と tool を pytest と破壊検査で確かめ、中盤のセーブで出力の大きさと複合
tool の往復時間を測った（[記録](../records/20260926_tool-output-size.md)）。CP6 の
第三者視点レビューの指摘を反映した後、テストと破壊検査を回し直した。

### 検証項目（チェックリスト）

- [x] pytest が 43 件通った（失敗・スキップ 0 件。CP6 の反映後、`0c6bbf8` の時点）
- [x] 破壊検査 33 通りがすべて、狙ったテストで落ちた（CP6 の反映後。内訳は下の
      「破壊検査の内訳」）。加えて、反映前に `get_animals` のテキストだけを送る設定を
      外すと `test_get_animals_defaults_to_counts_and_takes_race_and_detail` が落ちる
      ことを確かめた
- [x] 中盤のセーブで 3 つの tool の出力が 51.7〜71.1% 小さくなった（文字数）。
      複合 tool は、同じ節を返す 8 つの tool の合計より 50.9% 小さい
- [x] 複合 tool の往復時間は `ping` の 0.99 倍（中央値 202.4 ms と 204.7 ms）
- [x] 実装のブランチが触れたファイルは `README.md` と `mcp_server/` の下だけである
      （`git diff --name-only develop task/TASK0006-overview-impl`）
- [x] `main.py` の差分のうち、3 つの tool と複合 tool の外にあるのは、5 つの tool
      （`hunt_animal`・`add_bill`・`equip_item`・`assign_bed`・`deconstruct`）の説明の
      文言、import の追加、CP6 で足したトークンの検査と `_new_client` の `transport`
      引数だけである（差分の塊 13 個を並べて確かめた）
- [x] CP5: 実装の最初の 2 コミットに `/code-review`（medium）を当て、正しさのバグ 0 件・
      指摘 1 件を得た。指摘は今対応とし、説明を直した
- [x] CP6: 12 観点と再評価層でレビューし、指摘 111 件を 27 束にまとめ、全束の disposition
      の裁定を受けて反映した（裁定記録を参照）。反映後に決定論の検査（review-precheck）と
      自己走査を回し直した

### 検証手順

#### 自動

```sh
uv run --project mcp_server pytest mcp_server
```

終了コード 0 で合格。破壊検査と大きさの計測のスクリプトはリポジトリに残していない。

#### 破壊検査の内訳

`mcp_server/` の実装から 1 箇所ずつ規則を外し（置換が 1 箇所に当たらなければ止める）、
pytest を回し、元のバイト列へ戻した。33 通りすべてで終了コードが 1 になり、狙ったテストが
落ちた。

| 外した規則 | 落ちたテスト（代表） |
|---|---|
| 野生動物を数えずに並べる | `test_other_animals_cost_the_same_whether_one_or_a_hundred` |
| `race` の大文字小文字を区別する | `test_race_lists_that_race_with_ids_for_targeting` |
| `detail` で素通しする（動物） | `test_detail_returns_the_bridge_list_unchanged` |
| ブリッジのエラーを素通しする（動物） | `test_bridge_errors_pass_through_unchanged` |
| 電力を使う建物を種類ごとにまとめる | `test_powered_buildings_cost_the_same_whether_one_or_a_hundred` |
| 稼働しているものだけを数える | `test_powered_kinds_count_what_is_switched_on_and_sum_output` |
| 出力の合計を丸める | 同上 |
| `detail` で素通しする（建物） | `test_buildings_detail_returns_the_bridge_answer_unchanged` |
| 習得待ちから習得済みを除く | `test_training_keeps_learned_apart_from_pending` |
| 入植者から技能を落とす | `test_colonists_keep_state_and_drop_skills` |
| エラーだけの要素の一覧をエラーとする | `test_a_record_that_merely_has_an_error_field_is_data` |
| 読み出しを同時に送る | `test_overview_sends_every_read_at_once` |
| 失敗を節へ畳む | `test_overview_keeps_the_other_sections_when_one_read_fails` ほか 5 件 |
| 読み出しが状態を確かめる | `test_overview_folds_a_failure_even_without_the_clients_error_hook` |
| 入植者の節を整える | `test_overview_returns_every_section_with_colonists_shaped` |
| dict は `error` だけを持つときにエラーとする | `test_a_record_that_merely_has_an_error_field_is_data` |
| 空の `race` を未指定とする | `test_an_empty_race_means_none_was_given` ほか 6 件 |
| 一致しない `race` で失敗する | `test_get_animals_fails_on_a_race_that_matches_nothing` |
| `race` を `detail` より優先する | `test_race_takes_precedence_over_detail` |
| null の種を空文字として並べる | `test_an_animal_without_a_race_label_is_counted_not_crashed_on` |
| null の種を空文字として照合する | 同上 |
| `detail` で素通しする（訓練） | `test_training_detail_returns_the_bridge_list_unchanged` |
| tool が訓練の `detail` を渡す | `test_get_animal_training_lists_pending_and_takes_detail` |
| 整形の失敗をその節に留める | `test_overview_folds_colonists_of_an_unexpected_shape` |
| 文言の無い失敗を型の名前で示す | `test_overview_names_the_failure_when_it_has_no_message` |
| 全節が失敗したら呼び出しを失敗させる | `test_overview_fails_when_no_section_can_be_read` |
| 読み出し以外の例外を伝播させる | `test_overview_lets_failures_other_than_a_read_propagate` |
| 複合 tool を読み出し専用と示す | `test_overview_is_marked_read_only` |
| テストの transport がクライアントへ届く | tool のテスト 13 件 |
| ヘッダーにできないトークンで起動を止める | `test_a_token_that_cannot_be_a_header_stops_the_server_without_showing_it`（3 件） |
| 同上の前後の空白の条件だけを外す | 同上（空白の 1 件） |
| 同上の ASCII の条件だけを外す | 同上（非 ASCII の 1 件） |
| `race` の型を文字列にする（null を許さない） | `test_new_arguments_are_optional_in_the_schemas` |

#### 実機

- **tool の出力の大きさと往復時間**
    - 目的: LLM が受け取るテキストが前後でどれだけ変わったか、複合 tool が 1 回分の待ちで
      返るかを確かめる
    - 前提条件: RimWorld で MCP Mod を有効にし、中盤以降のセーブを読み込む
    - 期待結果: 3 つの tool の既定の出力が変更前より小さい。複合 tool の往復時間の中央値が
      `ping` の 2 倍以下
    - 観察方法: MCP サーバーを `create_connected_server_and_client_session` でメモリ上に
      起動し、tool を呼んで返ったテキストの文字数とバイト数を数える。`main.py` の
      読み込み元を変更前と変更後で替えて同じ手順を回す。複合 tool と `ping` を 10 回ずつ
      呼んで時間を測る
    - 復元手順: なし（読み出しだけを行う）

## 作業記録

- 実装は `task/TASK0006-overview-impl` で行った。作業書と記録はこのブランチに置く
- **FastMCP が戻り値の型で出力の形を変える**と分かった。`dict` は 1 つのテキスト、
  `list` は要素ごとのテキスト、合併型はテキストと structured content の両方になる。
  `get_animals` を `dict | list` にしたところ、同じ結果を 2 通りで送っていた（中盤の
  セーブで約 12,800 文字）。テキストだけを送る設定にし、テストで structured content が
  無いことを確かめる形にした
- **軽いセーブでは、同時に送っても速くならない**と分かった。TASK0005 の「同時なら 1 回分の
  待ち」は重いセーブでしか成り立たない。複合 tool は軽いセーブでも順に送るのと同程度で、
  遅くはならない。原因はブリッジの作りにあると見ており（記録を参照）、Mod 側の変更なので
  本作業では扱わない
- CP5 の `/code-review` は「並列の GET がブリッジで詰まることはない」と述べたが、上の
  実測と食い違う。コードを読んだだけの推論なので採らなかった
- 他の tool の説明（`hunt_animal`・`add_bill`・`assign_bed`・`deconstruct`）と README を
  直した。到達基準の「3 つ以外の tool の定義が変わっていない」は、この直しを含めない書き方
  だったので、利用者の裁定で書き換えた（裁定記録を参照）。`assign_bed` の案内は変更前から
  実態と合っていなかった（ベッドは電力を使わず、`get_buildings` に載らない）
- 字下げが出力の 36〜40% を占めると分かり、利用者は削ると決めた。85 の tool 全部に効くので
  別の作業書で扱う。採番は TASK0007・0008 が並行作業で使われていたので、起こす直前に
  次の空き番号を走査する
- CP6 は 12 観点を並列に走らせ、指摘 111 件（高 1・中 34・低 76）を主題で 27 束に
  まとめた。束への帰属は照合器で全件確かめた。再評価層（上位モデル）が束ね方と重要度の
  根拠の誤りを 1 件ずつ見つけ、採った。統合と裁定は fork の本体チェックアウトの
  `.claude/tmp/review/20260926-TASK0006/` にある（追跡外）
- CP6 の統合の段で 4 件を実測で確定した。hook の無いクライアントでは失敗の節から
  ブリッジの理由が落ちる／`race` の不一致は空の成功応答で返る／タイムアウトの節の理由が
  空になる／記録の字下げの節の training の値が実出力と別の量だった
- ID の入手先を案内に書くとき、`get_cells_info` が ThingID を返すと一度読み違えた。
  ブリッジ（`GetCellsRect`）はセルごとに defName だけを返し、ThingID は `get_cell_info`
  が返す。案内は「`get_cells_info` でセルを探し、`get_cell_info` で ThingID を読む」の
  2 段にした
- 実装の最初の 2 コミット以降の差分は CP5 の `/code-review` を当てていなかったが、CP6 の
  レビューが実装のブランチ全体を覆った
- 作業中に `develop` へ TASK0007 が入った。ブリッジの `/messages` のラベルが文字列に
  変わったが、複合 tool はこの節を素通しするので整形に響かない。作業書のブランチは
  `develop` へ載せ直した
- `frozen` を立てた後に spec-derive を回した。本作業の目標 6 件が「SREQ 未採番の新規
  候補」に出た。うち 5 件は LLM から見える tool の外部仕様を変えるが、要求一覧が無いので
  採番しない（要求一覧を起こすかは残課題で裁定待ち）。記録を生む 1 件は随伴層として別枠に
  出た

## 機能への反映

特記なし。

## 裁定記録

- **作業の取り決め（目的・目標・非目標・到達基準）**（2026-09-26・ユーザー）: 承認
- **upstream へ送るか**（2026-09-26・ユーザー）: 送れる形にしておく。実装のブランチを
  作業書のブランチから分ける
- **既定の出力を絞るか**（2026-09-26・ユーザー）: 絞る。引数で従来の形に戻せるようにする
    - 根拠: 目的がトークンの削減なので、LLM が引数を付け忘れても削減が効く側を既定にする
- **CP6 の第三者視点レビューを実施するか**（2026-09-26・ユーザー）: 実施する
- **優先度の `drive`**（2026-09-26・ユーザー）: high
- **到達基準の書き換え**（2026-09-26・ユーザー）: 「3 つ以外の tool の定義が変わって
  いない」を「3 つ以外の tool は、変えた tool を名指す説明の文言だけが変わる」へ改め、
  他の tool の説明と README を直す
    - 根拠: 既定の出力を絞った後も、他の tool の説明が ID を旧い出力から取るよう案内して
      いた（CP5 の `/code-review` の指摘）
- **出力の字下げ**（2026-09-26・ユーザー）: 削る。本作業に混ぜず、別の作業書で扱う
- **CP6 の各指摘の disposition**（2026-09-26・ユーザー「推奨で」）: 27 束すべてを推奨
  どおりとした。今対応を実装のブランチの `0c6bbf8`・`6d6fbf0` と本ブランチで反映した。
  受容と起票は次のとおり
    - 受容: パスの二重定義（個別 tool を定数へ寄せると到達基準を偽にする）、
      `damaged` に上限を置かない（修理に ID が要る）、起動経路と依存（dev 依存は実行時に
      import しない・2 ファイル化は `mcp run` が解決する・mcp の下限が必要な API を
      持つ）、`get_animals` の戻り型の 3 形（`detail` は従来の list を返す裁定の要求）、
      狩りに呼び出しが 1 回増えること（既定を絞る対価）、`get_game_state` の
      "Call this first"（直すと到達基準を偽にし、複合 tool の説明が名指せば足りる）、
      型注釈・命名・コミットの分け方の一部
    - 起票: 下の「後続作業（起票）」の 4 件
- **`get_animal_training` にも従来の形へ戻す引数を足すか**（2026-09-26・ユーザー）: 足す。
  `wanted` は `pending` へ改める（CP6 の指摘。README の語と揃える）
- **到達基準の再度の書き換え**（2026-09-26・ユーザー）: 「3 つ以外の tool は、変えた
  tool を名指す説明の文言だけが変わる」に「ID の入手先の案内を実態に合わせる説明の
  文言」を加え、`equip_item` の案内も直す
    - 根拠: `equip_item` が案内する `get_things` は ID を持たず、行き止まる（差分外・既存
      だが、受け持つ仕組みが無い）

## stakeholder 未裁定の残課題

- 要求一覧を起こすか。本作業は LLM から見える tool の外部仕様を変えるが、このリポジトリは
  要求一覧を持たない（TASK0003 の裁定「新設しない」は、その作業について下された）
- upstream へ送る順。本作業の実装は TASK0003 の `mcp_server/main.py` の変更の上に
  乗るので、TASK0003 を先に送るか、衝突を解いて送るかを決める必要がある。**テストも
  TASK0003 の `_new_client`・`_raise_with_reason` を差し替えるので、TASK0003 抜きでは
  tool のテストが走らない**。`git merge-tree` の衝突は import の 1 行にしか現れず、
  この依存は衝突に出ない（CP6 の指摘）
- TASK0005 の記録の「約トークン」は「バイト数 ÷ 4」で出しており、日本語のラベルでは
  少なく見積もっている可能性がある。記録へ注記を足すか

## 後続作業（起票）

CP6 の裁定（2026-09-26・ユーザー）で起票と決めたもの。いずれも新しい設計か Mod の変更
（本作業の非目標）を要する。作業書はまだ起こしていない。

- 飼育動物を種ごとにまとめる。中盤のセーブでは 205 頭のうち 135 頭が飼育動物で、既定の
  出力に 1 頭ずつ残る。名前の付いたペットをどう扱うかの判断を伴う
- ブリッジが要求ごとに ThreadPool のスレッドをふさぐ作りを直す。軽いセーブで同時に
  送った要求が 1 フレームに 1 本ずつしか進まない。ゲームが止まったときは 8 本の読み出し
  がスレッドをふさぎ、一部の節がブリッジの 503 より先に Python 側の 20 秒で切れうる
  （未実測の推論）。Mod 側の変更になる
- 全 tool に MCP の annotations（読み出し専用・破壊的）を付ける。85 の tool の分類が要る。
  本作業では複合 tool にだけ付けた
- ブリッジの `hunt` が、ThingID でなくラベルの一致でも標的を選び、飼育動物を除かない。
  既定の出力から野生動物の ID を外したので、LLM が種名を渡すと飼育動物に当たりうる
  （未実測の推論）。Mod 側の変更になる
