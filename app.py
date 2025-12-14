import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import google.generativeai as genai

# --- Configuração da Página ---
st.set_page_config(page_title="Finanças Chat", page_icon="💬", layout="wide")

# --- CSS Moderno ---
st.markdown("""
<style>
    .stAppHeader {display:none;}
    .stChatMessage { padding: 1rem; border-radius: 10px; margin-bottom: 10px; }
    [data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; color: #00CC96; }
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
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'])
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

# --- NOVA FUNÇÃO: UPLOAD DE IMAGEM ---
def upload_comprovante(arquivo, user_id):
    """Envia arquivo para o Bucket 'comprovantes' do Supabase"""
    try:
        # Cria um nome único para o arquivo: ID_do_Usuario + Timestamp + NomeOriginal
        nome_arquivo = f"{user_id}_{int(time.time())}_{arquivo.name}"
        
        # Lê os bytes do arquivo
        arquivo_bytes = arquivo.getvalue()
        
        # Faz o upload
        bucket_name = "comprovantes"
        supabase.storage.from_(bucket_name).upload(nome_arquivo, arquivo_bytes, {"content-type": arquivo.type})
        
        # Pega a URL pública para salvar no banco
        url_publica = supabase.storage.from_(bucket_name).get_public_url(nome_arquivo)
        return url_publica
    except Exception as e:
        st.error(f"Erro no upload: {e}")
        return None

def salvar_transacao(user_id, data_iso, categoria, descricao, valor, tipo, url_comprovante=None):
    data = {
        "user_id": user_id,
        "data": data_iso,
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": False,
        "comprovante_url": url_comprovante # Nova coluna
    }
    supabase.table("transactions").insert(data).execute()

# --- CÉREBRO DO CHAT (IA) ---
def interpretar_comando_chat(texto_usuario):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA não configurada."}
    data_hoje = date.today().strftime("%Y-%m-%d")
    
    prompt = f"""
    Você é um assistente financeiro (hoje: {data_hoje}).
    Texto: "{texto_usuario}"
    
    Categorias: Alimentação, Transporte, Lazer, Saúde, Investimentos, Casa, Outros.
    
    1. Identifique Despesa/Receita, Valor, Categoria e Descrição.
    2. Se faltar VALOR, retorne "acao": "pergunta".
    3. Se tiver tudo, "acao": "salvar".
    
    Responda APENAS JSON.
    Exemplo Sucesso: {{"acao": "salvar", "dados": {{"data": "2024-12-14", "valor": 10.50, "categoria": "Lazer", "descricao": "Cinema", "tipo": "Despesa"}}, "resposta_ia": "Salvo!"}}
    Exemplo Falta: {{"acao": "pergunta", "msg": "Qual o valor?"}}
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        texto_limpo = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto_limpo)
    except Exception as e:
        return {"acao": "erro", "msg": f"Erro: {e}"}

