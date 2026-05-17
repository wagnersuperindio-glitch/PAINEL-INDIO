import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from plotly.subplots import make_subplots
import msal
import requests
import json
import hashlib
from pathlib import Path
from datetime import date, datetime
import os

# ─── CONFIG ───────────────────────────────────────────────────
st.set_page_config(
    page_title="Supermercados Índio — Painel de Lojas",
    page_icon="🛒",
    layout="wide",
    initial_sidebar_state="expanded"
)

# ─── AUTENTICAÇÃO ─────────────────────────────────────────────
def _hash(pwd: str) -> str:
    return hashlib.sha256(pwd.encode()).hexdigest()

USUARIOS = {
    "wagner":          {"hash": _hash("Ind!o@W2026"),  "nome": "Wagner Antonelli"},
    "carolina":        {"hash": _hash("Ind!o@C2026"),  "nome": "Carolina"},
    "david":           {"hash": _hash("Ind!o@D2026"),  "nome": "David"},
    "nicolas":         {"hash": _hash("Ind!o@N2026"),  "nome": "Nicolas"},
    "financeiro":      {"hash": _hash("Ind!o@Fin26"),  "nome": "Financeiro"},
    "fiscaltributario":{"hash": _hash("Ind!o@FT2026"), "nome": "Fiscal Tributário"},
}

def login_screen():
    st.markdown("""
    <style>
    .login-box {
        max-width: 380px; margin: 80px auto; background: white;
        border-radius: 16px; padding: 40px; box-shadow: 0 8px 32px rgba(0,0,0,0.12);
        text-align: center;
    }
    .login-title { font-size: 26px; font-weight: 800; color: #1B2A4A; margin-bottom: 4px; }
    .login-sub   { font-size: 13px; color: #888; margin-bottom: 28px; }
    </style>
    <div class="login-box">
        <div class="login-title">🛒 Supermercados Índio</div>
        <div class="login-sub">Painel de Lojas — Acesso Restrito</div>
    </div>
    """, unsafe_allow_html=True)

    col1, col2, col3 = st.columns([1, 2, 1])
    with col2:
        usuario = st.text_input("Usuário", placeholder="seu usuário").strip().lower()
        senha   = st.text_input("Senha", type="password", placeholder="••••••••")
        entrar  = st.button("Entrar", use_container_width=True, type="primary")

        if entrar:
            if usuario in USUARIOS and USUARIOS[usuario]["hash"] == _hash(senha):
                st.session_state["autenticado"] = True
                st.session_state["usuario"]     = usuario
                st.session_state["nome"]        = USUARIOS[usuario]["nome"]
                st.rerun()
            else:
                st.error("Usuário ou senha incorretos.")

def check_auth():
    if "autenticado" not in st.session_state or not st.session_state["autenticado"]:
        login_screen()
        st.stop()

check_auth()

# Credenciais — lidas do Streamlit Secrets (cloud) ou variáveis de ambiente (local)
def _secret(key, default=""):
    try:
        return st.secrets[key]
    except Exception:
        return os.environ.get(key, default)

CLIENT_ID         = _secret("POWERBI_CLIENT_ID",     "63cdc2e6-d4de-4c1b-acb6-5dd8db8c603e")
TENANT_ID         = _secret("POWERBI_TENANT_ID",     "45d3d314-8ae9-4a13-92d6-ade3ede81811")
CLIENT_SECRET     = _secret("POWERBI_CLIENT_SECRET", "")   # configurar no Streamlit Cloud Secrets
PBI_USERNAME      = _secret("POWERBI_USERNAME",      "bi.indio@teleconsistemas.com.br")
PBI_PASSWORD      = _secret("POWERBI_PASSWORD",      "")   # configurar no Streamlit Cloud Secrets
WORKSPACE_ID      = "5bebea90-6285-45cd-8107-95afdd267f6b"
DATASET_GERENCIAL = "586615c6-7d19-44ce-af2d-359b40d9f4bf"
DATASET_PDV       = "29e69b70-8009-4b52-aca3-9db1dbdb66ab"
AUTHORITY         = f"https://login.microsoftonline.com/{TENANT_ID}"
TOKEN_CACHE       = Path(__file__).parent / "token_cache.json"

