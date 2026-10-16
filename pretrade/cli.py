"""売買前チェックシステム CLI。

使い方:
    python -m pretrade.cli entry            # 対話形式で新規トレード仮説を登録
    python -m pretrade.cli entry --ticker 7203 --alpha "..." ...  # 非対話形式
    python -m pretrade.cli list              # 保有中(未決済)の一覧
    python -m pretrade.cli exit --id 3       # 対話形式で決済の振り返りを登録
    python -m pretrade.cli report --month 2026-08
    python -m pretrade.cli export-csv [--out data/trade_theses.csv]
    python -m pretrade.cli fetch-data --codes 7203,9984 --from 2026-01-01 --to 2026-09-01
    python -m pretrade.cli score --ticker 7203
    python -m pretrade.cli screen
    python -m pretrade.cli memo-add --month 3 --day 28 --note "配当権利落ちで下げやすい" --tags 権利落ち,3月
    python -m pretrade.cli memo-due
    python -m pretrade.cli seasonality
    python -m pretrade.cli cash-check
    python -m pretrade.cli topix-fit-set --ticker 593A --market-cap 1.2e11 \
        --annual-trading-value 3e10 --segment グロース --cap-percentile 40
    python -m pretrade.cli topix-forecast-add --ticker 593A --broker 大和証券 \
        --review-date 2026-10 --type new --mentioned-at 2026-09-02
    python -m pretrade.cli topix-rank --review-date 2026-10
    python -m pretrade.cli topix-watchlist --review-date 2026-10
    python -m pretrade.cli topix-outcome-add --ticker 593A --review-date 2026-10 \
        --outcome "予想通り採用" --announcement-date 2026-10-07 --reaction-pct 1.81
    python -m pretrade.cli topix-outcome-report --review-date 2026-10
"""
import argparse
import sys
from datetime import date

from .db import get_connection, RATIONALE_CATEGORIES, EXIT_REASONS, AS_EXPECTED_CHOICES
from .rr import calculate_rr, RR_WARNING_THRESHOLD
from .models import create_thesis, close_thesis, list_open, get_thesis
from .report import monthly_report_text
from .csv_export import export_csv
from .fetch_cache import fetch_and_cache, load_cache
from .scan import build_score_inputs
from .scoring import score_stock, format_score_result
from .screener import find_unrecognized_progress, DEFAULT_PROGRESS_THRESHOLD, DEFAULT_REACTION_THRESHOLD
from .calendar_memos import add_memo, list_memos, due_memos
from .calendar_seasonality import (
    monthly_return_stats,
    earnings_concentration_by_month,
    estimate_ex_rights_dates,
    quarter_end_rebalance_dates,
)
from .cash_control import (
    check_take_profit_candidates,
    check_stop_loss_breaches,
    check_crash_buy_opportunity,
    moving_average_deviation,
)
from .slack_notify import send_slack_message
from . import signals
from .topix_db import (
    add_forecast as topix_add_forecast,
    add_outcome as topix_add_outcome,
    accuracy_report as topix_accuracy_report,
    forecasts_by_ticker as topix_forecasts_by_ticker,
    list_forecasts as topix_list_forecasts,
    list_outcomes as topix_list_outcomes,
)
from .topix_review import (
    OUTCOME_CHOICES,
    build_candidates_from_raw,
    precede_watchlist,
)
from .topix_fit_store import load_fit_inputs, save_fit_inputs
from .market_calls import CALL_TYPES, OUTCOME_CHOICES as CALL_OUTCOME_CHOICES, summarize_accuracy_by_source
from .market_calls_db import (
    add_call as market_add_call,
    all_calls_as_domain,
    list_calls as market_list_calls,
    set_outcome as market_set_outcome,
)


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


def cmd_fetch_data(args):
    codes = [c.strip() for c in args.codes.split(",") if c.strip()]
    path = fetch_and_cache(codes, args.from_date, args.to_date, args.out)
    print(f"データを取得しキャッシュしました: {path}")
    return 0


