import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import google.generativeai as genai

# --- Configuração da Página (Mobile First) ---
st.set_page_config(page_title="FinApp", page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# --- CSS: Otimização Mobile e Visual App ---
st.markdown("""
<style>
    /* Esconde elementos padrão do Streamlit que poluem o mobile */
    .stAppHeader, .stToolbar {display:none !important;}
    
    /* Ajuste das Abas para parecerem menu de App */
    .stTabs [data-baseweb="tab-list"] {
        gap: 2px;
        background-color: #0e1117;
        position: sticky;
        top: 0;
        z-index: 999;
        padding-top: 10px;
    }
    .stTabs [data-baseweb="tab"] {
        height: 50px;
        white-space: pre-wrap;
        background-color: #262730;
        border-radius: 5px 5px 0px 0px;
        gap: 1px;
        padding-top: 10px;
        padding-bottom: 10px;
        flex-grow: 1; /* Força ocupar largura total no mobile */
        text-align: center;
    }
    .stTabs [aria-selected="true"] {
        background-color: #FF4B4B !important;
        color: white !important;
    }

    /* Cards de Transação */
    .card-container {
        background-color: #262730;
        padding: 12px;
        border-radius: 12px;
        margin-bottom: 10px;
        border: 1px solid #363945;
    }
    .card-top { display: flex; justify-content: space-between; align-items: center; }
    .card-desc { font-weight: 600; font-size: 16px; }
    .card-sub { font-size: 12px; color: #a0a0a0; }
    .val-rec { color: #00CC96; font-weight: bold; }
    .val-desp { color: #FF4B4B; font-weight: bold; }
    
    /* Botões Grandes para Dedo */
    .stButton button { min-height: 45px; border-radius: 10px; }
</style>
""", unsafe_allow_html=True)

# --- Conexões ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except: return None

supabase: Client = init_connection()

try:
    if "gemini" in st.secrets:
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
        IA_AVAILABLE = True
    else: IA_AVAILABLE = False
except: IA_AVAILABLE = False

# --- Backend Functions ---
def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except: return None

def carregar_transacoes(user_id):
    try:
        # Pega as últimas 50 para o contexto da IA ser rápido
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).limit(50).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'])
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

def executar_sql(acao, dados, user_id):
    """Função Mestra de CRUD"""
    try:
        tabela = supabase.table("transactions")
        
        if acao == 'insert':
            del dados['id'] # Garante que não tenta inserir ID
            tabela.insert(dados).execute()
            
        elif acao == 'update':
            id_transacao = dados.get('id')
            if not id_transacao: return False
            # Remove campos que não devem ser atualizados
            payload = {k: v for k, v in dados.items() if k in ['valor', 'descricao', 'categoria', 'data', 'tipo']}
            tabela.update(payload).eq("id", id_transacao).eq("user_id", user_id).execute()
            
        elif acao == 'delete':
            id_transacao = dados.get('id')
            tabela.delete().eq("id", id_transacao).eq("user_id", user_id).execute()
            
        return True
    except Exception as e:
        st.error(f"Erro SQL ({acao}): {e}")
        return False

def upload_comprovante(arquivo, user_id):
    try:
        nome = f"{user_id}_{int(time.time())}_{arquivo.name}"
        supabase.storage.from_("comprovantes").upload(nome, arquivo.getvalue(), {"content-type": arquivo.type})
        return supabase.storage.from_("comprovantes").get_public_url(nome)
    except: return None

