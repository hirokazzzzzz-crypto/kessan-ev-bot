"""売買判断支援システム ダッシュボード(Phase 4)。

Phase 1〜3のCLI機能を1つのStreamlit画面に統合する。

起動:
    streamlit run app.py
"""
from datetime import date

import pandas as pd
import streamlit as st

from pretrade import signals
from pretrade.cash_control import (
    check_crash_buy_opportunity,
    check_stop_loss_breaches,
    check_take_profit_candidates,
    moving_average_deviation,
)
from pretrade.calendar_memos import add_memo, due_memos, list_memos
from pretrade.calendar_seasonality import (
    earnings_concentration_by_month,
    monthly_return_stats,
    quarter_end_rebalance_dates,
)
from pretrade.dashboard_data import (
    cash_alerts_table,
    memos_table,
    monthly_stats_table,
    open_theses_table,
    score_breakdown_table,
    screener_table,
    topix_candidates_table,
    topix_forecasts_table,
    topix_outcomes_table,
)
from pretrade.db import AS_EXPECTED_CHOICES, EXIT_REASONS, RATIONALE_CATEGORIES, get_connection
from pretrade.fetch_cache import fetch_and_cache, load_cache
from pretrade.models import close_thesis, create_thesis, get_thesis, list_open
from pretrade.report import monthly_report_text
from pretrade.rr import RR_WARNING_THRESHOLD, calculate_rr
from pretrade.scan import build_score_inputs
from pretrade.screener import find_unrecognized_progress
from pretrade.scoring import score_stock
from pretrade.topix_fit_store import load_fit_inputs as load_topix_fit_inputs, save_fit_inputs as save_topix_fit_inputs
from pretrade.topix_db import (
    accuracy_report as topix_accuracy_report,
    add_forecast as topix_add_forecast,
    add_outcome as topix_add_outcome,
    forecasts_by_ticker as topix_forecasts_by_ticker,
    list_forecasts as topix_list_forecasts,
    list_outcomes as topix_list_outcomes,
)
from pretrade.topix_review import (
    OUTCOME_CHOICES as TOPIX_OUTCOME_CHOICES,
    build_candidates_from_raw as topix_build_candidates_from_raw,
    precede_watchlist as topix_precede_watchlist,
)

st.set_page_config(page_title="売買判断支援ダッシュボード", layout="wide")


def load_market_cache():
    try:
        return load_cache()
    except FileNotFoundError:
        return None


def _build_topix_candidates(conn, cache, review_date, basis_date):
    """市場データキャッシュ・JPX適合度入力・採用予想ログを組み合わせて候補一覧を作る(cli.pyと同じロジック)。"""
    fit_inputs_raw = load_topix_fit_inputs()
    forecasts_grouped = topix_forecasts_by_ticker(conn, review_date)
    return topix_build_candidates_from_raw(
        fit_inputs_raw, forecasts_grouped, cache.get("tickers", {}), cache.get("topix", []), basis_date
    )


# Streamlitのスクリプトはリランのたびにワーカースレッドをまたぐことがあり、
# sqlite3の接続はスレッドをまたいで使い回せないため、st.cache_resourceでは
# キャッシュせず毎回開き直す(SQLiteへの接続はローカルファイルのため軽量)。
conn = get_connection()

with st.sidebar:
    st.title("売買判断支援システム")
    page = st.radio(
        "ページ",
        [
            "概要",
            "売買前チェック(Phase1)",
            "銘柄選定・スクリーニング(Phase2)",
            "シーズナリティ・現金比率(Phase3)",
            "TOPIX採用予想・需給分析(Phase5)",
        ],
    )

    with st.expander("市場データの取得(J-Quants)"):
        codes_input = st.text_input("銘柄コード(カンマ区切り)", key="fetch_codes")
        from_date = st.text_input("開始日(YYYY-MM-DD)", key="fetch_from")
        to_date = st.text_input("終了日(YYYY-MM-DD)", key="fetch_to")
        if st.button("取得してキャッシュ"):
            codes = [c.strip() for c in codes_input.split(",") if c.strip()]
            if not codes or not from_date or not to_date:
                st.error("銘柄コード・開始日・終了日を入力してください。")
            else:
                try:
                    path = fetch_and_cache(codes, from_date, to_date)
                    st.success(f"取得しました: {path}")
                except Exception as e:  # noqa: BLE001 - J-Quants API/認証エラーをそのまま表示する
                    st.error(f"取得に失敗しました: {e}")