def cmd_score(args):
    cache = load_cache(args.cache)
    ticker_data = cache.get("tickers", {}).get(args.ticker)
    if ticker_data is None:
        print(f"キャッシュに {args.ticker} のデータがありません。先に fetch-data を実行してください。")
        return 1

    inputs = build_score_inputs(args.ticker, ticker_data["statements"], ticker_data["quotes"])
    result = score_stock(inputs)
    print(format_score_result(result))
    return 0


def cmd_screen(args):
    cache = load_cache(args.cache)
    candidates = find_unrecognized_progress(
        cache.get("tickers", {}),
        cache.get("topix", []),
        progress_threshold=args.progress_threshold,
        reaction_threshold=args.reaction_threshold,
    )
    if not candidates:
        print("条件に合致する「未認識の好進捗」銘柄はありませんでした。")
        return 0

    print("--- 未認識の好進捗 銘柄ランキング ---")
    for c in candidates:
        print(
            f"{c.ticker}: 進捗率={c.progress_rate_pct:.1f}% "
            f"対TOPIX反応={c.relative_reaction_pct:+.1f}% "
            f"据え置き{c.stagnant_days}日 スコア={c.rank_score:.1f}"
        )
    return 0


def cmd_memo_add(args):
    conn = get_connection(args.db)
    tags = [t.strip() for t in args.tags.split(",")] if args.tags else []
    memo = add_memo(conn, event_month=args.month, event_day=args.day, note=args.note, tags=tags)
    print(f"登録しました: id={memo.id} {memo.event_month}/{memo.event_day} タグ=[{memo.tags}]")
    return 0


def cmd_memo_list(args):
    conn = get_connection(args.db)
    memos = list_memos(conn, tag=args.tag)
    if not memos:
        print("登録されているメモはありません。")
        return 0
    for m in memos:
        print(f"#{m.id} {m.event_month}/{m.event_day} [{m.tags}] {m.note}")
    return 0


def cmd_memo_due(args):
    conn = get_connection(args.db)
    memos = due_memos(conn, window_days=args.window)
    if not memos:
        print("直近のシーズナリティメモはありません。")
        return 0
    for m in memos:
        text = f"[シーズナリティリマインド] {m.event_month}/{m.event_day} [{m.tags}] {m.note}"
        print(text)
        send_slack_message(text)
    return 0


def cmd_seasonality(args):
    cache = load_cache(args.cache)
    topix = cache.get("topix", [])
    tickers = cache.get("tickers", {})

    print("--- 月次騰落率統計(TOPIX) ---")
    monthly = monthly_return_stats(topix)
    for month in sorted(monthly.keys()):
        s = monthly[month]
        print(
            f"  {month:2d}月: 平均{s['avg_return_pct']:+.2f}% "
            f"勝率{s['win_rate_pct']:.0f}% (n={s['n']})"
        )

    print("--- 決算集中期(開示件数/月) ---")
    earnings = earnings_concentration_by_month(tickers)
    for month in sorted(earnings.keys()):
        print(f"  {month:2d}月: {earnings[month]}件")

    print(f"--- {args.year}年 四半期末リバランス時期 ---")
    for d in quarter_end_rebalance_dates(args.year):
        print(f"  {d}")

    ex_rights = estimate_ex_rights_dates(tickers)
    if ex_rights:
        print("--- 権利落ち日の目安(近似値) ---")
        for ticker, d in ex_rights.items():
            print(f"  {ticker}: {d}")

    return 0


def cmd_cash_check(args):
    conn = get_connection(args.db)
    open_theses = list_open(conn)
    cache = load_cache(args.cache)
    tickers = cache.get("tickers", {})

    latest_prices = {}
    ma_deviations = {}
    for thesis in open_theses:
        data = tickers.get(thesis.ticker)
        if not data:
            continue
        quotes = data.get("quotes", [])
        closes = signals.close_series(quotes)
        if closes and closes[-1] is not None:
            latest_prices[thesis.ticker] = closes[-1]
        ma_deviations[thesis.ticker] = moving_average_deviation(quotes)

    alerts = check_take_profit_candidates(open_theses, latest_prices, ma_deviations)
    alerts += check_stop_loss_breaches(open_theses, latest_prices)

    score_results = [
        score_stock(build_score_inputs(ticker, data.get("statements", []), data.get("quotes", [])))
        for ticker, data in tickers.items()
    ]
    crash_alert = check_crash_buy_opportunity(cache.get("topix", []), score_results)
    if crash_alert:
        alerts.append(crash_alert)

    if not alerts:
        print("現時点でアラートはありません。")
        return 0

    for a in alerts:
        text = f"[{a.alert_type}] {a.message}"
        print(text)
        send_slack_message(text)
    return 0