# Metas mensais individuais por loja (CodLoja → Meta mensal R$)
# ⚠ AJUSTE ESSES VALORES com as metas reais de cada loja
METAS_LOJAS = {
    1:  1800000,   # MATRIZ
    2:   950000,   # Filial 1 (Jardim - Guaiba)
    3:  1450000,   # Filial 3 (Coronel Nassuca)
    6:  1080000,   # Filial 5 (Centro - Eldorado)
    7:  1050000,   # Filial 6 (Guaiba - Passo Fundo)
    9:  1100000,   # Filial 7 (São Jerônimo)
    10: 1350000,   # Filial 8 (Arroio dos Ratos)
    11: 1420000,   # Filial 9 (Charqueadas 1º Maio)
    12: 1280000,   # Filial 10 (Charqueadas 2)
    13: 1250000,   # Filial 11 (Guaiba Centro)
}

# ─── CSS ──────────────────────────────────────────────────────
st.markdown("""
<style>
    .main { background-color: #F5F6FA; }
    .stMetric { background: white; border-radius: 10px; padding: 12px; box-shadow: 0 2px 8px rgba(0,0,0,0.06); }
    .titulo-painel { color: #1B2A4A; font-size: 28px; font-weight: 800; margin-bottom: 4px; }
    .subtitulo-painel { color: #666; font-size: 14px; margin-bottom: 20px; }
    .card-kpi { background: white; border-radius: 12px; padding: 16px 20px; box-shadow: 0 2px 10px rgba(0,0,0,0.07); text-align: center; }
    .kpi-valor { font-size: 24px; font-weight: 800; color: #1B2A4A; }
    .kpi-label { font-size: 11px; color: #888; text-transform: uppercase; letter-spacing: 0.5px; }
    div[data-testid="stSidebarNav"] { display: none; }
    .status-critico { color: #C0392B; font-weight: bold; }
    .status-atencao { color: #E6872A; font-weight: bold; }
    .status-ok      { color: #1F7A4B; font-weight: bold; }
</style>
""", unsafe_allow_html=True)

# ─── AUTH ──────────────────────────────────────────────────────
@st.cache_resource(ttl=3000)
def get_token():
    """Tenta 3 métodos de autenticação em ordem de preferência."""
    # 1. Client credentials (service principal) — funciona se app foi registrado no PBI workspace
    try:
        app_conf = msal.ConfidentialClientApplication(
            CLIENT_ID, authority=AUTHORITY, client_credential=CLIENT_SECRET
        )
        result = app_conf.acquire_token_for_client(
            scopes=["https://analysis.windows.net/powerbi/api/.default"]
        )
        if "access_token" in result:
            return result["access_token"]
    except Exception:
        pass

    # 2. Username/password (ROPC) — usa credenciais do usuário Power BI
    if PBI_USERNAME and PBI_PASSWORD:
        app_pub = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY)
        result = app_pub.acquire_token_by_username_password(
            username=PBI_USERNAME,
            password=PBI_PASSWORD,
            scopes=["https://analysis.windows.net/powerbi/api/Dataset.Read.All"]
        )
        if "access_token" in result:
            return result["access_token"]

    # 3. Token cache local (desenvolvimento)
    cache = msal.SerializableTokenCache()
    if TOKEN_CACHE.exists():
        cache.deserialize(TOKEN_CACHE.read_text())
    app_pub = msal.PublicClientApplication(CLIENT_ID, authority=AUTHORITY, token_cache=cache)
    accounts = app_pub.get_accounts()
    if accounts:
        result = app_pub.acquire_token_silent(
            ["https://analysis.windows.net/powerbi/api/Dataset.Read.All"],
            account=accounts[0]
        )
        if result and "access_token" in result:
            return result["access_token"]

    raise Exception(
        "Autenticação Power BI falhou. Verifique:\n"
        "1. No Streamlit Cloud → Settings → Secrets: configure POWERBI_PASSWORD\n"
        "2. Ou adicione o Service Principal ao workspace no app.powerbi.com"
    )


