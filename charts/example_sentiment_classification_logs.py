import streamlit as st
import plotly.express as px
import pandas as pd


def render(files):
    if not files:
        return

    dfs = []
    for f_path in files:
        try:
            path = str(f_path)
            if path.lower().endswith(".xlsx"):
                dfs.append(pd.read_excel(f_path))
            else:
                dfs.append(pd.read_csv(f_path))
        except Exception:
            pass

    if not dfs:
        return

    df = pd.concat(dfs, ignore_index=True)

    required_cols = {"Review_ID", "True_Label", "Predicted_Label", "Source"}
    missing = required_cols - set(df.columns)
    if missing:
        st.error(f"Отсутствуют колонки: {', '.join(sorted(missing))}")
        return

    df = df.copy()
    df["True_Label"] = df["True_Label"].astype(str).fillna("Unknown")
    df["Predicted_Label"] = df["Predicted_Label"].astype(str).fillna("Unknown")

    st.subheader("Матрица ошибок (Confusion Matrix)")

    mode = st.selectbox(
        "Отображение значений",
        ["Абсолютные значения", "Проценты (Normalized)"],
        index=0,
    )

    labels = sorted(set(df["True_Label"].unique()).union(set(df["Predicted_Label"].unique())))
    if not labels:
        return

    cm = pd.crosstab(df["True_Label"], df["Predicted_Label"]).reindex(index=labels, columns=labels, fill_value=0)

    if mode == "Проценты (Normalized)":
        cm_norm = cm.div(cm.sum(axis=1).replace(0, pd.NA), axis=0).fillna(0.0) * 100.0
        z = cm_norm.values
        text = cm_norm.round(1).astype(str) + "%"
        zmax = 100.0
        colorbar_title = "%"
    else:
        z = cm.values
        text = cm.astype(int).astype(str)
        zmax = float(cm.values.max()) if cm.values.size else 0.0
        colorbar_title = "Count"

    # Darker red scale for better contrast with white text on dark background
    dark_red_scale = [
        [0.0, "#231F20"],
        [0.12, "#2b0b0d"],
        [0.28, "#3a0d10"],
        [0.45, "#5a0f14"],
        [0.62, "#7a1118"],
        [0.78, "#a0141d"],
        [0.90, "#c01721"],
        [1.0, "#EE1C25"],
    ]

    fig = px.imshow(
        z,
        x=labels,
        y=labels,
        color_continuous_scale=dark_red_scale,
        zmin=0,
        zmax=zmax if zmax > 0 else None,
        aspect="auto",
        text_auto=False,
    )

    fig.update_traces(
        text=text,
        texttemplate="%{text}",
        textfont=dict(color="#eae7e7", size=12),
        hovertemplate="True: %{y}<br>Pred: %{x}<br>Value: %{z}<extra></extra>",
    )

    fig.update_layout(
        template="plotly_dark",
        title=dict(
            text="Confusion Matrix: True Label vs Predicted Label",
            font=dict(size=16, color="#eae7e7"),
            x=0.0,
            xanchor="left",
        ),
        paper_bgcolor="#231F20",
        plot_bgcolor="#231F20",
    )
    fig.update_layout(margin=dict(l=60, r=20, t=60, b=60))

    fig.update_layout(
        coloraxis_colorbar=dict(
            title=dict(text=colorbar_title, font=dict(size=12, color="#eae7e7")),
            tickfont=dict(size=11, color="#eae7e7"),
            outlinecolor="rgba(234,231,231,0.35)",
            outlinewidth=1,
        )
    )

    fig.update_xaxes(
        title=dict(text="Predicted Label", font=dict(size=13, color="#eae7e7")),
        tickfont=dict(size=12, color="#eae7e7"),
        showgrid=True,
        gridcolor="rgba(234,231,231,0.18)",
        zeroline=False,
        showline=True,
        linecolor="rgba(234,231,231,0.35)",
        linewidth=1,
        ticks="outside",
        tickcolor="rgba(234,231,231,0.35)",
    )
    fig.update_yaxes(
        title=dict(text="True Label", font=dict(size=13, color="#eae7e7")),
        tickfont=dict(size=12, color="#eae7e7"),
        showgrid=True,
        gridcolor="rgba(234,231,231,0.18)",
        zeroline=False,
        showline=True,
        linecolor="rgba(234,231,231,0.35)",
        linewidth=1,
        ticks="outside",
        tickcolor="rgba(234,231,231,0.35)",
    )

    st.plotly_chart(fig, use_container_width=True)

    with st.expander("Сводка качества по классам", expanded=False):
        diag = pd.Series({lbl: int(cm.loc[lbl, lbl]) if lbl in cm.index and lbl in cm.columns else 0 for lbl in labels})
        support = cm.sum(axis=1).astype(int)
        predicted_total = cm.sum(axis=0).astype(int)

        recall = (diag / support.replace(0, pd.NA)).fillna(0.0)
        precision = (diag / predicted_total.replace(0, pd.NA)).fillna(0.0)
        f1 = (2 * precision * recall / (precision + recall).replace(0, pd.NA)).fillna(0.0)

        summary = pd.DataFrame(
            {
                "Support (True)": support,
                "Predicted Total": predicted_total,
                "TP (Diagonal)": diag,
                "Recall": (recall * 100).round(1),
                "Precision": (precision * 100).round(1),
                "F1": (f1 * 100).round(1),
            }
        ).loc[labels]

        st.dataframe(summary, use_container_width=True)

        if len(labels) >= 2:
            worst_recall = summary.sort_values(["Recall", "Support (True)"], ascending=[True, False]).head(min(5, len(labels)))
            st.caption("Классы, распознаваемые хуже всего (по Recall):")
            st.dataframe(worst_recall, use_container_width=True)

        if "Позитив" in labels and "Негатив" in labels:
            pos_as_neg = int(cm.loc["Позитив", "Негатив"]) if "Позитив" in cm.index and "Негатив" in cm.columns else 0
            neg_as_pos = int(cm.loc["Негатив", "Позитив"]) if "Негатив" in cm.index and "Позитив" in cm.columns else 0
            st.caption(f'Путаница "Позитив" ↔ "Негатив": Позитив→Негатив = {pos_as_neg}, Негатив→Позитив = {neg_as_pos}')