def cmd_topix_fit_set(args):
    data = load_fit_inputs(args.fit_data)
    data[args.ticker] = {
        "market_cap": args.market_cap,
        "annual_trading_value": args.annual_trading_value,
        "market_segment": args.segment,
        "market_cap_percentile": args.cap_percentile,
    }
    path = save_fit_inputs(data, args.fit_data)
    print(f"{args.ticker} のJPX適合度入力データを保存しました: {path}")
    print("  ※浮動株時価総額の正式データではなく、発行済株式ベースの近似値である点に注意してください。")
    return 0


def cmd_topix_forecast_add(args):
    conn = get_connection(args.db)
    forecast = topix_add_forecast(
        conn,
        ticker=args.ticker,
        broker=args.broker,
        review_date=args.review_date,
        forecast_type=args.type,
        mentioned_at=args.mentioned_at,
        source_note=args.note or "",
    )
    print(f"登録しました: id={forecast.id} {forecast.ticker} {forecast.broker} ({forecast.forecast_type})")
    return 0


def cmd_topix_forecast_list(args):
    conn = get_connection(args.db)
    forecasts = topix_list_forecasts(conn, review_date=args.review_date, ticker=args.ticker)
    if not forecasts:
        print("登録されている採用予想はありません。")
        return 0
    for f in forecasts:
        print(f"#{f.id} {f.ticker} {f.broker} [{f.forecast_type}] {f.mentioned_at} {f.source_note}")
    return 0


def _build_candidates_for_review(args):
    """キャッシュ(J-Quants)・JPX適合度入力・採用予想ログを組み合わせて候補一覧を作る。

    対象ティッカーは「キャッシュに価格データがある銘柄」かつ
    「JPX適合度入力または採用予想ログのどちらかがある銘柄」に限定する
    (どちらも無い銘柄は判定材料が無いため候補として出さない)。
    """
    cache = load_cache(args.cache)
    fit_inputs_raw = load_fit_inputs(args.fit_data)
    conn = get_connection(args.db)
    forecasts_grouped = topix_forecasts_by_ticker(conn, args.review_date)

    return build_candidates_from_raw(
        fit_inputs_raw, forecasts_grouped, cache.get("tickers", {}), cache.get("topix", []), args.basis_date
    )


def _print_candidate(c, index=None):
    prefix = f"{index}. " if index is not None else ""
    flag = " ★先回り候補" if c.is_precede_candidate else ""
    print(f"{prefix}{c.name}({c.ticker}){flag}")
    print(f"    採用候補度: {c.candidate_score:.0f}  パターン: {c.pattern}")
    print(f"    採用予想の根拠: {c.forecast_basis}")
    fit = c.jpx_fit
    print(f"    JPX基準適合度(近似): {fit.fit_score}/{fit.max_score}" + ("" if not fit.data_notes else f"  [{'; '.join(fit.data_notes)}]"))
    pricing = c.priced_in
    if pricing.relative_reaction_pct is not None:
        print(f"    織り込み度: {pricing.priced_in_level}(対TOPIX相対{pricing.relative_reaction_pct:+.1f}%, 基準日{pricing.since_date})")
    else:
        print(f"    織り込み度: {pricing.priced_in_level}")
    if c.price_position:
        pos = c.price_position
        print(f"    現在の株価位置: 52週高値から{pos['pct_from_high']:+.1f}% / 52週安値から{pos['pct_from_low']:+.1f}%")
    print(f"    注目すべき時期: {c.watch_period}")


def cmd_topix_rank(args):
    candidates = _build_candidates_for_review(args)
    if not candidates:
        print("候補銘柄がありません。topix-fit-set または topix-forecast-add でデータを登録してください。")
        return 0
    print(f"--- TOPIX採用候補ランキング(基準日={args.basis_date}) ---")
    for i, c in enumerate(candidates, start=1):
        _print_candidate(c, index=i)
    return 0


