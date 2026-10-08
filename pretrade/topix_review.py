"""TOPIX採用予想・需給分析(Phase 5)。

「正式発表後の採用銘柄を追う」のではなく、「採用される可能性が高い銘柄を、
正式発表前から発掘する」ことが目的。以下の3つを組み合わせて判断する:

1. JPX選定基準への適合度(近似) -- score_jpx_fit()
   J-Quants の契約APIには浮動株比率(大株主構成)のエンドポイントがなく、
   JPX本家の算出方法も非公開データに依存するため、ここで出せるのはあくまで
   「発行済株式ベースの時価総額・売買代金から試算した近似値」。
   JpxFitResult.data_notes に欠けている入力を明記し、呼び出し側が
   近似である旨を表示する前提で設計している。

2. 証券会社等の採用予想の集計 -- aggregate_forecasts()
   自動取得できるソースがないため、BrokerForecast は手動ログ(CLIの
   topix-forecast-add、または db.py の topix_broker_forecasts テーブル)
   で積み上げる想定。

3. 織り込み度の分析 -- compute_pricing_in()
   「予想が最初に出た日」以降の対TOPIX相対パフォーマンスを見る。
   screener.py の analyze_ticker() と同じ考え方(対TOPIX相対反応度)を
   再利用している。

入力は J-Quants API V2 のレスポンス形式(data 配列の要素)をそのまま渡す想定。
ネットワークアクセスは行わない(テスト容易性のため、既存モジュールと同じ方針)。
"""
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import Optional

from .signals import to_float, sort_quotes

# -- JPX基準適合度(近似) -------------------------------------------------
# 2026年10月TOPIX改革(第2段階見直し)の公表基準(大和証券等の解説記事より):
#   新規採用: 年間売買代金回転率 >= 0.20 かつ 浮動株時価総額の累積比率が上位96%以内
#   既存銘柄残留: 回転率 >= 0.14 かつ 上位97%以内
# 浮動株時価総額が算出できないため、ここでは「発行済株式ベース時価総額」を代用し、
# その旨を data_notes に残す。
NEW_INCLUSION_TURNOVER_MIN = 0.20
MARKET_SEGMENTS_ELIGIBLE = {"プライム", "スタンダード", "グロース"}

POINTS_TURNOVER_OK = 2
POINTS_SEGMENT_ELIGIBLE = 1
POINTS_MARKET_CAP_RANK = 2  # market_cap_percentile が与えられ、上位70%以内なら加点(簡易基準)
MARKET_CAP_RANK_THRESHOLD_PCT = 70.0


@dataclass
class JpxFitInputs:
    ticker: str
    market_cap: Optional[float] = None  # 発行済株式ベース時価総額(浮動株時価総額の近似)
    annual_trading_value: Optional[float] = None  # 年間売買代金(円)
    market_segment: Optional[str] = None  # "プライム"/"スタンダード"/"グロース"
    market_cap_percentile: Optional[float] = None  # 時価総額の市場内パーセンタイル(0-100、手動入力も可)


@dataclass
class JpxFitResult:
    ticker: str
    fit_score: int  # 0-5の近似スコア(満点は厳密なJPX基準とは一致しない)
    max_score: int
    turnover_ratio: Optional[float]
    breakdown: list
    data_notes: list = field(default_factory=list)
    is_approximate: bool = True


def compute_turnover_ratio(inputs: JpxFitInputs) -> Optional[float]:
    if not inputs.annual_trading_value or not inputs.market_cap:
        return None
    return inputs.annual_trading_value / inputs.market_cap


