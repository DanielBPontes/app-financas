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

# --- CSS (Estilo Moderno & Clean) ---
st.markdown("""
<style>
    /* Esconde cabeçalho padrão */
    .stAppHeader {display:none;}
    
    /* Ajustes Gerais */
    .stChatMessage { padding: 1rem; border-radius: 12px; margin-bottom: 10px; }
    
    /* Métricas do Dashboard */
    [data-testid="stMetricValue"] { font-size: 26px; font-weight: 800; color: #00CC96; }
    
    /* Estilo dos Cards de Transação */
    .trans-card {
        padding: 10px;
        border-radius: 10px;
        margin-bottom: 8px;
        background-color: #262730; /* Ajuste conforme tema dark/light */
    }
    .icon-box { font-size: 24px; text-align: center; }
    .val-despesa { color: #FF4B4B; font-weight: bold; text-align: right; }
    .val-receita { color: #00CC96; font-weight: bold; text-align: right; }
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

def upload_comprovante(arquivo, user_id):
    """Envia arquivo para o Bucket 'comprovantes'"""
    try:
        nome_arquivo = f"{user_id}_{int(time.time())}_{arquivo.name}"
        arquivo_bytes = arquivo.getvalue()
        bucket_name = "comprovantes"
        supabase.storage.from_(bucket_name).upload(nome_arquivo, arquivo_bytes, {"content-type": arquivo.type})
        return supabase.storage.from_(bucket_name).get_public_url(nome_arquivo)
    except Exception as e:
        st.error(f"Erro upload: {e}")
        return None

def salvar_transacao(user_id, data_iso, categoria, descricao, valor, tipo, comprovante_url=None):
    # Tenta inferir tipo se não vier da IA (IA as vezes falha no tipo explícito)
    if tipo is None:
        tipo = "Despesa" # Default
        
    data = {
        "user_id": user_id,
        "data": data_iso,
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": False,
        "comprovante_url": comprovante_url,
        "tipo": tipo # Certifique-se de ter criado essa coluna no Supabase, ou remova se não usar
    }
    supabase.table("transactions").insert(data).execute()

# --- UI Helpers (Ícones e Formatação) ---
def get_categoria_icon(categoria):
    mapa = {
        "Alimentação": "🍔", "Transporte": "🚗", "Lazer": "🎮", 
        "Saúde": "💊", "Investimentos": "📈", "Casa": "🏠", 
        "Outros": "📦", "Educação": "📚", "Trabalho": "💼"
    }
    return mapa.get(categoria, "💸")

# --- IA Logic ---
def interpretar_comando_chat(texto_usuario):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    data_hoje = date.today().strftime("%Y-%m-%d")
    
    prompt = f"""
    Hoje: {data_hoje}.
    Usuário: "{texto_usuario}"
    
    1. Identifique: Valor, Categoria (Alimentação, Transporte, Lazer, Saúde, Casa, Investimentos, Outros), Descrição, Data.
    2. Identifique TIPO: 'Despesa' ou 'Receita'.
    3. JSON Obrigatório. Se faltar valor, acao='pergunta'. Se ok, acao='confirmar'.
    
    Exemplo: {{"acao": "confirmar", "dados": {{"data": "2024-12-14", "valor": 50.00, "categoria": "Alimentação", "descricao": "Pizza", "tipo": "Despesa"}}, "msg_ia": "Entendi: Pizza (R$ 50)"}}
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        clean_text = response.text.replace('```json', '').replace('```', '').strip()
        return json.loads(clean_text)
    except: return {"acao": "erro", "msg": "Erro na IA"}

# --- Lógica de Análise ---
def gerar_analise_mensal_condicional(df_mes):
    if df_mes.empty: return "Sem dados."
    total = df_mes['valor'].sum()
    dias = df_mes['data_dt'].dt.date.nunique()
    
    if total < 500 and dias < 3: # Regra relaxada para testes
        return f"📉 **Dados insuficientes.**\nContinue usando o app para liberar a consultoria.\nAtual: R$ {total:.2f} em {dias} dias."
    
    resumo = df_mes.groupby('categoria')['valor'].sum().to_string()
    prompt = f"Analise estes gastos (Total R$ {total}):\n{resumo}\nSeja um consultor financeiro breve e direto."
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
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
            if st.form_submit_button("Entrar", use_container_width=True):
                user = login_user(u, p)
                if user:
                    st.session_state['user'] = user
                    st.rerun()
                else: st.error("Erro no login.")
    st.stop()

# =======================================================
# APP PRINCIPAL
# =======================================================
user = st.session_state['user']

with st.sidebar:
    st.markdown(f"👤 **{user['username']}**")
    menu = st.radio("Menu", ["💬 Chat Financeiro", "📊 Dashboard", "🧠 Relatórios"], index=0)
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

# --- 1. CHAT COM FLUXO DE ANEXO ---
if menu == "💬 Chat Financeiro":
    st.title("Assistente Financeiro")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Olá! Quanto você gastou ou recebeu hoje?"}]
    
    # Estado para transação pendente de confirmação/anexo
    if "pending_transaction" not in st.session_state:
        st.session_state.pending_transaction = None

    # Exibe Histórico
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Se NÃO tiver pendência, mostra o input normal
    if not st.session_state.pending_transaction:
        if prompt := st.chat_input("Ex: Almoço 45 reais"):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()
    
    # Processamento Lógico (Separado da renderização para evitar loops)
    if st.session_state.messages[-1]["role"] == "user" and not st.session_state.pending_transaction:
        with st.chat_message("assistant"):
            with st.spinner("Analisando..."):
                last_msg = st.session_state.messages[-1]["content"]
                resultado = interpretar_comando_chat(last_msg)
                
                if resultado['acao'] == 'confirmar':
                    # SALVA NO ESTADO E PEDE CONFIRMAÇÃO/ANEXO
                    st.session_state.pending_transaction = resultado['dados']
                    st.rerun() # Recarrega para mostrar a interface de anexo
                
                elif resultado['acao'] == 'pergunta':
                    msg = f"🤔 {resultado['msg']}"
                    st.markdown(msg)
                    st.session_state.messages.append({"role": "assistant", "content": msg})
                else:
                    msg = "⚠️ Não entendi. Tente 'Gastei X em Y'."
                    st.markdown(msg)
                    st.session_state.messages.append({"role": "assistant", "content": msg})

    # --- INTERFACE DE CONFIRMAÇÃO E ANEXO ---
    if st.session_state.pending_transaction:
        d = st.session_state.pending_transaction
        
        with st.chat_message("assistant"):
            st.info(f"🧾 **Confirmação:** R$ {d['valor']} em {d['categoria']} ({d['descricao']})")
            st.markdown("**Deseja anexar um comprovante antes de salvar?**")
            
            # Container do Formulário de Confirmação
            with st.container(border=True):
                arquivo = st.file_uploader("📸 Foto do Recibo (Opcional)", type=['jpg', 'png', 'pdf'])
                
                c1, c2 = st.columns(2)
                
                # Botão SALVAR
                if c1.button("✅ Salvar Lançamento", type="primary", use_container_width=True):
                    url_final = None
                    if arquivo:
                        with st.spinner("Subindo anexo..."):
                            url_final = upload_comprovante(arquivo, user['id'])
                    
                    try:
                        salvar_transacao(user['id'], d['data'], d['categoria'], d['descricao'], d['valor'], d.get('tipo', 'Despesa'), url_final)
                        
                        msg_sucesso = f"✅ Salvo com sucesso! R$ {d['valor']}" + (" (Com anexo)" if url_final else "")
                        st.session_state.messages.append({"role": "assistant", "content": msg_sucesso})
                        st.session_state.pending_transaction = None # Limpa pendência
                        st.toast("Transação registrada!", icon="🚀")
                        time.sleep(0.5)
                        st.rerun()
                    except Exception as e:
                        st.error(f"Erro: {e}")

                # Botão CANCELAR
                if c2.button("❌ Cancelar", use_container_width=True):
                    st.session_state.pending_transaction = None
                    st.session_state.messages.append({"role": "assistant", "content": "🚫 Operação cancelada."})
                    st.rerun()

# --- 2. DASHBOARD (UI/UX Melhorada) ---
elif menu == "📊 Dashboard":
    st.title(f"Visão de {meses_map[mes_sel]}/{ano_sel}")
    
    if not df_mes.empty:
        # Métricas Topo
        total = df_mes['valor'].sum()
        c1, c2, c3 = st.columns(3)
        c1.metric("Saldo do Mês", f"R$ {total:,.2f}")
        c2.metric("Lançamentos", len(df_mes))
        c3.metric("Média Diária", f"R$ {total/30:,.2f}")
        
        st.markdown("---")
        
        # Área Principal: Extrato em Cards
        c_extrato, c_grafico = st.columns([1, 1])
        
        with c_extrato:
            st.subheader("📝 Últimas Movimentações")
            
            # Ordena por data mais recente
            df_show = df_mes.sort_values(by="data_dt", ascending=False).head(10)
            
            for index, row in df_show.iterrows():
                # Lógica Visual do Card
                icone = get_categoria_icon(row['categoria'])
                is_receita = row.get('tipo') == 'Receita' # Ajuste se não tiver essa coluna ainda
                cor_valor = "#00CC96" if is_receita else "#FF4B4B"
                sinal = "+" if is_receita else "-"
                
                # Container Card
                with st.container(border=True):
                    col_ico, col_desc, col_val, col_act = st.columns([1, 5, 3, 1])
                    
                    with col_ico:
                        st.markdown(f"<div class='icon-box'>{icone}</div>", unsafe_allow_html=True)
                    
                    with col_desc:
                        st.markdown(f"**{row['descricao']}**")
                        st.caption(f"{row['data_dt'].strftime('%d/%m')} • {row['categoria']}")
                    
                    with col_val:
                        st.markdown(f"<div style='text-align:right; color:{cor_valor}; font-weight:bold;'>{sinal} R$ {row['valor']:.2f}</div>", unsafe_allow_html=True)
                    
                    with col_act:
                        if row.get('comprovante_url') and str(row['comprovante_url']) != "None":
                            st.link_button("📎", row['comprovante_url'], help="Ver anexo")
        
        with c_grafico:
            st.subheader("🍩 Distribuição")
            gastos = df_mes.groupby("categoria")['valor'].sum().reset_index()
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.6, color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_layout(showlegend=True, margin=dict(t=20, b=20, l=20, r=20))
            st.plotly_chart(fig, use_container_width=True)

            st.subheader("📅 Gasto Diário")
            diario = df_mes.groupby("data")['valor'].sum().reset_index()
            fig2 = px.bar(diario, x="data", y="valor", color="valor", color_continuous_scale="Reds")
            fig2.update_layout(xaxis_title=None, yaxis_title=None, showlegend=False)
            st.plotly_chart(fig2, use_container_width=True)

    else:
        st.info("Nenhum dado neste mês. Vá ao Chat e diga 'Gastei...'")

# --- 3. RELATÓRIOS ---
elif menu == "🧠 Relatórios":
    st.title("Consultoria IA")
    if st.button("Gerar Análise do Mês", type="primary"):
        with st.spinner("Analisando..."):
            analise = gerar_analise_mensal_condicional(df_mes)
            st.markdown("---")
            st.markdown(analise)