if page == "概要":
    st.title("売買判断支援ダッシュボード")
    st.write("「なぜ勝てると考えるのか(アルファ)」を売買の前に言語化させ、勢いで買わない/売らない仕組み。")

    open_theses = list_open(conn)
    cache = load_market_cache()

    col1, col2 = st.columns(2)
    col1.metric("保有中トレード数", len(open_theses))
    col2.metric(
        "市場データキャッシュ",
        "あり" if cache else "なし",
        cache.get("fetched_at") if cache else "先に fetch-data を実行してください",
    )

    if open_theses:
        st.subheader("保有中のトレード仮説")
        st.dataframe(open_theses_table(open_theses), use_container_width=True)


elif page == "売買前チェック(Phase1)":
    st.header("Phase 1: 売買前チェックシステム(アルファ明確化ゲート)")
    tab_entry, tab_list, tab_exit, tab_report = st.tabs(
        ["買う前チェック", "保有中一覧", "決済チェック", "月次レポート"]
    )

    with tab_entry:
        with st.form("entry_form"):
            ticker = st.text_input("銘柄コード")
            alpha = st.text_area("アルファ仮説(なぜ勝てると考えるか)")
            category = st.selectbox("根拠分類", RATIONALE_CATEGORIES)
            entry_price = st.number_input("エントリー価格", min_value=0.0, step=1.0)
            target_price = st.number_input("目標価格(利確想定)", min_value=0.0, step=1.0)
            stop_price = st.number_input("損切り価格", min_value=0.0, step=1.0)
            holding_period = st.text_input("保有期間の想定")
            exit_condition = st.text_area("撤退条件")
            submitted = st.form_submit_button("登録")

        if submitted:
            if not ticker or not alpha or not holding_period or not exit_condition:
                st.error("すべての項目を入力してください。")
            else:
                try:
                    rr = calculate_rr(entry_price, target_price, stop_price)
                except ValueError as e:
                    st.error(str(e))
                else:
                    if rr.warning:
                        st.warning(
                            f"リスクリワード比 {rr.ratio:.2f} は {RR_WARNING_THRESHOLD:.1f} 未満です。"
                            "エントリーを再検討してください。"
                        )
                    thesis = create_thesis(
                        conn,
                        ticker=ticker,
                        alpha_thesis=alpha,
                        rationale_category=category,
                        entry_price=entry_price,
                        target_price=target_price,
                        stop_price=stop_price,
                        holding_period=holding_period,
                        exit_condition=exit_condition,
                    )
                    st.success(f"登録しました: id={thesis.id} RR比={thesis.rr_ratio:.2f}")

    with tab_list:
        theses = list_open(conn)
        if theses:
            st.dataframe(open_theses_table(theses), use_container_width=True)
        else:
            st.info("保有中のトレードはありません。")

    with tab_exit:
        theses = list_open(conn)
        if not theses:
            st.info("決済対象のトレードがありません。")
        else:
            options = {f"#{t.id} {t.ticker}": t.id for t in theses}
            selected_label = st.selectbox("決済するトレード", list(options.keys()))
            selected = get_thesis(conn, options[selected_label])
            st.write(f"当初の仮説: {selected.alpha_thesis}")
            st.write(f"撤退条件: {selected.exit_condition}")

            with st.form("exit_form"):
                exit_price = st.number_input("決済価格", min_value=0.0, step=1.0)
                exit_reason = st.selectbox("利確損切り区分", EXIT_REASONS)
                as_expected = st.selectbox("想定通りだったか", AS_EXPECTED_CHOICES)
                reflection = st.text_area("振り返り")
                submitted_exit = st.form_submit_button("決済を記録")

            if submitted_exit:
                closed = close_thesis(
                    conn,
                    selected.id,
                    exit_price=exit_price,
                    exit_reason=exit_reason,
                    as_expected=as_expected,
                    reflection=reflection,
                )
                st.success(f"決済を記録しました: 損益率={closed.pnl_pct:+.2f}%")

    with tab_report:
        month = st.text_input("対象月(YYYY-MM)", value=date.today().strftime("%Y-%m"))
        if st.button("レポート表示"):
            st.text(monthly_report_text(conn, month))


