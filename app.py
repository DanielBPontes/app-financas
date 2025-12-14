import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import google.generativeai as genai

# --- Configuração da Página ---
st.set_page_config(page_title="Finanças Chat Pro", page_icon="💳", layout="wide")

# --- CSS PRO (Estilo Mobile/App) ---
st.markdown("""
<style>
    /* Remover cabeçalho padrão */
    .stAppHeader {display:none;}
    
    /* Área do Chat */
    .stChatMessage { padding: 1rem; border-radius: 12px; margin-bottom: 10px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
    
    /* Card de Transação (Estilo Nubank/App) */
    .transaction-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 12px;
        margin-bottom: 12px;
        display: flex;
        align-items: center;
        justify-content: space-between;
        border-left: 5px solid #4B4B4B;
        transition: transform 0.2s;
    }
    .transaction-card:hover { transform: scale(1.01); }
    
    .t-icon { font-size: 24px; margin-right: 15px; width: 40px; text-align: center; }
    .t-info { flex-grow: 1; }
    .t-desc { font-weight: 600; font-size: 16px; display: block; }
    .t-date { font-size: 12px; color: #A0A0A0; }
    .t-value { font-weight: bold; font-size: 16px; }
    
    /* Cores por tipo */
    .despesa { border-left-color: #FF4B4B !important; }
    .receita { border-left-color: #00CC96 !important; }
    .val-despesa { color: #FF4B4B; }
    .val-receita { color: #00CC96; }

    /* Botões de Ação */
    .stButton button { width: 100%; border-radius: 8px; font-weight: bold; }
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

# --- Mapeamento de Ícones ---
ICONS = {
    "Alimentação": "🍔", "Transporte": "🚗", "Lazer": "🎉", 
    "Saúde": "💊", "Investimentos": "📈", "Casa": "🏠", 
    "Outros": "📦", "Receita": "💰"
}

# --- Backend Functions ---
def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except: return None

def carregar_transacoes(user_id):
    try:
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'])
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

def upload_imagem(arquivo, user_id):
    """Faz upload para o bucket 'comprovantes' no Supabase"""
    try:
        nome_arquivo = f"{user_id}/{int(time.time())}_{arquivo.name}"
        arquivo_bytes = arquivo.getvalue()
        supabase.storage.from_("comprovantes").upload(nome_arquivo, arquivo_bytes, {"content-type": arquivo.type})
        # Retorna a URL pública
        url = supabase.storage.from_("comprovantes").get_public_url(nome_arquivo)
        return url
    except Exception as e:
        st.error(f"Erro upload: {e}")
        return None

def salvar_transacao(user_id, dados, url_anexo=None):
    data = {
        "user_id": user_id,
        "data": dados['data'],
        "categoria": dados['categoria'],
        "descricao": dados['descricao'],
        "valor": float(dados['valor']),
        "tipo": dados.get('tipo', 'Despesa'),
        "comprovante_url": url_anexo # Precisa criar essa coluna no Supabase se não existir
    }
    supabase.table("transactions").insert(data).execute()

# --- CÉREBRO DO CHAT (IA) ---
def interpretar_comando_chat(texto_usuario):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off."}
    data_hoje = date.today().strftime("%Y-%m-%d")
    
    prompt = f"""
    Hoje: {data_hoje}. User: "{texto_usuario}"
    Categorias: Alimentação, Transporte, Lazer, Saúde, Investimentos, Casa, Outros.
    
    Se faltar valor: {{"acao": "pergunta", "msg": "qual valor?"}}
    Se ok: {{"acao": "confirmar_dados", "dados": {{ "data": "YYYY-MM-DD", "valor": 0.00, "categoria": "X", "descricao": "Y", "tipo": "Despesa/Receita" }} }}
    Responda JSON puro.
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        resp = model.generate_content(prompt)
        return json.loads(resp.text.replace('```json','').replace('```','').strip())
    except Exception as e: return {"acao": "erro", "msg": str(e)}

# --- Componente Visual de Card ---
def render_card(row):
    tipo_class = "receita" if row['tipo'] == "Receita" else "despesa"
    val_class = "val-receita" if row['tipo'] == "Receita" else "val-despesa"
    icon = ICONS.get(row['categoria'], "💸")
    data_fmt = row['data_dt'].strftime("%d/%m")
    
    html = f"""
    <div class="transaction-card {tipo_class}">
        <div class="t-icon">{icon}</div>
        <div class="t-info">
            <span class="t-desc">{row['descricao']}</span>
            <span class="t-date">{data_fmt} • {row['categoria']}</span>
        </div>
        <div class="t-value {val_class}">R$ {row['valor']:.2f}</div>
    </div>
    """
    st.markdown(html, unsafe_allow_html=True)
    if pd.notna(row.get('comprovante_url')) and row['comprovante_url']:
        with st.expander("Ver Comprovante"):
            st.image(row['comprovante_url'], width=200)

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        st.title("🔒 Login")
        with st.form("login"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
                user = login_user(u, p)
                if user:
                    st.session_state['user'] = user
                    st.rerun()
                else: st.error("Acesso negado.")
    st.stop()

# =======================================================
# APP PRINCIPAL
# =======================================================
user = st.session_state['user']

# Sidebar
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/3135/3135715.png", width=50)
    st.markdown(f"Olá, **{user['username']}**")
    menu = st.radio("Menu", ["Chat & Lançamento", "Extrato Visual", "Análises"], label_visibility="collapsed")
    
    st.divider()
    if st.button("Sair", icon="🚪"):
        st.session_state.clear()
        st.rerun()

# --- ESTADOS DO CHAT ---
if "chat_history" not in st.session_state: st.session_state.chat_history = []
if "temp_transaction" not in st.session_state: st.session_state.temp_transaction = None
if "flow_step" not in st.session_state: st.session_state.flow_step = "listening" # listening, confirming, uploading

# 1. CHAT INTELIGENTE COM FLUXO DE ANEXO
if menu == "Chat & Lançamento":
    st.title("💬 Lançamento Inteligente")
    
    # Renderiza Histórico
    for msg in st.session_state.chat_history:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --- FLUXO 1: Escutando (Input Normal) ---
    if st.session_state.flow_step == "listening":
        if prompt := st.chat_input("Ex: Almoço 45 reais..."):
            st.session_state.chat_history.append({"role": "user", "content": prompt})
            st.rerun() # Rerun para mostrar msg do user logo

        # Processamento após rerun
        if st.session_state.chat_history and st.session_state.chat_history[-1]["role"] == "user":
            last_msg = st.session_state.chat_history[-1]["content"]
            
            # Só processa se ainda não tiver uma transação pendente engatilhada
            if st.session_state.temp_transaction is None:
                with st.spinner("Interpretando..."):
                    res = interpretar_comando_chat(last_msg)
                    
                    if res['acao'] == 'confirmar_dados':
                        # SALVA NA MEMÓRIA TEMPORÁRIA
                        st.session_state.temp_transaction = res['dados']
                        st.session_state.flow_step = "confirming"
                        st.session_state.chat_history.append({"role": "assistant", "content": f"Entendi: **{res['dados']['categoria']} - R$ {res['dados']['valor']}**. Deseja anexar comprovante?"})
                        st.rerun()
                    
                    elif res['acao'] == 'pergunta':
                        st.session_state.chat_history.append({"role": "assistant", "content": res['msg']})
                    else:
                        st.session_state.chat_history.append({"role": "assistant", "content": "Não entendi."})

    # --- FLUXO 2: Decisão de Anexo (Botões) ---
    elif st.session_state.flow_step == "confirming":
        # Container fixo no final para os botões não sumirem
        with st.container():
            col_a, col_b = st.columns(2)
            
            if col_a.button("📸 Sim, anexar foto", type="primary", use_container_width=True):
                st.session_state.flow_step = "uploading"
                st.rerun()
                
            if col_b.button("💾 Não, salvar sem anexo", use_container_width=True):
                # Salva direto
                dados = st.session_state.temp_transaction
                salvar_transacao(user['id'], dados, None)
                st.session_state.chat_history.append({"role": "assistant", "content": "✅ Salvo com sucesso!"})
                # Reseta
                st.session_state.temp_transaction = None
                st.session_state.flow_step = "listening"
                st.rerun()

    # --- FLUXO 3: Upload ---
    elif st.session_state.flow_step == "uploading":
        st.info("Faça o upload do comprovante abaixo:")
        uploaded_file = st.file_uploader("Escolha a imagem", type=['png', 'jpg', 'jpeg', 'pdf'])
        
        if uploaded_file is not None:
            if st.button("Confirmar Upload e Salvar", type="primary"):
                with st.spinner("Enviando imagem..."):
                    url = upload_imagem(uploaded_file, user['id'])
                    dados = st.session_state.temp_transaction
                    salvar_transacao(user['id'], dados, url)
                    
                    st.session_state.chat_history.append({"role": "assistant", "content": "✅ Salvo com comprovante!"})
                    st.session_state.temp_transaction = None
                    st.session_state.flow_step = "listening"
                    st.rerun()
        
        if st.button("Cancelar anexo"):
             st.session_state.flow_step = "confirming"
             st.rerun()

# 2. EXTRATO VISUAL (UI APRIMORADA)
elif menu == "Extrato Visual":
    st.title("💳 Extrato")
    
    # Filtros
    c1, c2 = st.columns([2,1])
    mes_atual = date.today().month
    mes = c1.slider("Mês", 1, 12, mes_atual)
    
    df = carregar_transacoes(user['id'])
    
    if not df.empty:
        df_filtered = df[df['data_dt'].dt.month == mes]
        
        # Resumo do Mês
        total_desp = df_filtered[df_filtered['tipo']!='Receita']['valor'].sum()
        total_rec = df_filtered[df_filtered['tipo']=='Receita']['valor'].sum()
        saldo = total_rec - total_desp
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Receitas", f"R$ {total_rec:.2f}")
        k2.metric("Despesas", f"R$ {total_desp:.2f}")
        k3.metric("Saldo", f"R$ {saldo:.2f}", delta_color="normal")
        
        st.markdown("### Últimos Lançamentos")
        st.markdown("---")
        
        if df_filtered.empty:
            st.info("Sem lançamentos neste mês.")
        else:
            # RENDERIZAÇÃO DOS CARDS (O LOOP MÁGICO)
            for index, row in df_filtered.iterrows():
                render_card(row)
    else:
        st.warning("Nenhuma transação encontrada.")

# 3. ANÁLISES (Mantido Simples)
elif menu == "Análises":
    st.title("📊 Gráficos")
    df = carregar_transacoes(user['id'])
    if not df.empty:
        gastos = df[df['tipo'] != 'Receita']
        fig = px.bar(gastos, x='categoria', y='valor', color='categoria', title="Gastos por Categoria")
        st.plotly_chart(fig, use_container_width=True)
