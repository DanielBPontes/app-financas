import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import google.generativeai as genai

# --- 1. Configuração Mobile-First ---
st.set_page_config(page_title="FinApp", page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# --- 2. CSS "App Nativo" (A Mágica acontece aqui) ---
st.markdown("""
<style>
    /* RESET GERAL */
    .stAppHeader {display:none !important;} /* Remove barra vermelha do Streamlit */
    .block-container {padding-top: 1rem !important; padding-bottom: 5rem !important;} /* Ajusta espaçamento */
    
    /* ESTILO DE NAVEGAÇÃO (SEGMENTED CONTROL - iOS Style) */
    div[role="radiogroup"] {
        flex-direction: row;
        justify-content: center;
        background-color: #1E1E1E;
        padding: 5px;
        border-radius: 12px;
        margin-bottom: 20px;
    }
    div[role="radiogroup"] label {
        background-color: transparent;
        border: none;
        padding: 10px 20px;
        border-radius: 8px;
        transition: 0.3s;
        text-align: center;
        flex-grow: 1;
        margin: 0 2px;
        cursor: pointer;
    }
    /* Item Selecionado */
    div[role="radiogroup"] label[data-checked="true"] {
        background-color: #00CC96 !important; /* Cor de Destaque */
        color: black !important;
        font-weight: bold;
        box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    /* Esconde as bolinhas do Radio Button */
    div[role="radiogroup"] div[data-testid="stMarkdownContainer"] p {
        font-size: 14px; /* Tamanho texto menu */
    }
    
    /* CARDS DE TRANSAÇÃO (Estilo Nubank) */
    .app-card {
        background-color: #262730;
        border-radius: 16px;
        padding: 16px;
        margin-bottom: 12px;
        box-shadow: 0 4px 6px rgba(0,0,0,0.1);
        border: 1px solid #333;
    }
    .card-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 5px; }
    .card-title { font-weight: 700; font-size: 16px; color: #FFF; }
    .card-meta { font-size: 12px; color: #AAA; }
    .card-amount { font-weight: 800; font-size: 16px; }
    
    /* Cores Semânticas */
    .txt-green { color: #00CC96; }
    .txt-red { color: #FF4B4B; }
    
    /* INPUTS OTIMIZADOS PARA DEDO */
    .stButton button {
        width: 100%;
        height: 50px; /* Área de toque segura */
        border-radius: 12px;
        font-weight: 600;
    }
    
    /* MENSAGENS CHAT */
    .stChatMessage { background-color: #262730; border-radius: 15px; border: none; }
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

def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'])
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

def executar_sql(acao, dados, user_id):
    try:
        tabela = supabase.table("transactions")
        if acao == 'insert':
            if 'id' in dados: del dados['id']
            tabela.insert(dados).execute()
        elif acao == 'update':
            if not dados.get('id'): return False
            payload = {k: v for k, v in dados.items() if k in ['valor', 'descricao', 'categoria', 'data', 'tipo']}
            tabela.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            tabela.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro: {e}")
        return False

def upload_comprovante(arquivo, user_id):
    try:
        nome = f"{user_id}_{int(time.time())}_{arquivo.name}"
        supabase.storage.from_("comprovantes").upload(nome, arquivo.getvalue(), {"content-type": arquivo.type})
        return supabase.storage.from_("comprovantes").get_public_url(nome)
    except: return None

# --- Agente IA V2 ---
def agente_financeiro_ia(texto_usuario, df_contexto):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['id', 'data', 'descricao', 'valor', 'categoria']].head(20).to_json(orient="records")

    prompt = f"""
    Agente SQL Mobile. Hoje: {date.today()}.
    Contexto: {contexto}
    User: "{texto_usuario}"
    
    Retorne JSON:
    {{
        "acao": "insert" | "update" | "delete" | "search" | "pergunta",
        "dados": {{ "id": int (se achar), "data": "YYYY-MM-DD", "valor": float, "categoria": "str", "descricao": "str", "tipo": "Receita/Despesa" }},
        "msg_ia": "Texto curto para mobile"
    }}
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest', generation_config={"response_mime_type": "application/json"})
        return json.loads(model.generate_content(prompt).text)
    except Exception as e: return {"acao": "erro", "msg": str(e)}

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None
if not st.session_state['user']:
    st.markdown("<br><br><h2 style='text-align:center'>FinApp Mobile</h2>", unsafe_allow_html=True)
    with st.form("login"):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            user = login_user(u, p)
            if user: st.session_state['user'] = user; st.rerun()
            else: st.error("Erro")
    st.stop()

# =======================================================
# NAVEGAÇÃO PRINCIPAL (SUBSTITUI SIDEBAR)
# =======================================================
user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 60)

# Menu Superior Horizontal (Estilo App)
# O CSS lá em cima transforma este Radio em botões visuais
selected_nav = st.radio("Navegação", ["💬 Chat", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")

st.markdown("---") # Divisor sutil

# --- TELA 1: CHAT ---
if selected_nav == "💬 Chat":
    if "messages" not in st.session_state: st.session_state.messages = []
    if "pending_op" not in st.session_state: st.session_state.pending_op = None

    # Histórico (Limpo)
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Input (Sticky Bottom Nativo do Streamlit)
    if not st.session_state.pending_op:
        if prompt := st.chat_input("Digite: Gastei 50 no Uber..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()

    # Processamento
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user" and not st.session_state.pending_op:
        with st.chat_message("assistant"):
            with st.spinner("🤖"):
                res = agente_financeiro_ia(st.session_state.messages[-1]["content"], df_total)
                if res['acao'] in ['insert', 'update', 'delete']:
                    st.session_state.pending_op = res
                    st.rerun()
                else:
                    msg = res.get('msg_ia', res.get('msg'))
                    st.markdown(msg)
                    st.session_state.messages.append({"role": "assistant", "content": msg})

    # Card de Confirmação (Estilo Mobile)
    if st.session_state.pending_op:
        op = st.session_state.pending_op
        d = op['dados']
        tipo = op['acao'].upper()
        
        with st.container():
            st.info(f"CONFIRMAR {tipo}?")
            # Preview Card
            st.markdown(f"""
            <div class="app-card">
                <div class="card-title">{d.get('descricao')}</div>
                <div class="card-amount">R$ {d.get('valor')}</div>
                <div class="card-meta">{d.get('categoria')} • {d.get('data')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            anexo = None
            if tipo == 'INSERT':
                anexo = st.file_uploader("📸 Foto (Opcional)", type=['jpg', 'pdf'])
            
            c1, c2 = st.columns(2)
            if c1.button("✅ Confirmar", type="primary"):
                url = None
                if anexo: url = upload_comprovante(anexo, user['id'])
                
                final_data = d.copy(); final_data['user_id'] = user['id']
                if url: final_data['comprovante_url'] = url
                
                if executar_sql(op['acao'], final_data, user['id']):
                    st.toast("Feito!", icon="✅")
                    st.session_state.messages.append({"role": "assistant", "content": "✅ Operação realizada."})
                else:
                    st.error("Erro SQL")
                
                st.session_state.pending_op = None
                time.sleep(1)
                st.rerun()
                
            if c2.button("❌ Cancelar"):
                st.session_state.pending_op = None
                st.rerun()

# --- TELA 2: EXTRATO (DASHBOARD) ---
elif selected_nav == "💳 Extrato":
    # Filtro Compacto (Expander para não poluir)
    with st.expander("📅 Filtrar Data", expanded=False):
        c1, c2 = st.columns(2)
        mes = c1.selectbox("Mês", range(1,13), index=date.today().month-1)
        ano = c2.number_input("Ano", 2024, 2030, date.today().year)

    # Dados do Mês
    if not df_total.empty:
        df_mes = df_total[(df_total['data_dt'].dt.month == mes) & (df_total['data_dt'].dt.year == ano)]
        
        # Resumo Cards (Side by Side Mobile friendly with CSS hack)
        rec = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        desp = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        
        col_a, col_b = st.columns(2)
        col_a.metric("Entrou", f"R$ {rec:.0f}")
        col_b.metric("Saiu", f"R$ {desp:.0f}", delta_color="inverse")
        st.caption(f"Saldo Líquido: R$ {rec - desp:.2f}")
        
        st.markdown("### Histórico")
        
        if df_mes.empty: st.info("Sem dados.")
        
        # Loop de Cards Otimizados
        for _, row in df_mes.iterrows():
            is_receita = row['tipo'] == 'Receita'
            cor_val = "txt-green" if is_receita else "txt-red"
            sinal = "+" if is_receita else "-"
            
            # HTML Puro para controle total do layout
            st.markdown(f"""
            <div class="app-card">
                <div class="card-header">
                    <span class="card-title">{row['descricao']}</span>
                    <span class="card-amount {cor_val}">{sinal} {row['valor']:.0f}</span>
                </div>
                <div class="card-header">
                    <span class="card-meta">{row['categoria']} • {row['data_dt'].strftime('%d/%m')}</span>
                    <span class="card-meta">#{row['id']}</span>
                </div>
            </div>
            """, unsafe_allow_html=True)
            
            # Ações escondidas no expander do próprio card? Não dá no HTML puro.
            # Solução UX: Botão de ação discreto abaixo do card se precisar excluir
            # Mas para manter limpo, deixamos a exclusão pelo Chat ("Apagar ID X") 
            # ou um botão simples aqui:
            c_del, c_view = st.columns([1, 4])
            if c_del.button("🗑️", key=f"del_{row['id']}"):
                executar_sql('delete', {'id': row['id']}, user['id'])
                st.toast("Apagado")
                time.sleep(0.5)
                st.rerun()
                
            if row.get('comprovante_url'):
                c_view.link_button("📎 Ver Anexo", row['comprovante_url'])

# --- TELA 3: ANÁLISE ---
elif selected_nav == "📈 Análise":
    st.subheader("Para onde foi o dinheiro?")
    if not df_total.empty:
        df_mes = df_total[df_total['data_dt'].dt.month == date.today().month]
        gastos = df_mes[df_mes['tipo'] != 'Receita']
        
        if not gastos.empty:
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.7, color_discrete_sequence=px.colors.qualitative.Pastel)
            fig.update_layout(legend=dict(orientation="h", yanchor="bottom", y=-0.2, xanchor="center", x=0.5))
            st.plotly_chart(fig, use_container_width=True)
            
            # Lista Top Gastos
            top_cats = gastos.groupby('categoria')['valor'].sum().sort_values(ascending=False).head(3)
            st.markdown("**Maiores Gastos:**")
            for cat, val in top_cats.items():
                st.progress(int(val/gastos['valor'].sum()*100), text=f"{cat}: R$ {val:.0f}")

# --- Rodapé Fixo (Sidebar usada apenas para Sair/Config) ---
with st.sidebar:
    st.title("Configurações")
    st.write(f"Logado como: {user['username']}")
    if st.button("Sair da Conta"):
        st.session_state.clear()
        st.rerun()
