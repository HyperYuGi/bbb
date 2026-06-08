"""
Overnight Backtest — Streamlit App
Strategia: Kup o HH:MM ET, sprzedaj następnego dnia o HH:MM ET

Instalacja:
    pip install streamlit yfinance pandas plotly

Uruchomienie:
    streamlit run overnight_backtest_app.py
"""

import streamlit as st
import yfinance as yf
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import pytz

# ── Konfiguracja strony ────────────────────────────────────────────────────────
st.set_page_config(
    page_title="Overnight Backtest",
    page_icon="📈",
    layout="wide",
)

st.title("📈 Overnight Backtest")
st.caption("Kup X minut przed zamknięciem → sprzedaj Y minut po otwarciu następnego dnia")

# ── Panel boczny — ustawienia ──────────────────────────────────────────────────
with st.sidebar:
    st.header("⚙️ Ustawienia")

    ticker = st.text_input("Ticker", value="MSTR").upper().strip()

    st.subheader("Czas transakcji (ET)")
    col1, col2 = st.columns(2)
    with col1:
        buy_h  = st.number_input("Kupno — godz.", min_value=9,  max_value=15, value=15)
        buy_m  = st.number_input("Kupno — min.",  min_value=0,  max_value=59, value=45, step=5)
    with col2:
        sell_h = st.number_input("Sprzedaż — godz.", min_value=9,  max_value=16, value=9)
        sell_m = st.number_input("Sprzedaż — min.",  min_value=0,  max_value=59, value=45, step=5)

    buy_time  = f"{buy_h:02d}:{buy_m:02d}"
    sell_time = f"{sell_h:02d}:{sell_m:02d}"

    st.subheader("Okres i kapitał")
    period_label = st.selectbox(
        "Okres historyczny",
        ["3 miesiące", "6 miesięcy", "1 rok", "2 lata", "5 lat"],
        index=2,
    )
    period_days = {
        "3 miesiące": 90,
        "6 miesięcy": 180,
        "1 rok":      365,
        "2 lata":     730,
        "5 lat":      1825,
    }[period_label]

    capital   = st.number_input("Kapitał startowy ($)", min_value=100, value=10_000, step=500)
    comm_pct  = st.number_input("Prowizja (%)", min_value=0.0, max_value=2.0, value=0.0, step=0.01,
                                 help="Prowizja na jedno wejście/wyjście. Łącznie odejmowane 2× na transakcję.")

    run = st.button("▶ Uruchom backtest", type="primary", use_container_width=True)

# ── Funkcje ────────────────────────────────────────────────────────────────────
ET = pytz.timezone("America/New_York")

@st.cache_data(show_spinner=False)
def load_data(ticker: str, days: int) -> pd.DataFrame:
    end   = datetime.now(ET)
    start = end - timedelta(days=days)
    df = yf.download(ticker, start=start, end=end, interval="15m", progress=False, auto_adjust=True)
    if df.empty:
        return df
    df.index = pd.to_datetime(df.index).tz_convert(ET)
    return df


def get_price_at(df: pd.DataFrame, time_str: str) -> dict:
    """Zwróć {date: close_price} dla podanej godziny HH:MM."""
    result = {}
    for idx, row in df.iterrows():
        if idx.strftime("%H:%M") == time_str:
            val = row["Close"]
            result[idx.date()] = float(val.iloc[0] if hasattr(val, "iloc") else val)
    return result


def run_backtest(df: pd.DataFrame, buy_time: str, sell_time: str,
                 capital: float, comm_pct: float) -> pd.DataFrame:
    buys  = get_price_at(df, buy_time)
    sells = get_price_at(df, sell_time)
    sell_dates = sorted(sells.keys())
    trades = []

    for buy_date in sorted(buys.keys()):
        buy_price = buys[buy_date]
        sell_date = next((d for d in sell_dates if d > buy_date), None)
        if sell_date is None:
            continue
        sell_price = sells[sell_date]
        pct = (sell_price - buy_price) / buy_price * 100 - comm_pct * 2
        trades.append({
            "Data kupna":      buy_date,
            "Cena kupna":      round(buy_price, 2),
            "Data sprzedaży":  sell_date,
            "Cena sprzedaży":  round(sell_price, 2),
            "Zmiana %":        round(pct, 3),
        })

    return pd.DataFrame(trades)


