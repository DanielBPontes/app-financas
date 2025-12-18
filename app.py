import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date, timedelta
import json
import google.generativeai as genai
import time

# --- 1. Configuração Mobile-First & Layout ---
st.set_page_config(
    page_title="AppFinanças",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CSS Profissional (Glassmorphism + Chat Customizado) ---
st.markdown("""
<style>
    /* Fundo Geral Dark Clean */
    .stApp {
        background-color: #0E1117;
        font-family: 'Inter', sans-serif;
    }

    /* Remove elementos nativos intrusivos */
    header {visibility: hidden;}
    .stDeployButton {display:none;}
    section[data-testid="stSidebar"] {display: none;}
    .block-container {padding-top: 1.5rem !important; max-width: 100% !important;}

    /* --- GLASSMORPHISM CARDS --- */
    div[data-testid="stMetric"], .glass-card {
        background: rgba(255, 255, 255, 0.03);
        border: 1px solid rgba(255, 255, 255, 0.08);
        padding: 20px;
        border-radius: 16px;
        backdrop-filter: blur(12px);
        box-shadow: 0 4px 20px rgba(0, 0, 0, 0.2);
        transition: all 0.3s ease;
    }
    div[data-testid="stMetric"]:hover, .glass-card:hover {
        transform: translateY(-3px);
        border-color: #00CC96;
        background: rgba(255, 255, 255, 0.06);
    }

    /* --- CHAT UI CUSTOMIZADA (Estilo WhatsApp/Telegram) --- */
    .chat-container {
        display: flex;
        flex-direction: column;
        gap: 15px;
        padding: 10px;
        max-height: 60vh;
        overflow-y: auto;
    }
    
    .msg-row {
        display: flex;
        width: 100%;
    }
    
    .msg-row.user {
        justify-content: flex-end;
    }
    
    .msg-row.bot {
        justify-content: flex-start;
    }
    
    .msg-bubble {
        padding: 12px 16px;
        border-radius: 12px;
        max-width: 80%;
        font-size: 0.95rem;
        line-height: 1.4;
        position: relative;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    
    .msg-bubble.user {
        background: linear-gradient(135deg, #00CC96 0%, #00a87d 100%);
        color: #000;
        border-bottom-right-radius: 2px;
        font-weight: 500;
    }
    
    .msg-bubble.bot {
        background: #262730;
        color: #fff;
        border: 1px solid #333;
        border-bottom-left-radius: 2px;
    }
    
    .avatar {
        width: 35px; height: 35px;
        border-radius: 50%;
        display: flex; align-items: center; justify-content: center;
        font-size: 1.2rem;
        margin: 0 8px;
        background: #333;
        border: 1px solid #444;
    }

    /* Inputs Modernos */
    .stTextInput input, .stNumberInput input, .stDateInput input, .stSelectbox div[data-baseweb="select"] {
        background-color: #1E1E1E !important;
        border: 1px solid #333 !important;
        border-radius: 10px !important;
        color: white !important;
    }
    
    /* Toast */
    div[data-baseweb="toast"] {
        background-color: #262730 !important;
        border: 1px solid #00CC96 !important;
    }
</style>
""", unsafe_allow_html=True)

# --- Utilitários ---
def fmt_real(valor):
    if valor is None or pd.isna(valor): return "0,00"
    return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Conexões ---
@st.cache_resource
def init_connection():
    try:
        return create_client(st.secrets["supabase"]["url"], st.secrets["supabase"]["key"])
    except: return None

supabase: Client = init_connection()

try:
    if "gemini" in st.secrets:
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
        IA_AVAILABLE = True
    else: IA_AVAILABLE = False
except: IA_AVAILABLE = False

# --- Backend & Callbacks ---

def carregar_dados_generico(tabela, user_id):
    # (Mantido igual ao seu, resumido para focar na mudança UI)
    try:
        res = supabase.table(tabela).select("*").eq("user_id", user_id).execute()
        df = pd.DataFrame(res.data)
        if tabela == 'goals':
            cols = ['id', 'descricao', 'valor_alvo', 'valor_atual', 'data_limite', 'user_id']
        elif tabela == 'recurrent_expenses':
            cols = ['id', 'descricao', 'valor_parcela', 'valor_total', 'parcelas_restantes', 'eh_infinito', 'dia_vencimento', 'user_id']
        else:
            cols = ['id', 'descricao', 'valor', 'user_id', 'created_at']
            
        if df.empty: df = pd.DataFrame(columns=cols)
        # Garantir colunas
        for c in cols: 
            if c not in df.columns: df[c] = None

        if tabela == 'goals':
            df['valor_alvo'] = pd.to_numeric(df['valor_alvo'], errors='coerce').fillna(0)
            df['valor_atual'] = pd.to_numeric(df['valor_atual'], errors='coerce').fillna(0)
            df['data_limite'] = pd.to_datetime(df['data_limite'], errors='coerce')
        return df
    except: return pd.DataFrame()

def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty: 
            df['valor'] = pd.to_numeric(df['valor'])
            df['data'] = pd.to_datetime(df['data']).dt.date
        else: return pd.DataFrame(columns=['id', 'data', 'descricao', 'valor', 'categoria', 'tipo', 'user_id'])
        return df
    except: return pd.DataFrame()

def executar_sql(tabela, acao, dados, user_id):
    try:
        ref = supabase.table(tabela)
        if acao == 'insert':
            if 'id' in dados and pd.isna(dados['id']): del dados['id']
            dados['user_id'] = user_id
            ref.insert(dados).execute()
        elif acao == 'update':
            if not dados.get('id'): return False
            payload = {k: v for k, v in dados.items() if k not in ['user_id', 'created_at']}
            ref.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            ref.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        print(e)
        return False

# --- FUNÇÃO MÁGICA DE AUTO-SAVE (CALLBACK) ---
def callback_auto_save():
    """Salva automaticamente alterações do DataEditor"""
    if "editor_extrato" not in st.session_state: return
    
    changes = st.session_state["editor_extrato"]
    user_id = st.session_state['user']['id']
    df_base = st.session_state['df_extrato_atual'] # DataFrame original antes da edição

    # 1. Edições
    for idx, updates in changes["edited_rows"].items():
        # Recupera o ID real da linha baseado no index
        row_id = df_base.iloc[idx]['id']
        updates['id'] = row_id
        
        # Conversão de data se necessário
        if 'data' in updates and isinstance(updates['data'], (date, datetime)):
            updates['data'] = str(updates['data'])
            
        executar_sql('transactions', 'update', updates, user_id)

    # 2. Adições
    for new_row in changes["added_rows"]:
        if 'tipo' not in new_row: new_row['tipo'] = 'Despesa'
        if 'data' not in new_row: new_row['data'] = str(date.today())
        executar_sql('transactions', 'insert', new_row, user_id)

    # 3. Remoções
    for idx in changes["deleted_rows"]:
        row_id = df_base.iloc[idx]['id']
        executar_sql('transactions', 'delete', {'id': row_id}, user_id)
    
    if changes["edited_rows"] or changes["added_rows"] or changes["deleted_rows"]:
        st.toast("💾 Salvo automaticamente!", icon="✅")


# --- IA ---
def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = df_contexto[['data', 'descricao', 'valor', 'categoria']].head(10).to_json(orient="records", date_format="iso") if not df_contexto.empty else "[]"
    
    prompt = f"""
    Você é um assistente financeiro. Contexto: {contexto}. Hoje: {date.today()}.
    Entrada: '{entrada}'.
    Se for gasto/receita, JSON: {{ "acao": "insert", "dados": {{ "data": "YYYY-MM-DD", "valor": 0.00, "categoria": "Categoria", "descricao": "Desc", "tipo": "Despesa/Receita" }}, "msg_ia": "Feito!" }}
    Se for conversa, JSON: {{ "acao": "chat", "msg_ia": "Resposta" }}
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        res = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(res.text)
    except: return {"acao": "erro", "msg": "Erro IA"}

def analisar_gastos_ia(df_mes):
    if not IA_AVAILABLE or df_mes.empty: return "Sem dados."
    prompt = f"Analise em 3 linhas com emojis (onde gastou, dica economia) esse CSV: {df_mes.to_csv(index=False)}"
    try:
        return genai.GenerativeModel('gemini-1.5-flash').generate_content(prompt).text
    except: return "Erro análise."

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<br><br><h1 style='text-align:center'>💳 Finanças IA</h1>", unsafe_allow_html=True)
        with st.form("login_form"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", type="primary"):
                try:
                    resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                    if resp.data: 
                        st.session_state['user'] = resp.data[0]; st.rerun()
                    else: st.error("Login Inválido")
                except: st.error("Erro Conexão")
    st.stop()

user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 300)

# =======================================================
# NAVEGAÇÃO
# =======================================================
# Navegação superior limpa
st.markdown('<div style="margin-top: -30px;"></div>', unsafe_allow_html=True)
selected_nav = st.radio(
    "Menu", ["💬 Chat", "💳 Extrato", "📊 Dashboard", "🎯 Metas"], 
    label_visibility="collapsed", horizontal=True
)
st.markdown("---")

# =======================================================
# 1. CHAT (NOVA UI/UX CUSTOMIZADA)
# =======================================================
if selected_nav == "💬 Chat":
    if "msgs" not in st.session_state: 
        st.session_state.msgs = [{"role": "assistant", "content": f"Olá! Como posso ajudar nas suas finanças hoje?"}]

    # --- Renderização Personalizada (HTML) ---
    chat_html = '<div class="chat-container">'
    for m in st.session_state.msgs:
        tipo = "user" if m["role"] == "user" else "bot"
        avatar = "👤" if tipo == "user" else "🤖"
        
        # Monta o HTML da bolha
        row_html = f"""
        <div class="msg-row {tipo}">
            {'<div class="avatar">' + avatar + '</div>' if tipo == 'bot' else ''}
            <div class="msg-bubble {tipo}">
                {m["content"]}
            </div>
            {'<div class="avatar">' + avatar + '</div>' if tipo == 'user' else ''}
        </div>
        """
        chat_html += row_html
    chat_html += '</div>'
    
    st.markdown(chat_html, unsafe_allow_html=True)

    # --- Área de Input Fixa ---
    st.markdown("<br>", unsafe_allow_html=True)
    with st.container():
        c1, c2 = st.columns([5, 1])
        with c1:
            prompt = st.chat_input("Digite ou mande um áudio...", key="chat_input_principal")
        with c2:
            # Simulação visual de Audio (funcionalidade depende do st.audio_input)
            audio = st.audio_input("🎤", label_visibility="collapsed")

    # Lógica de Processamento
    user_input = prompt if prompt else (audio if audio else None)
    tipo_input = "audio" if audio else "texto"

    if user_input:
        st.session_state.msgs.append({"role": "user", "content": "🎤 Áudio" if tipo_input == "audio" else user_input})
        
        # Feedback visual imediato
        with st.spinner("Processando..."):
            res = agente_financeiro_ia(user_input, df_total, tipo_input)
            
            if res.get('acao') == 'insert':
                # Salva a intenção de inserção para confirmação
                st.session_state.op_pendente = res
                st.session_state.msgs.append({"role": "assistant", "content": f"Entendi. Deseja salvar: **{res['dados']['descricao']}** (R$ {res['dados']['valor']})?"})
            else:
                st.session_state.msgs.append({"role": "assistant", "content": res.get('msg_ia', 'Erro.')})
        st.rerun()

    # Confirmação de Transação (Card Bonito)
    if st.session_state.get("op_pendente"):
        d = st.session_state.op_pendente['dados']
        st.markdown(f"""
        <div class="glass-card" style="border-left: 4px solid #00CC96; margin-top:10px;">
            <h3 style="margin:0">{d['descricao']}</h3>
            <h2 style="margin:0; color:#00CC96">R$ {fmt_real(d['valor'])}</h2>
            <p style="margin:0; color:#888">{d['categoria']} • {d['data']}</p>
        </div>
        """, unsafe_allow_html=True)
        
        cb1, cb2 = st.columns(2)
        if cb1.button("✅ Confirmar Salvar"):
            executar_sql('transactions', 'insert', d, user['id'])
            st.session_state.msgs.append({"role": "assistant", "content": "Salvo com sucesso! 💸"})
            st.session_state.op_pendente = None
            st.rerun()
        if cb2.button("❌ Cancelar"):
            st.session_state.msgs.append({"role": "assistant", "content": "Operação cancelada."})
            st.session_state.op_pendente = None
            st.rerun()

# =======================================================
# 2. EXTRATO (COM AUTO-SAVE)
# =======================================================
elif selected_nav == "💳 Extrato":
    col1, col2 = st.columns(2)
    mes_sel = col1.selectbox("Mês", range(1,13), index=date.today().month-1)
    ano_sel = col2.number_input("Ano", 2023, 2030, value=date.today().year)

    if not df_total.empty:
        df_total['data_dt'] = pd.to_datetime(df_total['data'])
        df_mes = df_total[(df_total['data_dt'].dt.month == mes_sel) & (df_total['data_dt'].dt.year == ano_sel)].copy()
        df_mes = df_mes.sort_values('data', ascending=False)
        
        # Cards KPI Glassmorphism
        g = df_mes[df_mes['tipo'] == 'Despesa']['valor'].sum()
        r = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        
        k1, k2, k3 = st.columns(3)
        k1.metric("Entradas", f"R$ {fmt_real(r)}", delta_color="normal")
        k2.metric("Saídas", f"R$ {fmt_real(g)}", delta_color="inverse")
        k3.metric("Saldo", f"R$ {fmt_real(r-g)}")
        
        # --- TABELA COM AUTO-SAVE ---
        # 1. Salvar o estado atual para o callback comparar
        st.session_state['df_extrato_atual'] = df_mes.reset_index(drop=True)
        
        st.data_editor(
            st.session_state['df_extrato_atual'],
            column_config={
                "id": None, "user_id": None, "created_at": None,
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "descricao": st.column_config.TextColumn("Descrição"),
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", min_value=0.0),
                "categoria": st.column_config.SelectboxColumn("Cat.", options=["Alimentação", "Transporte", "Casa", "Lazer", "Investimento"]),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Receita"])
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic",
            key="editor_extrato",          # Chave única
            on_change=callback_auto_save   # <--- O SEGREDO ESTÁ AQUI
        )
    else: st.info("Sem dados.")

# =======================================================
# 3. DASHBOARD
# =======================================================
elif selected_nav == "📊 Dashboard":
    st.subheader("Análise Visual")
    if not df_total.empty:
        df_chart = df_total[pd.to_datetime(df_total['data']).dt.month == date.today().month]
        
        c_graf1, c_graf2 = st.columns([2,1])
        with c_graf1:
            st.markdown("##### 📅 Fluxo Diário")
            df_day = df_chart[df_chart['tipo']=='Despesa'].groupby('data')['valor'].sum().reset_index()
            fig = px.bar(df_day, x='data', y='valor', color_discrete_sequence=['#FF4B4B'])
            fig.update_layout(template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)', height=250)
            st.plotly_chart(fig, use_container_width=True)
            
        with c_graf2:
            st.markdown("##### 🍕 Por Categoria")
            df_cat = df_chart[df_chart['tipo']=='Despesa'].groupby('categoria')['valor'].sum().reset_index()
            fig2 = px.pie(df_cat, values='valor', names='categoria', hole=0.7, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig2.update_layout(showlegend=False, template="plotly_dark", paper_bgcolor='rgba(0,0,0,0)', height=250, margin=dict(t=0,b=0,l=0,r=0))
            st.plotly_chart(fig2, use_container_width=True)
            
        if st.button("✨ Gerar Relatório IA"):
             st.info(analisar_gastos_ia(df_chart))

# =======================================================
# 4. METAS (Simplificado)
# =======================================================
elif selected_nav == "🎯 Metas":
    with st.expander("➕ Adicionar Meta"):
        with st.form("meta_add"):
            c1, c2 = st.columns(2)
            d = c1.text_input("Objetivo")
            v = c2.number_input("Valor Alvo", min_value=0.0)
            if st.form_submit_button("Salvar") and d:
                executar_sql('goals', 'insert', {'descricao':d, 'valor_alvo':v, 'valor_atual':0}, user['id'])
                st.rerun()
    
    df_metas = carregar_dados_generico('goals', user['id'])
    for _, row in df_metas.iterrows():
        p = min(1.0, row['valor_atual']/row['valor_alvo']) if row['valor_alvo'] > 0 else 0
        st.markdown(f"""
        <div class="glass-card" style="margin-bottom:10px;">
            <div style="display:flex; justify-content:space-between;">
                <b>{row['descricao']}</b>
                <span>{int(p*100)}%</span>
            </div>
            <div style="background:#444; height:8px; border-radius:4px; margin-top:5px;">
                <div style="width:{p*100}%; background:#00CC96; height:8px; border-radius:4px;"></div>
            </div>
        </div>
        """, unsafe_allow_html=True)

st.markdown("<br><br>", unsafe_allow_html=True)
if st.button("Sair", type="secondary"):
    st.session_state.clear()
    st.rerun()