def score_jpx_fit(inputs: JpxFitInputs) -> JpxFitResult:
    breakdown = []
    notes = []
    score = 0
    max_score = POINTS_TURNOVER_OK + POINTS_SEGMENT_ELIGIBLE + POINTS_MARKET_CAP_RANK

    turnover = compute_turnover_ratio(inputs)
    if turnover is None:
        notes.append("年間売買代金または時価総額が未入力のため、回転率を算出できません")
        breakdown.append(("売買代金回転率(>=0.20)", 0, "データ不足"))
    else:
        matched = turnover >= NEW_INCLUSION_TURNOVER_MIN
        pts = POINTS_TURNOVER_OK if matched else 0
        score += pts
        breakdown.append(
            ("売買代金回転率(>=0.20)", pts, f"回転率={turnover:.3f}" + ("(基準達成)" if matched else "(基準未達)"))
        )

    if inputs.market_segment is None:
        notes.append("市場区分が未入力です")
        breakdown.append(("市場区分(プライム/スタンダード/グロース)", 0, "データ不足"))
    else:
        matched = inputs.market_segment in MARKET_SEGMENTS_ELIGIBLE
        pts = POINTS_SEGMENT_ELIGIBLE if matched else 0
        score += pts
        breakdown.append(
            ("市場区分(プライム/スタンダード/グロース)", pts, inputs.market_segment + ("(対象)" if matched else "(対象外)"))
        )

    if inputs.market_cap_percentile is None:
        notes.append("時価総額パーセンタイルが未入力のため、浮動株時価総額基準を代用評価できません")
        breakdown.append(("時価総額ランク(簡易基準、上位70%以内)", 0, "データ不足"))
    else:
        matched = inputs.market_cap_percentile <= MARKET_CAP_RANK_THRESHOLD_PCT
        pts = POINTS_MARKET_CAP_RANK if matched else 0
        score += pts
        breakdown.append(
            (
                "時価総額ランク(簡易基準、上位70%以内)",
                pts,
                f"上位{inputs.market_cap_percentile:.1f}%" + ("(基準達成)" if matched else "(基準未達)"),
            )
        )

    if not notes:
        notes.append("浮動株比率データが取得できないため、本スコアは発行済株式ベースの近似値です")

    return JpxFitResult(
        ticker=inputs.ticker,
        fit_score=score,
        max_score=max_score,
        turnover_ratio=turnover,
        breakdown=breakdown,
        data_notes=notes,
    )


# -- 証券会社等の採用予想の集計 -------------------------------------------

@dataclass
class BrokerForecast:
    ticker: str
    broker: str
    review_date: str  # "2026-10" のような対象入替回を表す文字列
    forecast_type: str  # "new"(新規採用予想) | "exclude"(除外予想)
    mentioned_at: str  # ISO日付。予想が公表/報道された日
    source_note: str = ""


@dataclass
class ForecastSummary:
    ticker: str
    mention_count: int
    brokers: list
    first_mentioned_at: Optional[str]
    latest_mentioned_at: Optional[str]
    forecast_type: Optional[str]  # 複数ある場合は最新のforecast_typeを採用


def aggregate_forecasts(forecasts: list) -> ForecastSummary:
    """1銘柄分の BrokerForecast リストを要約する。空リストなら mention_count=0。"""
    if not forecasts:
        return ForecastSummary(
            ticker="", mention_count=0, brokers=[], first_mentioned_at=None,
            latest_mentioned_at=None, forecast_type=None,
        )
    ordered = sorted(forecasts, key=lambda f: f.mentioned_at)
    ticker = ordered[0].ticker
    brokers = sorted({f.broker for f in ordered})
    return ForecastSummary(
        ticker=ticker,
        mention_count=len(ordered),
        brokers=brokers,
        first_mentioned_at=ordered[0].mentioned_at,
        latest_mentioned_at=ordered[-1].mentioned_at,
        forecast_type=ordered[-1].forecast_type,
    )


def format_forecast_basis(summary: ForecastSummary) -> str:
    if summary.mention_count == 0:
        return "予想情報なし(未発見の可能性)"
    brokers_str = "・".join(summary.brokers)
    return f"{brokers_str}が言及({summary.mention_count}件、初回{summary.first_mentioned_at})"


# -- 織り込み度の分析 -----------------------------------------------------

