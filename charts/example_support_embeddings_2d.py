import streamlit as st
import plotly.express as px
import pandas as pd


def render(files):
    if not files:
        return

    dfs = []
    for f_path in files:
        try:
            f_path_str = str(f_path)
            if f_path_str.lower().endswith(".xlsx"):
                dfs.append(pd.read_excel(f_path))
            else:
                dfs.append(pd.read_csv(f_path))
        except Exception:
            pass

    if not dfs:
        return

    df = pd.concat(dfs, ignore_index=True)

    required_cols = ["Ticket_ID", "Original_Text", "Category", "Cluster_Label", "x", "y"]
    missing = [c for c in required_cols if c not in df.columns]
    if missing:
        st.warning(f"Missing required columns: {', '.join(missing)}")
        return

    df = df.copy()
    df["Category"] = df["Category"].astype(str).fillna("Unknown")
    df["Original_Text"] = df["Original_Text"].astype(str).fillna("")
    df["Ticket_ID"] = df["Ticket_ID"].astype(str).fillna("")
    df["Cluster_Label"] = df["Cluster_Label"].astype(str).fillna("Unknown")
    df["x"] = pd.to_numeric(df["x"], errors="coerce")
    df["y"] = pd.to_numeric(df["y"], errors="coerce")
    df = df.dropna(subset=["x", "y"])
    if df.empty:
        st.info("No valid points to display (x/y are empty after cleaning).")
        return

    categories = sorted(df["Category"].dropna().unique().tolist())
    category_options = ["All"] + categories
    selected_category = st.selectbox("Category filter", options=category_options, index=0)

    if selected_category != "All":
        df = df[df["Category"] == selected_category].copy()
        if df.empty:
            st.info("No data for selected category.")
            return

    df["Cluster_ID"] = df["Cluster_Label"].astype(str)

    cluster_values = sorted(df["Cluster_ID"].unique().tolist(), key=lambda v: (len(v), v))
    n_clusters = len(cluster_values)

    # Ensure every cluster gets a distinct color (up to the palette size).
    # For large N, use a continuous colorscale sampled into N distinct colors.
    if n_clusters <= 24:
        palette = px.colors.qualitative.Dark24
    else:
        palette = px.colors.sample_colorscale("Turbo", [i / max(n_clusters - 1, 1) for i in range(n_clusters)])

    color_map = {c: palette[i] for i, c in enumerate(cluster_values)}

    fig = px.scatter(
        df,
        x="x",
        y="y",
        color="Cluster_ID",
        color_discrete_map=color_map,
        hover_data={
            "Ticket_ID": True,
            "Category": True,
            "Original_Text": True,
            "x": False,
            "y": False,
            "Cluster_ID": True,
        },
        template="plotly_dark",
    )

    fig.update_traces(
        marker=dict(size=8, opacity=0.9, line=dict(width=0.6, color="#cfd4da")),
        selector=dict(mode="markers"),
    )

    fig.update_layout(
        title=dict(
            text="Semantic Similarity Map (2D projection)",
            font=dict(size=16, color="#cfd4da"),
            x=0.0,
            xanchor="left",
        ),
        legend=dict(
            title=dict(text="Cluster ID", font=dict(size=12, color="#cfd4da")),
            font=dict(size=11, color="#cfd4da"),
            bgcolor="rgba(0,0,0,0)",
            bordercolor="rgba(207,212,218,0.25)",
            borderwidth=1,
        ),
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        hoverlabel=dict(
            bgcolor="#000000",
            bordercolor="rgba(207,212,218,0.35)",
            font=dict(color="#cfd4da", size=12),
        ),
    )
    fig.update_layout(margin=dict(l=20, r=20, t=60, b=20))

    fig.update_xaxes(
        title=dict(text="Dim 1", font=dict(size=12, color="#cfd4da")),
        showgrid=True,
        gridcolor="rgba(207,212,218,0.18)",
        zeroline=False,
        showline=True,
        linecolor="rgba(207,212,218,0.25)",
        ticks="outside",
        tickcolor="rgba(207,212,218,0.25)",
        tickfont=dict(size=11, color="#cfd4da"),
    )
    fig.update_yaxes(
        title=dict(text="Dim 2", font=dict(size=12, color="#cfd4da")),
        showgrid=True,
        gridcolor="rgba(207,212,218,0.18)",
        zeroline=False,
        showline=True,
        linecolor="rgba(207,212,218,0.25)",
        ticks="outside",
        tickcolor="rgba(207,212,218,0.25)",
        tickfont=dict(size=11, color="#cfd4da"),
    )

    st.plotly_chart(fig, use_container_width=True)