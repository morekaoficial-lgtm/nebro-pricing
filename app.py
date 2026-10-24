#!/usr/bin/env python3
"""
Calculadora de Listas de Precios — NEBRO SHOP
Conecta con nebro-shop para obtener costos y calcular listas de precios
Sistema de listas FIJAS sobre costo (octubre 2026) — Mayoreo A mantiene su cálculo original
Reglas especiales (oct-2026): Público ×3 si costo < $50; svip = costo + $1 ($1–$199) o + $5 (≥ $200)
"""

import streamlit as st
import pandas as pd
import requests
from datetime import datetime
import os
import time

# ============================================================
# CONFIGURACIÓN DE SHOPIFY — NEBRO SHOP
# ============================================================
SHOPIFY_TOKEN = st.secrets.get("nebro", {}).get("SHOPIFY_ACCESS_TOKEN",
    os.getenv("NEBRO_SHOPIFY_ACCESS_TOKEN"))
SHOPIFY_SHOP = st.secrets.get("nebro", {}).get("SHOPIFY_SHOP",
    os.getenv("NEBRO_SHOPIFY_SHOP", "nebro-shop"))
SHOPIFY_API_VERSION = "2025-01"
SHOPIFY_BASE_URL = f"https://{SHOPIFY_SHOP}.myshopify.com/admin/api/{SHOPIFY_API_VERSION}"
SHOPIFY_HEADERS = {"X-Shopify-Access-Token": SHOPIFY_TOKEN}

# Rate limiting: 2 requests por segundo para evitar 429
LAST_REQUEST_TIME = 0
MIN_REQUEST_INTERVAL = 0.5

def shopify_request(url, headers=None, timeout=30):
    """Hace request a Shopify con rate limiting de 2 req/s"""
    global LAST_REQUEST_TIME
    headers = headers or SHOPIFY_HEADERS
    elapsed = time.time() - LAST_REQUEST_TIME
    if elapsed < MIN_REQUEST_INTERVAL:
        time.sleep(MIN_REQUEST_INTERVAL - elapsed)
    response = requests.get(url, headers=headers, timeout=timeout)
    LAST_REQUEST_TIME = time.time()
    return response

# ============================================================
# LISTAS DE PRECIOS NEBRO — SISTEMA ACTUAL (octubre 2026)
# Precio = Costo × (1 + porcentaje)  —  porcentaje FIJO para todo costo
# Excepciones:
#   - Público: Costo × 3 si costo < $50; si no, Costo × 2
#   - svip:    Costo + $1 si costo $1–$199; Costo + $5 si costo ≥ $200
# Mayoreo A NO se toca: sigue calculándose con costo ÷ factor (ver más abajo)
# ============================================================
PRICE_LISTS = [
    "Público",
    "Mayoreo C",
    "Mayoreo B",
    "Mayoreo A",
    "Mayoreo Z",
    "Media Caja",
    "Caja",
    "svip",
]

# Margen sobre costo por lista (precio = costo × (1 + margen))
# Público y svip tienen reglas especiales — ver calc_publico() / calc_svip()
LIST_MARKUPS = {
    "Público":    1.00,    # base: 100% → costo × 2 (×3 si costo < $50)
    "Mayoreo C":  0.65,    # 65%
    "Mayoreo B":  0.50,    # 50%
    "Mayoreo Z":  0.1775,  # 17.75%
    "Media Caja": 0.1112,  # 11.12%
    "Caja":       0.0527,  # 5.27%
    "svip":       0.00,    # regla especial: +$1 ($1–$199) / +$5 (≥ $200)
}

# Rangos de costo solo para filtrado/visualización (ya no afectan porcentajes)
COST_BUCKETS = [
    (0, 50, "$0-50"),
    (51, 150, "$51-150"),
    (151, 300, "$151-300"),
    (301, 500, "$301-500"),
    (501, 1000, "$501-1000"),
    (1001, float("inf"), "$1001+"),
]

# ============================================================
# LISTAS DE PRECIOS NEBRO — SISTEMA ANTIGUO (LEGACY)
# ============================================================
PRICE_LISTS_LEGACY = [
    "Público",
    "2,000 - 3%",
    "5,000 - 6%",
    "Mayoreo A",
    "10,000 - 8%",
    "20,000 - 12%",
    "30,000 - 15%",
    "50,000 - 20%",
]

