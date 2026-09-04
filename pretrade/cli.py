"""売買前チェックシステム CLI。

使い方:
    python -m pretrade.cli entry            # 対話形式で新規トレード仮説を登録
    python -m pretrade.cli entry --ticker 7203 --alpha "..." ...  # 非対話形式
    python -m pretrade.cli list              # 保有中(未決済)の一覧
    python -m pretrade.cli exit --id 3       # 対話形式で決済の振り返りを登録
    python -m pretrade.cli report --month 2026-08
    python -m pretrade.cli export-csv [--out data/trade_theses.csv]
"""
import argparse
import sys

from .db import get_connection, RATIONALE_CATEGORIES, EXIT_REASONS, AS_EXPECTED_CHOICES
from .rr import calculate_rr, RR_WARNING_THRESHOLD
from .models import create_thesis, close_thesis, list_open, get_thesis
from .report import monthly_report_text
from .csv_export import export_csv


def _prompt(label, cast=str, choices=None):
    while True:
        suffix = f" [{'/'.join(choices)}]" if choices else ""
        raw = input(f"{label}{suffix}: ").strip()
        if choices and raw not in choices:
            print(f"  -> {choices} のいずれかを入力してください")
            continue
        try:
            return cast(raw)
        except ValueError:
            print("  -> 数値を入力してください")


def cmd_entry(args):
    conn = get_connection(args.db)

    ticker = args.ticker or _prompt("銘柄コード")
    alpha_thesis = args.alpha or _prompt("アルファ仮説(なぜ勝てると考えるか)")
    rationale_category = args.category or _prompt(
        "根拠分類", choices=RATIONALE_CATEGORIES
    )
    entry_price = args.entry_price if args.entry_price is not None else _prompt(
        "エントリー価格", cast=float
    )
    target_price = args.target_price if args.target_price is not None else _prompt(
        "目標価格(利確想定)", cast=float
    )
    stop_price = args.stop_price if args.stop_price is not None else _prompt(
        "損切り価格", cast=float
    )
    holding_period = args.holding_period or _prompt("保有期間の想定")
    exit_condition = args.exit_condition or _prompt("撤退条件")

    try:
        rr = calculate_rr(entry_price, target_price, stop_price)
    except ValueError as e:
        print(f"エラー: {e}")
        return 1

    if rr.warning:
        print(
            f"[警告] リスクリワード比 {rr.ratio:.2f} は "
            f"{RR_WARNING_THRESHOLD:.1f} 未満です。エントリーを再検討してください。"
        )
    else:
        print(f"リスクリワード比: {rr.ratio:.2f}")

    thesis = create_thesis(
        conn,
        ticker=ticker,
        alpha_thesis=alpha_thesis,
        rationale_category=rationale_category,
        entry_price=entry_price,
        target_price=target_price,
        stop_price=stop_price,
        holding_period=holding_period,
        exit_condition=exit_condition,
    )
    print(f"登録しました: id={thesis.id} ticker={thesis.ticker} RR比={thesis.rr_ratio:.2f}")
    return 0


def cmd_list(args):
    conn = get_connection(args.db)
    theses = list_open(conn)
    if not theses:
        print("保有中(未決済)のトレード仮説はありません。")
        return 0
    for t in theses:
        flag = " [RR警告]" if t.rr_ratio < RR_WARNING_THRESHOLD else ""
        print(
            f"#{t.id} {t.ticker} ({t.rationale_category}) "
            f"entry={t.entry_price} target={t.target_price} stop={t.stop_price} "
            f"RR={t.rr_ratio:.2f}{flag} 保有期間={t.holding_period}"
        )
    return 0


def cmd_exit(args):
    conn = get_connection(args.db)
    thesis_id = args.id or int(_prompt("決済するトレードのid", cast=int))

    existing = get_thesis(conn, thesis_id)
    if existing is None:
        print(f"id={thesis_id} は見つかりません")
        return 1
    if existing.status == "closed":
        print(f"id={thesis_id} は既に決済済みです")
        return 1

    print(f"当初の仮説: {existing.alpha_thesis}")
    print(f"撤退条件  : {existing.exit_condition}")

    exit_price = args.exit_price if args.exit_price is not None else _prompt(
        "決済価格", cast=float
    )
    exit_reason = args.exit_reason or _prompt("利確損切り区分", choices=EXIT_REASONS)
    as_expected = args.as_expected or _prompt("想定通りだったか", choices=AS_EXPECTED_CHOICES)
    reflection = args.reflection or _prompt("振り返り(何が想定通り/想定外だったか)")

    thesis = close_thesis(
        conn,
        thesis_id,
        exit_price=exit_price,
        exit_reason=exit_reason,
        as_expected=as_expected,
        reflection=reflection,
    )
    print(f"決済を記録しました: id={thesis.id} 損益率={thesis.pnl_pct:+.2f}%")
    return 0


def cmd_report(args):
    conn = get_connection(args.db)
    print(monthly_report_text(conn, args.month))
    return 0


def cmd_export_csv(args):
    conn = get_connection(args.db)
    path = export_csv(conn, args.out)
    print(f"CSVを書き出しました: {path}")
    return 0


def build_parser():
    parser = argparse.ArgumentParser(description="売買前チェックシステム(アルファ明確化ゲート)")
    parser.add_argument("--db", default=None, help="SQLiteファイルのパス(省略時は data/pretrade.db)")
    sub = parser.add_subparsers(dest="command", required=True)

    p_entry = sub.add_parser("entry", help="買う前チェック: 新規トレード仮説を登録")
    p_entry.add_argument("--ticker")
    p_entry.add_argument("--alpha")
    p_entry.add_argument("--category", choices=RATIONALE_CATEGORIES)
    p_entry.add_argument("--entry-price", type=float)
    p_entry.add_argument("--target-price", type=float)
    p_entry.add_argument("--stop-price", type=float)
    p_entry.add_argument("--holding-period")
    p_entry.add_argument("--exit-condition")
    p_entry.set_defaults(func=cmd_entry)

    p_list = sub.add_parser("list", help="保有中(未決済)のトレード仮説を一覧")
    p_list.set_defaults(func=cmd_list)

    p_exit = sub.add_parser("exit", help="売る前/決済チェック: 振り返りを登録")
    p_exit.add_argument("--id", type=int)
    p_exit.add_argument("--exit-price", type=float)
    p_exit.add_argument("--exit-reason", choices=EXIT_REASONS)
    p_exit.add_argument("--as-expected", choices=AS_EXPECTED_CHOICES)
    p_exit.add_argument("--reflection")
    p_exit.set_defaults(func=cmd_exit)

    p_report = sub.add_parser("report", help="月次レポート(仮説vs結果・根拠別勝率)")
    p_report.add_argument("--month", required=True, help="YYYY-MM形式")
    p_report.set_defaults(func=cmd_report)

    p_csv = sub.add_parser("export-csv", help="既存のポジション管理CSVと連携するための書き出し")
    p_csv.add_argument("--out", default="data/trade_theses.csv")
    p_csv.set_defaults(func=cmd_export_csv)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