def cmd_topix_watchlist(args):
    candidates = _build_candidates_for_review(args)
    watchlist = precede_watchlist(candidates)
    if not watchlist:
        print("「採用可能性が高い×織り込み度が低い」先回り候補は現在ありません。")
        return 0
    print("--- TOPIX採用先回り候補ウォッチリスト ---")
    for i, c in enumerate(watchlist, start=1):
        _print_candidate(c, index=i)
    return 0


def cmd_topix_outcome_add(args):
    conn = get_connection(args.db)
    outcome = topix_add_outcome(
        conn,
        ticker=args.ticker,
        review_date=args.review_date,
        outcome=args.outcome,
        announcement_date=args.announcement_date,
        price_reaction_pct=args.reaction_pct,
        note=args.note or "",
    )
    print(f"登録しました: id={outcome.id} {outcome.ticker} [{outcome.outcome}]")
    return 0


def cmd_topix_outcome_report(args):
    conn = get_connection(args.db)
    report = topix_accuracy_report(conn, review_date=args.review_date)
    print(f"--- TOPIX採用予想 精度レポート(件数={report['total']}) ---")
    for outcome, count in report["by_outcome"].items():
        print(f"  {outcome}: {count}件")
    outcomes = topix_list_outcomes(conn, review_date=args.review_date)
    for o in outcomes:
        reaction = f"{o.price_reaction_pct:+.2f}%" if o.price_reaction_pct is not None else "―"
        print(f"    {o.ticker}: [{o.outcome}] 発表日反応={reaction} {o.note}")
    return 0


def cmd_call_add(args):
    conn = get_connection(args.db)
    call = market_add_call(
        conn,
        ticker=args.ticker,
        source=args.source,
        call_type=args.type,
        called_at=args.called_at,
        price_at_call=args.price,
        note=args.note or "",
        url=args.url or "",
    )
    print(f"登録しました: id={call.id} {call.ticker} [{call.source}] {call.call_type}")
    return 0


def cmd_call_list(args):
    conn = get_connection(args.db)
    calls = market_list_calls(conn, ticker=args.ticker, source=args.source)
    if not calls:
        print("登録されている発言ログはありません。")
        return 0
    for c in calls:
        price = f"{c.price_at_call:.0f}円" if c.price_at_call is not None else "価格不明"
        print(f"#{c.id} {c.ticker} [{c.source}] {c.call_type} {c.called_at or '日付不明'} {price} 結果={c.outcome}")
        if c.note:
            print(f"    メモ: {c.note}")
    return 0


def cmd_call_outcome_set(args):
    conn = get_connection(args.db)
    call = market_set_outcome(conn, args.id, args.outcome)
    print(f"更新しました: id={call.id} {call.ticker} [{call.source}] -> {call.outcome}")
    return 0