# Descuentos sobre Mayoreo A para el sistema antiguo
DISCOUNTS_LEGACY = {
    "Público":         {"type": "costo_x",  "value": 2.00},   # Costo × 2
    "2,000 - 3%":      {"type": "discount", "value": 0.03},  # Mayoreo A - 3%
    "5,000 - 6%":      {"type": "discount", "value": 0.06},  # Mayoreo A - 6%
    "Mayoreo A":       {"type": "discount", "value": 0.00},  # Sin descuento
    "10,000 - 8%":     {"type": "discount", "value": 0.08},  # Mayoreo A - 8%
    "20,000 - 12%":    {"type": "discount", "value": 0.12},  # Mayoreo A - 12%
    "30,000 - 15%":    {"type": "discount", "value": 0.15},  # Mayoreo A - 15%
    "50,000 - 20%":    {"type": "discount", "value": 0.20},  # Mayoreo A - 20%
}

# Rangos de costo para calcular Mayoreo A (mantener igual)
MAYOREO_A_RANGES = [
    {"min": 0,    "max": 29.99,  "factor": 0.73, "margin_pct": 27},
    {"min": 30,   "max": 50,     "factor": 0.74, "margin_pct": 26},
    {"min": 50.01, "max": 150,    "factor": 0.75, "margin_pct": 25},
    {"min": 150.01, "max": float("inf"), "factor": 0.78, "margin_pct": 22},
]


# ============================================================
# FUNCIONES DE CÁLCULO
# ============================================================
def get_mayoreo_a_range(cost):
    """Devuelve la fila de rango según el costo para calcular Mayoreo A"""
    for row in MAYOREO_A_RANGES:
        if row["min"] <= cost <= row["max"]:
            return row
    return MAYOREO_A_RANGES[-1]

def calculate_mayoreo_a(cost):
    """Calcula el precio Mayoreo A basado en el costo"""
    if cost is None or cost <= 0:
        return None
    row = get_mayoreo_a_range(cost)
    return round(cost / row["factor"], 2)

def get_rangename_pricing(cost):
    """Devuelve el bucket de costo (solo informativo/filtros)"""
    for lo, hi, name in COST_BUCKETS:
        if lo <= cost <= hi:
            return name
    return "$1001+"

def calc_publico(cost):
    """Público: Costo × 3 si costo < $50; si no, Costo × 2."""
    if cost is None or cost <= 0:
        return None
    return round(cost * (3.00 if cost < 50 else 2.00), 2)

def calc_svip(cost):
    """svip: Costo + $1 si costo $1–$199; Costo + $5 si costo ≥ $200."""
    if cost is None or cost <= 0:
        return None
    return round(cost + (1 if cost <= 199 else 5), 2)

def fmt_pct(value):
    """Formatea 0.1775 → '17.75%', 0.50 → '50%'"""
    txt = f"{value * 100:.2f}".rstrip("0").rstrip(".")
    return f"{txt}%"

def calculate_prices(cost):
    """Calcula todas las listas de precios para un costo dado (porcentajes FIJOS)"""
    if cost is None or cost <= 0:
        return {lst: None for lst in PRICE_LISTS}

    mayoreo_a = calculate_mayoreo_a(cost)
    prices = {}

    for lst in PRICE_LISTS:
        if lst == "Mayoreo A":
            # Mayoreo A: sin cambios (costo ÷ factor por rango)
            prices[lst] = mayoreo_a
        elif lst == "Público":
            # Público: ×3 si costo < $50, si no ×2
            prices[lst] = calc_publico(cost)
        elif lst == "svip":
            # svip: +$1 ($1–$199) / +$5 (≥ $200)
            prices[lst] = calc_svip(cost)
        elif lst in LIST_MARKUPS:
            # Mayoreo C, B, Z, Media Caja, Caja: Costo × (1 + margen fijo)
            prices[lst] = round(cost * (1 + LIST_MARKUPS[lst]), 2)
        else:
            prices[lst] = None

    return prices

def calculate_prices_legacy(cost):
    """Calcula todas las listas de precios con el sistema ANTIGUO (legacy)"""
    if cost is None or cost <= 0:
        return {lst: None for lst in PRICE_LISTS_LEGACY}

    mayoreo_a = calculate_mayoreo_a(cost)
    prices = {}

    for lst in PRICE_LISTS_LEGACY:
        rule = DISCOUNTS_LEGACY[lst]
        if rule["type"] == "costo_x":
            # Público: Costo × 2
            prices[lst] = round(cost * rule["value"], 2)
        elif rule["type"] == "discount":
            # Resto: Mayoreo A - descuento%
            prices[lst] = round(mayoreo_a * (1 - rule["value"]), 2)

    return prices

def get_rangename(cost):
    """Devuelve el nombre del rango de costo para Mayoreo A"""
    for row in MAYOREO_A_RANGES:
        if row["min"] <= cost <= row["max"]:
            if row["max"] == float("inf"):
                return f"${row['min']}+"
            return f"${row['min']}-{row['max']}"
    return "$150+"

def get_margin_info(cost):
    """Devuelve info de margen para el rango actual"""
    row = get_mayoreo_a_range(cost)
    return f"Margen: {row['margin_pct']}% (÷{row['factor']})"