# --- IA: Cérebro Avançado ---
def agente_financeiro_ia(texto_usuario, df_contexto):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    # Prepara contexto (JSON das últimas transações para a IA "ver" o que editar)
    contexto_json = "[]"
    if not df_contexto.empty:
        # Passa apenas colunas essenciais para economizar tokens e não confundir
        cols = ['id', 'data', 'descricao', 'valor', 'categoria']
        contexto_json = df_contexto[cols].head(15).to_json(orient="records")

    prompt = f"""
    Você é um assistente financeiro (Agente SQL).
    Hoje: {date.today()}.
    
    CONTEXTO (Últimas transações do usuário):
    {contexto_json}
    
    USUÁRIO DISSE: "{texto_usuario}"
    
    SUA MISSÃO:
    Identifique a intenção: 'insert' (novo), 'update' (editar existente), 'delete' (apagar) ou 'search' (buscar/responder).
    
    1. INSERT: Extraia dados.
    2. UPDATE/DELETE: Procure no CONTEXTO qual ID o usuário quer alterar (pela descrição/valor/data). Se achar, retorne o ID.
    3. SEARCH: Se o usuário perguntar "quanto gastei com X", responda em 'msg_ia'.
    
    SCHEMA JSON RESPOSTA (Obrigatório):
    {{
        "acao": "insert" | "update" | "delete" | "search" | "pergunta",
        "dados": {{
            "id": int (obrigatório para update/delete),
            "data": "YYYY-MM-DD",
            "valor": 0.00,
            "categoria": "Str",
            "descricao": "Str",
            "tipo": "Receita" | "Despesa"
        }},
        "msg_ia": "Explicação para o usuário"
    }}
    
    Se não achar a transação para editar/apagar no contexto, devolva acao="pergunta" e msg_ia="Não achei essa transação.".
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest', generation_config={"response_mime_type": "application/json"})
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        return {"acao": "erro", "msg": str(e)}

# =======================================================
# LOGIN (Mantido Simples)
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    c1, c2, c3 = st.columns([1,8,1])
    with c2:
        st.markdown("<h1 style='text-align: center;'>💸 FinApp</h1>", unsafe_allow_html=True)
        with st.form("login"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
                user = login_user(u, p)
                if user:
                    st.session_state['user'] = user
                    st.rerun()
                else: st.error("Erro.")
    st.stop()

# =======================================================
# APP PRINCIPAL (Layout Mobile por Abas)
# =======================================================
user = st.session_state['user']
df_total = carregar_transacoes(user['id'])

# NAVEGAÇÃO SUPERIOR (Substitui Sidebar)
tab_chat, tab_dash, tab_perfil = st.tabs(["💬 Chat IA", "📊 Extrato", "⚙️ Perfil"])

# --- ABA 1: CHAT COM PODERES DE EDIÇÃO ---
with tab_chat:
    if "messages" not in st.session_state: st.session_state.messages = []
    if "pending_op" not in st.session_state: st.session_state.pending_op = None # Armazena operação pendente

    # Histórico
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Input (Se não houver pendência)
    if not st.session_state.pending_op:
        if prompt := st.chat_input("Ex: Gastei 20 no mc, ou 'Mude o Mcdonalds para 30'"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()

    # Cérebro
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user" and not st.session_state.pending_op:
        with st.chat_message("assistant"):
            with st.spinner("🤖 Processando..."):
                last_msg = st.session_state.messages[-1]["content"]
                # Envia DF recente para IA ter contexto
                res = agente_financeiro_ia(last_msg, df_total)
                
                if res['acao'] in ['insert', 'update', 'delete']:
                    st.session_state.pending_op = res
                    st.rerun()
                
                elif res['acao'] == 'search':
                    # IA apenas responde (ex: "Você gastou 500 em uber")
                    st.markdown(res['msg_ia'])
                    st.session_state.messages.append({"role": "assistant", "content": res['msg_ia']})
                
                else: # Pergunta ou Erro
                    st.markdown(res.get('msg_ia', res.get('msg')))
                    st.session_state.messages.append({"role": "assistant", "content": res.get('msg_ia', 'Erro')})

    # Confirmação de Operação (Insert, Update, Delete)
    if st.session_state.pending_op:
        op = st.session_state.pending_op
        tipo_op = op['acao'].upper()
        dados = op['dados']
        
        with st.chat_message("assistant"):
            st.markdown(f"**Confirme a operação: {tipo_op}**")
            
            # Card de Preview
            st.info(f"""
            🆔 ID: {dados.get('id', 'Novo')}
            📅 Data: {dados.get('data')}
            📝 Desc: {dados.get('descricao')}
            💵 Valor: R$ {dados.get('valor')}
            """)
            
            # Upload apenas se for INSERT
            url_anexo = None
            if op['acao'] == 'insert':
                arquivo = st.file_uploader("Anexo (Opcional)", type=['jpg', 'pdf'], key="anexo_chat")
                if arquivo: url_anexo = "uploading..." # Flag placeholder

            c_sim, c_nao = st.columns(2)
            
            if c_sim.button("✅ Confirmar", type="primary", use_container_width=True):
                # Upload real
                if op['acao'] == 'insert' and 'arquivo' in locals() and arquivo:
                    url_anexo = upload_comprovante(arquivo, user['id'])
                
                # Executa SQL
                dados_finais = dados.copy()
                dados_finais['user_id'] = user['id']
                if url_anexo: dados_finais['comprovante_url'] = url_anexo
                
                if executar_sql(op['acao'], dados_finais, user['id']):
                    st.session_state.messages.append({"role": "assistant", "content": f"✅ Sucesso! ({op['msg_ia']})"})
                    st.toast(f"{tipo_op} Realizado!", icon="🚀")
                else:
                    st.session_state.messages.append({"role": "assistant", "content": "❌ Erro no banco de dados."})
                
                st.session_state.pending_op = None
                time.sleep(1)
                st.rerun()
                
            if c_nao.button("❌ Cancelar", use_container_width=True):
                st.session_state.pending_op = None
                st.session_state.messages.append({"role": "assistant", "content": "Cancelado."})
                st.rerun()

# --- ABA 2: EXTRATO VISUAL ---
with tab_dash:
    if not df_total.empty:
        # Filtros Compactos
        c_mes, c_ano = st.columns(2)
        mes_sel = c_mes.selectbox("Mês", range(1,13), index=date.today().month-1, label_visibility="collapsed")
        ano_sel = c_ano.number_input("Ano", 2024, 2030, date.today().year, label_visibility="collapsed")
        
        # Filtra Data
        df_mes = df_total[(df_total['data_dt'].dt.month == mes_sel) & (df_total['data_dt'].dt.year == ano_sel)]
        
        # Dashboard Cards
        rec = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        desp = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        saldo = rec - desp
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Entrada", f"{rec:.0f}") # Remove centavos no card mobile pra caber
        k2.metric("Saída", f"{desp:.0f}")
        k3.metric("Saldo", f"{saldo:.0f}", delta_color="normal")
        
        st.markdown("---")
        
        # Lista de Cards (Extrato)
        if df_mes.empty:
            st.info("Nada aqui.")
        else:
            df_show = df_mes.sort_values(by="data_dt", ascending=False)
            
            for i, row in df_show.iterrows():
                tipo_cor = "val-rec" if row['tipo'] == 'Receita' else "val-desp"
                sinal = "+" if row['tipo'] == 'Receita' else "-"
                
                # HTML Card Personalizado
                st.markdown(f"""
                <div class="card-container">
                    <div class="card-top">
                        <span class="card-desc">{row['descricao']}</span>
                        <span class="{tipo_cor}">{sinal} R$ {row['valor']:.2f}</span>
                    </div>
                    <div class="card-top">
                        <span class="card-sub">{row['categoria']} • {row['data_dt'].strftime('%d/%m')}</span>
                        <span class="card-sub">ID: {row['id']}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
                
                # Ações Rápidas (Expander para não poluir)
                with st.expander("Opções / Anexo"):
                    if row.get('comprovante_url'):
                        st.image(row['comprovante_url'], width=150)
                    
                    if st.button("🗑️ Excluir", key=f"del_{row['id']}", use_container_width=True):
                        executar_sql('delete', {'id': row['id']}, user['id'])
                        st.toast("Apagado!")
                        time.sleep(1)
                        st.rerun()

# --- ABA 3: PERFIL & CONFIG ---
with tab_perfil:
    st.markdown(f"### 👤 {user['username']}")
    st.info(f"ID Usuário: `{user['id']}`")
    
    st.markdown("---")
    if st.button("🚪 Sair da Conta", type="primary", use_container_width=True):
        st.session_state.clear()
        st.rerun()
