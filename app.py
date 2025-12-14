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

# --- CSS (Gambiarra de Otimização Mobile) ---
st.markdown("""
<style>
    /* 1. Esconde cabeçalho padrão para ganhar espaço no celular */
    .stAppHeader {display:none;}
    
    /* 2. Ajustes de Fonte e Espaçamento Mobile */
    .stChatMessage { padding: 1rem; border-radius: 12px; margin-bottom: 10px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }
    [data-testid="stMetricValue"] { font-size: 22px !important; font-weight: 800; }
    
    /* 3. Cards de Transação - Visual "App" */
    .icon-box { font-size: 24px; text-align: center; }
    .val-despesa { color: #FF4B4B; font-weight: bold; text-align: right; font-size: 15px; }
    .val-receita { color: #00CC96; font-weight: bold; text-align: right; font-size: 15px; }
    .card-desc { font-weight: 600; font-size: 15px; line-height: 1.2; }
    .card-sub { font-size: 12px; color: #888; }

    /* 4. Hack para Colunas Responsivas (Quebra linha no mobile) */
    @media (max-width: 640px) {
        [data-testid="column"] {
            width: 100% !important;
            flex: 1 1 auto !important;
            min-width: 100% !important;
        }
    }
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

# --- Backend Functions (CRUD Completo) ---
def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except: return None

def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        response = query.execute()
        
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'])
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

def executar_sql(acao, dados, user_id):
    """Realiza Insert, Update ou Delete"""
    try:
        tabela = supabase.table("transactions")
        
        if acao == 'insert':
            # Remove ID se existir para não dar erro de auto-incremento
            if 'id' in dados: del dados['id']
            tabela.insert(dados).execute()
            
        elif acao == 'update':
            id_t = dados.get('id')
            if not id_t: return False
            # Limpa payload
            payload = {k: v for k, v in dados.items() if k in ['valor', 'descricao', 'categoria', 'data', 'tipo']}
            tabela.update(payload).eq("id", id_t).eq("user_id", user_id).execute()
            
        elif acao == 'delete':
            id_t = dados.get('id')
            tabela.delete().eq("id", id_t).eq("user_id", user_id).execute()
            
        return True
    except Exception as e:
        st.error(f"Erro SQL: {e}")
        return False

def upload_comprovante(arquivo, user_id):
    try:
        nome_arquivo = f"{user_id}_{int(time.time())}_{arquivo.name}"
        bucket_name = "comprovantes"
        supabase.storage.from_(bucket_name).upload(nome_arquivo, arquivo.getvalue(), {"content-type": arquivo.type})
        return supabase.storage.from_(bucket_name).get_public_url(nome_arquivo)
    except: return None

# --- UI Helpers ---
def get_categoria_icon(categoria):
    mapa = {"Alimentação": "🍔", "Transporte": "🚗", "Lazer": "🎮", "Saúde": "💊", "Investimentos": "📈", "Casa": "🏠", "Outros": "📦", "Educação": "📚", "Salário": "💰"}
    return mapa.get(categoria, "💸")

# --- IA: Cérebro Agente (V2) ---
def agente_financeiro_ia(texto_usuario, df_contexto):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    # Contexto: Passa as últimas 15 transações para a IA "ver" o que editar
    contexto_json = "[]"
    if not df_contexto.empty:
        cols = ['id', 'data', 'descricao', 'valor', 'categoria']
        contexto_json = df_contexto[cols].head(15).to_json(orient="records")

    prompt = f"""
    Você é um Agente Financeiro SQL. Hoje: {date.today()}.
    
    CONTEXTO RECENTE DO USUÁRIO:
    {contexto_json}
    
    COMANDO: "{texto_usuario}"
    
    MISSÃO:
    1. INSERT: Se for gasto novo.
    2. UPDATE/DELETE: Procure no CONTEXTO o ID correspondente (pela descrição/valor/data).
    3. SEARCH: Se for pergunta de análise ("quanto gastei?"), responda em 'msg_ia'.
    
    RESPOSTA JSON OBRIGATÓRIA:
    {{
        "acao": "insert" | "update" | "delete" | "search" | "pergunta",
        "dados": {{
            "id": int (SÓ PREENCHA SE ACHAR NO CONTEXTO),
            "data": "YYYY-MM-DD",
            "valor": 0.00,
            "categoria": "Str",
            "descricao": "Str",
            "tipo": "Receita" | "Despesa"
        }},
        "msg_ia": "Texto explicativo"
    }}
    
    Se não achar o ID para editar/apagar, devolva acao="pergunta" e avise.
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest', generation_config={"response_mime_type": "application/json"})
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        return {"acao": "erro", "msg": str(e)}

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

# Sidebar Clássica (Mantida como você pediu)
with st.sidebar:
    st.markdown(f"### 👤 {user['username']}")
    menu = st.radio("Menu", ["💬 Chat & Lançamento", "📊 Dashboard", "🧠 Consultoria IA"])
    st.divider()
    
    meses_map = {1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril", 5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"}
    c_m, c_a = st.columns(2)
    mes_sel = c_m.selectbox("Mês", list(meses_map.keys()), format_func=lambda x: meses_map[x], index=date.today().month - 1)
    ano_sel = c_a.number_input("Ano", 2024, 2030, date.today().year)
    
    if st.button("Sair", icon="🚪"):
        st.session_state['user'] = None
        st.rerun()

# Carrega Dados Globais (Necessário para o Agente ler o contexto)
df_total = carregar_transacoes(user['id'], limite=50) # Carrega 50 últimos para contexto rápido
if not df_total.empty:
    df_mes = df_total[(df_total['data_dt'].dt.month == mes_sel) & (df_total['data_dt'].dt.year == ano_sel)]
else:
    df_mes = pd.DataFrame()

# --- 1. CHAT COM AGENTE INTELIGENTE ---
if menu == "💬 Chat & Lançamento":
    st.title("Assistente IA")

    if "messages" not in st.session_state: st.session_state.messages = []
    if "pending_op" not in st.session_state: st.session_state.pending_op = None # Nova variável de estado

    # Histórico
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Input
    if not st.session_state.pending_op:
        if prompt := st.chat_input("Ex: Uber 20, ou 'Apague o gasto do Mcdonalds'"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()

    # Processamento IA
    if st.session_state.messages and st.session_state.messages[-1]["role"] == "user" and not st.session_state.pending_op:
        with st.chat_message("assistant"):
            with st.spinner("Analisando..."):
                last_msg = st.session_state.messages[-1]["content"]
                # Passa o DF_TOTAL para a IA procurar IDs para edição/exclusão
                res = agente_financeiro_ia(last_msg, df_total)
                
                # Se for Search ou Pergunta, responde direto
                if res['acao'] in ['search', 'pergunta', 'erro']:
                    msg_ia = res.get('msg_ia', res.get('msg'))
                    st.markdown(msg_ia)
                    st.session_state.messages.append({"role": "assistant", "content": msg_ia})
                
                # Se for Modificação (Insert/Update/Delete), pede confirmação
                else:
                    st.session_state.pending_op = res
                    st.rerun()

    # Confirmação de Operação
    if st.session_state.pending_op:
        op = st.session_state.pending_op
        tipo = op['acao'].upper()
        d = op['dados']
        
        with st.chat_message("assistant"):
            st.markdown(f"**Confirmação: {tipo}**")
            
            # Card de Preview da Ação
            cor_borda = "#FF4B4B" if tipo == 'DELETE' else "#00CC96"
            st.markdown(f"""
            <div style="border-left: 5px solid {cor_borda}; padding: 10px; background: #262730; border-radius: 5px;">
                <b>ID:</b> {d.get('id', 'Novo')}<br>
                <b>Desc:</b> {d.get('descricao')}<br>
                <b>Valor:</b> R$ {d.get('valor')}
            </div>
            """, unsafe_allow_html=True)
            
            # Opção de Anexo (Só no Insert)
            arquivo = None
            if op['acao'] == 'insert':
                arquivo = st.file_uploader("Anexo (Opcional)", type=['jpg', 'pdf'])

            c1, c2 = st.columns(2)
            if c1.button("✅ Confirmar", type="primary", use_container_width=True):
                # Upload se tiver
                url_final = None
                if arquivo:
                    with st.spinner("Enviando foto..."):
                        url_final = upload_comprovante(arquivo, user['id'])
                
                # Prepara dados finais
                dados_sql = d.copy()
                dados_sql['user_id'] = user['id']
                if url_final: dados_sql['comprovante_url'] = url_final
                
                # Executa
                if executar_sql(op['acao'], dados_sql, user['id']):
                    st.session_state.messages.append({"role": "assistant", "content": f"✅ Feito! ({op.get('msg_ia', 'Sucesso')})"})
                    st.toast(f"{tipo} realizado!", icon="🚀")
                else:
                    st.session_state.messages.append({"role": "assistant", "content": "❌ Erro no banco."})
                
                st.session_state.pending_op = None
                time.sleep(1)
                st.rerun()

            if c2.button("❌ Cancelar", use_container_width=True):
                st.session_state.pending_op = None
                st.session_state.messages.append({"role": "assistant", "content": "Operação cancelada."})
                st.rerun()

# --- 2. DASHBOARD (Otimizado Mobile via CSS) ---
elif menu == "📊 Dashboard":
    st.title(f"Visão: {meses_map[mes_sel]}")
    
    if not df_mes.empty:
        rec = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        desp = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        saldo = rec - desp
        
        c1, c2, c3 = st.columns(3)
        c1.metric("Entradas", f"R$ {rec:,.2f}")
        c2.metric("Saídas", f"R$ {desp:,.2f}")
        c3.metric("Saldo", f"R$ {saldo:,.2f}")
        
        st.markdown("---")
        
        # Estrutura Responsiva: No mobile o CSS vai jogar um embaixo do outro
        c_extrato, c_grafico = st.columns([1, 1])
        
        with c_extrato:
            st.subheader("📝 Extrato")
            df_show = df_mes.sort_values(by="data_dt", ascending=False).head(15)
            
            for _, row in df_show.iterrows():
                is_receita = row['tipo'] == 'Receita'
                sinal = "+" if is_receita else "-"
                cor_classe = "val-receita" if is_receita else "val-despesa"
                icon = get_categoria_icon(row['categoria'])
                
                st.markdown(f"""
                <div style="background: #262730; padding: 10px; border-radius: 10px; margin-bottom: 8px; display: flex; align-items: center;">
                    <div class="icon-box" style="width: 40px;">{icon}</div>
                    <div style="flex-grow: 1; padding-left: 10px;">
                        <div class="card-desc">{row['descricao']}</div>
                        <div class="card-sub">{row['data_dt'].strftime('%d/%m')} • ID: {row['id']}</div>
                    </div>
                    <div class="{cor_classe}">{sinal} {row['valor']:.0f}</div>
                </div>
                """, unsafe_allow_html=True)
                
                # Link discreto para comprovante
                if row.get('comprovante_url'):
                    st.caption(f"[Ver Anexo]({row['comprovante_url']})")

        with c_grafico:
            st.subheader("📊 Gráfico")
            gastos = df_mes[df_mes['tipo'] != 'Receita']
            if not gastos.empty:
                fig = px.pie(gastos, values='valor', names='categoria', hole=0.6, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem gastos.")

    else:
        st.info("Sem dados neste mês.")

# --- 3. CONSULTORIA ---
elif menu == "🧠 Consultoria IA":
    st.title("Consultoria IA")
    if st.button("Gerar Análise", type="primary", use_container_width=True):
        analise = gerar_analise_mensal(df_mes)
        st.markdown(analise)