def dax_query(dataset_id: str, query: str) -> list[dict]:
    token = get_token()
    headers = {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}
    body = {"queries": [{"query": query}], "serializerSettings": {"includeNulls": True}}
    r = requests.post(
        f"https://api.powerbi.com/v1.0/myorg/groups/{WORKSPACE_ID}/datasets/{dataset_id}/executeQueries",
        headers=headers, json=body, timeout=30
    )
    r.raise_for_status()
    return r.json().get("results", [{}])[0].get("tables", [{}])[0].get("rows", [])


# ─── DADOS ─────────────────────────────────────────────────────
@st.cache_data(ttl=300, show_spinner="Carregando dados do Power BI...")
def carregar_vendas(data_ini: str, data_fim: str) -> pd.DataFrame:
    yi, mi, di = data_ini.split("-")
    yf, mf, df_ = data_fim.split("-")

    # Query 1: Vendas e CMV do dataset gerencial
    query_ger = f"""
    EVALUATE
    SUMMARIZECOLUMNS(
        VendasDia[CodLoja],
        Lojas[Nome],
        FILTER(ALL(VendasDia),
            VendasDia[DataVenda] >= DATE({yi},{mi},{di}) &&
            VendasDia[DataVenda] <= DATE({yf},{mf},{df_})
        ),
        "Vendas", SUM(VendasDia[ValorTotal]),
        "CMV",    SUM(VendasDia[TotalCmvCustoGerencial])
    )
    """
    rows = dax_query(DATASET_GERENCIAL, query_ger)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.columns = [c.split("[")[-1].rstrip("]") for c in df.columns]
    df["CodLoja"] = df["CodLoja"].astype(int)
    df["Vendas"]  = df["Vendas"].astype(float)
    df["CMV"]     = df["CMV"].astype(float)

    # Filtrar lojas inativas
    df = df[~df["CodLoja"].isin([5, 8])].copy()

    # Query 2: Contagem de transações (cupons) do dataset PDV
    try:
        query_pdv = f"""
        EVALUATE
        SUMMARIZECOLUMNS(
            VendasPDV_Dia[CodLoja],
            FILTER(ALL(VendasPDV_Dia),
                VendasPDV_Dia[Data] >= DATE({yi},{mi},{di}) &&
                VendasPDV_Dia[Data] <= DATE({yf},{mf},{df_})
            ),
            "Cupons", SUM(VendasPDV_Dia[QTD_Vendas])
        )
        """
        rows_pdv = dax_query(DATASET_PDV, query_pdv)
        if rows_pdv:
            df_pdv = pd.DataFrame(rows_pdv)
            df_pdv.columns = [c.split("[")[-1].rstrip("]") for c in df_pdv.columns]
            df_pdv["CodLoja"] = df_pdv["CodLoja"].astype(int)
            df_pdv["Cupons"]  = df_pdv["Cupons"].astype(float)
            df = df.merge(df_pdv[["CodLoja", "Cupons"]], on="CodLoja", how="left")
        else:
            df["Cupons"] = 0.0
    except Exception:
        df["Cupons"] = 0.0

    df["Cupons"] = df["Cupons"].fillna(0).astype(int)
    df["Meta"]      = df["CodLoja"].map(METAS_LOJAS).fillna(0)
    df["Margem"]    = (df["Vendas"] - df["CMV"]) / df["Vendas"]
    df["Ticket"]    = df.apply(lambda r: r["Vendas"] / r["Cupons"] if r["Cupons"] > 0 else 0, axis=1)
    df["Ating"]     = df.apply(lambda r: r["Vendas"] / r["Meta"] if r["Meta"] > 0 else 0, axis=1)
    df["LucroBruto"] = df["Vendas"] - df["CMV"]
    return df.sort_values("Vendas", ascending=False).reset_index(drop=True)


