import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import google.generativeai as genai

# --- Configuração da Página ---
st.set_page_config(page_title="Finanças Chat", page_icon="💬", layout="wide")

# --- CSS (Estilo de Chat Moderno) ---
st.markdown("""
<style>
    /* Esconde o menu hamburger padrão para limpar a tela */
    .stAppHeader {display:none;}
    
    /* Estilo das mensagens do chat */
    .stChatMessage { padding: 1rem; border-radius: 10px; margin-bottom: 10px; }
    
    /* Métricas */
    [data-testid="stMetricValue"] { font-size: 24px; font-weight: bold; color: #00CC96; }
</style>
""", unsafe_allow_html=True)

# --- Conexões e Configurações ---
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

def salvar_transacao(user_id, data_iso, categoria, descricao, valor, tipo):
    data = {
        "user_id": user_id,
        "data": data_iso,
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": False # Padrão no chat é não recorrente, pode aprimorar depois
    }
    supabase.table("transactions").insert(data).execute()

# --- CÉREBRO DO CHAT (IA) ---
def interpretar_comando_chat(texto_usuario, historico_recente):
    """
    Usa o Gemini para converter texto livre em JSON estruturado ou pedir info.
    """
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA não configurada."}

    data_hoje = date.today().strftime("%Y-%m-%d")
    
    # Prompt de Engenharia para Extração de Dados
    prompt = f"""
    Você é um assistente financeiro que registra gastos via chat.
    Hoje é: {data_hoje}.
    
    Categorias válidas: Alimentação, Transporte, Lazer, Saúde, Investimentos, Casa, Outros.
    
    Texto do usuário: "{texto_usuario}"
    
    Sua missão:
    1. Identificar se é Despesa ou Receita.
    2. Extrair Valor, Categoria (use a mais próxima das válidas) e Descrição.
    3. Se o usuário não disse a data, assuma HOJE.
    
    REGRAS CRÍTICAS:
    - Se faltar o VALOR, sua resposta JSON deve ter "acao": "pergunta" e "msg": "qual o valor?".
    - Se tiver tudo, sua resposta JSON deve ter "acao": "salvar" e os dados formatados.
    
    Responda APENAS o JSON, sem markdown.
    
    Exemplo Saída Sucesso:
    {{
        "acao": "salvar",
        "dados": {{
            "data": "2024-12-14",
            "valor": 10.50,
            "categoria": "Lazer",
            "descricao": "Brawl Stars",
            "tipo": "Despesa"
        }},
        "resposta_ia": "Feito! R$ 10,50 registrados em Lazer."
    }}
    
    Exemplo Saída Falta Info:
    {{
        "acao": "pergunta",
        "msg": "Entendi que foi Uber, mas qual foi o valor?"
    }}
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        response = model.generate_content(prompt)
        # Limpeza para garantir que venha só o JSON
        texto_limpo = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(texto_limpo)
    except Exception as e:
        return {"acao": "erro", "msg": f"Não entendi. Erro: {e}"}

# --- Lógica de Análise com Travas ---
def gerar_analise_mensal_condicional(df_mes):
    if df_mes.empty: return "Sem dados."
    
    # --- AS REGRAS QUE VOCÊ PEDIU ---
    total_gasto = df_mes['valor'].sum()
    dias_unicos = df_mes['data_dt'].dt.date.nunique()
    
    # 1. Trava de Dados Mínimos
    if total_gasto < 1000 and dias_unicos < 10:
        return f"""
        🚫 **Análise Indisponível**
        
        Para a IA gerar uma análise de qualidade, preciso de dados mais concretos.
        
        **Progresso Atual:**
        - Total Gasto: R$ {total_gasto:.2f} (Meta: R$ 1.000,00)
        - Dias Registrados: {dias_unicos} (Meta: 10 dias)
        
        *Continue lançando seus gastos no Chat!*
        """
    
    # Se passou, gera a análise
    resumo = df_mes.groupby('categoria')['valor'].sum().to_string()
    prompt = f"Analise estes gastos (Total R$ {total_gasto}):\n{resumo}\nSeja um consultor financeiro criativo e direto."
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        return model.generate_content(prompt).text
    except Exception as e: return f"Erro na IA: {e}"

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

# Sidebar minimalista
with st.sidebar:
    st.markdown(f"👤 **{user['username']}**")
    menu = st.radio("Navegação", ["💬 Chat Financeiro", "📊 Dashboard", "🧠 Relatórios & IA"], index=0)
    
    st.divider()
    # Filtro de Data Global
    meses_map = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez"}
    c_m, c_a = st.columns(2)
    mes_sel = c_m.selectbox("Mês", list(meses_map.keys()), format_func=lambda x: meses_map[x], index=date.today().month - 1)
    ano_sel = c_a.number_input("Ano", 2024, 2030, date.today().year)
    
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

# Carrega dados
df = carregar_transacoes(user['id'])
if not df.empty:
    df_mes = df[(df['data_dt'].dt.month == mes_sel) & (df['data_dt'].dt.year == ano_sel)]
else:
    df_mes = pd.DataFrame()

# --- 1. CHAT FINANCEIRO (NOVA INTERFACE PRINCIPAL) ---
if menu == "💬 Chat Financeiro":
    st.title("Assistente Financeiro")
    st.caption("Ex: 'Gastei 25 no uber' ou 'Recebi 500 de freela'")

    # Inicializa histórico do chat
    if "messages" not in st.session_state:
        st.session_state.messages = []
        # Mensagem de boas vindas
        st.session_state.messages.append({"role": "assistant", "content": "Olá! O que vamos registrar hoje?"})

    # Mostra mensagens antigas
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Input do Usuário
    if prompt := st.chat_input("Digite aqui..."):
        # 1. Mostra msg usuário
        st.session_state.messages.append({"role": "user", "content": prompt})
        with st.chat_message("user"):
            st.markdown(prompt)

        # 2. Processa com IA
        with st.chat_message("assistant"):
            with st.spinner("Processando..."):
                resultado = interpretar_comando_chat(prompt, st.session_state.messages)
                
                resposta_final = ""
                
                if resultado['acao'] == 'salvar':
                    d = resultado['dados']
                    try:
                        salvar_transacao(user['id'], d['data'], d['categoria'], d['descricao'], d['valor'], d['tipo'])
                        resposta_final = f"✅ {resultado['resposta_ia']}"
                        
                        # Feedback visual extra
                        st.toast(f"Salvo: R$ {d['valor']} ({d['categoria']})", icon="💾")
                        time.sleep(1) # Tempo para o usuário ler antes de recarregar (se precisasse atualizar tabela)
                        
                    except Exception as e:
                        resposta_final = f"Erro ao salvar no banco: {e}"
                        
                elif resultado['acao'] == 'pergunta':
                    resposta_final = f"🤔 {resultado['msg']}"
                
                else:
                    resposta_final = f"⚠️ {resultado.get('msg', 'Erro desconhecido')}"

                st.markdown(resposta_final)
                st.session_state.messages.append({"role": "assistant", "content": resposta_final})

# --- 2. DASHBOARD ---
elif menu == "📊 Dashboard":
    st.title(f"Visão de {meses_map[mes_sel]}/{ano_sel}")
    
    if not df_mes.empty:
        total = df_mes['valor'].sum()
        c1, c2 = st.columns(2)
        c1.metric("Total Gasto", f"R$ {total:,.2f}")
        c2.metric("Lançamentos", len(df_mes))
        
        # Gráfico simples
        gastos_cat = df_mes.groupby("categoria")['valor'].sum().reset_index()
        fig = px.pie(gastos_cat, values='valor', names='categoria', hole=0.5, color_discrete_sequence=px.colors.qualitative.Pastel)
        st.plotly_chart(fig, use_container_width=True)
        
        # Tabela Recente
        st.subheader("Últimos Registros")
        st.dataframe(df_mes[['data', 'categoria', 'descricao', 'valor']].head(), hide_index=True, use_container_width=True)
    else:
        st.info("Nenhum dado neste mês. Vá ao Chat e diga 'Gastei...'")

# --- 3. RELATÓRIOS & TRAVAS ---
elif menu == "🧠 Relatórios & IA":
    st.title("Consultoria Financeira")
    
    if st.button("Gerar Análise do Mês", type="primary"):
        with st.spinner("Analisando seus hábitos..."):
            # Chama a função que tem a trava de R$ 1000 ou 10 dias
            analise = gerar_analise_mensal_condicional(df_mes)
            st.markdown("---")
            st.markdown(analise)