elif page == "銘柄選定・スクリーニング(Phase2)":
    st.header("Phase 2: 銘柄選定基準の自動スコアリング / 未認識の好進捗スクリーナー")
    cache = load_market_cache()

    if cache is None:
        st.warning("market_cache.json が見つかりません。サイドバーから市場データを取得してください。")
    else:
        tab_score, tab_screen = st.tabs(["スコアリング(2-2)", "未認識の好進捗スクリーナー(2-0)"])

        with tab_score:
            tickers_in_cache = list(cache.get("tickers", {}).keys())
            if not tickers_in_cache:
                st.info("キャッシュに銘柄データがありません。")
            else:
                ticker = st.selectbox("銘柄コード", tickers_in_cache)
                if st.button("スコア計算"):
                    data = cache["tickers"][ticker]
                    inputs = build_score_inputs(ticker, data["statements"], data["quotes"])
                    result = score_stock(inputs)
                    st.metric("スコア合計", result.total_score)
                    st.table(score_breakdown_table(result))

        with tab_screen:
            progress_threshold = st.slider("進捗率閾値(%)", 0.0, 100.0, 30.0)
            reaction_threshold = st.slider("対TOPIX反応閾値(%)", -20.0, 20.0, 5.0)
            if st.button("スクリーニング実行"):
                candidates = find_unrecognized_progress(
                    cache.get("tickers", {}),
                    cache.get("topix", []),
                    progress_threshold=progress_threshold,
                    reaction_threshold=reaction_threshold,
                )
                if candidates:
                    st.dataframe(screener_table(candidates), use_container_width=True)
                else:
                    st.info("条件に合致する「未認識の好進捗」銘柄はありませんでした。")


elif page == "シーズナリティ・現金比率(Phase3)":
    st.header("Phase 3: 年間シーズナリティ・市場イベントカレンダー / 現金比率コントロール")
    cache = load_market_cache()
    tab_season, tab_memo, tab_cash = st.tabs(["シーズナリティ分析(2-1)", "メモ(2-1)", "現金比率アラート(2-4)"])

    with tab_season:
        if cache is None:
            st.warning("market_cache.json が見つかりません。サイドバーから市場データを取得してください。")
        else:
            topix = cache.get("topix", [])
            stats = monthly_return_stats(topix)
            if stats:
                st.subheader("月次騰落率統計(TOPIX)")
                # 月を文字列化すると"10"や"11"が辞書順で先頭に来てしまうため、
                # 整数インデックスのまま渡して1〜12月の順序を維持する。
                monthly_series = pd.Series(
                    {m: s["avg_return_pct"] for m, s in sorted(stats.items())}
                )
                st.bar_chart(monthly_series)
                st.table(monthly_stats_table(stats))
            else:
                st.info("月次統計を計算するにはより長期間のデータが必要です。")

            earnings = earnings_concentration_by_month(cache.get("tickers", {}))
            if earnings:
                st.subheader("決算集中期(開示件数/月)")
                earnings_series = pd.Series(dict(sorted(earnings.items())))
                st.bar_chart(earnings_series)

            year = st.number_input("四半期末リバランス対象年", value=date.today().year, step=1)
            st.subheader(f"{int(year)}年 四半期末リバランス時期")
            for d in quarter_end_rebalance_dates(int(year)):
                st.write(d)

    with tab_memo:
        with st.form("memo_form"):
            memo_month = st.number_input("月", min_value=1, max_value=12, step=1)
            memo_day = st.number_input("日", min_value=1, max_value=31, step=1)
            note = st.text_area("メモ")
            tags = st.text_input("タグ(カンマ区切り)")
            submitted_memo = st.form_submit_button("メモを登録")

        if submitted_memo:
            if not note:
                st.error("メモの内容を入力してください。")
            else:
                add_memo(
                    conn,
                    event_month=int(memo_month),
                    event_day=int(memo_day),
                    note=note,
                    tags=[t.strip() for t in tags.split(",") if t.strip()],
                )
                st.success("登録しました")

        st.subheader("直近のリマインド(前後7日)")
        due = due_memos(conn)
        if due:
            st.table(memos_table(due))
        else:
            st.info("直近のメモはありません。")

        st.subheader("全メモ一覧")
        all_memos = list_memos(conn)
        if all_memos:
            st.table(memos_table(all_memos))
        else:
            st.info("メモがありません。")

    with tab_cash:
        if cache is None:
            st.warning("market_cache.json が見つかりません。サイドバーから市場データを取得してください。")
        else:
            open_theses = list_open(conn)
            tickers = cache.get("tickers", {})

            latest_prices, ma_deviations = {}, {}
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
                score_stock(build_score_inputs(tk, d.get("statements", []), d.get("quotes", [])))
                for tk, d in tickers.items()
            ]
            crash_alert = check_crash_buy_opportunity(cache.get("topix", []), score_results)
            if crash_alert:
                alerts.append(crash_alert)

            if alerts:
                st.table(cash_alerts_table(alerts))
            else:
                st.info("現時点でアラートはありません。")


