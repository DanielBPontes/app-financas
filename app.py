import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import google.generativeai as genai

# --- 1. Configuração Mobile-First ---
st.set_page_config(page_title="AppFinanças", page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# --- CSS (Mantido igual) ---
st.markdown("""
<style>
    .stAppHeader {display:none !important;} 
    .block-container {padding-top: 1rem !important; padding-bottom: 6rem !important;} 
    div[role="radiogroup"] {
        flex-direction: row; justify-content: center; background-color: #1E1E1E;
        padding: 5px; border-radius: 12px; margin-bottom: 20px;
    }
    div[role="radiogroup"] label {
        background: transparent; border: none; padding: 10px 15px; border-radius: 8px;
        text-align: center; flex-grow: 1; cursor: pointer; color: #888;
    }
    div[role="radiogroup"] label[data-checked="true"] {
        background-color: #00CC96 !important; color: #000 !important;
        font-weight: bold; box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    .stButton button { width: 100%; border-radius: 12px; font-weight: 600; }
    div[data-testid="stAudioInput"] { margin-top: -10px; margin-bottom: 10px; }
    .app-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border: 1px solid #333; margin-bottom: 10px;
    }
</style>
""", unsafe_allow_html=True)

# --- Conexões e Funções Backend (Mantidas) ---
# ... (Seu código de conexão supabase/gemini aqui permanece igual) ...

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

# --- Funções Auxiliares ---
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
            df['data_dt'] = pd.to_datetime(df['data'], errors='coerce') # Safety fix
            df['valor'] = pd.to_numeric(df['valor'], errors='coerce')
        return df
    except: return pd.DataFrame()

def executar_sql(acao, dados, user_id):
    try:
        tabela = supabase.table("transactions")
        # Sanitização de Data
        if 'data' in dados:
             # Garante que envie apenas string YYYY-MM-DD
             dados['data'] = str(dados['data']).split('T')[0]

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
        st.error(f"Erro SQL: {e}"); return False

def fmt_real(valor):
    if valor is None: valor = 0.0
    return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['id', 'data', 'descricao', 'valor', 'categoria']].head(15).to_json(orient="records")

    prompt_base = f"""
    Atue como um Assistente Financeiro JSON. Hoje é {date.today()}.
    Histórico recente: {contexto}
    
    REGRA: Valores float com PONTO (Ex: 13.50).
    Datas sempre formato YYYY-MM-DD.
    
    Retorne JSON puro:
    {{
        "acao": "insert" | "update" | "delete" | "search" | "pergunta",
        "dados": {{
            "id": int (p/ update/del), "data": "YYYY-MM-DD", "valor": float,
            "categoria": "Alimentação"|"Transporte"|"Lazer"|"Casa"|"Outros",
            "descricao": "str", "tipo": "Receita"|"Despesa"
        }},
        "msg_ia": "Resposta curta e amigável"
    }}
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if tipo_entrada == "audio":
            audio_bytes = entrada.getvalue()
            response = model.generate_content(
                [prompt_base, {"mime_type": "audio/wav", "data": audio_bytes}, "Extraia a transação deste áudio."],
                generation_config={"response_mime_type": "application/json"}
            )
        else:
            full_prompt = f"{prompt_base}\nUser: '{entrada}'"
            response = model.generate_content(full_prompt, generation_config={"response_mime_type": "application/json"})
            
        return json.loads(response.text)
    except Exception as e: return {"acao": "erro", "msg": f"Erro IA: {str(e)}"}

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None
if not st.session_state['user']:
    st.markdown("<br><h2 style='text-align:center'>🔒 Login</h2>", unsafe_allow_html=True)
    with st.form("login"):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            user = login_user(u, p)
            if user: st.session_state['user'] = user; st.rerun()
            else: st.error("Acesso negado")
    st.stop()

# =======================================================
# LÓGICA & NAVEGAÇÃO
# =======================================================
user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 100)

with st.sidebar:
    st.write(f"Logado: {user['username']}")
    if st.button("Sair"): st.session_state.clear(); st.rerun()

# CONTROLE DE ESTADO CRÍTICO
if "audio_key" not in st.session_state: st.session_state.audio_key = 0 # KEY DINÂMICA
if "messages" not in st.session_state: st.session_state.messages = []
if "pending_op" not in st.session_state: st.session_state.pending_op = None
if "last_audio_id" not in st.session_state: st.session_state.last_audio_id = None

selected_nav = st.radio("Menu", ["💬 Chat", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# TELA 1: CHAT IA (CORRIGIDO)
# =======================================================
if selected_nav == "💬 Chat":
    
    # Renderiza Histórico
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --- INPUT ---
    # Só mostra inputs se não houver operação pendente
    if not st.session_state.pending_op:
        
        col_s1, col_s2, col_s3 = st.columns(3)
        input_texto_simulado = None
        
        if col_s1.button("🍔 Almoço"): input_texto_simulado = "Gastei 30,00 com almoço"
        if col_s2.button("🚗 Uber"): input_texto_simulado = "Gastei 15,00 Uber"
        if col_s3.button("💰 Recebi"): input_texto_simulado = "Recebi 100,00 Pix"

        # SOLUÇÃO DO LOOP: Key dinâmica limpa o áudio após sucesso
        audio_val = st.audio_input("Grave aqui", label_visibility="collapsed", key=f"audio_rec_{st.session_state.audio_key}") 
        
        text_val = st.chat_input("Digite ou fale...")

        conteudo_final = None
        tipo_final = None

        # Lógica de Prioridade
        if input_texto_simulado:
            conteudo_final = input_texto_simulado
            tipo_final = "texto"
            # Ignora áudio antigo se clicar no botão
            st.session_state.last_audio_id = audio_val 

        elif text_val:
            conteudo_final = text_val
            tipo_final = "texto"
            st.session_state.last_audio_id = audio_val

        elif audio_val:
            # VERIFICAÇÃO DE LOOP: Só processa se for diferente do último processado
            if audio_val != st.session_state.last_audio_id:
                conteudo_final = audio_val
                tipo_final = "audio"
                st.session_state.last_audio_id = audio_val
                st.session_state.messages.append({"role": "user", "content": "🎤 *Áudio processado...*"})

        # Execução IA
        if conteudo_final:
            if tipo_final == "texto":
                st.session_state.messages.append({"role": "user", "content": conteudo_final})

            with st.chat_message("assistant"):
                with st.spinner("🤖"):
                    res = agente_financeiro_ia(conteudo_final, df_total, tipo_final)
                    
                    if res['acao'] in ['insert', 'update', 'delete']:
                        st.session_state.pending_op = res
                        st.rerun() # Rerun para mudar UI para modo confirmação
                    else:
                        msg = res.get('msg_ia', "Não entendi.")
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})

    # --- CONFIRMAÇÃO (MODO MODAL) ---
    else: # Existe pending_op
        op = st.session_state.pending_op
        d = op['dados']
        acao = op['acao'].upper()
        
        with st.container():
            st.info(f"O assistente sugere: **{acao}**")
            val_fmt = fmt_real(d.get('valor', 0))
            
            st.markdown(f"""
            <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
                <div class="card-title" style="font-weight:bold; font-size:1.1em">{d.get('descricao', 'Sem descrição')}</div>
                <div class="card-amount" style="font-size:1.5em">R$ {val_fmt}</div>
                <div class="card-meta" style="color:#888">{d.get('categoria')} • {d.get('data')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            if c1.button("✅ Confirmar", type="primary", use_container_width=True):
                if executar_sql(op['acao'], {**d, 'user_id': user['id']}, user['id']):
                    st.toast("Sucesso!")
                    st.session_state.messages.append({"role": "assistant", "content": f"✅ {acao} realizado: {d.get('descricao')}"})
                    
                    # TRUQUE ANTI-LOOP: Incrementa a key para limpar o widget de áudio
                    st.session_state.audio_key += 1
                    st.session_state.last_audio_id = None # Reseta memória de áudio
                    
                st.session_state.pending_op = None
                time.sleep(1)
                st.rerun()
            
            if c2.button("❌ Cancelar", use_container_width=True):
                st.session_state.pending_op = None
                st.toast("Cancelado")
                st.session_state.audio_key += 1 # Limpa o áudio mesmo se cancelar para não ficar travado
                st.rerun()

# =======================================================
# TELA 2: EXTRATO (Mantido, apenas correções de bug)
# =======================================================
elif selected_nav == "💳 Extrato":
    # ... (Seu código da aba extrato mantido igual, apenas verifique o df_total) ...
    # Recomendo apenas garantir que df_total não quebre se vier vazio no início:
    if not df_total.empty:
        # código existente...
        pass
    else:
        st.info("Nenhuma transação encontrada.")

# ... Restante do código (Análise) permanece igual ...
