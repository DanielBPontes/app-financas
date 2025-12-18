import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date, timedelta
import json
import google.generativeai as genai
import time  # <--- 1. CORREÇÃO: Import necessário para time.sleep()

# --- 1. Configuração Mobile-First ---
st.set_page_config(page_title="AppFinanças", page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# --- 2. CSS Otimizado ---
st.markdown("""
<style>
    /* Ocultar Barra Lateral e Cabeçalho do Streamlit */
    section[data-testid="stSidebar"] {display: none !important;}
    .stAppHeader {display:none !important;} 
    .stDeployButton {display:none !important;}
    
    /* Layout Mobile */
    .block-container {
        padding-top: 1rem !important; 
        padding-bottom: 5rem !important; 
        padding-left: 0.5rem !important; 
        padding-right: 0.5rem !important;
    }
    
    /* MENU DE NAVEGAÇÃO (Pills Horizontais) */
    div[role="radiogroup"] {
        display: flex; 
        flex-direction: row; /* Garante direção horizontal */
        justify-content: space-between; /* Espalha os itens */
        background-color: #1E1E1E; 
        padding: 4px; 
        border-radius: 12px; 
        margin-bottom: 15px;
        width: 100%;
    }
    div[role="radiogroup"] label {
        flex: 1; /* Faz todos ocuparem o mesmo espaço */
        text-align: center; 
        background: transparent; border: none; 
        padding: 8px 4px; border-radius: 8px;
        cursor: pointer; color: #888; font-size: 0.9rem;
        margin: 0 2px;
    }
    div[role="radiogroup"] label[data-checked="true"] {
        background-color: #00CC96 !important; color: #000 !important;
        font-weight: 700; box-shadow: 0 2px 5px rgba(0,0,0,0.3);
    }
    
    /* CARDS GERAIS */
    .app-card {
        background-color: #262730; padding: 15px; border-radius: 16px;
        border: 1px solid #333; margin-bottom: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
    }
    
    /* INPUTS MAIORES (Touch Friendly) */
    .stButton button { width: 100%; height: 55px; border-radius: 12px; font-weight: 600; font-size: 1rem; }
    input { font-size: 16px !important; }

    /* STATUS FINANCEIRO */
    .budget-card {
        background: linear-gradient(135deg, #262730 0%, #1e1e1e 100%);
        padding: 20px; border-radius: 16px;
        border-left: 6px solid #00CC96; margin-bottom: 20px;
    }
</style>
""", unsafe_allow_html=True)

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

# --- Backend Functions ---
# 2. CORREÇÃO: Função ajustada para retornar as colunas certas para cada tabela
def carregar_dados_generico(tabela, user_id):
    colunas_padrao = ['id', 'descricao', 'valor', 'user_id', 'created_at']
    
    # Define colunas específicas se a tabela estiver vazia
    if tabela == 'goals':
        colunas_padrao = ['id', 'descricao', 'valor_alvo', 'valor_atual', 'data_limite', 'user_id']
    elif tabela == 'recurrent_expenses':
        colunas_padrao = ['id', 'descricao', 'valor', 'dia_vencimento', 'user_id']

    try:
        res = supabase.table(tabela).select("*").eq("user_id", user_id).execute()
        df = pd.DataFrame(res.data)
        
        if df.empty: 
            return pd.DataFrame(columns=colunas_padrao)
        return df
    except: 
        return pd.DataFrame(columns=colunas_padrao)

def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty: df['valor'] = pd.to_numeric(df['valor'])
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
            if not dados.get('id') or pd.isna(dados.get('id')): return False
            payload = {k: v for k, v in dados.items() if k not in ['user_id', 'created_at']}
            ref.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            ref.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro BD: {e}"); return False

def fmt_real(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA ---
def limpar_json(texto):
    texto = texto.replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['data', 'descricao', 'valor', 'categoria']].head(3).to_json(orient="records")

    prompt = f"""
    Contexto: {contexto}. Data Hoje: {date.today()}.
    Interprete: '{entrada}'.
    Se for gasto/receita, retorne JSON: {{ "acao": "insert", "dados": {{ "data": "YYYY-MM-DD", "valor": 0.00, "categoria": "Categoria", "descricao": "Curta", "tipo": "Despesa" }}, "msg_ia": "Texto curto" }}
    Se não, retorne: {{ "acao": "chat", "msg_ia": "Resposta curta" }}
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        if tipo_entrada == "audio":
            response = model.generate_content([prompt, {"mime_type": "audio/wav", "data": entrada.getvalue()}], generation_config={"response_mime_type": "application/json"})
        else:
            response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return limpar_json(response.text)
    except: return {"acao": "erro", "msg": "Erro IA"}

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    st.markdown("<br><br><h2 style='text-align:center'>🔒 AppFinanças</h2>", unsafe_allow_html=True)
    with st.container(border=True):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.button("Entrar", type="primary"):
            try:
                resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                if resp.data: st.session_state['user'] = resp.data[0]; st.rerun()
                else: st.error("Login Inválido")
            except: st.error("Erro Conexão")
    st.stop()

user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 200)

# =======================================================
# NAVEGAÇÃO PRINCIPAL (CORRIGIDA PARA HORIZONTAL)
# =======================================================
# 3. CORREÇÃO: Adicionado horizontal=True
selected_nav = st.radio(
    "Navegação", 
    ["💬 Chat", "💳 Extrato", "📈 Análise", "⚙️ Ajustes"], 
    label_visibility="collapsed",
    horizontal=True
)
st.markdown("<div style='margin-bottom:10px'></div>", unsafe_allow_html=True)

# =======================================================
# 1. CHAT (Lançamento Rápido)
# =======================================================
if selected_nav == "💬 Chat":
    if "msgs" not in st.session_state: st.session_state.msgs = [{"role": "assistant", "content": f"Oi, {user['username']}! O que gastou hoje?"}]
    if "op_pendente" not in st.session_state: st.session_state.op_pendente = None

    chat_container = st.container()
    with chat_container:
        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.markdown(m["content"])
    
    if st.session_state.op_pendente:
        op = st.session_state.op_pendente
        d = op.get('dados', {})
        st.markdown(f"""
        <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
            <h3 style="margin:0">{d.get('descricao')}</h3>
            <h1 style="margin:0">R$ {fmt_real(d.get('valor', 0))}</h1>
            <p style="margin:0; color:#888">{d.get('categoria')} • {d.get('data')}</p>
        </div>
        """, unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("✅ Salvar", type="primary"):
            executar_sql('transactions', 'insert', d, user['id'])
            st.toast("Salvo!"); st.session_state.op_pendente = None; st.rerun()
        if c2.button("❌ Cancelar"):
            st.session_state.op_pendente = None; st.rerun()
    
    else:
        st.markdown("---")
        col_a, col_b, col_c = st.columns(3)
        if col_a.button("☕ Café"): 
            st.session_state.msgs.append({"role": "user", "content": "Café R$ 5,00"})
            st.session_state.op_pendente = {"dados": {"descricao": "Café", "valor": 5.0, "categoria": "Alimentação", "tipo": "Despesa", "data": str(date.today())}}
            st.rerun()
            
        audio_val = st.audio_input("Voz", label_visibility="collapsed")
        text_val = st.chat_input("Ex: Almoço 30 reais")

        final_input, tipo = None, "texto"
        if text_val: final_input = text_val
        elif audio_val: final_input = audio_val; tipo = "audio"

        if final_input:
            user_msg = "🎤 *Áudio*" if tipo == "audio" else final_input
            st.session_state.msgs.append({"role": "user", "content": user_msg})
            with st.chat_message("assistant"):
                with st.spinner("..."):
                    res = agente_financeiro_ia(final_input, df_total, tipo)
                    if res.get('acao') == 'insert': st.session_state.op_pendente = res
                    else: st.session_state.msgs.append({"role": "assistant", "content": res.get('msg_ia')})
            st.rerun()

# =======================================================
# 2. EXTRATO
# =======================================================
elif selected_nav == "💳 Extrato":
    c1, c2 = st.columns([2, 1])
    mes_sel = c1.selectbox("Mês", range(1,13), index=date.today().month-1, label_visibility="collapsed")
    ano_sel = c2.number_input("Ano", 2024, 2030, date.today().year, label_visibility="collapsed")

    if not df_total.empty:
        df_total['data_dt'] = pd.to_datetime(df_total['data'], errors='coerce')
        df_mes = df_total[(df_total['data_dt'].dt.month == mes_sel) & (df_total['data_dt'].dt.year == ano_sel)].copy()
        
        gastos = df_mes[df_mes['tipo'] == 'Despesa']['valor'].sum()
        receitas = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        saldo = receitas - gastos

        st.markdown(f"""
        <div class="budget-card">
            <div style="display:flex; justify-content:space-between; margin-bottom:10px;">
                <span style="color:#FF4B4B">▼ Gastos</span>
                <span style="font-size:1.2em; font-weight:bold">R$ {fmt_real(gastos)}</span>
            </div>
            <div style="display:flex; justify-content:space-between;">
                <span style="color:#00CC96">▲ Receitas</span>
                <span style="font-size:1.2em; font-weight:bold">R$ {fmt_real(receitas)}</span>
            </div>
            <div style="margin-top:15px; padding-top:10px; border-top:1px solid #444; text-align:right">
                <small>Saldo:</small> <b style="color:{'#00CC96' if saldo >=0 else '#FF4B4B'}">R$ {fmt_real(saldo)}</b>
            </div>
        </div>
        """, unsafe_allow_html=True)

        df_edit = df_mes[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values('data', ascending=False)
        mudancas = st.data_editor(
            df_edit,
            column_config={
                "id": None,
                "valor": st.column_config.NumberColumn("R$", format="%.2f", width="small"),
                "descricao": st.column_config.TextColumn("Item", width="medium"),
                "data": None,
                "tipo": None,
                "categoria": st.column_config.SelectboxColumn("Cat", options=["Alimentação", "Transporte", "Casa", "Lazer", "Outros"], width="small")
            },
            hide_index=True, use_container_width=True, num_rows="dynamic", key="editor_extrato"
        )
        
        if st.button("💾 Salvar Alterações", type="primary"):
            ids_orig = df_edit['id'].tolist()
            ids_new = []
            
            for i, row in mudancas.iterrows():
                d = row.to_dict()
                if isinstance(d.get('data'), (date, datetime)): d['data'] = d['data'].strftime('%Y-%m-%d')
                
                if pd.isna(d.get('id')): 
                    if 'data' not in d or pd.isna(d['data']): d['data'] = str(date.today())
                    if 'tipo' not in d: d['tipo'] = 'Despesa'
                    executar_sql('transactions', 'insert', d, user['id'])
                else: 
                    ids_new.append(d['id'])
                    executar_sql('transactions', 'update', d, user['id'])
            
            for x in set(ids_orig) - set(ids_new):
                executar_sql('transactions', 'delete', {'id': x}, user['id'])
            st.rerun()

    else: st.info("Sem dados.")

# =======================================================
# 3. ANÁLISE
# =======================================================
elif selected_nav == "📈 Análise":
    st.subheader("Para onde foi o dinheiro?")
    
    if not df_total.empty:
        df_total['data_dt'] = pd.to_datetime(df_total['data'])
        df_chart = df_total[df_total['data_dt'].dt.month == date.today().month]
        df_chart = df_chart[df_chart['tipo'] == 'Despesa']
        
        if not df_chart.empty:
            fig = px.pie(df_chart, values='valor', names='categoria', hole=0.6, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=300, paper_bgcolor='rgba(0,0,0,0)')
            st.plotly_chart(fig, use_container_width=True)
            
            top_cats = df_chart.groupby('categoria')['valor'].sum().sort_values(ascending=False)
            for cat, val in top_cats.items():
                st.markdown(f"""
                <div style="background:#262730; padding:10px; border-radius:8px; margin-bottom:5px; display:flex; justify-content:space-between">
                    <span>{cat}</span>
                    <b>R$ {fmt_real(val)}</b>
                </div>
                """, unsafe_allow_html=True)
        else: st.info("Nada gasto este mês.")

# =======================================================
# 4. AJUSTES (ANTIGA SIDEBAR)
# =======================================================
elif selected_nav == "⚙️ Ajustes":
    st.subheader("Configurações")
    
    # 1. Metas
    with st.expander("🎯 Metas & Sonhos", expanded=True):
        # Garante que as colunas 'valor_alvo' e 'valor_atual' existam no DF
        df_metas = carregar_dados_generico("goals", user['id'])
        
        edit_metas = st.data_editor(
            df_metas,
            num_rows="dynamic",
            column_config={
                "id": None, "user_id": None, "created_at": None,
                "descricao": "Meta",
                "valor_alvo": st.column_config.NumberColumn("Alvo", format="R$ %.2f"),
                "valor_atual": st.column_config.NumberColumn("Guardado", format="R$ %.2f"),
                "data_limite": None 
            },
            key="editor_metas_adj",
            use_container_width=True
        )
        if st.button("Salvar Metas"):
            ids_orig = df_metas['id'].tolist() if not df_metas.empty else []
            ids_new = []
            
            for i, row in edit_metas.iterrows():
                d = row.to_dict()
                if pd.isna(d.get('id')): 
                    executar_sql('goals', 'insert', d, user['id'])
                else: 
                    ids_new.append(d['id'])
                    executar_sql('goals', 'update', d, user['id'])
            
            if not edit_metas.empty and 'id' in edit_metas.columns:
                 ids_new = edit_metas['id'].dropna().tolist()
                 
            for x in set(ids_orig) - set(ids_new):
                executar_sql('goals', 'delete', {'id': x}, user['id'])
            
            st.success("Atualizado!")
            time.sleep(1); st.rerun()

    # 2. Fixos
    with st.expander("🔄 Contas Fixas"):
        df_recorrente = carregar_dados_generico("recurrent_expenses", user['id'])
        edit_rec = st.data_editor(
            df_recorrente,
            num_rows="dynamic",
            column_config={
                "id": None, "user_id": None, "created_at": None,
                "descricao": "Conta",
                "valor": st.column_config.NumberColumn("R$", format="%.2f"),
                "dia_vencimento": st.column_config.NumberColumn("Dia", min_value=1, max_value=31)
            },
            key="editor_rec_adj",
            use_container_width=True
        )
        if st.button("Salvar Fixos"):
            ids_orig = df_recorrente['id'].tolist() if not df_recorrente.empty else []
            ids_new = []
            
            for i, row in edit_rec.iterrows():
                d = row.to_dict()
                if pd.isna(d.get('id')): executar_sql('recurrent_expenses', 'insert', d, user['id'])
                else: 
                    ids_new.append(d['id'])
                    executar_sql('recurrent_expenses', 'update', d, user['id'])
            
            if not edit_rec.empty and 'id' in edit_rec.columns:
                ids_new = edit_rec['id'].dropna().tolist()

            for x in set(ids_orig) - set(ids_new):
                executar_sql('recurrent_expenses', 'delete', {'id': x}, user['id'])
            st.success("Atualizado!")
            time.sleep(1); st.rerun()

    st.markdown("---")
    if st.button("Sair da Conta", type="secondary"):
        st.session_state.clear()
        st.rerun()