# ============================================================
# FUNCIONES DE ESTILO / COLORES
# ============================================================
def style_price_rows(df):
    """Aplica colores a las celdas de precios basado en % de ganancia vs costo.
    - Pérdida (precio < costo) → 🔴 Rojo
    - Ganancia del 0% al 5% sobre costo → 🟡 Amarillo
    - Ganancia > 5% sobre costo → 🟢 Verde
    """
    def _style_row(row):
        styles = ["" for _ in range(len(row))]
        cost = row.get("Costo")
        if pd.isna(cost) or cost <= 0:
            return styles

        # Columnas de precios a colorear
        price_cols = [c for c in PRICE_LISTS if c in row.index]
        if "Mayoreo A" in row.index and "Mayoreo A" not in price_cols:
            price_cols.append("Mayoreo A")
        if "Precio Actual Shopify" in row.index:
            price_cols.append("Precio Actual Shopify")

        for col in price_cols:
            if col not in row.index:
                continue
            val = row[col]
            if pd.isna(val):
                continue

            profit_pct = ((val - cost) / cost * 100) if cost > 0 else 0
            idx = row.index.get_loc(col)

            if profit_pct < 0:
                # Pérdida → Rojo
                styles[idx] = "background-color: #ffebee; color: #c62828; font-weight: 600;"
            elif 0 <= profit_pct <= 5:
                # Ganancia del 0% al 5% sobre costo → Amarillo
                styles[idx] = "background-color: #fff9c4; color: #f57f17; font-weight: 600;"
            elif profit_pct > 5:
                # Ganancia > 5% sobre costo → Verde
                styles[idx] = "background-color: #e8f5e9; color: #2e7d32; font-weight: 600;"

        return styles

    return df.style.apply(_style_row, axis=1)


# ============================================================
# FUNCIONES DE SHOPIFY
# ============================================================
@st.cache_data(ttl=300)
def fetch_shopify_data():
    """Obtiene todos los productos de nebro-shop con sus costos."""
    products = []
    inventory_item_ids = []

    # ── FASE 1: Obtener todos los productos ──
    url = f"{SHOPIFY_BASE_URL}/products.json?limit=250"
    while url:
        r = shopify_request(url, timeout=60)
        if r.status_code != 200:
            return []

        data = r.json()
        for product in data.get("products", []):
            for variant in product.get("variants", []):
                inv_id = variant.get("inventory_item_id")
                products.append({
                    "ID": product.get("id"),
                    "Título": product.get("title", ""),
                    "Tipo": product.get("product_type", ""),
                    "Vendor": product.get("vendor", ""),
                    "SKU": variant.get("sku") or "Sin SKU",
                    "Variante": variant.get("title", ""),
                    "Costo": None,
                    "Precio Actual": float(variant.get("price", 0) or 0),
                    "Status": product.get("status", ""),
                    "Variante ID": variant.get("id"),
                    "Inventory Item ID": inv_id,
                })
                if inv_id:
                    inventory_item_ids.append(inv_id)

        # Paginación
        link_header = r.headers.get("Link", "")
        url = None
        if 'rel="next"' in link_header:
            for part in link_header.split(","):
                if 'rel="next"' in part:
                    url = part.split(";")[0].strip().strip("<").strip(">")
                    break

    # ── FASE 2: Obtener costos en batch ──
    if inventory_item_ids:
        chunk_size = 250
        cost_map = {}

        for i in range(0, len(inventory_item_ids), chunk_size):
            chunk = inventory_item_ids[i:i + chunk_size]
            ids_str = ",".join(str(cid) for cid in chunk)

            batch_url = f"{SHOPIFY_BASE_URL}/inventory_items.json?ids={ids_str}&limit=250"
            br = shopify_request(batch_url, timeout=60)

            if br.status_code == 200:
                for item in br.json().get("inventory_items", []):
                    item_id = item.get("id")
                    cost_str = item.get("cost")
                    if cost_str and item_id:
                        try:
                            cost_map[item_id] = float(cost_str)
                        except:
                            pass

        # Asignar costos a productos
        for p in products:
            inv_id = p["Inventory Item ID"]
            if inv_id and inv_id in cost_map:
                p["Costo"] = cost_map[inv_id]

    return products

def fetch_shopify_products_with_progress():
    """Wrapper con barra de progreso."""
    progress_bar = st.progress(0)
    status_text = st.empty()

    def _update(msg, pct):
        status_text.text(msg)
        progress_bar.progress(min(pct, 0.99))

    _update("📥 Obteniendo productos de nebro-shop...", 0.05)
    products = fetch_shopify_data()
    _update(f"✅ Listo! {len(products)} variantes cargadas", 1.0)
    time.sleep(0.5)
    progress_bar.empty()
    status_text.empty()

    return products

