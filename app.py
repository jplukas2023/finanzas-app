import os
from datetime import date, datetime
from typing import Tuple

import streamlit as st
import pandas as pd
import altair as alt

# ==== Dependencias externas ====
# pip install streamlit gspread google-auth pandas altair
import gspread
from google.oauth2.service_account import Credentials

# ===============================
# ⚙️ Configuración básica de la app
# ===============================
st.set_page_config(page_title="Gastos & Ingresos — Google Sheets", page_icon="💸", layout="wide")
st.title("💸 Registro de Gastos e Ingresos (Google Sheets)")
st.caption("MVP multiusuario — PC y móvil. Comparte tu hoja con el service account para sincronizar.")

# -------------------------------
# 🔐 Autenticación con Google Sheets
# -------------------------------
def get_gspread_client() -> gspread.Client:
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    sa_info = None

    # 1) Secrets (ideal para Streamlit Cloud)
    if "gcp_service_account" in st.secrets:
        sa_info = dict(st.secrets["gcp_service_account"])  # debe ser un dict

    # 2) Subida manual del JSON
    if sa_info is None:
        with st.sidebar:
            st.subheader("Credenciales Google")
            uploaded = st.file_uploader(
                "Sube tu service_account.json",
                type=["json"],
                accept_multiple_files=False,
            )
        if uploaded is not None:
            import json
            sa_info = json.load(uploaded)

    if sa_info is None:
        st.warning("Sube tu service_account.json en la barra lateral o configura st.secrets['gcp_service_account'].")
        st.stop()

    creds = Credentials.from_service_account_info(sa_info, scopes=scopes)
    return gspread.authorize(creds)


def get_worksheet(gc: gspread.Client, sheet_id: str, ws_title: str) -> gspread.Worksheet:
    sh = gc.open_by_key(sheet_id)
    try:
        ws = sh.worksheet(ws_title)
    except gspread.exceptions.WorksheetNotFound:
        ws = sh.add_worksheet(title=ws_title, rows=1000, cols=12)
        ws.append_row(["id", "fecha", "categoria", "monto", "nota", "tags", "usuario", "ts"])
    headers = ws.row_values(1)
    if not headers:
        ws.update("A1:H1", [["id", "fecha", "categoria", "monto", "nota", "tags", "usuario", "ts"]])
    return ws


def ensure_sheets(gc: gspread.Client, sheet_id: str) -> Tuple[gspread.Worksheet, gspread.Worksheet]:
    gastos_ws = get_worksheet(gc, sheet_id, "gastos")
    ingresos_ws = get_worksheet(gc, sheet_id, "ingresos")
    return gastos_ws, ingresos_ws


