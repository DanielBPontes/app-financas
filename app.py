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

# --- Conexões ---
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

# --- Funções Backend ---
def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except:
        return None

def carregar_transacoes(user_id):
    try:
        # Carrega TUDO do usuário (o filtro de data será feito no Pandas para ser mais rápido na UI)
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data'] = pd.to_datetime(df['data']).dt.date
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except:
        return pd.DataFrame()

def salvar_transacao(user_id, data_gasto, categoria, descricao, valor, tipo, recorrente):
    data = {
        "user_id": user_id,
        "data": data_gasto.isoformat(),
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": recorrente,
    }
    supabase.table("transactions").insert(data).execute()

# --- Funções de IA ---
def gerar_relatorio_mensal_ia(df_mes, mes, ano):
    """Gera um relatório textual completo do mês"""
    if df_mes.empty:
        return "Sem dados para gerar relatório."
    
    resumo_cat = df_mes.groupby('categoria')['valor'].sum().to_string()
    total = df_mes['valor'].sum()
    maior_gasto = df_mes.loc[df_mes['valor'].idxmax()]
    
    prompt = f"""
    Atue como um analista financeiro pessoal. Escreva um Relatório Mensal para {mes}/{ano}.
    
    Dados do Mês:
    - Total Gasto: R$ {total}
    - Detalhe por Categoria:
    {resumo_cat}
    - Maior gasto único: {maior_gasto['descricao']} (R$ {maior_gasto['valor']})
    
    Estrutura do Relatório:
    1. **Resumo Executivo**: Visão geral do mês.
    2. **Análise de Categorias**: Onde o dinheiro foi mais concentrado.
    3. **Alerta**: Comentário sobre o maior gasto.
    4. **Veredito**: Se o mês foi equilibrado ou exagerado.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erro na IA: {e}"

def analisar_busca_especifica(query, df_busca):
    """Analisa um conjunto específico de gastos buscados (Ex: Brawl Stars)"""
    total = df_busca['valor'].sum()
    qtd = len(df_busca)
    
    prompt = f"""
    O usuário buscou por "{query}" e encontrou {qtd} transações totalizando R$ {total}.
    
    Analise esses gastos brevemente. Se for gasto supérfluo (jogos, ifood), dê um puxão de orelha engraçado. 
    Se for essencial, parabenize.
    Seja curto (2 linhas).
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except:
        return "Análise indisponível."

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
            "Rendimento (Juros)": round(saldo - total_aportado, 2), "Saldo Total": round(saldo, 2)
        })
    return pd.DataFrame(dados_evolucao), saldo

# --- Login System ---
if 'user' not in st.session_state: st.session_state['user'] = None

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
                    else: st.error("Credenciais inválidas.")
                else: st.error("Erro Conexão.")
    st.stop()

# =======================================================
# APLICAÇÃO PRINCIPAL
# =======================================================

user = st.session_state['user']
df = carregar_transacoes(user['id'])

# --- SIDEBAR GLOBAL (Controle de Data) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4149/4149666.png", width=50)
    st.markdown(f"Olá, **{user['username']}**")
    st.divider()
    
    # Navegação
    menu = st.radio("Menu", ["Dashboard Mensal", "Busca & Relatórios", "Lançamentos", "Simulador Juros"])
    
    st.divider()
    st.markdown("📅 **Período de Análise**")
    
    # Seletores de Data Globais
    col_s1, col_s2 = st.columns(2)
    meses_dict = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez"}
    
    mes_selecionado = col_s1.selectbox("Mês", list(meses_dict.keys()), format_func=lambda x: meses_dict[x], index=date.today().month - 1)
    ano_selecionado = col_s2.number_input("Ano", 2023, 2030, date.today().year)
    
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

# Filtragem Global do DataFrame pelo Mês Selecionado
if not df.empty:
    df['data_dt'] = pd.to_datetime(df['data'])
    df_mes = df[(df['data_dt'].dt.month == mes_selecionado) & (df['data_dt'].dt.year == ano_selecionado)]
else:
    df_mes = pd.DataFrame()

