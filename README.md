# kessan-ev-bot

決算またぎ売買のための意思決定支援システム。「なぜ勝てると考えるのか(アルファ)」を
売買の**前に**言語化させ、勢いで買わない/売らない仕組みを提供する。

## Phase 1: 売買前チェックシステム(アルファ明確化ゲート)

発注前にアルファ仮説・根拠分類・想定利益損失幅・損切り価格・保有期間・撤退条件の入力を必須とし、
リスクリワード比を自動計算する。決済時には振り返りを入力し、当初の仮説と結果を突合する月次レポートを
根拠分類別の勝率とあわせて確認できる。

### セットアップ

```bash
pip install -r requirements.txt
```

### 使い方(CLI)

```bash
# 買う前チェック: 新規トレード仮説を登録(対話形式)
python main.py entry

# 買う前チェック: 非対話形式(スクリプト/自動化向け)
python main.py entry \
  --ticker 7203 \
  --alpha "1Q進捗率30%超、TOPIX比で株価反応薄。上方修正据え置きで未認識" \
  --category "決算超過/上方修正" \
  --entry-price 1000 --target-price 1200 --stop-price 950 \
  --holding-period "3週間" \
  --exit-condition "次回決算で進捗率が鈍化したら撤退"

# 保有中(未決済)のトレード仮説を一覧
python main.py list

# 売る前/決済チェック: 振り返りを登録(対話形式)
python main.py exit --id 1

# 月次レポート: 仮説vs結果の突合 + 根拠分類別勝率
python main.py report --month 2026-09

# 既存のポジション管理CSVと連携するための書き出し(ticker列で突合)
python main.py export-csv --out data/trade_theses.csv
```

データは既定で `data/pretrade.db` (SQLite) に保存される。`--db` オプションで変更可能。

リスクリワード比(RR比 = 想定利益幅 ÷ 想定損失幅)が **2:1 未満** の場合は登録時に警告を表示する。

根拠分類は銘柄選定スコアリング基準(2-2)と揃えている:
決算超過/上方修正・PBR1倍割れ・PER割安・出来高急増・トレンド転換・その他。

## Phase 2: 銘柄選定基準の自動スコアリング(2-2)+「未認識の好進捗」スクリーナー(2-0)

J-Quants API V2から財務情報・株価四本値・TOPIXを取得し、銘柄選定基準を自動でスコアリングする。
あわせて、1Q進捗率が良好なのにTOPIX比で株価が反応しておらず、通期予想も据え置きの
「未認識の好進捗」銘柄を発掘してランキングする。

### 認証情報の設定

環境変数でJ-Quantsの認証情報を設定する(いずれか一方)。

```bash
export JQUANTS_REFRESH_TOKEN="..."
# または
export JQUANTS_MAILADDRESS="..."
export JQUANTS_PASSWORD="..."
```

### 使い方(CLI)

```bash
# J-Quants APIから財務・株価データを取得してローカルにキャッシュ(GitHub Actions定期バッチ想定)
python main.py fetch-data --codes 7203,9984 --from 2026-01-01 --to 2026-09-01

# 銘柄選定基準のスコアリング(決算超過/上方修正+2、PBR1倍割れ+1、PER割安+1、
# 出来高急増+1、トレンド転換+1、除外条件-3。内訳を表示)
python main.py score --ticker 7203

# 「未認識の好進捗」スクリーナー: 進捗率・対TOPIX株価反応・据え置き期間でランキング
python main.py screen
```

キャッシュファイルは既定で `data/market_cache.json`。`fetch-data`/`score`/`screen` とも
`--cache` オプションで場所を変更できる。API呼び出しを都度行わずキャッシュ経由にすることで、
レート制限の回避と結果の再現性を両立している。

スコアリング・スクリーニングのロジック(`signals.py` / `scoring.py` / `screener.py`)は
J-Quants APIの生データ形式の辞書を受け取る純粋関数として実装されており、ネットワークアクセスを
含まないため、実際のAPIキーがなくても単体テストで検証できる。

## Phase 3: 年間シーズナリティ・市場イベントカレンダー(2-1)+現金比率コントロール(2-4)

過去データの季節性分析と手動メモを組み合わせたカレンダー機能、および保有ポジションと相場全体の
状況から利確・損切り・押し目買いのタイミングをアラートする現金比率コントロール機能を追加した。

### 使い方(CLI)

```bash
# シーズナリティメモの登録(自由記述+タグ付け)
python main.py memo-add --month 3 --day 28 --note "配当権利落ちで下げやすい" --tags 権利落ち,3月

# メモの一覧・タグ絞り込み
python main.py memo-list --tag 権利落ち

# 今の時期に近いメモを表示(翌年以降も同時期が近づくたびにヒットする自動リマインド)
python main.py memo-due --window 7

# データ側の季節性分析(月次騰落率統計・決算集中期・四半期末リバランス・権利落ち日の目安)
python main.py seasonality --year 2026

# 現金比率コントロール: 利確検討リスト/損切り後押し/暴落時の仕込み提示
python main.py cash-check
```

`memo-due` と `cash-check` は、環境変数 `SLACK_WEBHOOK_URL` が設定されていれば同じ内容をSlackにも
通知する(未設定時はCLI出力のみでスキップされる)。

`seasonality`/`cash-check` は `fetch-data` で作成したキャッシュファイル(既定 `data/market_cache.json`)
を読み込んで動作する。`cash-check` はPhase 1の保有中トレード仮説(SQLite)とPhase 2のスコアリング結果を
組み合わせ、以下の基準でアラートする:

- 移動平均(既定25日)乖離+8%超、または含み益+20%超 -> 「利確検討」
- 保有銘柄の現在値が損切り価格を割れている -> 「損切り」
- TOPIXが移動平均から-10%超下方乖離 -> 「暴落仕込み」(待機資金投入+スコア上位銘柄を提示)

### ディレクトリ構成

```
pretrade/
  db.py                   SQLiteスキーマ・接続管理
  rr.py                   リスクリワード比の自動計算
  models.py                トレード仮説のデータモデル・登録/決済ロジック
  report.py                月次レポート(仮説vs結果、根拠別勝率集計)
  csv_export.py            既存ポジション管理CSVと連携するための書き出し
  jquants_client.py        J-Quants API V2の認証・データ取得ラッパー
  signals.py               財務・株価データから選定基準シグナルを導出する純粋関数群
  scoring.py                銘柄選定基準スコアリング(2-2)
  screener.py               「未認識の好進捗」スクリーナー(2-0)
  scan.py                   J-Quantsデータ -> ScoreInputs の変換
  fetch_cache.py            J-Quants APIの取得結果をローカルJSONにキャッシュ
  calendar_seasonality.py  年間シーズナリティ・市場イベントカレンダー データ分析側(2-1)
  calendar_memos.py         シーズナリティ手動メモ+自動リマインド(2-1)
  cash_control.py           現金比率コントロール(2-4)
  slack_notify.py           Slack Webhook通知
  cli.py                    CLIエントリポイント
main.py                     CLI簡易起動スクリプト
tests/                      pytestテスト一式
```

### テスト

```bash
python -m pytest
```

## 今後のフェーズ

- Phase 4: Streamlit/HTMLダッシュボードへの統合

詳細は仕様書を参照。
