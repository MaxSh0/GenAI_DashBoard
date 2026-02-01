import streamlit as st
import plotly.express as px
import pandas as pd


def render(files):
    if not files:
        return

    dfs = []
    for f_path in files:
        try:
            if str(f_path).lower().endswith(".xlsx"):
                dfs.append(pd.read_excel(f_path))
            else:
                dfs.append(pd.read_csv(f_path))
        except Exception:
            pass

    if not dfs:
        return

    df = pd.concat(dfs, ignore_index=True)

    required_cols = [
        "User_ID",
        "Date",
        "City",
        "Country",
        "Latitude",
        "Longitude",
        "Sentiment",
        "Message_Full",
        "Message_Preview",
    ]
    for c in required_cols:
        if c not in df.columns:
            df[c] = None

    df["Date"] = pd.to_datetime(df["Date"], errors="coerce", utc=True).dt.tz_convert(None)
    df["Latitude"] = pd.to_numeric(df["Latitude"], errors="coerce")
    df["Longitude"] = pd.to_numeric(df["Longitude"], errors="coerce")

    df["City"] = df["City"].fillna("").astype(str)
    df["Country"] = df["Country"].fillna("").astype(str)
    df["User_ID"] = df["User_ID"].fillna("").astype(str)
    df["Sentiment"] = df["Sentiment"].fillna("Unknown").astype(str)

    def _preview_fast(message_preview, message_full):
        if isinstance(message_preview, str):
            mp = message_preview.strip()
            if mp:
                return mp[:100]
        if isinstance(message_full, str):
            mf = message_full.strip()
            if mf:
                return mf[:100]
        return ""

    df["Message_Preview_100"] = [
        _preview_fast(mp, mf) for mp, mf in zip(df["Message_Preview"].tolist(), df["Message_Full"].tolist())
    ]

    df_valid = df.dropna(subset=["Latitude", "Longitude", "Date"]).copy()
    if df_valid.empty:
        st.info("Нет данных с валидными координатами и датой для отображения.")
        return

    st.subheader("Глобальное распределение пользователей и контент сообщений")

    min_date = df_valid["Date"].min().date()
    max_date = df_valid["Date"].max().date()

    c1, c2, c3 = st.columns([2, 1, 1], vertical_alignment="bottom")

    with c1:
        date_range = st.slider(
            "Диапазон дат",
            min_value=min_date,
            max_value=max_date,
            value=(min_date, max_date),
        )

    with c2:
        countries = sorted([c for c in df_valid["Country"].dropna().astype(str).unique().tolist() if c.strip()])
        focus_options = ["Все страны"] + countries
        focus_country = st.selectbox("Фокус: страна", options=focus_options, index=0)

    with c3:
        max_points = st.number_input(
            "Макс. точек на карте",
            min_value=500,
            max_value=200000,
            value=20000,
            step=5000,
            help="Ограничение количества точек для ускорения отрисовки. При превышении будет выполнена выборка.",
        )

    start_dt = pd.to_datetime(date_range[0])
    end_dt = pd.to_datetime(date_range[1]) + pd.Timedelta(days=1) - pd.Timedelta(microseconds=1)

    mask = (df_valid["Date"] >= start_dt) & (df_valid["Date"] <= end_dt)
    if focus_country != "Все страны":
        mask &= df_valid["Country"].astype(str) == focus_country

    dff = df_valid.loc[mask].copy()
    if dff.empty:
        st.warning("Нет данных за выбранный период/фильтр.")
        return

    if len(dff) > int(max_points):
        dff = dff.sample(n=int(max_points), random_state=42).copy()
        st.caption(f"Показана выборка {len(dff):,} точек из {mask.sum():,} для ускорения карты.")

    dff["Location"] = (dff["City"].str.strip() + ", " + dff["Country"].str.strip()).str.strip(", ").replace("", "—")
    dff["Date_str"] = dff["Date"].dt.strftime("%Y-%m-%d %H:%M")

    sentiment_order = ["Positive", "Neutral", "Negative", "Mixed", "Unknown"]
    present = [s for s in sentiment_order if s in set(dff["Sentiment"].unique())]
    others = sorted([s for s in dff["Sentiment"].unique().tolist() if s not in set(sentiment_order)])
    categories = present + others
    dff["Sentiment"] = pd.Categorical(dff["Sentiment"], categories=categories, ordered=True)

    color_map = {cat: "#1600ff" for cat in categories}
    color_map.update(
        {
            "Neutral": "#9aa0a6",
            "Positive": "#2ecc71",
            "Negative": "#e74c3c",
        }
    )

    hover_cols = ["Location", "Message_Preview_100", "Date_str", "Sentiment"]
    customdata = dff[hover_cols].to_numpy()

    fig = px.scatter_geo(
        dff,
        lat="Latitude",
        lon="Longitude",
        color="Sentiment",
        color_discrete_map=color_map,
        projection="natural earth",
        hover_name="User_ID",
    )

    fig.update_traces(
        customdata=customdata,
        marker=dict(size=6, opacity=0.85, line=dict(width=0)),
        hovertemplate=(
            "<b>User:</b> %{hovertext}<br>"
            "<b>Location:</b> %{customdata[0]}<br>"
            "<b>Date:</b> %{customdata[2]}<br>"
            "<b>Sentiment:</b> %{customdata[3]}<br>"
            "<b>Message:</b> %{customdata[1]}<extra></extra>"
        ),
    )

    fig.update_layout(
        template="plotly_dark",
        title=dict(
            text="",
            font=dict(size=16, color="#cfd4da"),
            x=0.01,
            xanchor="left",
        ),
        legend=dict(
            title=dict(text="Sentiment", font=dict(size=12, color="#cfd4da")),
            font=dict(size=11, color="#cfd4da"),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(207,212,218,0.25)",
            borderwidth=1,
            orientation="h",
            yanchor="bottom",
            y=1.02,
            xanchor="left",
            x=0.01,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    fig.update_layout(margin=dict(l=10, r=10, t=60, b=10))

    fig.update_geos(
        showland=True,
        landcolor="rgba(0,0,0,0)",
        showcountries=True,
        countrycolor="rgba(207,212,218,0.35)",
        showcoastlines=True,
        coastlinecolor="rgba(207,212,218,0.25)",
        showocean=True,
        oceancolor="rgba(0,0,0,0)",
        showlakes=True,
        lakecolor="rgba(0,0,0,0)",
        bgcolor="rgba(0,0,0,0)",
        lataxis=dict(showgrid=False),
        lonaxis=dict(showgrid=False),
    )

    if focus_country != "Все страны" and len(dff) >= 2:
        lat_min = float(dff["Latitude"].min())
        lat_max = float(dff["Latitude"].max())
        lon_min = float(dff["Longitude"].min())
        lon_max = float(dff["Longitude"].max())

        lat_pad = max((lat_max - lat_min) * 0.15, 1.0)
        lon_pad = max((lon_max - lon_min) * 0.15, 1.0)

        lat_range = [max(-90.0, lat_min - lat_pad), min(90.0, lat_max + lat_pad)]
        lon_range = [max(-180.0, lon_min - lon_pad), min(180.0, lon_max + lon_pad)]

        fig.update_geos(
            center=dict(lat=(lat_min + lat_max) / 2.0, lon=(lon_min + lon_max) / 2.0),
            lataxis=dict(range=lat_range, showgrid=False),
            lonaxis=dict(range=lon_range, showgrid=False),
        )

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Сводка по выбранному фильтру", expanded=False):
        total_msgs = int(len(dff))
        unique_users = int(dff["User_ID"].nunique(dropna=True))
        top_countries = (
            dff["Country"]
            .replace("", "—")
            .value_counts(dropna=False)
            .head(10)
            .rename_axis("Country")
            .reset_index(name="Messages")
        )
        st.write(
            {
                "messages": total_msgs,
                "unique_users": unique_users,
                "date_from": str(date_range[0]),
                "date_to": str(date_range[1]),
                "focus_country": focus_country,
                "points_on_map": total_msgs,
            }
        )
        st.dataframe(top_countries, use_container_width=True)