def cmd_call_accuracy_report(args):
    conn = get_connection(args.db)
    calls = all_calls_as_domain(conn)
    summary = summarize_accuracy_by_source(calls)
    if not summary:
        print("登録されている発言ログはありません。")
        return 0
    print("--- 発言元ごとの的中率(的中率の高い順) ---")
    for s in summary:
        rate = f"{s.hit_rate_pct:.0f}%" if s.hit_rate_pct is not None else "未確定のみ"
        print(f"  {s.source}: 的中率={rate} (的中{s.hits}/外れ{s.misses}/未確定{s.pending}, 計{s.total}件)")
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

    p_fetch = sub.add_parser("fetch-data", help="J-Quants APIから財務・株価データを取得しキャッシュ")
    p_fetch.add_argument("--codes", required=True, help="カンマ区切りの銘柄コード(例: 7203,9984)")
    p_fetch.add_argument("--from", dest="from_date", required=True, help="YYYY-MM-DD")
    p_fetch.add_argument("--to", dest="to_date", required=True, help="YYYY-MM-DD")
    p_fetch.add_argument("--out", default=None, help="キャッシュ先(省略時は data/market_cache.json)")
    p_fetch.set_defaults(func=cmd_fetch_data)

    p_score = sub.add_parser("score", help="銘柄選定基準のスコアリング(2-2)")
    p_score.add_argument("--ticker", required=True)
    p_score.add_argument("--cache", default=None, help="キャッシュファイル(省略時は data/market_cache.json)")
    p_score.set_defaults(func=cmd_score)

    p_screen = sub.add_parser("screen", help="「未認識の好進捗」スクリーナー(2-0)")
    p_screen.add_argument("--cache", default=None, help="キャッシュファイル(省略時は data/market_cache.json)")
    p_screen.add_argument("--progress-threshold", type=float, default=DEFAULT_PROGRESS_THRESHOLD)
    p_screen.add_argument("--reaction-threshold", type=float, default=DEFAULT_REACTION_THRESHOLD)
    p_screen.set_defaults(func=cmd_screen)

    p_memo_add = sub.add_parser("memo-add", help="シーズナリティ・市場イベントの手動メモを登録(2-1)")
    p_memo_add.add_argument("--month", type=int, required=True, help="1〜12")
    p_memo_add.add_argument("--day", type=int, required=True, help="1〜31")
    p_memo_add.add_argument("--note", required=True)
    p_memo_add.add_argument("--tags", default=None, help="カンマ区切りのタグ")
    p_memo_add.set_defaults(func=cmd_memo_add)

    p_memo_list = sub.add_parser("memo-list", help="シーズナリティメモの一覧")
    p_memo_list.add_argument("--tag", default=None)
    p_memo_list.set_defaults(func=cmd_memo_list)

    p_memo_due = sub.add_parser("memo-due", help="今の時期に近いシーズナリティメモを表示(自動リマインド)")
    p_memo_due.add_argument("--window", type=int, default=7, help="前後何日以内を対象にするか")
    p_memo_due.set_defaults(func=cmd_memo_due)

    p_seasonality = sub.add_parser("seasonality", help="年間シーズナリティ・市場イベントカレンダー(2-1)")
    p_seasonality.add_argument("--cache", default=None, help="キャッシュファイル(省略時は data/market_cache.json)")
    p_seasonality.add_argument("--year", type=int, default=date.today().year)
    p_seasonality.set_defaults(func=cmd_seasonality)

    p_cash = sub.add_parser("cash-check", help="現金比率コントロール: 利確検討/損切り/暴落仕込みアラート(2-4)")
    p_cash.add_argument("--cache", default=None, help="キャッシュファイル(省略時は data/market_cache.json)")
    p_cash.set_defaults(func=cmd_cash_check)

    p_topix_fit = sub.add_parser(
        "topix-fit-set", help="TOPIX採用予想(Phase5): JPX基準適合度の入力データを登録(近似値)"
    )
    p_topix_fit.add_argument("--ticker", required=True)
    p_topix_fit.add_argument("--market-cap", type=float, default=None, help="発行済株式ベース時価総額(円)")
    p_topix_fit.add_argument("--annual-trading-value", type=float, default=None, help="年間売買代金(円)")
    p_topix_fit.add_argument("--segment", default=None, help="プライム/スタンダード/グロース")
    p_topix_fit.add_argument("--cap-percentile", type=float, default=None, help="時価総額の市場内パーセンタイル(0-100)")
    p_topix_fit.add_argument("--fit-data", default=None, help="保存先(省略時は data/topix_fit_inputs.json)")
    p_topix_fit.set_defaults(func=cmd_topix_fit_set)

    p_topix_fc_add = sub.add_parser(
        "topix-forecast-add", help="TOPIX採用予想(Phase5): 証券会社等の採用予想を手動ログ"
    )
    p_topix_fc_add.add_argument("--ticker", required=True)
    p_topix_fc_add.add_argument("--broker", required=True, help="例: 大和証券")
    p_topix_fc_add.add_argument("--review-date", required=True, help="対象の入替回(例: 2026-10)")
    p_topix_fc_add.add_argument("--type", dest="type", choices=["new", "exclude"], required=True)
    p_topix_fc_add.add_argument("--mentioned-at", required=True, help="予想が出た日(YYYY-MM-DD)")
    p_topix_fc_add.add_argument("--note", default=None)
    p_topix_fc_add.set_defaults(func=cmd_topix_forecast_add)

    p_topix_fc_list = sub.add_parser("topix-forecast-list", help="TOPIX採用予想(Phase5): ログ済み予想の一覧")
    p_topix_fc_list.add_argument("--review-date", default=None)
    p_topix_fc_list.add_argument("--ticker", default=None)
    p_topix_fc_list.set_defaults(func=cmd_topix_forecast_list)

    def _add_rank_args(p):
        p.add_argument("--review-date", required=True, help="対象の入替回(例: 2026-10)")
        p.add_argument("--basis-date", required=True, help="基準日(YYYY-MM-DD)")
        p.add_argument("--cache", default=None, help="キャッシュファイル(省略時は data/market_cache.json)")
        p.add_argument("--fit-data", default=None, help="JPX適合度入力データ(省略時は data/topix_fit_inputs.json)")

    p_topix_rank = sub.add_parser("topix-rank", help="TOPIX採用候補ランキング(Phase5)")
    _add_rank_args(p_topix_rank)
    p_topix_rank.set_defaults(func=cmd_topix_rank)

    p_topix_watch = sub.add_parser(
        "topix-watchlist", help="TOPIX採用先回り候補(採用可能性高×織り込み度低)のウォッチリスト(Phase5)"
    )
    _add_rank_args(p_topix_watch)
    p_topix_watch.set_defaults(func=cmd_topix_watchlist)

    p_topix_out_add = sub.add_parser(
        "topix-outcome-add", help="TOPIX採用予想(Phase5): 発表後の結果(予想通り/予想外/見送り)を記録"
    )
    p_topix_out_add.add_argument("--ticker", required=True)
    p_topix_out_add.add_argument("--review-date", required=True)
    p_topix_out_add.add_argument("--outcome", choices=OUTCOME_CHOICES, required=True)
    p_topix_out_add.add_argument("--announcement-date", default=None)
    p_topix_out_add.add_argument("--reaction-pct", type=float, default=None, help="発表日の株価反応(%)")
    p_topix_out_add.add_argument("--note", default=None)
    p_topix_out_add.set_defaults(func=cmd_topix_outcome_add)

    p_topix_out_report = sub.add_parser(
        "topix-outcome-report", help="TOPIX採用予想(Phase5): 予想通り/予想外/見送りの件数集計(精度確認)"
    )
    p_topix_out_report.add_argument("--review-date", default=None)
    p_topix_out_report.set_defaults(func=cmd_topix_outcome_report)

    p_call_add = sub.add_parser(
        "call-add", help="底値/天井判断の材料収集: SNS等の発言をログ(判断はしない、記録のみ)"
    )
    p_call_add.add_argument("--ticker", required=True)
    p_call_add.add_argument("--source", required=True, help="例: レオ, X:@leo_xxx")
    p_call_add.add_argument("--type", dest="type", choices=CALL_TYPES, required=True)
    p_call_add.add_argument("--called-at", default=None, help="発言日(YYYY-MM-DD、不明なら省略可)")
    p_call_add.add_argument("--price", type=float, default=None, help="発言時点の株価")
    p_call_add.add_argument("--note", default=None)
    p_call_add.add_argument("--url", default=None)
    p_call_add.set_defaults(func=cmd_call_add)

    p_call_list = sub.add_parser("call-list", help="底値/天井判断の材料収集: ログ済みの発言一覧")
    p_call_list.add_argument("--ticker", default=None)
    p_call_list.add_argument("--source", default=None)
    p_call_list.set_defaults(func=cmd_call_list)

    p_call_outcome = sub.add_parser(
        "call-outcome-set", help="底値/天井判断の材料収集: 発言の結果(的中/外れ)を後から記録"
    )
    p_call_outcome.add_argument("--id", type=int, required=True)
    p_call_outcome.add_argument("--outcome", choices=CALL_OUTCOME_CHOICES, required=True)
    p_call_outcome.set_defaults(func=cmd_call_outcome_set)

    p_call_report = sub.add_parser(
        "call-accuracy-report", help="底値/天井判断の材料収集: 発言元ごとの的中率レポート"
    )
    p_call_report.set_defaults(func=cmd_call_accuracy_report)

    return parser


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
