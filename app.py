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

# --- CSS (Estilo Moderno & Clean) ---
st.markdown("""
<style>
    /* Esconde cabeçalho padrão */
    .stAppHeader {display:none;}
    
    /* Ajustes Gerais */
    .stChatMessage { padding: 1rem; border-radius: 12px; margin-bottom: 10px; box-shadow: 0 2px 4px rgba(0,0,0,0.1); }
    
    /* Métricas do Dashboard */
    [data-testid="stMetricValue"] { font-size: 26px; font-weight: 800; }
    
    /* Estilo dos Cards de Transação */
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
        # ATENÇÃO: Em produção, use hash para senhas ou o Auth do Supabase
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except: return None

def carregar_transacoes(user_id):
    try:
        # Otimização: Poderia filtrar por data aqui para não baixar tudo
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'])
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

def upload_comprovante(arquivo, user_id):
    """Envia arquivo para o Bucket 'Comprovantes' e retorna URL pública"""
    try:
        # Cria nome único: ID_TIMESTAMP_NOME
        nome_arquivo = f"{user_id}_{int(time.time())}_{arquivo.name}"
        arquivo_bytes = arquivo.getvalue()
        
        bucket_name = "Comprovantes"
        
        # Upload
        supabase.storage.from_(bucket_name).upload(nome_arquivo, arquivo_bytes, {"content-type": arquivo.type})
        
        # Pega URL Pública
        url_response = supabase.storage.from_(bucket_name).get_public_url(nome_arquivo)
        return url_response
    except Exception as e:
        st.error(f"Erro no Upload: {e}")
        return None

def salvar_transacao(user_id, dados, comprovante_url=None):
    try:
        data = {
            "user_id": user_id,
            "data": dados['data'],
            "categoria": dados['categoria'],
            "descricao": dados['descricao'],
            "valor": float(dados['valor']),
            "tipo": dados.get('tipo', 'Despesa'),
            "recorrente": False,
            "comprovante_url": comprovante_url # Coluna precisa existir no Supabase
        }
        supabase.table("transactions").insert(data).execute()
        return True
    except Exception as e:
        st.error(f"Erro ao salvar no banco: {e}")
        return False

# --- UI Helpers (Ícones) ---
def get_categoria_icon(categoria):
    mapa = {
        "Alimentação": "🍔", "Transporte": "🚗", "Lazer": "🎮", 
        "Saúde": "💊", "Investimentos": "📈", "Casa": "🏠", 
        "Outros": "📦", "Educação": "📚", "Trabalho": "💼", "Salário": "💰"
    }
    return mapa.get(categoria, "💸")

# --- IA Logic (Atualizada para flash-latest) ---
def interpretar_comando_chat(texto_usuario):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    data_hoje = date.today().strftime("%Y-%m-%d")
    
    # Prompt Otimizado para JSON Mode
    prompt = f"""
    Atue como um parser financeiro. Hoje é {data_hoje}.
    Frase do usuário: "{texto_usuario}"
    
    Instruções:
    1. Extraia: valor (float), categoria (use padrão de mercado), descricao (curta), data (YYYY-MM-DD).
    2. Identifique o tipo: "Receita" (ganhou dinheiro) ou "Despesa" (gastou dinheiro).
    3. Se faltar o valor, defina "acao" como "pergunta".
    4. Se tiver os dados, defina "acao" como "confirmar".
    
    Responda EXCLUSIVAMENTE com este schema JSON:
    {{
        "acao": "confirmar" | "pergunta",
        "msg": "Texto amigável para o usuário",
        "dados": {{
            "data": "YYYY-MM-DD",
            "valor": 0.00,
            "categoria": "String",
            "descricao": "String",
            "tipo": "Receita" | "Despesa"
        }}
    }}
    """
    
    try:
        # Configuração para JSON Mode
        generation_config = {"response_mime_type": "application/json"}
        
        # Modelo solicitado
        model = genai.GenerativeModel('gemini-flash-latest', generation_config=generation_config)
        
        response = model.generate_content(prompt)
        return json.loads(response.text)
    except Exception as e:
        return {"acao": "erro", "msg": f"Erro na IA: {e}"}

# --- Lógica de Análise (Consultoria) ---
def gerar_analise_mensal(df_mes):
    if df_mes.empty: return "Sem dados."
    
    receitas = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
    despesas = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
    saldo = receitas - despesas
    
    # Trava simples para não gastar tokens à toa
    if len(df_mes) < 3:
        return "📉 **Dados insuficientes.** Continue usando o app para liberar a consultoria."
    
    resumo = df_mes.groupby('categoria')['valor'].sum().to_string()
    
    prompt = f"""
    Atue como um consultor financeiro pessoal.
    Resumo do mês:
    - Entradas: R$ {receitas}
    - Saídas: R$ {despesas}
    - Saldo: R$ {saldo}
    
    Gastos por categoria:
    {resumo}
    
    Dê 3 dicas curtas e práticas baseadas nesses números. Use tom motivador e emojis.
    """
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
        st.title("🔒 Finanças Chat")
        with st.form("login"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar", use_container_width=True):
                user = login_user(u, p)
                if user:
                    st.session_state['user'] = user
                    st.rerun()
                else: st.error("Usuário ou senha inválidos.")
    st.stop()

# =======================================================
# APP PRINCIPAL
# =======================================================
user = st.session_state['user']

with st.sidebar:
    st.markdown(f"### Olá, {user['username']} 👋")
    menu = st.radio("Menu", ["💬 Chat & Lançamento", "📊 Dashboard", "🧠 Consultoria IA"])
    st.divider()
    
    # Filtros Globais
    meses_map = {1:"Janeiro", 2:"Fevereiro", 3:"Março", 4:"Abril", 5:"Maio", 6:"Junho", 7:"Julho", 8:"Agosto", 9:"Setembro", 10:"Outubro", 11:"Novembro", 12:"Dezembro"}
    c_m, c_a = st.columns(2)
    mes_sel = c_m.selectbox("Mês", list(meses_map.keys()), format_func=lambda x: meses_map[x], index=date.today().month - 1)
    ano_sel = c_a.number_input("Ano", 2024, 2030, date.today().year)
    
    if st.button("Sair", icon="🚪"):
        st.session_state['user'] = None
        st.rerun()

# Carregamento de Dados (Filtro Python - ideal mover para SQL em produção)
df = carregar_transacoes(user['id'])
if not df.empty:
    df_mes = df[(df['data_dt'].dt.month == mes_sel) & (df['data_dt'].dt.year == ano_sel)]
else:
    df_mes = pd.DataFrame()

# --- 1. CHAT & LANÇAMENTO ---
if menu == "💬 Chat & Lançamento":
    st.title("Lançamento Inteligente")

    if "messages" not in st.session_state:
        st.session_state.messages = [{"role": "assistant", "content": "Olá! O que vamos registrar hoje? (Ex: 'Almoço 30 reais' ou 'Recebi 1000') "}]
    
    if "pending_transaction" not in st.session_state:
        st.session_state.pending_transaction = None

    # Exibe Histórico
    for message in st.session_state.messages:
        with st.chat_message(message["role"]):
            st.markdown(message["content"])

    # Input do Chat (Bloqueado se tiver pendência para forçar decisão)
    if not st.session_state.pending_transaction:
        if prompt := st.chat_input("Digite aqui..."):
            st.session_state.messages.append({"role": "user", "content": prompt})
            st.rerun()
    
    # Processamento IA
    if st.session_state.messages[-1]["role"] == "user" and not st.session_state.pending_transaction:
        with st.chat_message("assistant"):
            with st.spinner("Processando..."):
                last_msg = st.session_state.messages[-1]["content"]
                res = interpretar_comando_chat(last_msg)
                
                if res['acao'] == 'confirmar':
                    st.session_state.pending_transaction = res['dados']
                    st.rerun()
                
                elif res['acao'] == 'pergunta':
                    st.markdown(res['msg'])
                    st.session_state.messages.append({"role": "assistant", "content": res['msg']})
                else:
                    err_msg = "Não entendi. Tente ser mais direto, ex: 'Uber 15 reais'."
                    st.markdown(err_msg)
                    st.session_state.messages.append({"role": "assistant", "content": err_msg})

    # Área de Confirmação & Anexo
    if st.session_state.pending_transaction:
        d = st.session_state.pending_transaction
        icon_tipo = "💰" if d['tipo'] == 'Receita' else "💸"
        
        with st.chat_message("assistant"):
            st.markdown(f"""
            **Confirma os dados?**
            
            {icon_tipo} **Tipo:** {d['tipo']}
            🏷️ **Categoria:** {d['categoria']}
            📝 **Descrição:** {d['descricao']}
            💵 **Valor:** R$ {d['valor']:.2f}
            """)
            
            st.info("Deseja anexar um comprovante?")
            
            # Formulário para Anexo
            with st.container(border=True):
                uploaded_file = st.file_uploader("Escolha a imagem (Opcional)", type=['jpg', 'png', 'pdf'], key="uploader")
                
                col_save, col_cancel = st.columns(2)
                
                if col_save.button("✅ Confirmar e Salvar", type="primary", use_container_width=True):
                    url_final = None
                    
                    # Lógica de Upload Corrigida
                    if uploaded_file is not None:
                        with st.spinner("Enviando comprovante..."):
                            url_final = upload_comprovante(uploaded_file, user['id'])
                            if not url_final:
                                st.error("Erro no upload. Tentando salvar sem anexo...")
                    
                    # Salva no Banco
                    sucesso = salvar_transacao(user['id'], d, url_final)
                    
                    if sucesso:
                        msg_ok = f"✅ Salvo: {d['descricao']} (R$ {d['valor']:.2f})" + (" 📎 com anexo." if url_final else ".")
                        st.session_state.messages.append({"role": "assistant", "content": msg_ok})
                        st.session_state.pending_transaction = None
                        st.toast("Transação Registrada!", icon="🎉")
                        time.sleep(1)
                        st.rerun()
                
                if col_cancel.button("❌ Cancelar", use_container_width=True):
                    st.session_state.pending_transaction = None
                    st.session_state.messages.append({"role": "assistant", "content": "🚫 Cancelado."})
                    st.rerun()

# --- 2. DASHBOARD (Lógica Financeira Corrigida) ---
elif menu == "📊 Dashboard":
    st.title(f"Visão Geral: {meses_map[mes_sel]}/{ano_sel}")
    
    if not df_mes.empty:
        # 1. Cálculos Corretos
        receitas = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        # Assume que tudo que não é receita é despesa
        despesas = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        saldo = receitas - despesas
        
        # 2. Métricas
        col1, col2, col3 = st.columns(3)
        col1.metric("Entradas", f"R$ {receitas:,.2f}", delta="Receitas")
        col2.metric("Saídas", f"R$ {despesas:,.2f}", delta="-Gastos", delta_color="inverse")
        col3.metric("Saldo Líquido", f"R$ {saldo:,.2f}", delta_color="normal")
        
        st.markdown("---")
        
        # 3. Layout: Extrato e Gráfico
        c_extrato, c_grafico = st.columns([1, 1])
        
        with c_extrato:
            st.subheader("📝 Extrato")
            # Ordena e mostra os top 10
            df_show = df_mes.sort_values(by="data_dt", ascending=False).head(10)
            
            for index, row in df_show.iterrows():
                is_receita = row.get('tipo') == 'Receita'
                sinal = "+" if is_receita else "-"
                cor = "#00CC96" if is_receita else "#FF4B4B"
                icon = get_categoria_icon(row['categoria'])
                
                with st.container(border=True):
                    c_ico, c_detalhes, c_valor, c_anexo = st.columns([1, 4, 3, 1])
                    c_ico.markdown(f"<div class='icon-box'>{icon}</div>", unsafe_allow_html=True)
                    
                    with c_detalhes:
                        st.markdown(f"**{row['descricao']}**")
                        st.caption(f"{row['data_dt'].strftime('%d/%m')} • {row['categoria']}")
                    
                    with c_valor:
                        st.markdown(f"<div style='text-align:right; color:{cor}; font-weight:bold;'>{sinal} R$ {row['valor']:.2f}</div>", unsafe_allow_html=True)
                    
                    with c_anexo:
                        # Exibe clip se tiver link válido
                        if row.get('comprovante_url') and str(row['comprovante_url']) != "None":
                            st.link_button("📎", row['comprovante_url'], help="Ver Comprovante")

        with c_grafico:
            st.subheader("🍩 Para onde foi o dinheiro?")
            # Filtra apenas despesas para o gráfico de pizza
            df_despesas = df_mes[df_mes['tipo'] != 'Receita']
            
            if not df_despesas.empty:
                gastos_cat = df_despesas.groupby("categoria")['valor'].sum().reset_index()
                fig = px.pie(gastos_cat, values='valor', names='categoria', hole=0.6, color_discrete_sequence=px.colors.qualitative.Pastel)
                st.plotly_chart(fig, use_container_width=True)
            else:
                st.info("Sem despesas registradas neste mês.")

    else:
        st.info(f"Nenhum lançamento em {meses_map[mes_sel]}/{ano_sel}.")

# --- 3. CONSULTORIA ---
elif menu == "🧠 Consultoria IA":
    st.title("Consultoria Financeira")
    st.markdown("A IA analisa seus gastos do mês e dá dicas personalizadas.")
    
    if st.button("Gerar Relatório Inteligente", type="primary"):
        with st.spinner("Analisando padrões..."):
            analise = gerar_analise_mensal(df_mes)
            st.markdown("### Relatório do Mês")
            st.markdown(analise)