@st.cache_data(ttl=300, show_spinner="Carregando quebras...")
def carregar_quebras(data_ini: str, data_fim: str) -> pd.DataFrame:
    # Tabela de quebras verificada no dataset PDV
    try:
        yi, mi, di = data_ini.split("-")
        yf, mf, df_ = data_fim.split("-")
        query = f"""
        EVALUATE
        SUMMARIZECOLUMNS(
            VendasPDV_Dia[CodLoja],
            Lojas[Nome],
            FILTER(ALL(VendasPDV_Dia),
                VendasPDV_Dia[Data] >= DATE({yi},{mi},{di}) &&
                VendasPDV_Dia[Data] <= DATE({yf},{mf},{df_})
            ),
            "QuebraTotal", SUM(VendasPDV_Dia[QuebraCaixa]),
            "Falta",       SUM(VendasPDV_Dia[Falta]),
            "Sobra",       SUM(VendasPDV_Dia[Sobra])
        )
        """
        rows = dax_query(DATASET_PDV, query)
        if not rows:
            return pd.DataFrame()
        df = pd.DataFrame(rows)
        df.columns = [c.split("[")[-1].rstrip("]") for c in df.columns]
        df["CodLoja"] = df["CodLoja"].astype(int)
        return df
    except Exception:
        return pd.DataFrame()


@st.cache_data(ttl=300, show_spinner="Carregando evolução diária...")
def carregar_evolucao(data_ini: str, data_fim: str) -> pd.DataFrame:
    yi, mi, di = data_ini.split("-")
    yf, mf, df_ = data_fim.split("-")
    query = f"""
    EVALUATE
    SUMMARIZECOLUMNS(
        VendasDia[DataVenda],
        FILTER(ALL(VendasDia),
            VendasDia[DataVenda] >= DATE({yi},{mi},{di}) &&
            VendasDia[DataVenda] <= DATE({yf},{mf},{df_})
        ),
        "Vendas", SUM(VendasDia[ValorTotal])
    )
    ORDER BY VendasDia[DataVenda]
    """
    rows = dax_query(DATASET_GERENCIAL, query)
    if not rows:
        return pd.DataFrame()
    df = pd.DataFrame(rows)
    df.columns = [c.split("[")[-1].rstrip("]") for c in df.columns]
    df["DataVenda"] = pd.to_datetime(df["DataVenda"])
    df["Vendas"] = df["Vendas"].astype(float)
    return df


# ─── HELPERS ──────────────────────────────────────────────────
def semaforo(ating, margem, ticket):
    if ating < 0.90 or margem < 0.27:
        return "🔴 CRÍTICO"
    elif ating < 0.97 or margem < 0.30 or ticket < 42:
        return "⚠ ATENÇÃO"
    elif ating >= 1.0 and margem >= 0.31:
        return "✅ DESTAQUE"
    return "✅ ESTÁVEL"

def fmt_brl(v): return f"R$ {v:,.0f}".replace(",", ".")
def fmt_pct(v): return f"{v:.1%}"


# ─── SIDEBAR ───────────────────────────────────────────────────
with st.sidebar:
    st.markdown("## 🛒 Índio")
    nome_usuario = st.session_state.get("nome", "")
    st.markdown(f"<small style='color:#aaa'>👤 {nome_usuario}</small>", unsafe_allow_html=True)
    if st.button("🚪 Sair", use_container_width=True):
        st.session_state.clear()
        st.rerun()
    st.markdown("---")
    st.markdown("### 📅 Período")
    col_ini, col_fim = st.columns(2)
    with col_ini:
        dt_ini = st.date_input("De", value=date(2026, 4, 1), key="dt_ini")
    with col_fim:
        dt_fim = st.date_input("Até", value=date(2026, 4, 25), key="dt_fim")

    st.markdown("---")
    st.markdown("### 🏪 Lojas")
    filtro_lojas = st.multiselect(
        "Filtrar lojas",
        options=list(METAS_LOJAS.keys()),
        format_func=lambda x: {
            1:"MATRIZ", 2:"Filial 1", 3:"Filial 3", 6:"Filial 5",
            7:"Filial 6", 9:"Filial 7", 10:"Filial 8", 11:"Filial 9",
            12:"Filial 10", 13:"Filial 11"
        }.get(x, str(x)),
        default=[]
    )
    st.markdown("---")
    if st.button("🔄 Atualizar dados", use_container_width=True, type="primary"):
        st.cache_data.clear()
        st.rerun()

    st.markdown(f"<small style='color:#aaa'>Última atualização: {datetime.now().strftime('%d/%m/%Y %H:%M')}</small>", unsafe_allow_html=True)

