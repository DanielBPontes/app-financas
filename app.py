import streamlit as st
import pandas as pd
from supabase import create_client, Client
from datetime import datetime, date
import time

# --- Configuração da Página ---
st.set_page_config(
    page_title="Finanças Pro", 
    page_icon="💳", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Conexão com Supabase ---
@st.cache_resource
def init_connection():
    url = st.secrets["supabase"]["url"]
    key = st.secrets["supabase"]["key"]
    return create_client(url, key)

supabase: Client = init_connection()

# --- Funções de Banco de Dados (CRUD) ---

def login_user(username, password):
    """Verifica credenciais no banco PostgreSQL"""
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        if len(response.data) > 0:
            return response.data[0] # Retorna o objeto do usuário (com ID)
        return None
    except Exception as e:
        st.error(f"Erro de conexão: {e}")
        return None

def carregar_transacoes(user_id):
    """Busca apenas as transações do usuário logado"""
    response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
    df = pd.DataFrame(response.data)
    if not df.empty:
        # Converter string de data para datetime objects
        df['data'] = pd.to_datetime(df['data']).dt.date
    return df

def salvar_transacao(user_id, data_gasto, categoria, descricao, valor, recorrente):
    data = {
        "user_id": user_id,
        "data": data_gasto.isoformat(),
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": recorrente
    }
    supabase.table("transactions").insert(data).execute()

def atualizar_banco_via_editor(edited_rows, original_df):
    """Processa as edições feitas na tabela visual"""
    # O st.data_editor retorna um dicionário com as mudanças.
    # É complexo processar updates em lote, então faremos iteração simples.
    
    # 1. Identificar linhas deletadas
    # (O Streamlit data_editor gerencia 'deleted_rows' se num_rows="dynamic")
    # Para simplificar este exemplo, focaremos na edição de valores existentes.
    
    # Loop pelas linhas editadas (índice do dataframe -> novas colunas)
    for idx, changes in edited_rows.items():
        # Pega o ID da transação na linha original
        transacao_id = original_df.iloc[idx]['id']
        
        # Prepara o payload de atualização
        payload = {}
        if "data" in changes: payload["data"] = changes["data"].isoformat() # Se for data, converte
        if "categoria" in changes: payload["categoria"] = changes["categoria"]
        if "descricao" in changes: payload["descricao"] = changes["descricao"]
        if "valor" in changes: payload["valor"] = float(changes["valor"])
        if "recorrente" in changes: payload["recorrente"] = changes["recorrente"]
        
        if payload:
            supabase.table("transactions").update(payload).eq("id", transacao_id).execute()

# --- CSS ---
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 24px; color: #00CC96; }
    div.stButton > button { width: 100%; border-radius: 5px; }
</style>
""", unsafe_allow_html=True)

# --- Gestão de Sessão ---
if 'user' not in st.session_state:
    st.session_state['user'] = None

# --- Tela de Login ---
if not st.session_state['user']:
    col1, col2, col3 = st.columns([1,2,1])
    with col2:
        st.title("🔒 Finanças Cloud")
        st.markdown("Acesse seus dados de qualquer lugar.")
        
        with st.form("login"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar")
            
            if submitted:
                user_data = login_user(username, password)
                if user_data:
                    st.session_state['user'] = user_data
                    st.rerun()
                else:
                    st.error("Usuário ou senha inválidos.")
    st.stop() # Para a execução aqui se não estiver logado

# =======================================================
# ÁREA LOGADA (O código abaixo só roda se tiver usuário)
# =======================================================

user = st.session_state['user']

# Sidebar
with st.sidebar:
    st.write(f"Usuário: **{user['username']}**")
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

st.title("💳 Painel Financeiro")

# Carregar Dados
df = carregar_transacoes(user['id'])

# --- Abas ---
tab1, tab2, tab3 = st.tabs(["📊 Dashboard & Edição", "📝 Novo Gasto", "🔁 Recorrentes"])

# --- ABA 1: Dashboard ---
with tab1:
    col1, col2, col3 = st.columns(3)
    
    if not df.empty:
        # Filtros de Data
        mes_atual = date.today().month
        df_mes = df[pd.to_datetime(df['data']).dt.month == mes_atual]
        
        total_mes = df_mes['valor'].sum()
        total_geral = df['valor'].sum()
        
        col1.metric("Gastos (Mês Atual)", f"R$ {total_mes:.2f}")
        col2.metric("Total Acumulado", f"R$ {total_geral:.2f}")
        col3.metric("Qtd. Lançamentos", len(df_mes))
        
        st.divider()
        st.subheader("📋 Editar Lançamentos")
        
        # Editor de Dados
        edited_df = st.data_editor(
            df,
            column_config={
                "id": None, # Esconde o ID
                "user_id": None, # Esconde o User ID
                "created_at": None,
                "valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "recorrente": st.column_config.CheckboxColumn(default=False),
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
            },
            hide_index=True,
            use_container_width=True,
            num_rows="fixed", # Edição de valores existentes (inserção na outra aba para segurança)
            key="editor_dados"
        )
        
        # Botão para salvar edições
        if st.button("💾 Salvar Alterações da Tabela"):
            # O Streamlit armazena o estado das edições na session_state
            edicoes = st.session_state["editor_dados"]["edited_rows"]
            
            if edicoes:
                with st.spinner("Atualizando banco de dados..."):
                    atualizar_banco_via_editor(edicoes, df)
                    st.success("Dados atualizados!")
                    time.sleep(1)
                    st.rerun()
            else:
                st.info("Nenhuma alteração detectada.")
            
    else:
        st.info("Nenhum dado encontrado. Faça seu primeiro lançamento na aba ao lado!")

# --- ABA 2: Novo Lançamento ---
with tab2:
    st.subheader("Adicionar Despesa")
    with st.form("entry_form", clear_on_submit=True):
        c1, c2 = st.columns(2)
        data_input = c1.date_input("Data", date.today())
        valor_input = c2.number_input("Valor", min_value=0.01, step=10.0, format="%.2f")
        
        cat_input = c1.selectbox("Categoria", ["Alimentação", "Transporte", "Lazer", "Casa", "Outros"])
        desc_input = c2.text_input("Descrição")
        recorrente_input = st.checkbox("Recorrente?")
        
        if st.form_submit_button("Lançar"):
            try:
                salvar_transacao(user['id'], data_input, cat_input, desc_input, valor_input, recorrente_input)
                st.success("✅ Salvo no Supabase!")
                time.sleep(1)
                st.rerun()
            except Exception as e:
                st.error(f"Erro ao salvar: {e}")

# --- ABA 3: Recorrentes ---
with tab3:
    st.subheader("Contas Fixas")
    if not df.empty:
        fixos = df[df['recorrente'] == True]
        if not fixos.empty:
            st.dataframe(fixos[['data', 'categoria', 'descricao', 'valor']], hide_index=True)
            st.markdown(f"**Total Fixo Estimado:** R$ {fixos['valor'].sum():.2f}")
        else:
            st.write("Sem contas recorrentes.")