# -------------------------------
# 📥 Parámetros en Sidebar
# -------------------------------
with st.sidebar:
    st.header("🔗 Conexión a Google Sheets")

    if "sheet_id" in st.secrets and st.secrets.get("sheet_id"):
        sheet_id = st.secrets.get("sheet_id")
        st.success("Usando Sheet ID desde Secrets (no necesitas pegarlo en el celular)")
        st.caption(f"Sheet conectado: {sheet_id[:6]}…{sheet_id[-4:]}")
    else:
        sheet_id = st.text_input("SHEET ID (de la URL)", value="")
        st.caption("Ejemplo: https://docs.google.com/spreadsheets/d/SELESTEID/edit → copia la parte SELESTEID")
        if not sheet_id:
            st.info("Pega tu Sheet ID para continuar.")

    st.divider()
    st.header("👤 Preferencias de usuario")
    # Leer ?user= o ?u= desde la URL si existe
    qp_user = ""
    try:
        q = st.query_params  # Streamlit recientes
        val = q.get("user") or q.get("u")
        if isinstance(val, list):
            qp_user = val[0] if val else ""
        else:
            qp_user = val or ""
    except Exception:
        try:
            q = st.experimental_get_query_params()  # fallback
            qp_user = (q.get("user") or q.get("u") or [""])[0]
        except Exception:
            qp_user = ""

    default_user = st.text_input(
        "Nombre/Iniciales para registrar (multiusuario)",
        value=(qp_user or ""),
        placeholder="Escribe tu nombre o iniciales",
    )

    st.divider()
    with st.expander("🏷️ Categorías (opcional)", expanded=False):
        st.caption("Editá estas listas solo si querés personalizar; si no, podés ignorarlo.")

        default_gastos = """Comida / Supermercado
Transporte / Gasolina
Vivienda / Renta / Hipoteca
Servicios (agua, luz, internet, tel)
Salud / Medicinas
Educación / Cursos / Libros
Entretenimiento / Streaming / Hobbies
Ropa / Compras personales
Viajes / Vacaciones
Mascotas
Suscripciones / Apps
Mantenimiento del hogar
Regalos / Donaciones
Impuestos / Trámites
Tarjetas / Intereses / Comisiones
Otros
"""

        default_ingresos = """Salario
Freelance / Consultoría
Ventas extra / Negocio
Bonos / Aguinaldo
Intereses / Inversiones
Reembolsos
Otros ingresos
"""

        gastos_list = st.text_area("Gastos (una por línea)", value=default_gastos, height=150)
        ingresos_list = st.text_area("Ingresos (una por línea)", value=default_ingresos, height=120)

    categorias_g = [c.strip() for c in (gastos_list if 'gastos_list' in locals() else "").splitlines() if c.strip()]
    categorias_i = [c.strip() for c in (ingresos_list if 'ingresos_list' in locals() else "").splitlines() if c.strip()]

# Si no hay sheet_id, detener
if not sheet_id:
    st.stop()

# -------------------------------
# 🔌 Conectar a la hoja y asegurar worksheets
# -------------------------------
client = get_gspread_client()
try:
    gastos_ws, ingresos_ws = ensure_sheets(client, sheet_id)
except Exception as e:
    st.error(f"No se pudo abrir la hoja: {e}")
    st.stop()


# -------------------------------
# 🧩 Helpers de IO
# -------------------------------
@st.cache_data(ttl=20)
def load_df_by_name(sheet_id: str, ws_title: str) -> pd.DataFrame:
    try:
        gc = get_gspread_client()
        sh = gc.open_by_key(sheet_id)
        ws = sh.worksheet(ws_title)
        values = ws.get_all_values()
    except Exception:
        values = []

    if not values:
        return pd.DataFrame(columns=["id", "fecha", "categoria", "monto", "nota", "tags", "usuario", "ts"])

    df = pd.DataFrame(values[1:], columns=[c.strip() for c in values[0]])
    if not df.empty:
        if "monto" in df.columns:
            df["monto"] = pd.to_numeric(df["monto"], errors="coerce").fillna(0)
        if "fecha" in df.columns:
            df["fecha"] = pd.to_datetime(df["fecha"], errors="coerce").dt.date
    return df


def next_id(ws_title: str) -> int:
    df = load_df_by_name(sheet_id, ws_title)
    if df.empty:
        return 1
    try:
        return int(pd.to_numeric(df["id"], errors="coerce").fillna(0).max()) + 1
    except Exception:
        return len(df) + 1


def append_row(ws: gspread.Worksheet, row: dict):
    ordered = [row.get(k, "") for k in ["id", "fecha", "categoria", "monto", "nota", "tags", "usuario", "ts"]]
    ws.append_row(ordered, value_input_option="USER_ENTERED")


# -------------------------------
# 🗂️ Tabs principales
# -------------------------------
tab1, tab2, tab3 = st.tabs(["➕ Registrar", "📜 Histórico", "📈 Reportes"])