# ─── CARREGAR DADOS ────────────────────────────────────────────
ini_str = dt_ini.strftime("%Y-%m-%d")
fim_str = dt_fim.strftime("%Y-%m-%d")

try:
    df_vendas  = carregar_vendas(ini_str, fim_str)
    df_quebras = carregar_quebras(ini_str, fim_str)
    df_evol    = carregar_evolucao(ini_str, fim_str)
    erro_dados = None
except Exception as e:
    df_vendas  = pd.DataFrame()
    df_quebras = pd.DataFrame()
    df_evol    = pd.DataFrame()
    erro_dados = str(e)

if filtro_lojas and not df_vendas.empty:
    df_vendas  = df_vendas[df_vendas["CodLoja"].isin(filtro_lojas)]
    df_quebras = df_quebras[df_quebras["CodLoja"].isin(filtro_lojas)] if not df_quebras.empty else df_quebras

# ─── HEADER ────────────────────────────────────────────────────
st.markdown(f"""
<div class="titulo-painel">🛒 Supermercados Índio — Painel de Lojas</div>
<div class="subtitulo-painel">Período: {dt_ini.strftime('%d/%m/%Y')} a {dt_fim.strftime('%d/%m/%Y')} &nbsp;|&nbsp; Dados: Power BI em tempo real</div>
""", unsafe_allow_html=True)

if erro_dados:
    st.error(f"⚠ Erro ao carregar dados do Power BI: {erro_dados}")
    st.stop()

if df_vendas.empty:
    st.warning("Nenhum dado encontrado para o período selecionado.")
    st.stop()

# ─── KPIs ──────────────────────────────────────────────────────
total_vendas  = df_vendas["Vendas"].sum()
total_meta    = df_vendas["Meta"].sum()
total_cmv     = df_vendas["CMV"].sum()
total_cupons  = df_vendas["Cupons"].sum()
total_lucro   = df_vendas["LucroBruto"].sum()
margem_media  = total_lucro / total_vendas
ticket_medio  = total_vendas / total_cupons
atingimento   = total_vendas / total_meta if total_meta > 0 else 0
gap_meta      = total_vendas - total_meta
total_quebra  = df_quebras["QuebraTotal"].sum() if not df_quebras.empty else 0

col1, col2, col3, col4, col5, col6, col7 = st.columns(7)
kpis = [
    (col1, "💰 Faturamento",   fmt_brl(total_vendas),  None),
    (col2, "🎯 Meta",          fmt_brl(total_meta),    None),
    (col3, "📊 Atingimento",   fmt_pct(atingimento),   f"{fmt_brl(gap_meta)} gap"),
    (col4, "📈 Margem Bruta",  fmt_pct(margem_media),  None),
    (col5, "🧾 Ticket Médio",  fmt_brl(ticket_medio),  None),
    (col6, "🛒 Cupons",        f"{total_cupons:,}".replace(",","."), None),
    (col7, "⚠ Quebra Caixa",  fmt_brl(total_quebra),  None),
]
for col, label, valor, delta in kpis:
    with col:
        st.metric(label=label, value=valor, delta=delta)

st.markdown("<br>", unsafe_allow_html=True)

# ─── TABS ──────────────────────────────────────────────────────
tab1, tab2, tab3, tab4 = st.tabs(["🏪 Ranking Lojas", "📈 Evolução Diária", "⚠ Quebras de Caixa", "📋 Diagnóstico"])