@dataclass
class PricingInResult:
    ticker: str
    since_date: Optional[str]
    price_reaction_pct: Optional[float]
    topix_reaction_pct: Optional[float]
    relative_reaction_pct: Optional[float]
    volume_surge_since: bool
    priced_in_level: str  # "high" | "medium" | "low" | "unknown"


PRICED_IN_HIGH_THRESHOLD = 15.0
PRICED_IN_LOW_THRESHOLD = 5.0


def _price_at_or_before(quotes_sorted: list, cutoff_date: str) -> Optional[float]:
    candidate = None
    for q in quotes_sorted:
        if (q.get("Date") or "") > cutoff_date:
            break
        close = to_float(q.get("AdjC")) or to_float(q.get("C"))
        if close is not None:
            candidate = close
    return candidate


def _latest_price(quotes_sorted: list) -> Optional[float]:
    for q in reversed(quotes_sorted):
        close = to_float(q.get("AdjC")) or to_float(q.get("C"))
        if close is not None:
            return close
    return None


def _volume_series(quotes_sorted: list) -> list:
    out = []
    for q in quotes_sorted:
        out.append(to_float(q.get("AdjVo")) or to_float(q.get("Vo")))
    return out


def _volume_surge_since(quotes_sorted: list, since_date: str, multiple: float = 1.5) -> bool:
    """since_date 以降の平均出来高が、それ以前の平均出来高のmultiple倍以上かを判定する。"""
    before = [q for q in quotes_sorted if (q.get("Date") or "") < since_date]
    after = [q for q in quotes_sorted if (q.get("Date") or "") >= since_date]
    before_vols = [v for v in _volume_series(before) if v is not None]
    after_vols = [v for v in _volume_series(after) if v is not None]
    if not before_vols or not after_vols:
        return False
    before_avg = sum(before_vols) / len(before_vols)
    after_avg = sum(after_vols) / len(after_vols)
    return bool(before_avg) and after_avg >= before_avg * multiple


def compute_pricing_in(ticker: str, quotes: list, topix_quotes: list, since_date: Optional[str]) -> PricingInResult:
    """since_date(通常は最初に採用予想が出た日)以降、対TOPIXでどれだけ上振れしたかを見る。

    since_date が None(予想言及が無い銘柄)の場合は "unknown" を返す
    -- 織り込み度を測る基準日が無いため判定不能、という扱い。
    """
    if since_date is None:
        return PricingInResult(
            ticker=ticker, since_date=None, price_reaction_pct=None, topix_reaction_pct=None,
            relative_reaction_pct=None, volume_surge_since=False, priced_in_level="unknown",
        )

    q_stock = sort_quotes(quotes)
    q_topix = sort_quotes(topix_quotes)

    pre_price = _price_at_or_before(q_stock, since_date)
    latest_price = _latest_price(q_stock)
    pre_topix = _price_at_or_before(q_topix, since_date)
    latest_topix = _latest_price(q_topix)

    if not pre_price or not latest_price or not pre_topix or not latest_topix:
        return PricingInResult(
            ticker=ticker, since_date=since_date, price_reaction_pct=None, topix_reaction_pct=None,
            relative_reaction_pct=None, volume_surge_since=False, priced_in_level="unknown",
        )

    price_reaction_pct = (latest_price / pre_price - 1) * 100
    topix_reaction_pct = (latest_topix / pre_topix - 1) * 100
    relative_reaction_pct = price_reaction_pct - topix_reaction_pct
    volume_surge = _volume_surge_since(q_stock, since_date)

    if relative_reaction_pct >= PRICED_IN_HIGH_THRESHOLD:
        level = "high"
    elif relative_reaction_pct <= PRICED_IN_LOW_THRESHOLD:
        level = "low"
    else:
        level = "medium"

    return PricingInResult(
        ticker=ticker,
        since_date=since_date,
        price_reaction_pct=price_reaction_pct,
        topix_reaction_pct=topix_reaction_pct,
        relative_reaction_pct=relative_reaction_pct,
        volume_surge_since=volume_surge,
        priced_in_level=level,
    )