def build_price_dataframe(products_list):
    """Construye DataFrame con todas las listas de precios"""
    rows = []
    for p in products_list:
        cost = p["Costo"]
        if cost is None or cost <= 0:
            continue

        prices = calculate_prices(cost)
        mayoreo_a = calculate_mayoreo_a(cost)
        row = {
            "Título": p["Título"],
            "Tipo": p["Tipo"],
            "SKU": p["SKU"],
            "Variante": p["Variante"],
            "Rango Costo": get_rangename_pricing(cost),
            "Costo": cost,
            "Mayoreo A": mayoreo_a,
        }
        for lst in PRICE_LISTS:
            if lst != "Mayoreo A":  # Evitar duplicado
                row[lst] = prices[lst]
        row["Precio Actual Shopify"] = p["Precio Actual"]
        row["Status"] = p["Status"]
        rows.append(row)

    return pd.DataFrame(rows)

# ============================================================
# UI - STREAMLIT
# ============================================================
st.set_page_config(page_title="Calculadora NEBRO SHOP", layout="wide")

# CSS personalizado
st.markdown("""
<style>
    .main-header { font-size: 2.2rem; font-weight: 700; color: #6a040f; margin-bottom: 0.5rem; }
    .sub-header { font-size: 1.1rem; color: #4a4a6a; margin-bottom: 2rem; }
    .cost-badge { background: #f0f0f0; padding: 8px 16px; border-radius: 8px; font-weight: 600; }
    .price-card { background: #fafafa; padding: 12px; border-radius: 8px; border-left: 4px solid #ffba08; }
    .stTabs [data-baseweb="tab-list"] { gap: 24px; }
    .stTabs [data-baseweb="tab"] { font-size: 1.1rem; font-weight: 600; }
    .nebro-accent { color: #6a040f; }
</style>
""", unsafe_allow_html=True)

st.markdown('<div class="main-header">📊 Calculadora NEBRO SHOP</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Sistema de pricing por costo — nebro.shop</div>', unsafe_allow_html=True)

# ───────────────────────────────────────────────
# TABS
# ───────────────────────────────────────────────
tab1, tab2, tab3 = st.tabs(["🛒 Productos Shopify", "🧮 Calculadora Manual", "🧮 Calculadora por Volumen"])

