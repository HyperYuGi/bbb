"""
Overnight Backtest — Streamlit App (Alpha Vantage)
Strategia: Kup o HH:MM ET, sprzedaj następnego dnia o HH:MM ET

requirements.txt:
    streamlit
    pandas
    plotly
    requests
"""

import streamlit as st
import requests
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots

st.set_page_config(page_title="Overnight Backtest", page_icon="📈", layout="wide")
st.title("📈 Overnight Backtest")
st.caption("Kup X minut przed zamknięciem → sprzedaj Y minut po otwarciu następnego dnia")

with st.sidebar:
    st.header("⚙️ Ustawienia")

    api_key = st.text_input("Klucz Alpha Vantage API", type="password",
                             help="Darmowy klucz: alphavantage.co/support/#api-key")
    ticker = st.text_input("Ticker", value="MSTR").upper().strip()

    st.subheader("Czas transakcji (ET)")
    col1, col2 = st.columns(2)
    with col1:
        buy_h = st.number_input("Kupno — godz.", min_value=9,  max_value=15, value=15)
        buy_m = st.number_input("Kupno — min.",  min_value=0,  max_value=59, value=45, step=5)
    with col2:
        sell_h = st.number_input("Sprzedaż — godz.", min_value=9,  max_value=16, value=9)
        sell_m = st.number_input("Sprzedaż — min.",  min_value=0,  max_value=59, value=45, step=5)

    buy_time  = f"{buy_h:02d}:{buy_m:02d}"
    sell_time = f"{sell_h:02d}:{sell_m:02d}"

    period_label = st.selectbox("Okres historyczny",
        ["1 miesiąc", "3 miesiące", "6 miesięcy", "1 rok", "2 lata"], index=3)
    slice_map = {
        "1 miesiąc":  [("year1month1",)],
        "3 miesiące": [("year1month1",), ("year1month2",), ("year1month3",)],
        "6 miesięcy": [("year1month1",), ("year1month2",), ("year1month3",),
                       ("year1month4",), ("year1month5",), ("year1month6",)],
        "1 rok":      [(f"year1month{i}",) for i in range(1, 13)],
        "2 lata":     [(f"year1month{i}",) for i in range(1, 13)] +
                      [(f"year2month{i}",) for i in range(1, 13)],
    }

    capital  = st.number_input("Kapitał startowy ($)", min_value=100, value=10_000, step=500)
    comm_pct = st.number_input("Prowizja (%)", min_value=0.0, max_value=2.0,
                                value=0.0, step=0.01)

    run = st.button("▶ Uruchom backtest", type="primary", use_container_width=True)


@st.cache_data(show_spinner=False)
def fetch_intraday(ticker: str, api_key: str, slices: list) -> pd.DataFrame:
    frames = []
    for (sl,) in slices:
        url = (
            "https://www.alphavantage.co/query"
            f"?function=TIME_SERIES_INTRADAY_EXTENDED"
            f"&symbol={ticker}&interval=15min&slice={sl}"
            f"&apikey={api_key}&datatype=csv"
        )
        r = requests.get(url, timeout=30)
        if r.status_code != 200 or r.text.startswith("{"):
            continue
        from io import StringIO
        df = pd.read_csv(StringIO(r.text))
        frames.append(df)
    if not frames:
        return pd.DataFrame()
    data = pd.concat(frames, ignore_index=True)
    data["time"] = pd.to_datetime(data["time"])
    data = data.sort_values("time").reset_index(drop=True)
    return data


def get_prices_at(df: pd.DataFrame, time_str: str) -> dict:
    result = {}
    for _, row in df.iterrows():
        t = row["time"]
        if t.strftime("%H:%M") == time_str:
            result[t.date()] = float(row["close"])
    return result


def run_backtest(df, buy_time, sell_time, capital, comm_pct):
    buys  = get_prices_at(df, buy_time)
    sells = get_prices_at(df, sell_time)
    sell_dates = sorted(sells.keys())
    trades = []
    for buy_date in sorted(buys.keys()):
        sell_date = next((d for d in sell_dates if d > buy_date), None)
        if sell_date is None:
            continue
        buy_price  = buys[buy_date]
        sell_price = sells[sell_date]
        pct = (sell_price - buy_price) / buy_price * 100 - comm_pct * 2
        trades.append({
            "Data kupna":     buy_date,
            "Cena kupna":     round(buy_price, 2),
            "Data sprzedaży": sell_date,
            "Cena sprzedaży": round(sell_price, 2),
            "Zmiana %":       round(pct, 3),
        })
    return pd.DataFrame(trades)