# ── TAB 1: RANKING ─────────────────────────────────────────────
with tab1:
    col_g, col_t = st.columns([6, 4])

    with col_g:
        st.markdown("#### Faturamento vs Meta por Loja")
        df_plot = df_vendas.copy()
        df_plot["NomeCurto"] = df_plot["Nome"].str.replace(r"\(.*\)", "", regex=True).str.strip()

        fig = go.Figure()
        cores_ating = ["#C0392B" if a < 0.90 else "#E6872A" if a < 1.0 else "#1F7A4B" for a in df_plot["Ating"]]
        fig.add_trace(go.Bar(
            y=df_plot["NomeCurto"],
            x=df_plot["Vendas"],
            name="Faturamento",
            orientation="h",
            marker_color=cores_ating,
            text=[fmt_pct(a) for a in df_plot["Ating"]],
            textposition="inside",
        ))
        fig.add_trace(go.Scatter(
            y=df_plot["NomeCurto"],
            x=df_plot["Meta"],
            name="Meta",
            mode="markers",
            marker=dict(symbol="line-ns", size=16, color="#1B2A4A", line=dict(width=3, color="#1B2A4A")),
        ))
        fig.update_layout(
            height=380, margin=dict(l=0, r=20, t=10, b=0),
            legend=dict(orientation="h", yanchor="bottom", y=1.02),
            plot_bgcolor="white", paper_bgcolor="white",
            xaxis=dict(tickprefix="R$ ", tickformat=",.0f", gridcolor="#eee"),
            yaxis=dict(autorange="reversed"),
            font=dict(family="Arial"),
        )
        st.plotly_chart(fig, use_container_width=True)

    with col_t:
        st.markdown("#### Tabela Detalhada")
        df_tab = df_vendas[["Nome","Vendas","Meta","Ating","Margem","Ticket","Cupons","LucroBruto"]].copy()
        df_tab["Status"] = df_vendas.apply(lambda r: semaforo(r["Ating"], r["Margem"], r["Ticket"]), axis=1)
        df_tab = df_tab.rename(columns={
            "Nome":"Loja","Vendas":"Faturamento","Ating":"Ating%",
            "Margem":"Margem%","Ticket":"Ticket Médio","LucroBruto":"Lucro Bruto"
        })
        df_tab["Faturamento"]  = df_tab["Faturamento"].apply(fmt_brl)
        df_tab["Meta"]         = df_tab["Meta"].apply(fmt_brl)
        df_tab["Ating%"]       = df_tab["Ating%"].apply(fmt_pct)
        df_tab["Margem%"]      = df_tab["Margem%"].apply(fmt_pct)
        df_tab["Ticket Médio"] = df_tab["Ticket Médio"].apply(fmt_brl)
        df_tab["Lucro Bruto"]  = df_tab["Lucro Bruto"].apply(fmt_brl)
        df_tab["Cupons"]       = df_tab["Cupons"].apply(lambda x: f"{x:,}".replace(",","."))
        df_tab["Loja"]         = df_tab["Loja"].str.replace(r"\(.*\)","",regex=True).str.strip()
        st.dataframe(df_tab.set_index("Loja"), use_container_width=True, height=380)

    # Gráfico de margem por loja
    st.markdown("#### Margem Bruta por Loja (%)")
    df_marg = df_vendas.copy()
    df_marg["NomeCurto"] = df_marg["Nome"].str.replace(r"\(.*\)", "", regex=True).str.strip()
    cores_marg = ["#C0392B" if m < 0.28 else "#E6872A" if m < 0.30 else "#1F7A4B" for m in df_marg["Margem"]]
    fig_m = px.bar(df_marg, x="NomeCurto", y="Margem", text=df_marg["Margem"].apply(fmt_pct),
                   color_discrete_sequence=cores_marg)
    fig_m.update_traces(marker_color=cores_marg, textposition="outside")
    fig_m.add_hline(y=0.30, line_dash="dash", line_color="#1B2A4A", annotation_text="Benchmark 30%")
    fig_m.update_layout(
        height=260, margin=dict(l=0, r=0, t=10, b=0),
        plot_bgcolor="white", paper_bgcolor="white",
        yaxis=dict(tickformat=".0%", gridcolor="#eee", range=[0, max(df_marg["Margem"])*1.2]),
        xaxis_title="", yaxis_title="", font=dict(family="Arial"),
        showlegend=False
    )
    st.plotly_chart(fig_m, use_container_width=True)


