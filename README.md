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

### ディレクトリ構成

```
pretrade/
  db.py           SQLiteスキーマ・接続管理
  rr.py           リスクリワード比の自動計算
  models.py       トレード仮説のデータモデル・登録/決済ロジック
  report.py       月次レポート(仮説vs結果、根拠別勝率集計)
  csv_export.py   既存ポジション管理CSVと連携するための書き出し
  cli.py          CLIエントリポイント
main.py           CLI簡易起動スクリプト
tests/            pytestテスト一式
```

### テスト

```bash
python -m pytest
```

## 今後のフェーズ

- Phase 2: 銘柄選定基準の自動スコアリング(2-2)、「未認識の好進捗」スクリーナー(2-0)
- Phase 3: 年間シーズナリティ・市場イベントカレンダー(2-1)、現金比率コントロール(2-4)
- Phase 4: Streamlit/HTMLダッシュボードへの統合

詳細は仕様書を参照。