# -- 52週レンジ内の現在位置 ------------------------------------------------

def price_position_in_52w_range(quotes: list, window_days: int = 365) -> Optional[dict]:
    """直近window_days日の高値・安値に対する現在値の位置を返す。
    戻り値: {"high": ..., "low": ..., "latest": ..., "pct_from_low": ..., "pct_from_high": ...}
    """
    q_sorted = sort_quotes(quotes)
    if not q_sorted:
        return None
    recent = q_sorted[-window_days:] if len(q_sorted) > window_days else q_sorted
    closes = [to_float(q.get("AdjC")) or to_float(q.get("C")) for q in recent]
    closes = [c for c in closes if c is not None]
    if not closes:
        return None
    high, low, latest = max(closes), min(closes), closes[-1]
    pct_from_low = (latest / low - 1) * 100 if low else None
    pct_from_high = (latest / high - 1) * 100 if high else None
    return {"high": high, "low": low, "latest": latest, "pct_from_low": pct_from_low, "pct_from_high": pct_from_high}


# -- パターン判定・総合候補スコア -----------------------------------------

PATTERN_PRICED_IN = "材料出尽くしリスク"  # A: 予想多数 + 大きく先行上昇
PATTERN_SURPRISE_UPSIDE = "予想外採用による上昇余地"  # B: 予想少数/無 + 反応薄
PATTERN_NEUTRAL = "判定不能/中間"


def classify_pattern(fit: JpxFitResult, forecast: ForecastSummary, pricing: PricingInResult) -> str:
    if forecast.mention_count >= 1 and pricing.priced_in_level == "high":
        return PATTERN_PRICED_IN
    if fit.fit_score >= 3 and forecast.mention_count == 0 and pricing.priced_in_level in ("low", "unknown"):
        return PATTERN_SURPRISE_UPSIDE
    if fit.fit_score >= 3 and forecast.mention_count >= 1 and pricing.priced_in_level == "low":
        # JPX基準も満たし予想もあるのに、まだ株価が反応していない -- 一番おいしい「先回り」候補
        return PATTERN_SURPRISE_UPSIDE
    return PATTERN_NEUTRAL


@dataclass
class TopixCandidate:
    ticker: str
    name: str
    candidate_score: float  # 採用候補度(JPX適合度+予想言及で加重)
    forecast_basis: str  # 採用予想の根拠
    jpx_fit: JpxFitResult
    priced_in: PricingInResult
    pattern: str
    price_position: Optional[dict]
    watch_period: str
    is_precede_candidate: bool  # 「採用可能性が高い × 織り込み度が低い」