def compute_stats(df_trades, capital):
    pct = df_trades["Zmiana %"]
    wins = (pct > 0).sum()
    n = len(df_trades)
    eq = capital
    equity = [capital]
    for p in pct:
        eq *= (1 + p / 100)
        equity.append(round(eq, 2))
    df_trades = df_trades.copy()
    df_trades["Equity"] = equity[1:]
    peak, max_dd = capital, 0.0
    for e in equity:
        if e > peak: peak = e
        dd = (peak - e) / peak * 100
        if dd > max_dd: max_dd = dd
    return {
        "n": n, "wins": int(wins), "win_rate": wins/n*100,
        "avg_pct": float(pct.mean()), "total_pct": (eq-capital)/capital*100,
        "max_gain": float(pct.max()), "max_loss": float(pct.min()),
        "max_dd": max_dd, "final_eq": eq, "df": df_trades, "equity": equity,
    }


if run:
    if not api_key:
        st.error("Wpisz klucz API Alpha Vantage w panelu bocznym.")
        st.stop()

    slices = slice_map[period_label]
    with st.spinner(f"Pobieranie danych {ticker} ({period_label})..."):
        df = fetch_intraday(ticker, api_key, slices)

    if df.empty:
        st.error("Brak danych — sprawdź ticker i klucz API.")
        st.stop()

    df_trades = run_backtest(df, buy_time, sell_time, capital, comm_pct)
    if df_trades.empty:
        st.warning("Brak transakcji dla podanych godzin. Spróbuj zmienić godziny kupna/sprzedaży.")
        st.stop()

    s = compute_stats(df_trades, capital)

    st.subheader(f"{ticker}  |  kupno {buy_time} → sprzedaż {sell_time} ET  |  {period_label}")

    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric("Wynik łączny",     f"{'+' if s['total_pct']>=0 else ''}{s['total_pct']:.1f}%")
    c2.metric("Kapitał końcowy",  f"${s['final_eq']:,.0f}")
    c3.metric("Win rate",         f"{s['win_rate']:.1f}%", f"{s['wins']}/{s['n']} transakcji")
    c4.metric("Śr. zmiana/trade", f"{s['avg_pct']:+.3f}%")
    c5.metric("Max drawdown",     f"-{s['max_dd']:.1f}%")

    c6, c7, c8 = st.columns(3)
    c6.metric("Najlepszy trade",  f"+{s['max_gain']:.2f}%")
    c7.metric("Najgorszy trade",  f"{s['max_loss']:.2f}%")
    c8.metric("Zysk / strata",    f"${s['final_eq']-capital:+,.0f}")

    df_t   = s["df"]
    equity = s["equity"]
    dates  = [str(d) for d in df_t["Data kupna"]]
    pcts   = df_t["Zmiana %"].tolist()
    colors = ["#1D9E75" if p >= 0 else "#D85A30" for p in pcts]

    fig = make_subplots(rows=2, cols=1,
        subplot_titles=("Equity curve", "Wynik każdej transakcji (%)"),
        row_heights=[0.6, 0.4], vertical_spacing=0.12)

    fig.add_trace(go.Scatter(x=["Start"]+dates, y=equity, mode="lines",
        line=dict(color="#378ADD", width=1.5),
        fill="tozeroy", fillcolor="rgba(55,138,221,0.07)"), row=1, col=1)
    fig.add_hline(y=capital, line_dash="dash", line_color="gray",
                  line_width=0.8, opacity=0.5, row=1, col=1)

    fig.add_trace(go.Bar(x=dates, y=pcts, marker_color=colors), row=2, col=1)
    fig.add_hline(y=0, line_color="gray", line_width=0.8, row=2, col=1)

    fig.update_layout(height=560, showlegend=False,
        plot_bgcolor="rgba(0,0,0,0)", paper_bgcolor="rgba(0,0,0,0)",
        margin=dict(l=10, r=10, t=40, b=10))
    fig.update_xaxes(showgrid=False)
    fig.update_yaxes(gridcolor="rgba(128,128,128,0.15)")
    st.plotly_chart(fig, use_container_width=True)

    with st.expander("📋 Historia transakcji", expanded=False):
        display = df_t.drop(columns=["Equity"]).copy()
        display["Zmiana %"] = display["Zmiana %"].apply(
            lambda x: f"+{x:.3f}%" if x >= 0 else f"{x:.3f}%")
        st.dataframe(display, use_container_width=True, hide_index=True)
        csv = df_t.to_csv(index=False).encode("utf-8")
        st.download_button("⬇ Pobierz CSV", csv, f"{ticker}_overnight.csv", "text/csv")

else:
    st.info("👈 Wpisz klucz API i ustaw parametry w panelu bocznym, następnie kliknij **Uruchom backtest**.")
