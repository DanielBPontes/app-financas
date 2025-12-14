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

# --- CSS Personalizado para UI "Clean" ---
st.markdown("""
<style>
    /* Estilo dos Cards de Métricas */
    [data-testid="stMetricValue"] {
        font-size: 26px;
        font-weight: 700;
    }
    /* Cores personalizadas para métricas */
    div[data-testid="stMetric"]:nth-child(1) [data-testid="stMetricValue"] { color: #FF4B4B; } /* Despesas */
    div[data-testid="stMetric"]:nth-child(2) [data-testid="stMetricValue"] { color: #00CC96; } /* Investimentos/Saldo */
    
    /* Ajuste de padding */
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- Conexão com Supabase ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        return None

supabase: Client = init_connection()

# --- Configuração da IA (Gemini) ---
try:
    if "gemini" in st.secrets:
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
        IA_AVAILABLE = True
    else:
        IA_AVAILABLE = False
except:
    IA_AVAILABLE = False

# --- Lógica de Negócios (Backend) ---

def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except:
        return None

def carregar_transacoes(user_id):
    try:
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

def analisar_financas_com_ia(df_transacoes):
    """Envia o resumo dos dados para o Gemini analisar"""
    # Prepara os dados em texto para a IA entender
    resumo = df_transacoes.groupby('categoria')['valor'].sum().to_string()
    total = df_transacoes['valor'].sum()
    
    prompt = f"""
    Atue como um consultor financeiro pessoal experiente.
    Analise meus gastos deste mês:
    {resumo}
    Total Gasto: R$ {total}
    
    1. Identifique onde estou gastando muito.
    2. Dê uma dica prática de economia baseada nesses dados.
    3. Seja direto e breve (máximo 4 linhas).
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erro na IA: {e}"

# --- Lógica da Calculadora (Baseada no BCB - Depósitos Regulares) ---
def calcular_investimento_bcb(meses, taxa_mensal, aporte_mensal):
    """
    Simula aplicação com depósitos regulares (regra do BCB: depósito no início do período).
    """
    taxa_dec = taxa_mensal / 100
    dados_evolucao = []
    
    saldo = 0
    total_aportado = 0
    
    for m in range(1, int(meses) + 1):
        total_aportado += aporte_mensal
        # Juros sobre o saldo anterior + aporte do mês (juros compostos)
        rendimento_mes = (saldo + aporte_mensal) * taxa_dec
        saldo = (saldo + aporte_mensal) + rendimento_mes
        
        dados_evolucao.append({
            "Mês": m,
            "Total Investido": round(total_aportado, 2),
            "Rendimento (Juros)": round(saldo - total_aportado, 2),
            "Saldo Total": round(saldo, 2)
        })
        
    return pd.DataFrame(dados_evolucao), saldo

# --- Login System ---
if 'user' not in st.session_state:
    st.session_state['user'] = None

if not st.session_state['user']:
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🔒 Login")
        with st.form("login_form"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            if st.form_submit_button("Acessar Sistema"):
                if supabase:
                    user = login_user(username, password)
                    if user:
                        st.session_state['user'] = user
                        st.rerun()
                    else:
                        st.error("Credenciais inválidas.")
                else:
                    st.error("Erro na conexão com Supabase. Verifique Secrets.")
    st.stop()

# =======================================================
# APLICAÇÃO PRINCIPAL
# =======================================================

user = st.session_state['user']

# Sidebar de Navegação
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4149/4149666.png", width=50)
    st.markdown(f"Olá, **{user['username']}**")
    st.markdown("---")
    menu = st.radio("Navegação", ["Dashboard", "Lançamentos", "Investimentos (Simulador)"])
    st.markdown("---")
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

df = carregar_transacoes(user['id'])

# --- ABA 1: DASHBOARD (Visualização Profissional) ---
if menu == "Dashboard":
    st.title("📊 Visão Geral")
    
    if not df.empty:
        # Filtros Rápidos
        col_f1, col_f2 = st.columns(2)
        mes_atual = date.today().month
        ano_atual = date.today().year
        
        # Dados do Mês
        df_mes = df[(pd.to_datetime(df['data']).dt.month == mes_atual) & (pd.to_datetime(df['data']).dt.year == ano_atual)]
        
        total_gasto = df_mes['valor'].sum()
        # Simulação de "Budget"
        budget = 2173.79 
        saldo_restante = budget - total_gasto
        
        # --- CARDS KPI ---
        col1, col2, col3 = st.columns(3)
        col1.metric("Gastos (Mês Atual)", f"R$ {total_gasto:,.2f}", delta=f"{-total_gasto/budget*100:.1f}% do Budget", delta_color="inverse")
        col2.metric("Saldo Estimado", f"R$ {saldo_restante:,.2f}")
        col3.metric("Média por Gasto", f"R$ {df_mes['valor'].mean():,.2f}" if not df_mes.empty else "R$ 0,00")
        
        st.markdown("---")

        # --- GRÁFICOS (PLOTLY) ---
        c1, c2 = st.columns([1, 1])
        
        with c1:
            st.subheader("Onde seu dinheiro vai?")
            if not df_mes.empty:
                gastos_cat = df_mes.groupby("categoria")['valor'].sum().reset_index()
                fig_pie = px.pie(gastos_cat, values='valor', names='categoria', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig_pie, use_container_width=True)
            else:
                st.write("Sem dados no mês.")
            
        with c2:
            st.subheader("Evolução Diária")
            if not df_mes.empty:
                gastos_dia = df_mes.groupby("data")['valor'].sum().reset_index()
                fig_bar = px.bar(gastos_dia, x='data', y='valor', color='valor', color_continuous_scale='Bluered')
                st.plotly_chart(fig_bar, use_container_width=True)
            else:
                st.write("Sem dados no mês.")
            
        # --- IA FINANCEIRA ---
        st.divider()
        with st.expander("🤖 Consultar IA Financeira (Gemini)", expanded=False):
            if IA_AVAILABLE:
                if st.button("Gerar Análise do Mês"):
                    with st.spinner("O robô está analisando suas contas..."):
                        analise = analisar_financas_com_ia(df_mes)
                        st.markdown(analise)
            else:
                st.warning("⚠️ Configure a chave da API do Gemini nos Secrets para usar este recurso.")
            
    else:
        st.info("Nenhum dado lançado ainda. Vá para a aba 'Lançamentos'.")

# --- ABA 2: LANÇAMENTOS (Controle de Dados) ---
elif menu == "Lançamentos":
    st.title("📝 Gestão de Transações")
    
    tab_form, tab_grid = st.tabs(["Novo Lançamento", "Tabela Completa"])
    
    with tab_form:
        with st.container(border=True):
            with st.form("transacao_form", clear_on_submit=True):
                c1, c2, c3 = st.columns(3)
                data_input = c1.date_input("Data", date.today())
                valor_input = c2.number_input("Valor (R$)", min_value=0.0, step=10.0)
                tipo_input = c3.selectbox("Tipo", ["Despesa", "Receita"])
                
                c4, c5 = st.columns(2)
                cat_input = c4.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Investimentos", "Saúde", "Outros"])
                desc_input = c5.text_input("Descrição")
                
                recorrente = st.checkbox("Recorrente (Mensal)")
                
                if st.form_submit_button("💾 Salvar Lançamento", type="primary"):
                    try:
                        salvar_transacao(user['id'], data_input, cat_input, desc_input, valor_input, tipo_input, recorrente)
                        st.success("Registrado com sucesso!")
                        time.sleep(1)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")

    with tab_grid:
        if not df.empty:
            st.markdown("### Histórico Recente")
            edited_df = st.data_editor(
                df,
                column_config={
                    "id": None, "user_id": None, "created_at": None,
                    "valor": st.column_config.NumberColumn(format="R$ %.2f"),
                    "data": st.column_config.DateColumn(format="DD/MM/YYYY"),
                    "recorrente": st.column_config.CheckboxColumn(default=False)
                },
                use_container_width=True,
                hide_index=True,
                num_rows="dynamic",
                key="editor_grid"
            )
        else:
            st.write("Sem dados.")

# --- ABA 3: INVESTIMENTOS (Calculadora BCB) ---
elif menu == "Investimentos (Simulador)":
    st.title("📈 Simulador de Juros Compostos")
    st.markdown("Baseado na metodologia da **Calculadora do Cidadão (BCB)** para depósitos regulares.")
    
    with st.container(border=True):
        col1, col2, col3 = st.columns(3)
        
        # Inputs configurados para serem idênticos à lógica do BCB
        meses = col1.number_input("Número de meses", min_value=1, value=12, step=1)
        taxa = col2.number_input("Taxa de juros mensal (%)", min_value=0.01, value=0.85, step=0.01, format="%.2f")
        aporte = col3.number_input("Valor do depósito regular (R$)", min_value=0.0, value=200.0, step=50.0)
        
        if st.button("Calcular", type="primary", use_container_width=True):
            df_calc, valor_final = calcular_investimento_bcb(meses, taxa, aporte)
            
            # --- RESULTADOS ---
            st.divider()
            c_res1, c_res2, c_res3 = st.columns(3)
            
            total_investido = aporte * meses
            total_juros = valor_final - total_investido
            
            c_res1.metric("Valor Total Investido", f"R$ {total_investido:,.2f}")
            c_res2.metric("Total em Juros", f"R$ {total_juros:,.2f}", delta="Rendimento", delta_color="normal")
            c_res3.metric("Valor Obtido ao Final", f"R$ {valor_final:,.2f}", delta="Montante Final")
            
            # --- GRÁFICO "BOLA DE NEVE" ---
            st.subheader("Evolução do Patrimônio")
            
            df_chart = df_calc.melt(id_vars=["Mês"], value_vars=["Total Investido", "Saldo Total"], var_name="Tipo", value_name="Reais")
            
            fig = px.area(
                df_chart, 
                x="Mês", 
                y="Reais", 
                color="Tipo", 
                color_discrete_map={"Total Investido": "#AAB1C2", "Saldo Total": "#00CC96"},
                title="Efeito dos Juros Compostos"
            )
            st.plotly_chart(fig, use_container_width=True)
            
            with st.expander("Ver Tabela Detalhada mês a mês"):
                st.dataframe(df_calc, use_container_width=True)


