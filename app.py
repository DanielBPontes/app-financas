import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client, Client
from datetime import datetime, date
import time
import google.generativeai as genai

# --- Configuração da Página e UX ---
st.set_page_config(
    page_title="Finanças Pro", 
    page_icon="💸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS Personalizado ---
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; }
    div[data-testid="stMetric"]:nth-child(1) [data-testid="stMetricValue"] { color: #FF4B4B; }
    div[data-testid="stMetric"]:nth-child(2) [data-testid="stMetricValue"] { color: #00CC96; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- Conexão e Configurações ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        return None

supabase: Client = init_connection()

try:
    if "gemini" in st.secrets:
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
        IA_AVAILABLE = True
    else:
        IA_AVAILABLE = False
except:
    IA_AVAILABLE = False

# --- Funções de Backend ---
def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except:
        return None

def carregar_transacoes(user_id):
    try:
        # Carrega TUDO do usuário (filtramos na memória/pandas para ser rápido na busca global)
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data'] = pd.to_datetime(df['data']).dt.date
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except:
        return pd.DataFrame()

def salvar_transacao(user_id, data_gasto, categoria, descricao, valor, recorrente):
    data = {
        "user_id": user_id,
        "data": data_gasto.isoformat(),
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": recorrente,
    }
    supabase.table("transactions").insert(data).execute()

# --- Função IA Genérica (Busca e Relatórios) ---
def consultar_ia(df, pergunta):
    """Envia os dados filtrados para o Gemini responder"""
    # Limita o tamanho dos dados para não estourar tokens se tiver milhares de linhas
    csv_resumo = df.to_csv(index=False)
    
    prompt = f"""
    Você é um assistente financeiro pessoal inteligente.
    Use os dados abaixo (em formato CSV) para responder à solicitação do usuário.
    
    DADOS FINANCEIROS:
    {csv_resumo}
    
    SOLICITAÇÃO DO USUÁRIO: 
    "{pergunta}"
    
    Diretrizes:
    1. Se for pedido um relatório, sumarize gastos por categoria e total.
    2. Se for uma busca específica (ex: "gastos com uber"), liste os valores e datas.
    3. Responda em Português, formatado em Markdown.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erro na IA: {e}"

# --- Calculadora BCB ---
def calcular_investimento_bcb(meses, taxa_mensal, aporte_mensal):
    taxa_dec = taxa_mensal / 100
    dados_evolucao = []
    saldo = 0
    total_aportado = 0
    for m in range(1, int(meses) + 1):
        total_aportado += aporte_mensal
        rendimento_mes = (saldo + aporte_mensal) * taxa_dec
        saldo = (saldo + aporte_mensal) + rendimento_mes
        dados_evolucao.append({
            "Mês": m, "Total Investido": round(total_aportado, 2),
            "Rendimento": round(saldo - total_aportado, 2), "Saldo Total": round(saldo, 2)
        })
    return pd.DataFrame(dados_evolucao), saldo

# --- Login ---
if 'user' not in st.session_state:
    st.session_state['user'] = None

if not st.session_state['user']:
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🔒 Login")
        with st.form("login_form"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar"):
                if supabase:
                    user = login_user(username, password)
                    if user:
                        st.session_state['user'] = user
                        st.rerun()
                    else:
                        st.error("Login falhou.")
                else:
                    st.error("Erro de conexão Supabase.")
    st.stop()

# =======================================================
# APP PRINCIPAL
# =======================================================
user = st.session_state['user']
df = carregar_transacoes(user['id'])

# --- SIDEBAR (Controle Mensal) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4149/4149666.png", width=50)
    st.write(f"Olá, **{user['username']}**")
    st.divider()
    
    # SELETOR DE DATA (Gerenciamento Mensal)
    st.header("🗓️ Período")
    col_mes, col_ano = st.columns(2)
    meses_nomes = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez"}
    
    mes_selecionado = col_mes.selectbox("Mês", list(meses_nomes.keys()), format_func=lambda x: meses_nomes[x], index=date.today().month-1)
    ano_selecionado = col_ano.number_input("Ano", min_value=2023, max_value=2030, value=date.today().year)
    
    st.divider()
    menu = st.radio("Menu", ["Dashboard", "Lançamentos", "Busca & IA", "Investimentos"])
    
    st.divider()
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

# Filtra o DataFrame Principal pelo Mês/Ano selecionado na Sidebar
if not df.empty:
    df_periodo = df[
        (pd.to_datetime(df['data']).dt.month == mes_selecionado) & 
        (pd.to_datetime(df['data']).dt.year == ano_selecionado)
    ]
else:
    df_periodo = pd.DataFrame()

# --- ABA: DASHBOARD ---
if menu == "Dashboard":
    st.title(f"📊 Visão Geral: {meses_nomes[mes_selecionado]}/{ano_selecionado}")
    
    if not df_periodo.empty:
        total_gasto = df_periodo['valor'].sum()
        budget = 2173.79 
        saldo = budget - total_gasto
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Gasto", f"R$ {total_gasto:,.2f}", delta=f"{(total_gasto/budget)*100:.1f}% do Budget", delta_color="inverse")
        c2.metric("Saldo Restante", f"R$ {saldo:,.2f}")
        c3.metric("Lançamentos", len(df_periodo))
        
        st.divider()
        
        g1, g2 = st.columns(2)
        with g1:
            st.subheader("Por Categoria")
            fig = px.pie(df_periodo, values='valor', names='categoria', hole=0.5, color_discrete_sequence=px.colors.qualitative.Set3)
            st.plotly_chart(fig, use_container_width=True)
            
        with g2:
            st.subheader("Evolução no Mês")
            daily = df_periodo.groupby('data')['valor'].sum().reset_index()
            fig2 = px.bar(daily, x='data', y='valor', color='valor', color_continuous_scale='Bluered')
            st.plotly_chart(fig2, use_container_width=True)

        # Botão rápido para relatório do mês
        if IA_AVAILABLE:
            if st.button("📄 Gerar Relatório deste Mês com IA"):
                with st.spinner("Lendo seus dados..."):
                    analise = consultar_ia(df_periodo, f"Gere um relatório executivo dos meus gastos de {meses_nomes[mes_selecionado]}/{ano_selecionado}. Destaque onde gastei mais.")
                    st.info(analise)
    else:
        st.warning(f"Sem dados para {meses_nomes[mes_selecionado]}/{ano_selecionado}.")

# --- ABA: LANÇAMENTOS ---
elif menu == "Lançamentos":
    st.title("📝 Novo Gasto")
    
    with st.container(border=True):
        with st.form("add_form", clear_on_submit=True):
            c1, c2 = st.columns(2)
            data_in = c1.date_input("Data", date.today())
            valor_in = c2.number_input("Valor", min_value=0.01, step=10.0)
            
            c3, c4 = st.columns(2)
            cat_in = c3.selectbox("Categoria", ["Alimentação", "Transporte", "Jogos/Lazer", "Casa", "Investimentos", "Outros"])
            desc_in = c4.text_input("Descrição (Ex: Brawl Stars, Uber)")
            rec_in = st.checkbox("Recorrente?")
            
            if st.form_submit_button("💾 Salvar", type="primary"):
                try:
                    salvar_transacao(user['id'], data_in, cat_in, desc_in, valor_in, rec_in)
                    st.success("Salvo!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(e)
    
    st.subheader(f"Histórico de {meses_nomes[mes_selecionado]}/{ano_selecionado}")
    if not df_periodo.empty:
        st.dataframe(df_periodo, use_container_width=True, hide_index=True)
    else:
        st.info("Nada neste mês.")

# --- ABA: BUSCA & IA (NOVA) ---
elif menu == "Busca & IA":
    st.title("🔍 Busca Inteligente")
    
    # Opções de filtro
    tipo_busca = st.radio("Onde buscar?", ["Apenas no Mês Selecionado", "Em Todo o Histórico"], horizontal=True)
    df_alvo = df_periodo if tipo_busca == "Apenas no Mês Selecionado" else df
    
    tab1, tab2 = st.tabs(["🔎 Busca por Texto", "🤖 Assistente IA"])
    
    # Sub-aba 1: Busca Rápida (Pandas)
    with tab1:
        termo = st.text_input("Digite o nome do gasto (ex: Brawl Stars, Mercado)", placeholder="Buscar...")
        
        if termo:
            # Filtra ignorando maiúsculas/minúsculas
            resultado = df_alvo[df_alvo['descricao'].str.contains(termo, case=False, na=False)]
            
            if not resultado.empty:
                total_busca = resultado['valor'].sum()
                st.metric(f"Total gasto com '{termo}'", f"R$ {total_busca:,.2f}")
                st.dataframe(resultado[['data', 'categoria', 'descricao', 'valor']], use_container_width=True)
            else:
                st.warning("Nenhum gasto encontrado com esse termo.")
                
    # Sub-aba 2: IA (Gemini)
    with tab2:
        st.markdown("Pergunte algo sobre seus dados. Ex: *'Quanto gastei com jogos no ano passado?'* ou *'Qual categoria é minha maior despesa?'*")
        pergunta = st.text_area("Sua pergunta:")
        
        if st.button("Perguntar à IA", type="primary"):
            if IA_AVAILABLE:
                if not df_alvo.empty:
                    with st.spinner("Analisando..."):
                        resposta = consultar_ia(df_alvo, pergunta)
                        st.markdown(resposta)
                else:
                    st.error("Sem dados para analisar neste período.")
            else:
                st.error("Configure a API Key do Gemini nos Secrets.")

# --- ABA: INVESTIMENTOS ---
elif menu == "Investimentos":
    st.title("📈 Simulador")
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        meses = c1.number_input("Meses", 1, 120, 12)
        taxa = c2.number_input("Taxa Mensal (%)", 0.01, 5.0, 0.85)
        aporte = c3.number_input("Aporte Mensal", 0.0, 10000.0, 200.0)
        
        if st.button("Simular"):
            df_calc, final = calcular_investimento_bcb(meses, taxa, aporte)
            st.metric("Total Acumulado", f"R$ {final:,.2f}")
            st.plotly_chart(px.area(df_calc, x="Mês", y="Saldo Total"), use_container_width=True)