# --- Lógica de Análise ---
def gerar_analise_mensal_condicional(df_mes):
    if df_mes.empty: return "Sem dados."
    total_gasto = df_mes['valor'].sum()
    dias_unicos = df_mes['data_dt'].dt.date.nunique()
    
    if total_gasto < 1000 and dias_unicos < 5: # Reduzi a trava para teste
        return f"📉 **Dados insuficientes.**\nPreciso de mais de R$ 1000 gastos ou 5 dias diferentes de registros.\nAtual: R$ {total_gasto:.2f} em {dias_unicos} dias."
    
    resumo = df_mes.groupby('categoria')['valor'].sum().to_string()
    prompt = f"Analise estes gastos (Total R$ {total_gasto}):\n{resumo}\nSeja um consultor financeiro criativo."
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        return model.generate_content(prompt).text
    except Exception as e: return f"Erro IA: {e}"

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    c1, c2, c3 = st.columns([1,1,1])
    with c2:
        st.title("💬 Finanças Chat")
        with st.form("login"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Acessar", use_container_width=True):
                user = login_user(u, p)
                if user:
                    st.session_state['user'] = user
                    st.rerun()
                else: st.error("Erro.")
    st.stop()

# =======================================================
# APP PRINCIPAL
# =======================================================
user = st.session_state['user']

with st.sidebar:
    st.markdown(f"👤 **{user['username']}**")
    menu = st.radio("Menu", ["💬 Chat & Anexo", "📊 Dashboard", "🧠 Relatórios"], index=0)
    st.divider()
    meses_map = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez"}
    c_m, c_a = st.columns(2)
    mes_sel = c_m.selectbox("Mês", list(meses_map.keys()), index=date.today().month - 1)
    ano_sel = c_a.number_input("Ano", 2024, 2030, date.today().year)
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

df = carregar_transacoes(user['id'])
if not df.empty:
    df_mes = df[(df['data_dt'].dt.month == mes_sel) & (df['data_dt'].dt.year == ano_sel)]
else:
    df_mes = pd.DataFrame()

# --- 1. CHAT COM ANEXO ---
if menu == "💬 Chat & Anexo":
    st.title("Assistente Financeiro")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "O que vamos registrar? Se tiver recibo, anexe abaixo!"}]

    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # --- ÁREA DE ANEXO (Expander para não poluir) ---
    with st.expander("📎 Anexar Comprovante/Recibo (Opcional)", expanded=False):
        arquivo_upload = st.file_uploader("Escolha uma imagem ou PDF", type=['png', 'jpg', 'jpeg', 'pdf'], key="uploader_chat")

    if prompt := st.chat_input("Ex: Gastei 150 na farmácia"):
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"): st.markdown(prompt)

        with st.chat_message("assistant"):
            with st.spinner("Processando..."):
                resultado = interpretar_comando_chat(prompt)
                resposta_final = ""
                
                if resultado['acao'] == 'salvar':
                    d = resultado['dados']
                    try:
                        # 1. Verifica se tem arquivo para subir
                        url_arquivo = None
                        if arquivo_upload is not None:
                            with st.spinner("Subindo comprovante..."):
                                url_arquivo = upload_comprovante(arquivo_upload, user['id'])
                        
                        # 2. Salva Transação com a URL
                        salvar_transacao(user['id'], d['data'], d['categoria'], d['descricao'], d['valor'], d['tipo'], url_arquivo)
                        
                        msg_extra = " (Com anexo 📎)" if url_arquivo else ""
                        resposta_final = f"✅ {resultado['resposta_ia']}{msg_extra}"
                        st.toast(f"Salvo: R$ {d['valor']}", icon="💾")
                        time.sleep(1)
                        
                    except Exception as e:
                        resposta_final = f"Erro ao salvar: {e}"
                        
                elif resultado['acao'] == 'pergunta':
                    resposta_final = f"🤔 {resultado['msg']}"
                else:
                    resposta_final = f"⚠️ {resultado.get('msg', 'Erro')}"

                st.markdown(resposta_final)
                st.session_state.messages.append({"role": "assistant", "content": resposta_final})
                # Força rerun para limpar o uploader se foi usado
                if resultado['acao'] == 'salvar':
                    time.sleep(0.5)
                    st.rerun()

# --- 2. DASHBOARD ---
elif menu == "📊 Dashboard":
    st.title(f"Visão de {mes_sel}/{ano_sel}")
    if not df_mes.empty:
        total = df_mes['valor'].sum()
        st.metric("Total Gasto", f"R$ {total:,.2f}")
        
        st.subheader("Últimos Registros")
        
        # Cria colunas para a tabela ficar bonita
        for index, row in df_mes.head(10).iterrows():
            with st.container(border=True):
                c1, c2, c3, c4 = st.columns([2, 3, 2, 1])
                c1.write(f"📅 {row['data_dt'].strftime('%d/%m')}")
                c2.write(f"**{row['descricao']}**")
                c3.write(f"R$ {row['valor']:.2f}")
                
                # Botão para ver comprovante se existir
                if row.get('comprovante_url') and str(row['comprovante_url']) != "None":
                    with c4:
                        st.link_button("📎 Ver", row['comprovante_url'])
                else:
                    with c4:
                        st.write("-")
    else:
        st.info("Sem dados.")

# --- 3. RELATÓRIOS ---
elif menu == "🧠 Relatórios":
    st.title("Consultoria")
    if st.button("Gerar Análise"):
        with st.spinner("Analisando..."):
            analise = gerar_analise_mensal_condicional(df_mes)
            st.markdown(analise)