# ===============================
# ➕ TAB 1: Registrar
# ===============================
with tab1:
    col1, col2 = st.columns(2)

    with col1:
        st.subheader("Gasto rápido")
        with st.form("form_gasto"):
            fecha_g = st.date_input("Fecha", value=date.today())
            cat_g = st.selectbox("Categoría", categorias_g or ["Comida / Supermercado"], index=0)
            monto_g = st.number_input("Monto (Q)", min_value=0.0, step=1.0)
            nota_g = st.text_input("Nota (opcional)")
            tags_g = st.text_input("Tags (separados por coma)")
            submitted_g = st.form_submit_button("Guardar gasto", type="primary")
        if submitted_g:
            if monto_g > 0 and cat_g:
                rid = next_id("gastos")
                append_row(
                    gastos_ws,
                    {
                        "id": rid,
                        "fecha": fecha_g.isoformat(),
                        "categoria": cat_g,
                        "monto": float(monto_g),
                        "nota": nota_g.strip(),
                        "tags": tags_g.strip(),
                        "usuario": default_user.strip(),
                        "ts": datetime.utcnow().isoformat(),
                    },
                )
                st.success(f"Gasto #{rid} guardado ✅")
                load_df_by_name.clear()
            else:
                st.error("Verifica monto (>0) y categoría.")

    with col2:
        st.subheader("Ingreso")
        with st.form("form_ingreso"):
            fecha_i = st.date_input("Fecha", value=date.today(), key="fecha_i")
            cat_i = st.selectbox("Categoría", categorias_i or ["Salario"], index=0, key="cat_i")
            monto_i = st.number_input("Monto (Q)", min_value=0.0, step=1.0, key="monto_i")
            nota_i = st.text_input("Nota (opcional)", key="nota_i")
            tags_i = st.text_input("Tags (separados por coma)", key="tags_i")
            submitted_i = st.form_submit_button("Guardar ingreso", type="primary")
        if submitted_i:
            if monto_i > 0 and cat_i:
                rid = next_id("ingresos")
                append_row(
                    ingresos_ws,
                    {
                        "id": rid,
                        "fecha": fecha_i.isoformat(),
                        "categoria": cat_i,
                        "monto": float(monto_i),
                        "nota": nota_i.strip(),
                        "tags": tags_i.strip(),
                        "usuario": default_user.strip(),
                        "ts": datetime.utcnow().isoformat(),
                    },
                )
                st.success(f"Ingreso #{rid} guardado ✅")
                load_df_by_name.clear()
            else:
                st.error("Verifica monto (>0) y categoría.")

# ===============================
# 📜 TAB 2: Histórico
# ===============================
with tab2:
    st.subheader("Gastos")
    gdf = load_df_by_name(sheet_id, "gastos")
    if gdf.empty:
        st.info("No hay gastos aún.")
    else:
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            min_d = gdf["fecha"].min()
            max_d = gdf["fecha"].max()
            rango = st.date_input("Rango de fechas", value=(min_d, max_d))
        with c2:
            cat_f = st.multiselect("Categorías", sorted(gdf["categoria"].dropna().unique().tolist()), default=[])
        with c3:
            user_f = st.multiselect("Usuarios", sorted(gdf["usuario"].dropna().unique().tolist()), default=[])

        gview = gdf.copy()
        if isinstance(rango, tuple) and len(rango) == 2:
            gview = gview[(gview["fecha"] >= rango[0]) & (gview["fecha"] <= rango[1])]
        if cat_f:
            gview = gview[gview["categoria"].isin(cat_f)]
        if user_f:
            gview = gview[gview["usuario"].isin(user_f)]

        st.dataframe(gview.sort_values("fecha", ascending=False), use_container_width=True)

    st.divider()
    st.subheader("Ingresos")
    idf = load_df_by_name(sheet_id, "ingresos")
    if idf.empty:
        st.info("No hay ingresos aún.")
    else:
        c1, c2, c3 = st.columns([1, 1, 2])
        with c1:
            min_d = idf["fecha"].min()
            max_d = idf["fecha"].max()
            rango2 = st.date_input("Rango de fechas", value=(min_d, max_d), key="rango2")
        with c2:
            cat_f2 = st.multiselect("Categorías", sorted(idf["categoria"].dropna().unique().tolist()), default=[], key="cat_f2")
        with c3:
            user_f2 = st.multiselect("Usuarios", sorted(idf["usuario"].dropna().unique().tolist()), default=[], key="user_f2")

        iview = idf.copy()
        if isinstance(rango2, tuple) and len(rango2) == 2:
            iview = iview[(iview["fecha"] >= rango2[0]) & (iview["fecha"] <= rango2[1])]
        if cat_f2:
            iview = iview[iview["categoria"].isin(cat_f2)]
        if user_f2:
            iview = iview[iview["usuario"].isin(user_f2)]

        st.dataframe(iview.sort_values("fecha", ascending=False), use_container_width=True)