# --- ABA 1: DASHBOARD MENSAL ---
if menu == "Dashboard Mensal":
    st.title(f"📊 Visão Geral: {meses_dict[mes_selecionado]}/{ano_selecionado}")
    
    if not df_mes.empty:
        total_gasto = df_mes['valor'].sum()
        budget = 2173.79 
        saldo_restante = budget - total_gasto
        
        # KPIs
        col1, col2, col3 = st.columns(3)
        col1.metric("Gastos no Mês", f"R$ {total_gasto:,.2f}", delta=f"{-total_gasto/budget*100:.1f}% do Budget", delta_color="inverse")
        col2.metric("Saldo Restante", f"R$ {saldo_restante:,.2f}")
        col3.metric("Lançamentos", len(df_mes))
        
        st.divider()
        
        # Gráficos
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("Categorias")
            gastos_cat = df_mes.groupby("categoria")['valor'].sum().reset_index()
            fig_pie = px.pie(gastos_cat, values='valor', names='categoria', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c2:
            st.subheader("Dia a Dia")
            gastos_dia = df_mes.groupby("data")['valor'].sum().reset_index()
            fig_bar = px.bar(gastos_dia, x='data', y='valor', color='valor')
            st.plotly_chart(fig_bar, use_container_width=True)
            
    else:
        st.info(f"Nenhum dado encontrado para {meses_dict[mes_selecionado]}/{ano_selecionado}.")

# --- ABA 2: BUSCA & RELATÓRIOS (NOVO!) ---
elif menu == "Busca & Relatórios":
    st.title("🔎 Inteligência Financeira")
    
    tab_busca, tab_relatorio = st.tabs(["Busca Detalhada", "Gerar Relatório Mensal"])
    
    # --- SUB-ABA: BUSCA INTELIGENTE ---
    with tab_busca:
        st.markdown("Encontre gastos específicos por descrição (ex: 'Brawl Stars', 'Uber', 'Mercado').")
        
        c_busca1, c_busca2 = st.columns([3, 1])
        termo_busca = c_busca1.text_input("O que você procura?", placeholder="Digite aqui...")
        filtrar_todos = c_busca2.checkbox("Buscar em todo histórico?", value=True, help="Se desmarcado, busca apenas no mês selecionado na lateral.")
        
        if termo_busca and not df.empty:
            # Lógica de Filtro
            df_alvo = df if filtrar_todos else df_mes
            
            # Filtro Case Insensitive (Pandas)
            resultado = df_alvo[df_alvo['descricao'].str.contains(termo_busca, case=False, na=False)]
            
            if not resultado.empty:
                total_busca = resultado['valor'].sum()
                
                # Exibe métricas da busca
                m1, m2 = st.columns(2)
                m1.metric("Total Gasto", f"R$ {total_busca:.2f}")
                m2.metric("Ocorrências", len(resultado))
                
                st.subheader("Histórico Encontrado")
                st.dataframe(resultado[['data', 'categoria', 'descricao', 'valor']], use_container_width=True)
                
                # Feedback da IA sobre a busca específica
                if IA_AVAILABLE:
                    st.markdown("---")
                    st.markdown("### 🤖 Opinião da IA")
                    with st.spinner("Analisando esse hábito de gasto..."):
                        opiniao = analisar_busca_especifica(termo_busca, resultado)
                        st.info(opiniao)
            else:
                st.warning("Nenhum gasto encontrado com esse termo.")

    # --- SUB-ABA: RELATÓRIO MENSAL ---
    with tab_relatorio:
        st.markdown(f"### Relatório de Fechamento: {meses_dict[mes_selecionado]}/{ano_selecionado}")
        st.markdown("A IA analisará todos os dados do mês selecionado e gerará um documento de análise.")
        
        if st.button("📄 Gerar Relatório Agora", type="primary"):
            if not df_mes.empty:
                with st.spinner("Lendo seus dados e escrevendo relatório..."):
                    relatorio = gerar_relatorio_mensal_ia(df_mes, meses_dict[mes_selecionado], ano_selecionado)
                    
                    st.markdown("---")
                    st.markdown(relatorio)
                    
                    # Botão para baixar (gambiarra simples para txt)
                    st.download_button("Baixar Relatório (.txt)", relatorio, file_name=f"Relatorio_{mes_selecionado}_{ano_selecionado}.txt")
            else:
                st.error("Não há dados neste mês para gerar relatório.")

# --- ABA 3: LANÇAMENTOS ---
elif menu == "Lançamentos":
    st.title("📝 Lançamentos")
    
    # Formulário
    with st.container(border=True):
        st.subheader("Novo Gasto/Receita")
        with st.form("transacao_form", clear_on_submit=True):
            c1, c2, c3 = st.columns(3)
            data_input = c1.date_input("Data", date.today())
            valor_input = c2.number_input("Valor (R$)", min_value=0.0, step=10.0)
            tipo_input = c3.selectbox("Tipo", ["Despesa", "Receita"])
            
            c4, c5 = st.columns(2)
            cat_input = c4.selectbox("Categoria", ["Alimentação", "Transporte", "Jogos/Lazer", "Investimentos", "Saúde", "Moradia", "Outros"])
            desc_input = c5.text_input("Descrição (ex: Gemas Brawl Stars)")
            
            recorrente = st.checkbox("Recorrente (Mensal)")
            
            if st.form_submit_button("💾 Salvar", type="primary"):
                try:
                    salvar_transacao(user['id'], data_input, cat_input, desc_input, valor_input, tipo_input, recorrente)
                    st.toast("Salvo com sucesso!", icon="✅")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro: {e}")

    # Grid de Edição (Mostra dados do mês selecionado)
    st.divider()
    st.subheader(f"Editando: {meses_dict[mes_selecionado]}/{ano_selecionado}")
    if not df_mes.empty:
        edited_df = st.data_editor(
            df_mes,
            column_config={
                "id": None, "user_id": None, "created_at": None, "data_dt": None,
                "valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "data": st.column_config.DateColumn(format="DD/MM/YYYY"),
            },
            use_container_width=True, hide_index=True, num_rows="dynamic", key="editor_grid"
        )
    else:
        st.info("Sem lançamentos neste período.")

# --- ABA 4: SIMULADOR ---
elif menu == "Simulador Juros":
    st.title("📈 Calculadora BCB")
    # (Mantive seu código original da calculadora aqui para economizar espaço visual na resposta,
    # ele funcionará igual pois está dentro da função calcular_investimento_bcb)
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        meses = c1.number_input("Meses", 1, 12, 12)
        taxa = c2.number_input("Taxa Mensal (%)", 0.01, 5.0, 0.85)
        aporte = c3.number_input("Aporte (R$)", 0.0, 10000.0, 200.0)
        
        if st.button("Simular"):
            df_calc, final = calcular_investimento_bcb(meses, taxa, aporte)
            st.metric("Resultado Final", f"R$ {final:,.2f}")
            st.plotly_chart(px.area(df_calc, x="Mês", y="Saldo Total"), use_container_width=True)
