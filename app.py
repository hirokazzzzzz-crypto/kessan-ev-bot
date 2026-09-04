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
)
from pretrade.db import AS_EXPECTED_CHOICES, EXIT_REASONS, RATIONALE_CATEGORIES, get_connection
from pretrade.fetch_cache import fetch_and_cache, load_cache
from pretrade.models import close_thesis, create_thesis, get_thesis, list_open
from pretrade.report import monthly_report_text
from pretrade.rr import RR_WARNING_THRESHOLD, calculate_rr
from pretrade.scan import build_score_inputs
from pretrade.screener import find_unrecognized_progress
from pretrade.scoring import score_stock

st.set_page_config(page_title="売買判断支援ダッシュボード", layout="wide")


def load_market_cache():
    try:
        return load_cache()
    except FileNotFoundError:
        return None


# Streamlitのスクリプトはリランのたびにワーカースレッドをまたぐことがあり、
# sqlite3の接続はスレッドをまたいで使い回せないため、st.cache_resourceでは
# キャッシュせず毎回開き直す(SQLiteへの接続はローカルファイルのため軽量)。
conn = get_connection()

with st.sidebar:
    st.title("売買判断支援システム")
    page = st.radio(
        "ページ",
        ["概要", "売買前チェック(Phase1)", "銘柄選定・スクリーニング(Phase2)", "シーズナリティ・現金比率(Phase3)"],
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