# ── TAB 2: EVOLUÇÃO ────────────────────────────────────────────
with tab2:
    if df_evol.empty:
        st.info("Sem dados de evolução para o período.")
    else:
        df_evol["VendasAcum"] = df_evol["Vendas"].cumsum()
        df_evol["DiasUteis"]  = range(1, len(df_evol) + 1)

        col_ev1, col_ev2 = st.columns(2)
        with col_ev1:
            st.markdown("#### Vendas Diárias")
            fig_d = px.bar(df_evol, x="DataVenda", y="Vendas",
                           text=df_evol["Vendas"].apply(lambda v: f"R${v/1000:.0f}k"),
                           color_discrete_sequence=["#1B2A4A"])
            fig_d.update_traces(textposition="outside")
            fig_d.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(tickprefix="R$ ", tickformat=",.0f", gridcolor="#eee"),
                xaxis_title="", yaxis_title="", font=dict(family="Arial"),
                showlegend=False
            )
            st.plotly_chart(fig_d, use_container_width=True)

        with col_ev2:
            st.markdown("#### Acumulado vs Projeção")
            dias_total_mes = 30
            dias_decorridos = len(df_evol)
            media_dia = total_vendas / dias_decorridos if dias_decorridos else 0
            projecao_mes = media_dia * dias_total_mes

            fig_ac = go.Figure()
            fig_ac.add_trace(go.Scatter(
                x=df_evol["DataVenda"], y=df_evol["VendasAcum"],
                name="Acumulado Real", fill="tozeroy",
                line=dict(color="#1B2A4A", width=2)
            ))
            fig_ac.add_hline(y=total_meta, line_dash="dash", line_color="#C0392B",
                             annotation_text=f"Meta {fmt_brl(total_meta)}")
            fig_ac.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(tickprefix="R$ ", tickformat=",.0f", gridcolor="#eee"),
                legend=dict(orientation="h"), font=dict(family="Arial"),
                xaxis_title="", yaxis_title=""
            )
            st.plotly_chart(fig_ac, use_container_width=True)

        met1, met2, met3 = st.columns(3)
        met1.metric("📅 Dias com dados", dias_decorridos)
        met2.metric("📊 Média diária", fmt_brl(media_dia))
        met3.metric("🔮 Projeção mês completo", fmt_brl(projecao_mes),
                    delta=fmt_brl(projecao_mes - total_meta))


# ── TAB 3: QUEBRAS ─────────────────────────────────────────────
with tab3:
    if df_quebras.empty:
        st.info("Sem dados de quebras para o período.")
    else:
        df_q = df_quebras.merge(df_vendas[["CodLoja","Vendas"]], on="CodLoja", how="left")
        df_q["Quebra%"] = df_q["QuebraTotal"] / df_q["Vendas"]
        df_q["Status"]  = df_q["Quebra%"].apply(
            lambda p: "🔴 CRÍTICO" if p > 0.005 else ("⚠ ATENÇÃO" if p > 0.002 else "✅ OK")
        )
        df_q = df_q.sort_values("QuebraTotal", ascending=False)

        col_q1, col_q2 = st.columns([5, 5])
        with col_q1:
            st.markdown("#### Quebra por Loja (R$)")
            df_q["NomeCurto"] = df_q["Nome"].str.replace(r"\(.*\)", "", regex=True).str.strip()
            cores_q = ["#C0392B" if p > 0.005 else "#E6872A" if p > 0.002 else "#1F7A4B" for p in df_q["Quebra%"]]
            fig_q = px.bar(df_q, x="NomeCurto", y="QuebraTotal",
                           text=df_q["QuebraTotal"].apply(lambda v: f"R$ {v:,.2f}"),
                           color_discrete_sequence=cores_q)
            fig_q.update_traces(marker_color=cores_q, textposition="outside")
            fig_q.update_layout(
                height=320, margin=dict(l=0, r=0, t=10, b=0),
                plot_bgcolor="white", paper_bgcolor="white",
                yaxis=dict(tickprefix="R$ ", tickformat=",.0f", gridcolor="#eee"),
                xaxis_title="", yaxis_title="", showlegend=False, font=dict(family="Arial")
            )
            st.plotly_chart(fig_q, use_container_width=True)

        with col_q2:
            st.markdown("#### Detalhamento")
            df_q_show = df_q[["Nome","QuebraTotal","Falta","Sobra","Quebra%","Status"]].copy()
            df_q_show.columns = ["Loja","Quebra Total","Falta","Sobra","Quebra %","Status"]
            df_q_show["Loja"]        = df_q_show["Loja"].str.replace(r"\(.*\)","",regex=True).str.strip()
            df_q_show["Quebra Total"]= df_q_show["Quebra Total"].apply(lambda v: f"R$ {v:,.2f}")
            df_q_show["Falta"]       = df_q_show["Falta"].apply(lambda v: f"R$ {v:,.2f}" if pd.notna(v) else "-")
            df_q_show["Sobra"]       = df_q_show["Sobra"].apply(lambda v: f"R$ {v:,.2f}" if pd.notna(v) else "-")
            df_q_show["Quebra %"]    = df_q_show["Quebra %"].apply(fmt_pct)
            st.dataframe(df_q_show.set_index("Loja"), use_container_width=True, height=320)