# ===============================
# 📈 TAB 3: Reportes (A, B, C, D, E)
# ===============================
with tab3:
    gdf = load_df_by_name(sheet_id, "gastos")
    idf = load_df_by_name(sheet_id, "ingresos")

    def add_period(df: pd.DataFrame) -> pd.DataFrame:
        if df.empty:
            return df
        out = df.copy()
        out["ym"] = pd.to_datetime(out["fecha"]).dt.to_period("M").astype(str)
        return out

    g = add_period(gdf)
    i = add_period(idf)

    all_months = sorted(set(g.get("ym", pd.Series(dtype=str))) | set(i.get("ym", pd.Series(dtype=str))))

    if not all_months:
        st.info("Aún no hay datos para reportar.")
    else:
        sel_months = st.multiselect("Meses a analizar", all_months, default=all_months[-1:])

        # === Resumen por mes (para KPIs y A) ===
        g_m = (g[g["ym"].isin(sel_months)].groupby("ym")["monto"].sum().reset_index(name="gastos")
               if not g.empty else pd.DataFrame({"ym": sel_months, "gastos": 0.0}))
        i_m = (i[i["ym"].isin(sel_months)].groupby("ym")["monto"].sum().reset_index(name="ingresos")
               if not i.empty else pd.DataFrame({"ym": sel_months, "ingresos": 0.0}))
        resumen = pd.merge(g_m, i_m, on="ym", how="outer").fillna(0).sort_values("ym")
        resumen["balance"] = resumen["ingresos"] - resumen["gastos"]

        c1, c2, c3 = st.columns(3)
        c1.metric("Gastos (selección)", f"Q{resumen['gastos'].sum():,.2f}")
        c2.metric("Ingresos (selección)", f"Q{resumen['ingresos'].sum():,.2f}")
        c3.metric("Balance", f"Q{resumen['balance'].sum():,.2f}")

        # A) Ingreso vs Gasto por mes (ahorro / déficit)
        st.markdown("### A) Ingreso vs Gasto por mes (ahorro / déficit)")

        base = resumen.copy()
        base["gasto_base"] = base[["gastos", "ingresos"]].min(axis=1)          # gasto dentro del ingreso
        base["ahorro"] = (base["ingresos"] - base["gastos"]).clip(lower=0)     # balance positivo
        base["deficit"] = (base["gastos"] - base["ingresos"]).clip(lower=0)    # exceso de gasto

        plot_df = base[["ym", "ingresos", "gasto_base", "ahorro", "deficit"]].rename(
            columns={"gasto_base": "Gasto", "ahorro": "Ahorro (balance +)", "deficit": "Déficit (balance −)"}
        )

        stack = plot_df.melt(
            id_vars=["ym", "ingresos"],
            value_vars=["Gasto", "Ahorro (balance +)", "Déficit (balance −)"],
            var_name="Parte",
            value_name="monto",
        )

        color_scale = alt.Scale(
            domain=["Gasto", "Ahorro (balance +)", "Déficit (balance −)"],
            range=["#ff7f0e", "#2ca02c", "#d62728"]  # naranja, verde, rojo
        )

        bars = (
            alt.Chart(stack)
            .mark_bar()
            .encode(
                x=alt.X("ym:N", title="Mes"),
                y=alt.Y("monto:Q", title="Monto"),
                color=alt.Color("Parte:N", scale=color_scale, title=""),
                tooltip=[
                    alt.Tooltip("ym:N", title="Mes"),
                    alt.Tooltip("Parte:N"),
                    alt.Tooltip("monto:Q", title="Monto", format=",.2f"),
                    alt.Tooltip("ingresos:Q", title="Ingreso (100%)", format=",.2f"),
                ],
            )
            .properties(height=320)
        )

        # Línea discontinua al nivel del ingreso (100%)
        ing_rule = (
            alt.Chart(plot_df)
            .mark_rule(color="#2ca02c", strokeDash=[4, 4])
            .encode(x="ym:N", y=alt.Y("ingresos:Q", title=""))
        )

        st.altair_chart(bars + ing_rule, use_container_width=True)

        # B) Distribución por categoría (gastos e ingresos)
        st.markdown("### B) Distribución por categoría")
        col1, col2 = st.columns(2)

        g_cat = (g[g["ym"].isin(sel_months)].groupby("categoria")["monto"].sum().reset_index()
                 if not g.empty else pd.DataFrame(columns=["categoria", "monto"]))
        i_cat = (i[i["ym"].isin(sel_months)].groupby("categoria")["monto"].sum().reset_index()
                 if not i.empty else pd.DataFrame(columns=["categoria", "monto"]))

        if not g_cat.empty:
            g_cat["pct"] = (g_cat["monto"] / g_cat["monto"].sum() * 100).fillna(0)
        if not i_cat.empty:
            i_cat["pct"] = (i_cat["monto"] / i_cat["monto"].sum() * 100).fillna(0)

        with col1:
            st.caption("Gastos por categoría")
            if g_cat.empty:
                st.info("Sin datos")
            else:
                st.altair_chart(
                    alt.Chart(g_cat)
                    .mark_arc(innerRadius=50)  # donut
                    .encode(
                        theta="monto:Q",
                        color="categoria:N",
                        tooltip=["categoria",
                                 alt.Tooltip("monto:Q", title="Monto", format=",.0f"),
                                 alt.Tooltip("pct:Q", title="%", format=".1f")],
                    )
                    .properties(height=320),
                    use_container_width=True,
                )

        with col2:
            st.caption("Ingresos por categoría")
            if i_cat.empty:
                st.info("Sin datos")
            else:
                st.altair_chart(
                    alt.Chart(i_cat)
                    .mark_arc(innerRadius=50)
                    .encode(
                        theta="monto:Q",
                        color="categoria:N",
                        tooltip=["categoria",
                                 alt.Tooltip("monto:Q", title="Monto", format=",.0f"),
                                 alt.Tooltip("pct:Q", title="%", format=".1f")],
                    )
                    .properties(height=320),
                    use_container_width=True,
                )

        # C) Tendencia (línea, últimos N meses)
        st.markdown("### C) Tendencia (línea, últimos N meses)")
        trend_window = st.selectbox("Rango de meses", [6, 12], index=0, format_func=lambda x: f"Últimos {x} meses")

        months_line = sorted(set(g.get("ym", pd.Series(dtype=str))) | set(i.get("ym", pd.Series(dtype=str))))
        trend_sel = months_line[-trend_window:] if len(months_line) > trend_window else months_line

        tg = (g[g["ym"].isin(trend_sel)].groupby("ym")["monto"].sum().reset_index(name="gastos")
              if not g.empty else pd.DataFrame({"ym": trend_sel, "gastos": 0.0}))
        ti = (i[i["ym"].isin(trend_sel)].groupby("ym")["monto"].sum().reset_index(name="ingresos")
              if not i.empty else pd.DataFrame({"ym": trend_sel, "ingresos": 0.0}))

        tdf = pd.merge(tg, ti, on="ym", how="outer").fillna(0).sort_values("ym")
        line_long = pd.melt(tdf, id_vars=["ym"], value_vars=["gastos", "ingresos"], var_name="tipo", value_name="monto")

        line_chart = alt.Chart(line_long).mark_line(point=True).encode(
            x=alt.X("ym:N", title="Mes"),
            y=alt.Y("monto:Q", title="Monto"),
            color=alt.Color("tipo:N", title=""),
            tooltip=["ym", "tipo", alt.Tooltip("monto:Q", format=",.0f")],
        )
        line_labels = alt.Chart(line_long).mark_text(align="center", dy=-10).encode(
            x="ym:N", y="monto:Q", text=alt.Text("monto:Q", format=",.0f"), color="tipo:N",
        )
        st.altair_chart(line_chart + line_labels, use_container_width=True)

        # C2) Balance mensual (barras)
        st.markdown("### C2) Balance mensual (barras)")
        balance_df = tdf.copy()
        balance_df["balance"] = balance_df["ingresos"] - balance_df["gastos"]

        bar = alt.Chart(balance_df).mark_bar().encode(
            x=alt.X("ym:N", title="Mes"),
            y=alt.Y("balance:Q", title="Balance (ingresos − gastos)"),
            color=alt.condition(alt.datum.balance >= 0, alt.value("#2ca02c"), alt.value("#d62728")),
            tooltip=["ym", alt.Tooltip("balance:Q", format=",.0f")],
        ).properties(height=300)
        bar_labels = alt.Chart(balance_df).mark_text(dy=-5).encode(
            x="ym:N", y="balance:Q", text=alt.Text("balance:Q", format=",.0f"),
        )
        st.altair_chart(bar + bar_labels, use_container_width=True)

        # D) Top categorías / tags
        st.markdown("### D) Top categorías / tags")
        g_cat2 = (g[g["ym"].isin(sel_months)].groupby("categoria")["monto"].sum().reset_index()
                  if not g.empty else pd.DataFrame(columns=["categoria", "monto"]))
        g_tags = g[g["ym"].isin(sel_months)].copy()
        if not g_tags.empty:
            g_tags["tags"] = g_tags["tags"].fillna("")
            exploded = []
            for _, r in g_tags.iterrows():
                parts = [t.strip() for t in str(r.get("tags", "")).split(",") if t.strip()]
                for t in parts:
                    exploded.append({"tag": t, "monto": r["monto"], "categoria": r["categoria"], "ym": r["ym"]})
            tags_df = pd.DataFrame(exploded)
        else:
            tags_df = pd.DataFrame(columns=["tag", "monto", "categoria", "ym"])

        colA, colB = st.columns(2)
        with colA:
            st.caption("Top categorías (gastos)")
            top_cat = g_cat2.sort_values("monto", ascending=False).head(10)
            st.dataframe(top_cat, use_container_width=True)
        with colB:
            st.caption("Top tags (gastos)")
            if tags_df.empty:
                st.info("Sin tags en los meses seleccionados")
            else:
                top_tags = tags_df.groupby("tag")["monto"].sum().reset_index().sort_values("monto", ascending=False).head(10)
                st.dataframe(top_tags, use_container_width=True)

        # E) Comparar mes actual vs anterior
        st.markdown("### E) Comparar mes actual vs anterior")
        if len(all_months) >= 2:
            last_m = all_months[-1]; prev_m = all_months[-2]
            g_last = g[g["ym"] == last_m]["monto"].sum(); g_prev = g[g["ym"] == prev_m]["monto"].sum()
            i_last = i[i["ym"] == last_m]["monto"].sum(); i_prev = i[i["ym"] == prev_m]["monto"].sum()
            bc1, bc2, bc3 = st.columns(3)
            bc1.metric(f"Gasto {last_m}", f"Q{g_last:,.2f}", delta=f"{(g_last - g_prev):+.2f}")
            bc2.metric(f"Ingreso {last_m}", f"Q{i_last:,.2f}", delta=f"{(i_last - i_prev):+.2f}")
            bc3.metric(f"Balance {last_m}", f"Q{(i_last - g_last):,.2f}", delta=f"{(i_last - g_last) - (i_prev - g_prev):+.2f}")
        else:
            st.info("Registra al menos dos meses para comparar.")

        st.markdown("### Exportar")
        st.download_button(
            "⬇️ Descargar resumen.csv",
            data=resumen.to_csv(index=False).encode("utf-8"),
            file_name="resumen.csv",
            mime="text/csv",
        )

st.caption("Hecho con ❤️ con Streamlit + Google Sheets. Moneda: Q. Multiusuario por columna 'usuario'.")
