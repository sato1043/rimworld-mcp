# rimworld-mcp の操作知識

tool の説明文に無い使い方だけを書く。説明文の事実は説明文を読み、ここではそれを前提に
スキルがどう動くかを書く。出典はこのリポジトリのコードで、`mcp_server/main.py`（tool）と
`MCP/Source/MCP/CommandExecutor.cs`（ゲームへの命令）を 2026-09-27 に読んだ。tool を
変えたら、ここも見直す。

## 目的別の選び方

- **状況の把握**: サイクルの初めは `get_colony_overview` を 1 回呼ぶ
- **出来事の追跡**: `get_events` を使う。返った `next` を方針ファイルに残すことで、
  前回から何が起きたかが分かる
- **入植者の ID**: `get_pawns` の `id`。同じ短い名前の入植者がいると、名前では最初に
  見つかった 1 人になるので ID を使う。ID でも名前でも、引けるのは今のマップにいる
  入植者だけで、キャラバンに出た入植者は見つからない（`GameStateReader.FindColonist`）
- **敵の ID**: `get_enemies`。`attack_target` に渡す
- **動物の ID**: `get_animals` の既定の出力にある種族のラベルで絞り、`hunt_animal` へ渡す
- **作業台・ベッド・建物の ID**: `get_production`（加工の指示のある作業台）・
  `get_room_assignments`（割り当て済みのベッド）・`get_buildings`（電力を使う建物）で
  見つからなければ、`get_cells_info` で範囲を見て `get_cell_info` でそのマスの ThingID を読む
- **肥沃な土**: `get_fertile_cells`

## 出来事の位置の持ち方

- `get_events` が返した最後の `next` を方針ファイルの「出来事の位置」へ書き、次のサイクルで
  `since` に渡す
- `gap` が true なら、読めなかった出来事がある。overview で状態を見直す
- `reloaded` が true なら、セーブが読み直された。前のサイクルの前提（配置・指示）が
  巻き戻っていないかを見直す
- 方針ファイルに位置が無い・壊れているときは、`since` を省いて呼ぶ。それより前の出来事は
  読んだものとして扱われ、`gap` も立たないので、overview の `threats` と `alerts` で今の状態を
  確かめ、経過のメモに「出来事の位置を失った」と書く
- 脅威の letter の型の定義は Defs `Misc/LetterDefs/StandardLetters.xml` と
  `CustomNotificationLetters.xml`、選択を迫る letter は `CustomChoiceLetters.xml` にある

## 出力の量を抑える

- **`get_cells_info` は 1 回 500 マス以下（たとえば 20×20）に留める。** 上限の 1024 マスまで
  受け付けるが、2026-09-27 のプレイでは 832 マス以上の 65 回がすべてハーネスの出力の上限を
  超えて読めず、500 マス以下の 4 回は収まった
- **火災の場所を探してマップを総なめにしない。** 火災は overview の `threats` に件数しか
  出ない（位置を返す tool は TASK0023 で扱う）。居住エリアの中と入植者の近くを小さな範囲で
  見るか、利用者に画面で場所を確かめてもらう
- 要約で足りるときは `detail` を渡さない。`get_animals`・`get_buildings`・
  `get_animal_training` は `detail` で 1 件ずつに展開する
- `get_pawns` は全員の全技能を返すので重い。容体だけなら overview の `colonists` で足りる
- overview の `messages`（最近の letter）と `get_events` は同じ letter を返す。出来事は
  `get_events` で追い、`messages` は読まない
- `get_events` の `limit` は既定のままでよい。`more` が true のときは続きを読む
- 1 マスずつの命令（`place_blueprint`・`mine_cell`・`cut_plant`）が 1 つの仕事で 20 回を
  超えそうなら、何サイクルかに分けるか、利用者に画面で行うよう頼む

## 命令の癖

- **`place_blueprint` は 1 回で 1 マスに 1 つ置く。** 壁で部屋を囲むと、壁の数だけ
  呼ぶことになる
- **`place_blueprint` が置けるのは建物（ThingDef）だけである。** 床（TerrainDef）と
  ゾーンは置けない
- **`place_blueprint` は、向きと素材の誤りを黙って既定へ倒す。** 向きが `North`・
  `South`・`East`・`West` のどれでもなければ `North` にする。素材の defName が
  見つからなければ既定の素材にする。応答の `rotation` と `stuff` で結果を確かめる
- 設計図は素材の在庫を確かめずに置ける。素材が無ければ建たないので、`get_things` で
  在庫を見る
- `mine_cell` と `cut_plant` も 1 回で 1 マスか 1 株である
- `add_bill` は回数だけを指定できる。「在庫 X 個まで繰り返す」「無制限」は指定できない
  ので、利用者に頼むか、回数を多めにして様子を見る（TASK0026 で扱う）
- `set_pause` で再開したら、速めるときは続けて `set_time_speed` を呼ぶ
- `draft_pawn` した入植者は自分で仕事をしない。戦闘が終わったら徴兵を解く

## tool に無い操作

次の操作は tool に無い。要るときは、利用者にゲームの画面で行うよう頼む。語はゲームの
日本語表示に合わせる。tool が足されたら、該当する行を消す。

- 「優先順位」画面での仕事の優先度の変更。`get_pawn_work` で読めるだけ（TASK0025 で扱う）
- ゾーンの新規作成（畑・倉庫）。既存のゾーンの作物・優先度・受け入れる物は変えられる
- 居住エリア・屋根エリアの塗り分け。`area_paint` は許可エリアだけ（TASK0024 で扱う）
- 床の設置
- 囚人の扱い（勧誘・解放・奴隷化等）の切り替え
- 医療の方針（薬を使うか）
- 交易・クエストの受諾・期限のある選択を迫る letter への回答
- 電源の入り切り（TASK0021 で扱う）
- セーブ・宇宙船の打ち上げ・キャラバンの編成と出発（TASK0017 で扱う）
- ゲーム内の時間を指定した分だけ進めること（速度を変えて実時間で待つしかない）