# ── TAB 4: DIAGNÓSTICO ─────────────────────────────────────────
with tab4:
    st.markdown("#### Semáforo de Performance por Loja")
    for _, row in df_vendas.iterrows():
        status = semaforo(row["Ating"], row["Margem"], row["Ticket"])
        cor_status = {"🔴 CRÍTICO":"#FFF0F0","⚠ ATENÇÃO":"#FFFBF0","✅ DESTAQUE":"#F0FFF6","✅ ESTÁVEL":"#F0FFF6"}
        borda = {"🔴 CRÍTICO":"#C0392B","⚠ ATENÇÃO":"#E6872A","✅ DESTAQUE":"#1F7A4B","✅ ESTÁVEL":"#1F7A4B"}
        nome_curto = row["Nome"].replace(r"\(.*\)","").strip()
        with st.container():
            st.markdown(f"""
            <div style="background:{cor_status.get(status,'#fff')};border-left:5px solid {borda.get(status,'#ccc')};
                        border-radius:8px;padding:12px 16px;margin-bottom:8px;">
              <b>{status}</b> &nbsp;|&nbsp; <b>{row['Nome']}</b>
              &nbsp;&nbsp;·&nbsp;&nbsp; Faturamento: <b>{fmt_brl(row['Vendas'])}</b>
              &nbsp;·&nbsp; Meta: <b>{fmt_brl(row['Meta'])}</b>
              &nbsp;·&nbsp; Atingimento: <b>{fmt_pct(row['Ating'])}</b>
              &nbsp;·&nbsp; Margem: <b>{fmt_pct(row['Margem'])}</b>
              &nbsp;·&nbsp; Ticket Médio: <b>{fmt_brl(row['Ticket'])}</b>
            </div>
            """, unsafe_allow_html=True)

    st.markdown("---")
    st.markdown("#### 🏆 Top 3 Melhores Desempenhos")
    top3 = df_vendas.nlargest(3, "Ating")
    for i, (_, row) in enumerate(top3.iterrows(), 1):
        st.success(f"**#{i} {row['Nome']}** — Atingimento {fmt_pct(row['Ating'])} | Margem {fmt_pct(row['Margem'])} | Ticket {fmt_brl(row['Ticket'])}")

    st.markdown("#### ⚠ Top 3 Precisam de Atenção")
    bot3 = df_vendas.nsmallest(3, "Ating")
    for i, (_, row) in enumerate(bot3.iterrows(), 1):
        st.error(f"**#{i} {row['Nome']}** — Atingimento {fmt_pct(row['Ating'])} | Margem {fmt_pct(row['Margem'])} | Ticket {fmt_brl(row['Ticket'])}")