# ============================================================
# TAB 1: PRODUCTOS SHOPIFY
# ============================================================
with tab1:
    st.subheader("Productos de nebro-shop con Costos y Listas de Precios")

    col1, col2 = st.columns([1, 3])
    with col1:
        if st.button("🔄 Cargar Productos", type="primary", use_container_width=True):
            products = fetch_shopify_products_with_progress()
            st.session_state["nebro_products"] = products
            st.success(f"✅ {len(products)} variantes cargadas")

    with col2:
        st.info("Haz clic en 'Cargar Productos' para obtener los costos de Shopify y calcular todas las listas de precios.")

    if "nebro_products" in st.session_state:
        products = st.session_state["nebro_products"]

        products_with_cost = [p for p in products if p["Costo"] is not None and p["Costo"] > 0]
        products_without_cost = [p for p in products if p["Costo"] is None or p["Costo"] <= 0]

        # Stats
        c1, c2, c3, c4 = st.columns(4)
        c1.metric("Total Variantes", len(products))
        c2.metric("Con Costo", len(products_with_cost))
        c3.metric("Sin Costo", len(products_without_cost))
        c4.metric("Rangos", len(MAYOREO_A_RANGES))

        # Filtros
        st.divider()
        col_f1, col_f2, col_f3 = st.columns(3)
        with col_f1:
            filter_type = st.multiselect(
                "Filtrar por Tipo de Producto",
                options=sorted(list(set(p["Tipo"] for p in products_with_cost if p["Tipo"]))),
                default=[]
            )
        with col_f2:
            filter_status = st.multiselect(
                "Filtrar por Status",
                options=["active", "draft", "archived"],
                default=["active"]
            )
        with col_f3:
            filter_range = st.multiselect(
                "Filtrar por Rango de Costo",
                options=["$0-$50", "$51-$150", "$151-$300", "$301-$500", "$501-$1000", "$1001+"],
                default=[]
            )

        # Buscadores
        col_s1, col_s2 = st.columns(2)
        with col_s1:
            search_title = st.text_input(
                "🔍 Buscar por Título",
                placeholder="Ej: Bocina, Audífonos, Cable...",
                value=""
            )
        with col_s2:
            search_sku = st.text_input(
                "🔍 Buscar por SKU",
                placeholder="Ej: ABC123, 69772...",
                value=""
            )

        # Aplicar filtros
        filtered = products_with_cost
        if filter_type:
            filtered = [p for p in filtered if p["Tipo"] in filter_type]
        if filter_status:
            filtered = [p for p in filtered if p["Status"] in filter_status]
        if filter_range:
            filtered = [p for p in filtered if get_rangename_pricing(p["Costo"]) in filter_range]
        if search_title:
            term = search_title.lower()
            filtered = [p for p in filtered if term in p["Título"].lower()]
        if search_sku:
            term = search_sku.lower()
            filtered = [p for p in filtered if term in p["SKU"].lower()]

        if filtered:
            df = build_price_dataframe(filtered)

            # Reordenar columnas
            cols_order = ["Título", "Tipo", "SKU", "Variante", "Rango Costo", "Costo"] + PRICE_LISTS + ["Precio Actual Shopify", "Status"]
            # Eliminar duplicados manteniendo orden
            seen = set()
            cols_unique = []
            for c in cols_order:
                if c in df.columns and c not in seen:
                    cols_unique.append(c)
                    seen.add(c)
            df = df[cols_unique]

            # Aplicar colores a precios según ganancia
            styled_df = style_price_rows(df)

            st.dataframe(
                styled_df,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Costo": st.column_config.NumberColumn("Costo", format="$%.2f"),
                    "Público": st.column_config.NumberColumn("Público", format="$%.2f"),
                    "Mayoreo A": st.column_config.NumberColumn("Mayoreo A", format="$%.2f"),
                    "Mayoreo C": st.column_config.NumberColumn("Mayoreo C", format="$%.2f"),
                    "Mayoreo B": st.column_config.NumberColumn("Mayoreo B", format="$%.2f"),
                    "Mayoreo Z": st.column_config.NumberColumn("Mayoreo Z", format="$%.2f"),
                    "Media Caja": st.column_config.NumberColumn("Media Caja", format="$%.2f"),
                    "Caja": st.column_config.NumberColumn("Caja", format="$%.2f"),
                    "svip": st.column_config.NumberColumn("svip", format="$%.2f"),
                    "Precio Actual Shopify": st.column_config.NumberColumn("Precio Actual", format="$%.2f"),
                }
            )

            # Leyenda de colores
            st.markdown("""
            <div style="display: flex; gap: 16px; margin-top: 8px; font-size: 0.85rem;">
                <span style="background: #ffebee; color: #c62828; padding: 4px 12px; border-radius: 4px; font-weight: 600;">🔴 Pérdida (precio < costo)</span>
                <span style="background: #fff9c4; color: #f57f17; padding: 4px 12px; border-radius: 4px; font-weight: 600;">🟡 Ganancia 0% – 5% sobre costo</span>
                <span style="background: #e8f5e9; color: #2e7d32; padding: 4px 12px; border-radius: 4px; font-weight: 600;">🟢 Ganancia > 5% sobre costo</span>
            </div>
            """, unsafe_allow_html=True)

            # Exportar
            st.divider()
            col_e1, col_e2 = st.columns(2)
            with col_e1:
                csv = df.to_csv(index=False).encode("utf-8")
                st.download_button(
                    "📥 Descargar CSV",
                    csv,
                    f"listas_precios_nebro_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                    "text/csv",
                    use_container_width=True
                )
            with col_e2:
                excel_file = f"listas_precios_nebro_{datetime.now().strftime('%Y%m%d')}.xlsx"
                with pd.ExcelWriter(excel_file, engine="openpyxl") as writer:
                    df.to_excel(writer, index=False, sheet_name="Listas de Precios")
                with open(excel_file, "rb") as f:
                    st.download_button(
                        "📥 Descargar Excel",
                        f.read(),
                        f"listas_precios_nebro_{datetime.now().strftime('%Y%m%d_%H%M')}.xlsx",
                        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                        use_container_width=True
                    )

            st.caption(f"Mostrando {len(df)} productos con costo definido")
        else:
            st.warning("No hay productos que coincidan con los filtros seleccionados.")

        # Mostrar productos sin costo
        if products_without_cost:
            with st.expander(f"⚠️ Productos sin costo ({len(products_without_cost)}):"):
                df_no_cost = pd.DataFrame(products_without_cost)
                st.dataframe(df_no_cost[["Título", "Tipo", "SKU", "Variante", "Precio Actual", "Status"]], use_container_width=True, hide_index=True)
    else:
        st.info("👆 Haz clic en 'Cargar Productos' para comenzar.")

