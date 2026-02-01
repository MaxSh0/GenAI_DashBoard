import streamlit as st
import plotly.graph_objects as go
import pandas as pd


def _safe_float(x, default=None):
    try:
        v = float(x)
        if pd.isna(v):
            return default
        return v
    except Exception:
        return default


def _metric_color(v):
    v = _safe_float(v, default=None)
    if v is None:
        return "#cfd4da"
    if v > 0.9:
        return "#22c55e"  # green
    if v > 0.6:
        return "#eab308"  # yellow
    return "#ef4444"  # red


def _normalize_columns(df: pd.DataFrame) -> pd.DataFrame:
    if df is None or df.empty:
        return df

    rename_map = {}
    for c in df.columns:
        key = str(c).strip().lower()
        if key in ("threshold",):
            rename_map[c] = "threshold"
        elif key in ("precision",):
            rename_map[c] = "precision"
        elif key in ("recall",):
            rename_map[c] = "recall"
        elif key in ("f1", "f1_score", "f1 score", "f1-score", "f1score"):
            rename_map[c] = "f1"

    df = df.rename(columns=rename_map)
    return df


def render(files):
    if not files:
        return

    dfs = []
    for f_path in files:
        try:
            p = str(f_path).lower()
            if p.endswith(".xlsx") or p.endswith(".xls"):
                dfs.append(pd.read_excel(f_path))
            else:
                dfs.append(pd.read_csv(f_path))
        except Exception:
            pass

    if not dfs:
        return

    df = pd.concat(dfs, ignore_index=True)
    df = _normalize_columns(df)

    required_cols = ["threshold", "precision", "recall", "f1"]
    if any(c not in df.columns for c in required_cols):
        return

    df = df[required_cols].copy()
    df["threshold"] = pd.to_numeric(df["threshold"], errors="coerce")
    for c in ["precision", "recall", "f1"]:
        df[c] = pd.to_numeric(df[c], errors="coerce")
    df = df.dropna(subset=required_cols)

    if df.empty:
        return

    df = df.sort_values("threshold").reset_index(drop=True)

    PRECISION_BLUE = "#1600ff"
    RECALL_PURPLE = "#8b5cf6"
    F1_RED = "#ef4444"
    LIGHT = "#cfd4da"

    t_min = _safe_float(df["threshold"].min())
    t_max = _safe_float(df["threshold"].max())
    if t_min is None or t_max is None:
        return

    col_chart, col_card = st.columns([4, 1], vertical_alignment="top")

    with col_card:
        default_value = _safe_float(df["threshold"].iloc[(len(df) - 1) // 2], default=t_min)
        if t_max > t_min:
            step = float((t_max - t_min) / max(200, (len(df) - 1) or 1))
            if step <= 0:
                step = 0.0001
        else:
            step = 0.0001

        threshold = st.slider(
            "threshold",
            min_value=float(t_min),
            max_value=float(t_max),
            value=float(default_value),
            step=float(step),
            format="%.4f",
            label_visibility="collapsed",
        )

        idx = (df["threshold"] - float(threshold)).abs().idxmin()
        row = df.loc[idx]
        t_sel = _safe_float(row["threshold"], default=float(threshold))
        p_sel = _safe_float(row["precision"], default=0.0)
        r_sel = _safe_float(row["recall"], default=0.0)
        f_sel = _safe_float(row["f1"], default=0.0)

        p_color = _metric_color(p_sel)
        r_color = _metric_color(r_sel)
        f_color = _metric_color(f_sel)

        try:
            from streamlit.components.v1 import html as st_html

            st_html(
                f"""
                <div style="
                    border: 1px solid rgba(207,212,218,0.25);
                    background: rgba(0,0,0,0.25);
                    border-radius: 12px;
                    padding: 14px;
                    margin-top: 10px;
                    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, Ubuntu, Cantarell, 'Helvetica Neue', Arial, 'Noto Sans', 'Liberation Sans', sans-serif;
                ">
                    <div style="display:flex; justify-content:space-between; align-items:baseline;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">Текущий порог</div>
                        <div style="color: {LIGHT}; font-size: 14px; font-weight: 600;">{t_sel:.4f}</div>
                    </div>
                    <div style="height: 10px;"></div>

                    <div style="display:flex; justify-content:space-between;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">Precision</div>
                        <div style="color: {p_color}; font-size: 14px; font-weight: 700;">{p_sel:.4f}</div>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">Recall</div>
                        <div style="color: {r_color}; font-size: 14px; font-weight: 700;">{r_sel:.4f}</div>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">F1</div>
                        <div style="color: {f_color}; font-size: 14px; font-weight: 700;">{f_sel:.4f}</div>
                    </div>
                </div>
                """,
                height=150,
            )
        except Exception:
            st.markdown(
                f"""
                <div style="
                    border: 1px solid rgba(207,212,218,0.25);
                    background: rgba(0,0,0,0.25);
                    border-radius: 12px;
                    padding: 14px;
                    margin-top: 10px;
                ">
                    <div style="display:flex; justify-content:space-between; align-items:baseline;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">Текущий порог</div>
                        <div style="color: {LIGHT}; font-size: 14px; font-weight: 600;">{t_sel:.4f}</div>
                    </div>
                    <div style="height: 10px;"></div>

                    <div style="display:flex; justify-content:space-between;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">Precision</div>
                        <div style="color: {p_color}; font-size: 14px; font-weight: 700;">{p_sel:.4f}</div>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">Recall</div>
                        <div style="color: {r_color}; font-size: 14px; font-weight: 700;">{r_sel:.4f}</div>
                    </div>
                    <div style="display:flex; justify-content:space-between;">
                        <div style="color: rgba(207,212,218,0.9); font-size: 12px;">F1</div>
                        <div style="color: {f_color}; font-size: 14px; font-weight: 700;">{f_sel:.4f}</div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

    with col_chart:
        fig = go.Figure()

        fig.add_trace(
            go.Scatter(
                x=df["threshold"],
                y=df["precision"],
                mode="lines",
                name="precision",
                line=dict(color=PRECISION_BLUE, width=2),
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["threshold"],
                y=df["recall"],
                mode="lines",
                name="recall",
                line=dict(color=RECALL_PURPLE, width=2, dash="dot"),
                opacity=0.95,
            )
        )
        fig.add_trace(
            go.Scatter(
                x=df["threshold"],
                y=df["f1"],
                mode="lines",
                name="f1",
                line=dict(color=F1_RED, width=2),
                opacity=0.95,
            )
        )

        fig.add_vline(
            x=float(t_sel),
            line_width=2,
            line_dash="dash",
            line_color=LIGHT,
            opacity=0.9,
        )

        fig.update_layout(
            template="plotly_dark",
            legend=dict(
                orientation="h",
                yanchor="bottom",
                y=1.02,
                xanchor="left",
                x=0.0,
                bgcolor="rgba(0,0,0,0)",
                font=dict(color=LIGHT, size=12),
            ),
            paper_bgcolor="rgba(0,0,0,0)",
            plot_bgcolor="rgba(0,0,0,0)",
            hovermode="x unified",
        )
        fig.update_layout(margin=dict(l=10, r=10, t=10, b=10))

        fig.update_xaxes(
            title=dict(text="threshold", font=dict(color=LIGHT)),
            showgrid=True,
            gridcolor="rgba(207,212,218,0.18)",
            zeroline=False,
            linecolor="rgba(207,212,218,0.25)",
            tickfont=dict(color=LIGHT),
        )
        fig.update_yaxes(
            title=dict(text="metric", font=dict(color=LIGHT)),
            range=[0, 1],
            showgrid=True,
            gridcolor="rgba(207,212,218,0.18)",
            zeroline=False,
            linecolor="rgba(207,212,218,0.25)",
            tickfont=dict(color=LIGHT),
        )

        st.plotly_chart(fig, use_container_width=True, config={"displayModeBar": False})