def watch_period_label(review_date_basis: str, today: Optional[date] = None) -> str:
    """基準日(review_date_basis, "YYYY-MM-DD")と今日の日付から、注目すべき時期のラベルを返す。"""
    today = today or date.today()
    try:
        basis = datetime.strptime(review_date_basis, "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return "基準日不明"
    days = (basis - today).days
    if days > 30:
        return "基準日まで1ヶ月超(早期発掘フェーズ)"
    if days > 0:
        return f"基準日まで{days}日(基準日接近)"
    if days == 0:
        return "基準日当日"
    return "基準日通過・発表待ち"


def build_candidate(
    ticker: str,
    name: str,
    jpx_inputs: JpxFitInputs,
    forecasts: list,
    quotes: list,
    topix_quotes: list,
    review_date_basis: str,
) -> TopixCandidate:
    fit = score_jpx_fit(jpx_inputs)
    forecast_summary = aggregate_forecasts([f for f in forecasts if f.ticker == ticker])
    pricing = compute_pricing_in(ticker, quotes, topix_quotes, forecast_summary.first_mentioned_at)
    pattern = classify_pattern(fit, forecast_summary, pricing)
    position = price_position_in_52w_range(quotes)

    # 候補度: JPX適合度(0-5) * 10 に、予想言及1件ごとに+5(最大+20)を加算した0-100目安。
    candidate_score = fit.fit_score * 10 + min(forecast_summary.mention_count, 4) * 5

    is_precede = pattern == PATTERN_SURPRISE_UPSIDE and fit.fit_score >= 3

    return TopixCandidate(
        ticker=ticker,
        name=name,
        candidate_score=candidate_score,
        forecast_basis=format_forecast_basis(forecast_summary),
        jpx_fit=fit,
        priced_in=pricing,
        pattern=pattern,
        price_position=position,
        watch_period=watch_period_label(review_date_basis),
        is_precede_candidate=is_precede,
    )


def build_candidates_from_raw(
    fit_inputs_raw: dict,
    forecasts_grouped: dict,
    tickers_data: dict,
    topix_quotes: list,
    review_date_basis: str,
) -> list:
    """cli.py / app.py の両方から使う共通ロジック。

    fit_inputs_raw: {ticker: {"name", "market_cap", "annual_trading_value",
                               "market_segment", "market_cap_percentile"}}
        (topix_fit_store.load_fit_inputs() の形式)
    forecasts_grouped: {ticker: [BrokerForecast, ...]} (topix_db.forecasts_by_ticker() の形式)
    tickers_data: {ticker: {"statements": [...], "quotes": [...]}} (market_cache.json の "tickers")

    対象ティッカーは「市場データキャッシュに価格データがある」かつ
    「JPX適合度入力または採用予想ログのどちらかがある」銘柄に限定する
    (どちらも無い銘柄は判定材料が無いため候補として出さない)。
    """
    target_tickers = (set(fit_inputs_raw.keys()) | set(forecasts_grouped.keys())) & set(tickers_data.keys())

    candidates = []
    for ticker in target_tickers:
        raw_fit = fit_inputs_raw.get(ticker, {})
        jpx_inputs = JpxFitInputs(
            ticker=ticker,
            market_cap=raw_fit.get("market_cap"),
            annual_trading_value=raw_fit.get("annual_trading_value"),
            market_segment=raw_fit.get("market_segment"),
            market_cap_percentile=raw_fit.get("market_cap_percentile"),
        )
        quotes = tickers_data.get(ticker, {}).get("quotes", [])
        forecasts = forecasts_grouped.get(ticker, [])
        candidate = build_candidate(
            ticker, raw_fit.get("name", ticker), jpx_inputs, forecasts, quotes, topix_quotes,
            review_date_basis=review_date_basis,
        )
        candidates.append(candidate)

    return rank_candidates(candidates)


def rank_candidates(candidates: list) -> list:
    """candidate_score 降順、同点は織り込み度が低い順(先回りしやすい順)。"""
    priced_in_order = {"low": 0, "unknown": 1, "medium": 2, "high": 3}
    return sorted(
        candidates,
        key=lambda c: (-c.candidate_score, priced_in_order.get(c.priced_in.priced_in_level, 1)),
    )


def precede_watchlist(candidates: list) -> list:
    """「採用可能性が高い × 織り込み度が低い」銘柄だけを抜き出す。"""
    return [c for c in candidates if c.is_precede_candidate]


# -- 発表後の結果分類(次回予想の精度向上用) -------------------------------

OUTCOME_AS_EXPECTED = "予想通り採用"
OUTCOME_UNEXPECTED = "予想外採用"
OUTCOME_PASSED_OVER = "採用見送り"
OUTCOME_CHOICES = [OUTCOME_AS_EXPECTED, OUTCOME_UNEXPECTED, OUTCOME_PASSED_OVER]


def classify_outcome(was_forecasted: bool, was_included: bool) -> str:
    if was_included and was_forecasted:
        return OUTCOME_AS_EXPECTED
    if was_included and not was_forecasted:
        return OUTCOME_UNEXPECTED
    return OUTCOME_PASSED_OVER