# ============================================================
# TAB 2: CALCULADORA MANUAL
# ============================================================
with tab2:
    st.subheader("Calculadora Manual de Listas de Precios NEBRO")

    col_input, col_results = st.columns([1, 2])

    with col_input:
        st.markdown("### 💰 Ingresa el Costo")
        cost_input = st.number_input(
            "Costo del producto ($)",
            min_value=0.0,
            max_value=100000.0,
            value=100.0,
            step=1.0,
            format="%.2f"
        )

        if cost_input > 0:
            row = get_mayoreo_a_range(cost_input)
            st.markdown(
                f"<div class='cost-badge'>Rango: {get_rangename(cost_input)} | "
                f"Margen: {row['margin_pct']}% (÷{row['factor']})</div>",
                unsafe_allow_html=True
            )

        st.divider()
        st.markdown("### 📋 Tabla de Mayoreo A")

        table_data = []
        for r in MAYOREO_A_RANGES:
            if r["max"] == float("inf"):
                rango = f"${r['min']}+"
            else:
                rango = f"${r['min']}-{r['max']}"
            table_data.append({
                "Rango Costo": rango,
                "Margen": f"{r['margin_pct']}%",
                "Divisor": f"÷{r['factor']}",
                "Fórmula": f"Costo ÷ {r['factor']}"
            })

        df_table = pd.DataFrame(table_data)
        st.dataframe(df_table, use_container_width=True, hide_index=True)

        st.markdown("### 📋 Porcentajes por Lista (sistema actual)")
        pricing_data = []
        for lst in PRICE_LISTS:
            if lst == "Mayoreo A":
                continue  # Mayoreo A se muestra en su propia tabla de rangos
            markup = LIST_MARKUPS[lst]
            if lst == "Público":
                formula = "Costo × 3.00 (< $50)" if cost_input < 50 else "Costo × 2.00 (≥ $50)"
                pct_label = "×3 / ×2"
                display_price = calc_publico(cost_input) if cost_input > 0 else round(cost_input * 2, 2)
            elif lst == "svip":
                formula = "Costo + $1 ($1–$199)" if cost_input <= 199 else "Costo + $5 (≥ $200)"
                pct_label = "+$1 / +$5"
                display_price = calc_svip(cost_input) if cost_input > 0 else round(cost_input, 2)
            else:
                formula = f"Costo × (1 + {fmt_pct(markup)})"
                pct_label = fmt_pct(markup)
                display_price = round(cost_input * (1 + markup), 2)
            pricing_data.append({
                "Lista": lst,
                "% sobre costo": pct_label,
                "Fórmula": formula,
                "Precio (tu costo)": display_price,
            })

        df_pricing = pd.DataFrame(pricing_data)
        st.dataframe(
            df_pricing,
            use_container_width=True,
            hide_index=True,
            column_config={
                "Precio (tu costo)": st.column_config.NumberColumn(format="$%.2f"),
            }
        )

        st.markdown("### 📋 Fórmulas")
        st.markdown("""
        - **Público** = Costo × 3 si costo < $50; si no, Costo × 2
        - **Mayoreo A** = Costo ÷ factor (ver tabla arriba, sin cambios)
        - **Mayoreo C, B, Z, Media Caja, Caja** = Costo × (1 + % fijo por lista)
        - **svip** = Costo + $1 si costo $1–$199; Costo + $5 si costo ≥ $200
        """)

    with col_results:
        if cost_input > 0:
            st.markdown("### 📊 Precios Calculados")
            prices = calculate_prices(cost_input)
            mayoreo_a = calculate_mayoreo_a(cost_input)

            # Card de Mayoreo A destacado
            st.markdown(f"""
            <div style="background: #6a040f; color: white; padding: 16px; border-radius: 12px; margin-bottom: 16px;">
                <div style="font-size: 0.9rem; opacity: 0.9; margin-bottom: 4px;">Mayoreo A (Base)</div>
                <div style="font-size: 2rem; font-weight: 700;">${mayoreo_a:,.2f}</div>
                <div style="font-size: 0.8rem; opacity: 0.8; margin-top: 4px;">
                    Costo: ${cost_input:,.2f} | {get_margin_info(cost_input)}
                </div>
            </div>
            """, unsafe_allow_html=True)

            # Cards de precios
            cols = st.columns(2)
            for i, lst in enumerate(PRICE_LISTS):
                with cols[i % 2]:
                    price = prices[lst]
                    margin = price - cost_input if price else 0
                    margin_pct = (margin / cost_input * 100) if cost_input > 0 else 0

                    st.markdown(f"""
                    <div class="price-card">
                        <div style="font-size: 0.9rem; color: #666; margin-bottom: 4px;">{lst}</div>
                        <div style="font-size: 1.6rem; font-weight: 700; color: #1a1a2e;">${price:,.2f}</div>
                        <div style="font-size: 0.8rem; color: #27ae60; margin-top: 4px;">
                            Margen: ${margin:,.2f} ({margin_pct:.1f}%)
                        </div>
                    </div>
                    """, unsafe_allow_html=True)

            st.divider()

            # Tabla detallada
            st.markdown("### 📋 Detalle por Lista")
            detail_data = []
            for lst in PRICE_LISTS:
                price = prices[lst]
                margin = price - cost_input
                margin_pct = (margin / cost_input * 100) if cost_input > 0 else 0

                if lst == "Público":
                    formula = "Costo × 3.00" if cost_input < 50 else "Costo × 2.00"
                elif lst == "Mayoreo A":
                    formula = f"Costo ÷ {get_mayoreo_a_range(cost_input)['factor']}"
                elif lst == "svip":
                    formula = "Costo + $1" if cost_input <= 199 else "Costo + $5"
                elif lst in LIST_MARKUPS:
                    formula = f"Costo × (1 + {fmt_pct(LIST_MARKUPS[lst])})"
                else:
                    formula = "—"

                detail_data.append({
                    "Lista": lst,
                    "Costo": cost_input,
                    "Precio": price,
                    "Margen $": margin,
                    "Margen %": f"{margin_pct:.1f}%",
                    "Fórmula": formula,
                })

            df_detail = pd.DataFrame(detail_data)
            st.dataframe(
                df_detail,
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Costo": st.column_config.NumberColumn(format="$%.2f"),
                    "Precio": st.column_config.NumberColumn(format="$%.2f"),
                    "Margen $": st.column_config.NumberColumn(format="$%.2f"),
                }
            )

            # Exportar cálculo manual
            csv_manual = df_detail.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Descargar CSV de este cálculo",
                csv_manual,
                f"calculo_manual_nebro_{cost_input:.0f}.csv",
                "text/csv",
                use_container_width=True
            )
        else:
            st.info("Ingresa un costo mayor a 0 para ver los cálculos.")