elif page == "TOPIX採用予想・需給分析(Phase5)":
    st.header("Phase 5: TOPIX採用予想・需給分析")
    st.caption(
        "正式発表後の採用銘柄を追うのではなく、採用される可能性が高い銘柄を正式発表前から発掘する。"
        "⚠️ JPX基準適合度は浮動株比率データを取得できないため近似値。証券会社の採用予想は自動取得できないため手動ログ。"
    )
    cache = load_market_cache()
    tab_rank, tab_forecast, tab_outcome = st.tabs(["採用候補ランキング", "採用予想ログ", "発表後の結果記録"])

    with tab_rank:
        if cache is None:
            st.warning("market_cache.json が見つかりません。サイドバーから市場データを取得してください。")
        else:
            col_a, col_b = st.columns(2)
            review_date = col_a.text_input("対象の入替回(例: 2026-10)", value="2026-10", key="topix_review_date")
            basis_date = col_b.text_input("基準日(YYYY-MM-DD)", value="2026-08-31", key="topix_basis_date")

            with st.expander("JPX基準適合度の入力(近似値、銘柄ごとに手動登録)"):
                tickers_in_cache = list(cache.get("tickers", {}).keys())
                if tickers_in_cache:
                    fit_ticker = st.selectbox("銘柄コード", tickers_in_cache, key="topix_fit_ticker")
                    fit_name = st.text_input("銘柄名", key="topix_fit_name")
                    fit_cap = st.number_input("発行済株式ベース時価総額(円)", min_value=0.0, step=1.0, key="topix_fit_cap")
                    fit_trading_value = st.number_input("年間売買代金(円)", min_value=0.0, step=1.0, key="topix_fit_tv")
                    fit_segment = st.selectbox("市場区分", ["プライム", "スタンダード", "グロース"], key="topix_fit_segment")
                    fit_percentile = st.slider("時価総額パーセンタイル(上位何%か)", 0.0, 100.0, 50.0, key="topix_fit_pct")
                    if st.button("この内容で保存", key="topix_fit_save"):
                        data = load_topix_fit_inputs()
                        data[fit_ticker] = {
                            "name": fit_name or fit_ticker,
                            "market_cap": fit_cap or None,
                            "annual_trading_value": fit_trading_value or None,
                            "market_segment": fit_segment,
                            "market_cap_percentile": fit_percentile,
                        }
                        save_topix_fit_inputs(data)
                        st.success(f"{fit_ticker} の適合度入力を保存しました。")
                else:
                    st.info("キャッシュに銘柄データがありません。先に市場データを取得してください。")

            if st.button("ランキングを更新", key="topix_rank_run"):
                candidates = _build_topix_candidates(conn, cache, review_date, basis_date)
                if not candidates:
                    st.info(
                        "候補銘柄がありません。「JPX基準適合度の入力」または「採用予想ログ」のどちらかを"
                        "登録した銘柄だけが対象になります。"
                    )
                else:
                    st.subheader("TOPIX採用候補ランキング")
                    st.dataframe(topix_candidates_table(candidates), use_container_width=True)

                    watchlist = topix_precede_watchlist(candidates)
                    st.subheader("★ 先回り候補ウォッチリスト(採用可能性高 × 織り込み度低)")
                    if watchlist:
                        st.dataframe(topix_candidates_table(watchlist), use_container_width=True)
                    else:
                        st.info("現在、先回り候補に該当する銘柄はありません。")

    with tab_forecast:
        with st.form("topix_forecast_form"):
            fc_ticker = st.text_input("銘柄コード")
            fc_broker = st.text_input("証券会社名(例: 大和証券)")
            fc_review_date = st.text_input("対象の入替回(例: 2026-10)")
            fc_type = st.selectbox("予想区分", ["new", "exclude"], format_func=lambda v: "新規採用予想" if v == "new" else "除外予想")
            fc_mentioned_at = st.text_input("予想が出た日(YYYY-MM-DD)")
            fc_note = st.text_area("メモ(出典・文脈など)")
            fc_submitted = st.form_submit_button("採用予想を登録")

        if fc_submitted:
            if not (fc_ticker and fc_broker and fc_review_date and fc_mentioned_at):
                st.error("銘柄コード・証券会社名・対象の入替回・予想が出た日は必須です。")
            else:
                topix_add_forecast(
                    conn, ticker=fc_ticker, broker=fc_broker, review_date=fc_review_date,
                    forecast_type=fc_type, mentioned_at=fc_mentioned_at, source_note=fc_note,
                )
                st.success("登録しました。")

        st.subheader("ログ済みの採用予想")
        forecast_filter = st.text_input("対象の入替回で絞り込み(空欄で全件)", key="topix_forecast_filter")
        forecasts = topix_list_forecasts(conn, review_date=forecast_filter or None)
        if forecasts:
            st.dataframe(topix_forecasts_table(forecasts), use_container_width=True)
        else:
            st.info("登録されている採用予想はありません。")

    with tab_outcome:
        with st.form("topix_outcome_form"):
            out_ticker = st.text_input("銘柄コード", key="topix_out_ticker")
            out_review_date = st.text_input("対象の入替回(例: 2026-10)", key="topix_out_review_date")
            out_outcome = st.selectbox("結果", TOPIX_OUTCOME_CHOICES, key="topix_out_outcome")
            out_announcement_date = st.text_input("発表日(YYYY-MM-DD、任意)", key="topix_out_announce")
            out_reaction = st.number_input("発表日の株価反応(%、任意)", value=0.0, step=0.1, key="topix_out_reaction")
            out_note = st.text_area("メモ", key="topix_out_note")
            out_submitted = st.form_submit_button("結果を記録")

        if out_submitted:
            if not (out_ticker and out_review_date):
                st.error("銘柄コードと対象の入替回は必須です。")
            else:
                topix_add_outcome(
                    conn, ticker=out_ticker, review_date=out_review_date, outcome=out_outcome,
                    announcement_date=out_announcement_date or None,
                    price_reaction_pct=out_reaction if out_reaction else None, note=out_note,
                )
                st.success("記録しました。")

        st.subheader("精度レポート(予想通り/予想外/見送りの件数)")
        report_filter = st.text_input("対象の入替回で絞り込み(空欄で全件)", key="topix_outcome_report_filter")
        report = topix_accuracy_report(conn, review_date=report_filter or None)
        st.write(f"件数: {report['total']}")
        st.table([{"結果": k, "件数": v} for k, v in report["by_outcome"].items()])

        outcomes = topix_list_outcomes(conn, review_date=report_filter or None)
        if outcomes:
            st.subheader("記録済みの結果一覧")
            st.dataframe(topix_outcomes_table(outcomes), use_container_width=True)
