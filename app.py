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

# --- CSS Personalizado (Estilo Dark/Clean) ---
st.markdown("""
<style>
    /* Cards de Métricas */
    [data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; }
    div[data-testid="stMetric"]:nth-child(1) [data-testid="stMetricValue"] { color: #FF4B4B; } /* Despesas */
    div[data-testid="stMetric"]:nth-child(2) [data-testid="stMetricValue"] { color: #00CC96; } /* Saldo */
    
    /* Ajustes Gerais */
    .block-container { padding-top: 2rem; }
    
    /* Estilo para a Calculadora (Parecido com BCB) */
    .calc-label { font-weight: bold; font-size: 16px; text-align: right; padding-top: 10px; }
    .calc-result { font-size: 20px; font-weight: bold; color: #00CC96; }
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

# --- Configuração IA ---
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
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            # Garante que data e hora sejam processadas
            df['data_dt'] = pd.to_datetime(df['data']) # Coluna auxiliar datetime
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except:
        return pd.DataFrame()

def salvar_transacao(user_id, data_gasto, categoria, descricao, valor, tipo, recorrente):
    data = {
        "user_id": user_id,
        "data": data_gasto.isoformat(), # Salva data e hora completa
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": recorrente,
        # Se quiser salvar o Tipo (Despesa/Receita), adicione coluna no Supabase ou trate valor negativo
    }
    supabase.table("transactions").insert(data).execute()

# --- Funções Auxiliares UI ---
def limpar_valor_input(valor_str):
    """Converte qualquer bagunça (10,50 / R$ 10 / 10.5) em float"""
    if not valor_str: return 0.0
    # Remove R$, espaços e troca vírgula por ponto
    v = str(valor_str).replace('R$', '').replace(' ', '').replace(',', '.')
    try:
        return float(v)
    except:
        return 0.0

def resetar_formulario():
    """Limpa os campos deletando as chaves da sessão (Evita o erro do Streamlit)"""
    keys_to_clear = ['novo_valor', 'nova_desc', 'nova_cat_outros']
    for key in keys_to_clear:
        if key in st.session_state:
            del st.session_state[key]
    st.session_state['confirmacao_pendente'] = False

# --- IA Functions ---
def analisar_financas(df_mes):
    if not IA_AVAILABLE: return "IA não configurada."
    resumo = df_mes.groupby('categoria')['valor'].sum().to_string()
    total = df_mes['valor'].sum()
    prompt = f"Analise estes gastos do mês (Total R$ {total}):\n{resumo}\nSeja breve, direto e dê uma dica de ouro."
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        return model.generate_content(prompt).text
    except Exception as e: return f"Erro IA: {e}"

# --- Calculadora Lógica ---
def calcular_juros_compostos(meses, taxa, aporte):
    taxa_dec = taxa / 100
    saldo = 0
    total_investido = 0
    evolucao = []
    
    for m in range(1, int(meses) + 1):
        # Lógica: Depósito no INÍCIO do mês (rende juros sobre o depósito também)
        saldo += aporte
        rendimento = saldo * taxa_dec
        saldo += rendimento
        total_investido += aporte
        
        evolucao.append({
            "Mês": m,
            "Total Investido": total_investido,
            "Juros": saldo - total_investido,
            "Saldo Total": saldo
        })
    return pd.DataFrame(evolucao), saldo

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        st.title("🔒 Acesso")
        with st.form("login"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
                user = login_user(u, p)
                if user:
                    st.session_state['user'] = user
                    st.rerun()
                else:
                    st.error("Dados incorretos.")
    st.stop()

# =======================================================
# APP PRINCIPAL
# =======================================================
user = st.session_state['user']
df = carregar_transacoes(user['id'])

# --- Sidebar ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4149/4149666.png", width=40)
    st.markdown(f"**{user['username']}**")
    menu = st.radio("Menu", ["Dashboard", "Lançamentos", "Relatórios & IA", "Simulador"], index=1)
    
    st.divider()
    st.markdown("📅 **Filtro de Data**")
    col_s1, col_s2 = st.columns(2)
    meses_map = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez"}
    mes_sel = col_s1.selectbox("Mês", list(meses_map.keys()), format_func=lambda x: meses_map[x], index=date.today().month - 1)
    ano_sel = col_s2.number_input("Ano", 2023, 2030, date.today().year)
    
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

# Filtro Global
if not df.empty:
    df_mes = df[(df['data_dt'].dt.month == mes_sel) & (df['data_dt'].dt.year == ano_sel)]
else:
    df_mes = pd.DataFrame()

# --- 1. DASHBOARD ---
if menu == "Dashboard":
    st.title("📊 Visão Geral")
    if not df_mes.empty:
        total = df_mes['valor'].sum()
        budget = 2500.00 # Exemplo fixo
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Total Gasto", f"R$ {total:,.2f}")
        c2.metric("Disponível", f"R$ {budget - total:,.2f}")
        c3.metric("Lançamentos", len(df_mes))
        
        g1, g2 = st.columns(2)
        with g1:
            fig = px.pie(df_mes, values='valor', names='categoria', hole=0.4, title="Por Categoria")
            st.plotly_chart(fig, use_container_width=True)
        with g2:
            dia_a_dia = df_mes.groupby(df_mes['data_dt'].dt.day)['valor'].sum().reset_index()
            fig2 = px.bar(dia_a_dia, x='data_dt', y='valor', title="Gasto Diário")
            st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("Sem dados neste mês.")

# --- 2. LANÇAMENTOS (CORRIGIDO E OTIMIZADO) ---
elif menu == "Lançamentos":
    st.title("🚀 Novo Lançamento")
    
    CATEGORIAS = {
        "Alimentação": ["iFood", "Mercado", "Restaurante", "Lanche"],
        "Transporte": ["Uber", "Combustível", "Ônibus", "Manutenção"],
        "Lazer": ["Jogos", "Streaming", "Bar", "Viagem"],
        "Saúde": ["Farmácia", "Médico", "Academia"],
        "Investimentos": ["Aporte", "Cripto", "Reserva"],
        "Casa": ["Aluguel", "Contas", "Limpeza"],
        "Outros": [] 
    }

    if 'confirmacao_pendente' not in st.session_state:
        st.session_state['confirmacao_pendente'] = False

    with st.container(border=True):
        # --- INPUTS ---
        c_val, c_tipo = st.columns([1, 1])
        # Key 'novo_valor' é essencial para podermos resetar depois
        valor_texto = c_val.text_input("Valor (R$)", placeholder="Ex: 15,90", key="novo_valor")
        valor_final = limpar_valor_input(valor_texto)
        tipo_input = c_tipo.radio("Tipo", ["Despesa", "Receita"], horizontal=True)

        c_data, c_cat = st.columns([1, 2])
        data_sel = c_data.date_input("Data", date.today())
        
        cat_princ = c_cat.selectbox("Categoria", list(CATEGORIAS.keys()))
        cat_final = cat_princ
        
        # Subcategoria ou Input Manual
        if cat_princ == "Outros":
            nome_outro = st.text_input("Especifique:", key="nova_cat_outros")
            if nome_outro: cat_final = nome_outro
        else:
            c_sub, c_desc = st.columns(2)
            sub_cat = c_sub.selectbox("Detalhe", CATEGORIAS[cat_princ])
            cat_final = sub_cat # Salva o detalhe (ex: iFood)
            desc_input = c_desc.text_input("Descrição (Opcional)", key="nova_desc")

        st.markdown("---")

        # --- BOTÕES E LÓGICA DE CONFIRMAÇÃO ---
        if not st.session_state['confirmacao_pendente']:
            if st.button("💾 Verificar e Salvar", type="primary", use_container_width=True):
                if valor_final > 0:
                    st.session_state['confirmacao_pendente'] = True
                    st.rerun()
                else:
                    st.toast("⚠️ Digite um valor válido!", icon="❌")
        else:
            # Captura a hora AGORA (no momento da confirmação)
            agora = datetime.now().time()
            data_completa = datetime.combine(data_sel, agora)
            
            # Card de Confirmação
            st.info(f"Confirmar: **R$ {valor_final:,.2f}** em **{cat_final}**?")
            
            b1, b2 = st.columns(2)
            if b1.button("✅ CONFIRMAR", type="primary", use_container_width=True):
                try:
                    desc_final = desc_input if 'desc_input' in locals() and desc_input else cat_final
                    
                    salvar_transacao(user['id'], data_completa, cat_final, desc_final, valor_final, tipo_input, False)
                    
                    st.toast("Salvo com sucesso!", icon="🎉")
                    time.sleep(0.5)
                    
                    # --- RESET MÁGICO (Corrige o erro de sessão) ---
                    resetar_formulario()
                    st.rerun()
                    
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")
            
            if b2.button("❌ Cancelar", use_container_width=True):
                st.session_state['confirmacao_pendente'] = False
                st.rerun()

    # --- GRID RECENTE ---
    if not df_mes.empty:
        st.subheader("📋 Histórico do Mês")
        # Formatação bonita para tabela
        df_show = df_mes[['data_dt', 'categoria', 'descricao', 'valor']].copy()
        
        # Ajuste Visual da Data (dd/mm/yyyy HH:MM)
        df_show['data_dt'] = df_show['data_dt'].dt.strftime('%d/%m/%Y %H:%M')
        
        st.dataframe(
            df_show,
            column_config={
                "data_dt": "Data/Hora",
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f")
            },
            use_container_width=True,
            hide_index=True
        )

# --- 3. RELATÓRIOS & IA ---
elif menu == "Relatórios & IA":
    st.title("🤖 Consultoria Inteligente")
    if not df_mes.empty:
        st.write("A IA analisa seus dados do mês selecionado na barra lateral.")
        if st.button("Gerar Análise"):
            with st.spinner("Pensando..."):
                analise = analisar_financas(df_mes)
                st.markdown(analise)
    else:
        st.warning("Sem dados para analisar.")

# --- 4. SIMULADOR (Estilo BCB) ---
elif menu == "Simulador":
    st.title("📈 Aplicação com Depósitos Regulares")
    
    with st.container(border=True):
        st.markdown("### Simule a aplicação")
        
        # Layout em colunas para simular o form do BCB (Label na esq, Input na dir)
        
        # Linha 1: Meses
        c1a, c1b = st.columns([1, 2])
        c1a.markdown('<div class="calc-label">Número de meses:</div>', unsafe_allow_html=True)
        meses = c1b.number_input("Meses", min_value=1, value=12, label_visibility="collapsed")
        
        # Linha 2: Taxa
        c2a, c2b = st.columns([1, 2])
        c2a.markdown('<div class="calc-label">Taxa mensal (%):</div>', unsafe_allow_html=True)
        taxa = c2b.number_input("Taxa", min_value=0.01, value=0.80, step=0.01, label_visibility="collapsed")
        
        # Linha 3: Aporte
        c3a, c3b = st.columns([1, 2])
        c3a.markdown('<div class="calc-label">Valor depósito regular (R$):</div>', unsafe_allow_html=True)
        aporte = c3b.number_input("Aporte", min_value=0.0, value=200.0, step=50.0, label_visibility="collapsed")
        
        st.markdown("---")
        
        # Botões
        b_calc, b_limp = st.columns([1, 1])
        calcular = b_calc.button("Calcular", type="primary", use_container_width=True)
        
        # Lógica
        if calcular:
            df_calc, final = calcular_juros_compostos(meses, taxa, aporte)
            
            # Resultado
            st.markdown(f"""
            <div style="background-color: #1E1E1E; padding: 15px; border-radius: 10px; text-align: center; margin-top: 20px;">
                <p style="margin:0; font-size: 14px; color: #aaa;">Valor obtido ao final</p>
                <p class="calc-result">R$ {final:,.2f}</p>
                <p style="margin:0; font-size: 12px; color: #aaa;">Total investido: R$ {meses*aporte:,.2f} | Juros: R$ {final-(meses*aporte):,.2f}</p>
            </div>
            """, unsafe_allow_html=True)
            
            st.markdown("### Evolução")
            st.plotly_chart(px.area(df_calc, x="Mês", y="Saldo Total"), use_container_width=True)