def compute_stats(df_trades: pd.DataFrame, capital: float) -> dict:
    n   = len(df_trades)
    pct = df_trades["Zmiana %"]
    wins = (pct > 0).sum()

    # Equity curve (składana)
    eq = capital
    equity = [capital]
    for p in pct:
        eq *= (1 + p / 100)
        equity.append(round(eq, 2))
    df_trades = df_trades.copy()
    df_trades["Equity"] = equity[1:]

    # Max drawdown
    peak, max_dd = capital, 0.0
    for e in equity:
        if e > peak:
            peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd:
            max_dd = dd

    return {
        "n":          n,
        "wins":       int(wins),
        "win_rate":   wins / n * 100,
        "avg_pct":    float(pct.mean()),
        "total_pct":  (eq - capital) / capital * 100,
        "max_gain":   float(pct.max()),
        "max_loss":   float(pct.min()),
        "max_dd":     max_dd,
        "final_eq":   eq,
        "df":         df_trades,
        "equity":     equity,
    }

# ── Główna logika ──────────────────────────────────────────────────────────────
if run:
    with st.spinner(f"Pobieranie danych {ticker} (interwał 15m, {period_label})..."):
        df = load_data(ticker, period_days)

    if df.empty:
        st.error(f"Nie udało się pobrać danych dla **{ticker}**. Sprawdź ticker i spróbuj ponownie.")
        st.stop()

    with st.spinner("Obliczanie transakcji..."):
        df_trades = run_backtest(df, buy_time, sell_time, capital, comm_pct)

    if df_trades.empty:
        st.warning("Brak transakcji — być może wybrane godziny nie pasują do dostępnych danych (rynek mógł być zamknięty).")
        st.stop()

    stats = compute_stats(df_trades, capital)
    s     = stats

    # ── Metryki ────────────────────────────────────────────────────────────────
    st.subheader(f"Wyniki — {ticker}  |  {buy_time} → {sell_time} ET  |  {period_label}")

    c1, c2, c3, c4, c5 = st.columns(5)
    sign = "+" if s["total_pct"] >= 0 else ""
    c1.metric("Wynik łączny",      f"{sign}{s['total_pct']:.1f}%")
    c2.metric("Kapitał końcowy",   f"${s['final_eq']:,.0f}")
    c3.metric("Win rate",          f"{s['win_rate']:.1f}%",  f"{s['wins']}/{s['n']} transakcji")
    c4.metric("Śr. zmiana/trade",  f"{s['avg_pct']:+.3f}%")
    c5.metric("Max drawdown",      f"-{s['max_dd']:.1f}%")

    c6, c7, c8 = st.columns(3)
    c6.metric("Najlepszy trade",  f"+{s['max_gain']:.2f}%")
    c7.metric("Najgorszy trade",  f"{s['max_loss']:.2f}%")
    c8.metric("Zysk / strata",    f"${s['final_eq']-capital:+,.0f}")

    # ── Wykresy ────────────────────────────────────────────────────────────────
    df_t   = s["df"]
    equity = s["equity"]
    dates  = [str(d) for d in df_t["Data kupna"]]
    pcts   = df_t["Zmiana %"].tolist()
    colors = ["#1D9E75" if p >= 0 else "#D85A30" for p in pcts]

    fig = make_subplots(
        rows=2, cols=1,
        subplot_titles=("Equity curve", "Wynik każdej transakcji (%)"),
        row_heights=[0.6, 0.4],
        vertical_spacing=0.12,
    )

    # Equity
    fig.add_trace(go.Scatter(
        x=["Start"] + dates, y=equity,
        mode="lines", name="Equity",
        line=dict(color="#378ADD", width=1.5),
        fill="tozeroy", fillcolor="rgba(55,138,221,0.07)",
    ), row=1, col=1)
    fig.add_hline(y=capital, line_dash="dash", line_color="gray",
                  line_width=0.8, opacity=0.5, row=1, col=1)

    # Bar trades
    fig.add_trace(go.Bar(
        x=dates, y=pcts,
        marker_color=colors, name="Trade %",
    ), row=2, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=0.8, row=2, col=1)

    fig.update_layout(
        height=580, showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)",
        paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10),
    )
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")

    st.plotly_chart(fig, use_container_width=True)

    # ── Tabela transakcji ──────────────────────────────────────────────────────
    with st.expander("📋 Historia transakcji", expanded=False):
        display = df_t.drop(columns=["Equity"]).copy()
        display["Zmiana %"] = display["Zmiana %"].apply(
            lambda x: f"+{x:.3f}%" if x >= 0 else f"{x:.3f}%"
        )
        st.dataframe(display, use_container_width=True, hide_index=True)

        csv = df_t.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Pobierz CSV", csv, f"{ticker}_overnight.csv", "text/csv")

else:
    st.info("👈 Ustaw parametry w panelu bocznym i kliknij **Uruchom backtest**.")
