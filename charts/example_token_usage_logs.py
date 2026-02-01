import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def render(files):
    if not files:
        return

    dfs = []
    for f_path in files:
        try:
            p = str(f_path)
            if p.lower().endswith(".xlsx"):
                dfs.append(pd.read_excel(f_path))
            else:
                dfs.append(pd.read_csv(f_path))
        except Exception:
            pass

    if not dfs:
        return

    df = pd.concat(dfs, ignore_index=True)

    required = {"Timestamp", "Model_Name", "Total_Tokens", "Latency_Seconds", "Cost_USD"}
    missing = [c for c in required if c not in df.columns]
    if missing:
        st.warning(f"Missing required columns: {', '.join(missing)}")
        return

    # Coerce types
    df["Timestamp"] = pd.to_datetime(df["Timestamp"], errors="coerce")
    df["Model_Name"] = df["Model_Name"].astype(str).fillna("Unknown")
    df["Total_Tokens"] = pd.to_numeric(df["Total_Tokens"], errors="coerce")
    df["Latency_Seconds"] = pd.to_numeric(df["Latency_Seconds"], errors="coerce")
    df["Cost_USD"] = pd.to_numeric(df["Cost_USD"], errors="coerce")

    # Basic cleaning
    df = df[
        df["Total_Tokens"].notna()
        & df["Latency_Seconds"].notna()
        & (df["Total_Tokens"] >= 0)
        & (df["Latency_Seconds"] >= 0)
    ].copy()

    if df.empty:
        st.info("No valid rows to display.")
        return

    st.subheader("Latency vs Total Tokens — anomaly detection")

    # Controls
    models = sorted(df["Model_Name"].dropna().unique().tolist())
    default_models = [m for m in models if ("gpt-4o" in m.lower() or "gemini" in m.lower())]
    if not default_models:
        default_models = models[: min(2, len(models))]

    selected_models = st.multiselect(
        "Model Name",
        options=models,
        default=default_models if default_models else models,
    )
    if selected_models:
        df = df[df["Model_Name"].isin(selected_models)].copy()

    if df.empty:
        st.info("No data after model filter.")
        return

    if df["Timestamp"].notna().any():
        dmin = df["Timestamp"].min()
        dmax = df["Timestamp"].max()
        if pd.notna(dmin) and pd.notna(dmax):
            start_date, end_date = st.slider(
                "Date Range",
                min_value=dmin.date(),
                max_value=dmax.date(),
                value=(dmin.date(), dmax.date()),
            )
            start_ts = pd.Timestamp(start_date)
            end_ts = pd.Timestamp(end_date) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)
            df = df[(df["Timestamp"] >= start_ts) & (df["Timestamp"] <= end_ts)].copy()

    if df.empty:
        st.info("No data after date filter.")
        return

    # Palette (strict)
    primary = "#EE1C25"
    secondary = "#231F20"
    accent = "#eae7e7"

    def _model_color(m: str) -> str:
        ml = (m or "").lower()
        if "gpt-4o" in ml or "gpt4o" in ml or "gpt-4" in ml:
            return primary
        if "gemini" in ml:
            return accent
        return secondary

    color_map = {m: _model_color(m) for m in models}

    # Trendline (overall) via linear regression
    x = df["Total_Tokens"].astype(float)
    y = df["Latency_Seconds"].astype(float)
    valid = x.notna() & y.notna()
    x = x[valid]
    y = y[valid]

    trend_x = None
    trend_y = None
    if len(x) >= 2 and x.nunique() >= 2:
        try:
            x_var = x.var()
            if pd.notna(x_var) and x_var != 0:
                cov_yx = y.cov(x)
                m = cov_yx / x_var
                b = y.mean() - m * x.mean()
                trend_x = pd.Series([x.min(), x.max()])
                trend_y = m * trend_x + b
        except Exception:
            trend_x = None
            trend_y = None

    fig = px.scatter(
        df,
        x="Total_Tokens",
        y="Latency_Seconds",
        color="Model_Name",
        size="Cost_USD",
        size_max=28,
        color_discrete_map=color_map,
        hover_data={
            "Timestamp": True,
            "Model_Name": True,
            "Total_Tokens": True,
            "Latency_Seconds": True,
            "Cost_USD": True,
        },
        template="plotly_dark",
    )

    if trend_x is not None and trend_y is not None:
        fig.add_trace(
            go.Scatter(
                x=trend_x.tolist(),
                y=trend_y.tolist(),
                mode="lines",
                name="Trend",
                line=dict(color=primary, width=2),
                opacity=0.9,
            )
        )

    fig.update_traces(
        marker=dict(
            line=dict(color=accent, width=0.6),
            opacity=0.85,
        ),
        selector=dict(mode="markers"),
    )

    fig.update_layout(
        title=dict(
            text="Latency vs Total Tokens (bubble size = Cost USD)",
            font=dict(size=16, color=accent),
            x=0.01,
            xanchor="left",
        ),
        legend=dict(
            title=dict(text="Model", font=dict(size=12, color=accent)),
            font=dict(size=11, color=accent),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(0,0,0,0)",
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0.01,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(margin=dict(l=40, r=20, t=70, b=45))

    fig.update_xaxes(
        title=dict(text="Total Tokens", font=dict(size=13, color=accent)),
        showgrid=True,
        gridcolor="rgba(234,231,231,0.18)",
        zeroline=False,
        linecolor="rgba(234,231,231,0.25)",
        tickfont=dict(size=11, color=accent),
    )
    fig.update_yaxes(
        title=dict(text="Latency (sec)", font=dict(size=13, color=accent)),
        showgrid=True,
        gridcolor="rgba(234,231,231,0.18)",
        zeroline=False,
        linecolor="rgba(234,231,231,0.25)",
        tickfont=dict(size=11, color=accent),
    )

    st.plotly_chart(fig, use_container_width=True)