# ============================================================
# TAB 3: CALCULADORA POR VOLUMEN (con productos Shopify)
# ============================================================
with tab3:
    st.subheader("🧮 Calculadora por Volumen — Sistema Antiguo")
    st.markdown("Carga los productos de nebro-shop y analiza la ganancia o pérdida con el **sistema antiguo de listas** (descuentos sobre Mayoreo A).")

    # ── Cargar productos ──
    col1_vol, col2_vol = st.columns([1, 3])
    with col1_vol:
        if st.button("🔄 Cargar Productos", type="primary", use_container_width=True, key="btn_volumen"):
            products_vol = fetch_shopify_products_with_progress()
            st.session_state["nebro_products_volumen"] = products_vol
            st.success(f"✅ {len(products_vol)} variantes cargadas")

    with col2_vol:
        st.info("Haz clic en 'Cargar Productos' para obtener los costos de Shopify.")

    # ── Input de cantidad ──
    qty_global = st.number_input(
        "📦 Cantidad / Volumen de venta (aplica a todos los productos)",
        min_value=1,
        max_value=100000,
        value=10,
        step=1,
        key="qty_global"
    )

    if "nebro_products_volumen" in st.session_state:
        products_vol = st.session_state["nebro_products_volumen"]
        products_with_cost_vol = [p for p in products_vol if p["Costo"] is not None and p["Costo"] > 0]

        # Stats
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Variantes", len(products_vol))
        c2.metric("Con Costo", len(products_with_cost_vol))
        c3.metric("Volumen", f"{qty_global:,} uds")

        # Filtros
        st.divider()
        col_f1, col_f2 = st.columns(2)
        with col_f1:
            filter_type_vol = st.multiselect(
                "Filtrar por Tipo de Producto",
                options=sorted(list(set(p["Tipo"] for p in products_with_cost_vol if p["Tipo"]))),
                default=[],
                key="filter_type_vol"
            )
        with col_f2:
            filter_status_vol = st.multiselect(
                "Filtrar por Status",
                options=["active", "draft", "archived"],
                default=["active"],
                key="filter_status_vol"
            )

        # Buscador
        search_title_vol = st.text_input(
            "🔍 Buscar por Título",
            placeholder="Ej: Bocina, Audífonos, Cable...",
            value="",
            key="search_title_vol"
        )

        # Aplicar filtros
        filtered_vol = products_with_cost_vol
        if filter_type_vol:
            filtered_vol = [p for p in filtered_vol if p["Tipo"] in filter_type_vol]
        if filter_status_vol:
            filtered_vol = [p for p in filtered_vol if p["Status"] in filter_status_vol]
        if search_title_vol:
            term = search_title_vol.lower()
            filtered_vol = [p for p in filtered_vol if term in p["Título"].lower()]

        if filtered_vol:
            # Construir DataFrame con análisis por volumen
            rows_vol = []
            for p in filtered_vol:
                cost = p["Costo"]
                if cost is None or cost <= 0:
                    continue

                prices = calculate_prices_legacy(cost)
                total_cost = cost * qty_global

                row = {
                    "Título": p["Título"],
                    "Tipo": p["Tipo"],
                    "SKU": p["SKU"],
                    "Variante": p["Variante"],
                    "Costo Unitario": cost,
                    "Costo Total": total_cost,
                }

                # Solo listas de volumen antiguas (excluir Público y Mayoreo A)
                for lst in PRICE_LISTS_LEGACY:
                    if lst in ["Público", "Mayoreo A"]:
                        continue

                    price_unit = prices[lst]
                    total_revenue = price_unit * qty_global
                    total_margin = total_revenue - total_cost
                    margin_pct = (total_margin / total_cost * 100) if total_cost > 0 else 0

                    row[f"{lst} Unit"] = price_unit
                    row[f"{lst} Ganancia"] = total_margin
                    row[f"{lst} Margen%"] = margin_pct

                rows_vol.append(row)

            df_vol = pd.DataFrame(rows_vol)

            # Función de coloreado por ganancia/pérdida
            def style_volume_products(df):
                def _style_row(row):
                    styles = ["" for _ in range(len(row))]
                    for col in df.columns:
                        if "Ganancia" in col:
                            idx = row.index.get_loc(col)
                            val = row[col]
                            if pd.isna(val):
                                continue
                            if val < 0:
                                styles[idx] = "background-color: #ffebee; color: #c62828; font-weight: 600;"
                            elif val >= 0:
                                styles[idx] = "background-color: #e8f5e9; color: #2e7d32; font-weight: 600;"
                        elif "Margen%" in col:
                            idx = row.index.get_loc(col)
                            val = row[col]
                            if pd.isna(val):
                                continue
                            if val < 0:
                                styles[idx] = "background-color: #ffebee; color: #c62828;"
                            elif val < 10:
                                styles[idx] = "background-color: #fff9c4; color: #f57f17;"
                            else:
                                styles[idx] = "background-color: #e8f5e9; color: #2e7d32;"
                    return styles
                return df.style.apply(_style_row, axis=1)

            st.markdown(f"### 📊 Productos con análisis por volumen ({qty_global:,} uds)")

            st.dataframe(
                style_volume_products(df_vol),
                use_container_width=True,
                hide_index=True,
                column_config={
                    "Costo Unitario": st.column_config.NumberColumn(format="$%.2f"),
                    "Costo Total": st.column_config.NumberColumn(format="$%.2f"),
                }
            )

            # Leyenda
            st.markdown("""
            <div style="display: flex; gap: 16px; margin-top: 8px; font-size: 0.85rem;">
                <span style="background: #ffebee; color: #c62828; padding: 4px 12px; border-radius: 4px; font-weight: 600;">🔴 Pérdida</span>
                <span style="background: #fff9c4; color: #f57f17; padding: 4px 12px; border-radius: 4px; font-weight: 600;">🟡 Margen < 10%</span>
                <span style="background: #e8f5e9; color: #2e7d32; padding: 4px 12px; border-radius: 4px; font-weight: 600;">🟢 Ganancia</span>
            </div>
            """, unsafe_allow_html=True)

            # Resumen de productos con pérdida
            st.divider()
            loss_products = []
            for _, row in df_vol.iterrows():
                for col in df_vol.columns:
                    if "Ganancia" in col and row[col] < 0:
                        loss_products.append({
                            "Producto": row["Título"],
                            "SKU": row["SKU"],
                            "Lista": col.replace(" Ganancia", ""),
                            "Ganancia": row[col],
                        })

            if loss_products:
                st.warning(f"⚠️ **{len(loss_products)} combinaciones** de producto+lista generan PÉRDIDA con volumen de {qty_global:,} uds.")
                df_loss = pd.DataFrame(loss_products)
                st.dataframe(df_loss, use_container_width=True, hide_index=True)
            else:
                st.success(f"✅ Todas las listas generan ganancia con volumen de {qty_global:,} uds.")

            # Exportar
            st.divider()
            csv_vol_products = df_vol.to_csv(index=False).encode("utf-8")
            st.download_button(
                "📥 Descargar CSV por Volumen",
                csv_vol_products,
                f"volumen_nebro_{qty_global}uds_{datetime.now().strftime('%Y%m%d_%H%M')}.csv",
                "text/csv",
                use_container_width=True
            )
        else:
            st.warning("No hay productos que coincidan con los filtros.")
    else:
        st.info("👆 Haz clic en 'Cargar Productos' para comenzar.")

# ============================================================
# FOOTER
# ============================================================
st.divider()
st.caption(f"📅 Calculadora NEBRO SHOP | Generado: {datetime.now().strftime('%Y-%m-%d %H:%M')}")
