import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date
import time
import json
import tempfile
import pathlib
import google.generativeai as genai

# --- 1. Configuração Mobile-First ---
st.set_page_config(page_title="AppFinanças", page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# --- 2. CSS "App Nativo" Otimizado ---
st.markdown("""
<style>
    /* RESET E ESPAÇAMENTO */
    .stAppHeader {display:none !important;} 
    .block-container {padding-top: 1rem !important; padding-bottom: 6rem !important;} 
    
    /* MENU DE NAVEGAÇÃO ESTILO iOS */
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
    
    /* ESTILIZAÇÃO DO CHAT */
    .chat-suggestion-btn {
        background-color: #262730; border: 1px solid #444; color: #FFF;
        border-radius: 20px; padding: 5px 15px; font-size: 12px; margin-right: 5px;
        cursor: pointer; display: inline-block;
    }
    .chat-suggestion-btn:hover { border-color: #00CC96; color: #00CC96; }
    
    /* BARRAS DE PROGRESSO */
    .stProgress > div > div > div > div { background-color: #00CC96; }
    
    /* INPUTS E BOTÕES */
    .stButton button { width: 100%; height: 50px; border-radius: 12px; font-weight: 600; }
    
    /* METAS */
    .budget-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border-left: 5px solid #00CC96; margin-bottom: 15px;
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
        st.error(f"Erro SQL: {e}"); return False

def upload_comprovante(arquivo, user_id):
    try:
        nome = f"{user_id}_{int(time.time())}_{arquivo.name}"
        supabase.storage.from_("comprovantes").upload(nome, arquivo.getvalue(), {"content-type": arquivo.type})
        return supabase.storage.from_("comprovantes").get_public_url(nome)
    except: return None

def fmt_real(valor):
    """Formata float para Moeda BRL Visual (ex: 1.234,56)"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA (Multimodal: Texto + Áudio) ---
def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['id', 'data', 'descricao', 'valor', 'categoria']].head(15).to_json(orient="records")

    prompt_base = f"""
    Atue como um Assistente Financeiro JSON. Hoje é {date.today()}.
    Histórico Recente: {contexto}
    
    REGRA DE OURO - VALORES: Retorne float EXATO com ponto. Ex: "13,50" vira 13.50. "100" vira 100.00.
    
    Retorne APENAS JSON neste formato:
    {{
        "acao": "insert" | "update" | "delete" | "search" | "pergunta",
        "dados": {{
            "id": int (apenas para update/delete),
            "data": "YYYY-MM-DD",
            "valor": float (Ex: 25.90),
            "categoria": "Alimentação" | "Transporte" | "Lazer" | "Contas" | "Investimento" | "Outros",
            "descricao": "Resumo curto (Ex: Almoço Mcdonalds)",
            "tipo": "Receita" ou "Despesa"
        }},
        "msg_ia": "Resposta curta e amigável em PT-BR"
    }}
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if tipo_entrada == "audio":
            # Salva audio temporariamente para upload
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as temp_audio:
                temp_audio.write(entrada.getvalue())
                temp_path = temp_audio.name
            
            # Upload para Gemini (File API)
            myfile = genai.upload_file(temp_path)
            response = model.generate_content([prompt_base, "Analise este áudio e extraia a transação:", myfile], 
                                            generation_config={"response_mime_type": "application/json"})
            # Limpeza
            pathlib.Path(temp_path).unlink() 
        else:
            # Texto Puro
            full_prompt = f"{prompt_base}\nUsuário disse: '{entrada}'"
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
        if st.form_submit_button("Acessar Sistema"):
            user = login_user(u, p)
            if user: st.session_state['user'] = user; st.rerun()
            else: st.error("Acesso negado")
    st.stop()

# =======================================================
# CONFIGURAÇÕES (SIDEBAR) & NAVEGAÇÃO
# =======================================================
user = st.session_state['user']
# Carrega dados
df_total = carregar_transacoes(user['id'], 100)

with st.sidebar:
    st.header("⚙️ Ajustes")
    st.write(f"Olá, **{user['username']}**")
    # Meta de Gastos (Feature Nova)
    meta_mensal = st.number_input("Meta de Gastos (Mês)", value=3000.0, step=100.0)
    if st.button("Sair"):
        st.session_state.clear(); st.rerun()

# Menu Principal
selected_nav = st.radio("Menu", ["💬 Chat IA", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# TELA 1: CHAT INTELIGENTE (TEXTO & VOZ)
# =======================================================
if selected_nav == "💬 Chat IA":
    if "messages" not in st.session_state: 
        st.session_state.messages = [{"role": "assistant", "content": "Olá! Posso registrar um gasto, uma receita ou responder dúvidas."}]
    if "pending_op" not in st.session_state: st.session_state.pending_op = None

    # Cabeçalho Criativo
    hora = datetime.now().hour
    saudacao = "Bom dia" if hora < 12 else "Boa tarde" if hora < 18 else "Boa noite"
    st.caption(f"{saudacao}, vamos organizar as finanças?")

    # Botões Rápidos (Suggestion Chips)
    col_s1, col_s2, col_s3 = st.columns(3)
    if col_s1.button("🍔 Almoço R$...", key="sug1"): 
        st.session_state.messages.append({"role": "user", "content": "Gastei com Almoço..."}) # Apenas exemplo visual
    if col_s2.button("🚗 Uber R$...", key="sug2"): pass
    if col_s3.button("💰 Recebi Pix...", key="sug3"): pass

    # Histórico de Chat
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # --- ÁREA DE INPUT ---
    # Se não tem operação pendente, mostra inputs
    if not st.session_state.pending_op:
        
        # 1. Input de Áudio (NOVO)
        audio_val = st.audio_input("🎙️ Falar Transação (Ex: 'Gastei 15 reais na padaria')")
        
        # 2. Input de Texto
        text_val = st.chat_input("Ou digite aqui...")

        # Lógica de Processamento
        entrada_conteudo = None
        tipo_input = None

        if audio_val:
            entrada_conteudo = audio_val
            tipo_input = "audio"
            # Hack visual para mostrar que enviou audio
            st.session_state.messages.append({"role": "user", "content": "🎤 *Áudio enviado...*"})
        elif text_val:
            entrada_conteudo = text_val
            tipo_input = "texto"
            st.session_state.messages.append({"role": "user", "content": text_val})

        # Se houve input, chama a IA
        if entrada_conteudo:
            with st.chat_message("assistant"):
                with st.spinner("🧠 Processando..."):
                    res = agente_financeiro_ia(entrada_conteudo, df_total, tipo_input)
                    
                    if res['acao'] in ['insert', 'update', 'delete']:
                        st.session_state.pending_op = res
                        st.rerun()
                    else:
                        msg = res.get('msg_ia', "Não entendi.")
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})
                        # Limpa áudio forçando rerun se necessário, ou pelo fluxo natural

    # --- CONFIRMAÇÃO DE AÇÃO ---
    if st.session_state.pending_op:
        op = st.session_state.pending_op
        d = op['dados']
        acao = op['acao'].upper()
        
        with st.container():
            st.warning(f"⚠️ CONFIRMAR {acao}?")
            
            # Card Preview
            val_fmt = fmt_real(d.get('valor', 0))
            st.markdown(f"""
            <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
                <div class="card-title">{d.get('descricao', 'Sem descrição')}</div>
                <div class="card-amount">R$ {val_fmt}</div>
                <div class="card-meta">{d.get('categoria')} • {d.get('data')}</div>
            </div>
            """, unsafe_allow_html=True)

            col_conf1, col_conf2 = st.columns(2)
            
            if col_conf1.button("✅ Confirmar", type="primary", use_container_width=True):
                # Prepara dados
                final_data = d.copy()
                final_data['user_id'] = user['id']
                
                if executar_sql(op['acao'], final_data, user['id']):
                    st.toast("Sucesso!", icon="🎉")
                    st.session_state.messages.append({"role": "assistant", "content": f"✅ {acao} realizado com sucesso."})
                
                st.session_state.pending_op = None
                time.sleep(1)
                st.rerun()
                
            if col_conf2.button("❌ Cancelar", use_container_width=True):
                st.session_state.pending_op = None
                st.rerun()

# =======================================================
# TELA 2: EXTRATO INTELIGENTE (EDITOR + METAS)
# =======================================================
elif selected_nav == "💳 Extrato":
    
    # Filtros
    c_f1, c_f2 = st.columns([2, 1])
    filtro_mes = c_f1.selectbox("Mês", range(1,13), index=date.today().month-1)
    filtro_ano = c_f2.number_input("Ano", 2024, 2030, date.today().year)

    if not df_total.empty:
        # Filtrar dados locais
        mask = (df_total['data_dt'].dt.month == filtro_mes) & (df_total['data_dt'].dt.year == filtro_ano)
        df_mes = df_total[mask].copy()
        
        # Cálculos
        total_rec = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        total_desp = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        saldo = total_rec - total_desp
        
        # --- FEATURE: PROGRESSO DA META ---
        if meta_mensal > 0:
            perc_gasto = min(total_desp / meta_mensal, 1.0)
            cor_barra = "red" if perc_gasto > 0.9 else "green"
            st.markdown(f"""
            <div class="budget-card">
                <span style="font-size:14px; color:#AAA;">Orçamento Mensal</span><br>
                <span style="font-size:20px; font-weight:bold;">R$ {fmt_real(total_desp)}</span> 
                <span style="font-size:14px;"> / {fmt_real(meta_mensal)}</span>
            </div>
            """, unsafe_allow_html=True)
            st.progress(perc_gasto)
            if perc_gasto >= 1.0: st.error("🚨 Orçamento Estourado!")

        # Resumo Financeiro
        c_r1, c_r2 = st.columns(2)
        c_r1.metric("Entradas", f"R$ {fmt_real(total_rec)}")
        c_r2.metric("Saídas", f"R$ {fmt_real(total_desp)}", delta_color="inverse")

        st.divider()
        st.subheader("📝 Editar Lançamentos")
        st.caption("Edite valores diretamente na tabela abaixo.")

        # --- FEATURE: EDITOR DE DADOS (DATA EDITOR) ---
        # [CORREÇÃO APLICADA AQUI]
        # Garantindo que a coluna 'data' seja do tipo datetime (não string)
        # para evitar o erro StreamlitAPIException
        df_editavel = df_mes.copy()
        df_editavel['data'] = pd.to_datetime(df_editavel['data'])
        
        # Selecionando e ordenando colunas
        df_editavel = df_editavel[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values(by='data', ascending=False)

        mudancas = st.data_editor(
            df_editavel,
            column_config={
                "id": None, # Oculto
                "valor": st.column_config.NumberColumn("Valor (R$)", format="R$ %.2f", min_value=0.0),
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Receita", "Despesa"], required=True),
                "categoria": st.column_config.SelectboxColumn("Categoria", options=["Alimentação", "Transporte", "Casa", "Lazer", "Investimento", "Outros"])
            },
            hide_index=True,
            use_container_width=True,
            num_rows="dynamic", # Permite adicionar linhas vazias
            key="editor_grid"
        )

        # Botão de Salvar Alterações
        if st.button("💾 Salvar Alterações na Tabela", type="primary"):
            with st.spinner("Sincronizando..."):
                ids_originais = df_mes['id'].tolist()
                
                # 1. Updates e Inserts
                for index, row in mudancas.iterrows():
                    dado = row.to_dict()
                    
                    # [CORREÇÃO] Converter Data (objeto) de volta para String (YYYY-MM-DD) para o Supabase
                    if isinstance(dado['data'], (pd.Timestamp, date, datetime)):
                        dado['data'] = dado['data'].strftime('%Y-%m-%d')

                    if pd.isna(dado['id']): 
                         pass # Inserts via tabela não tratados nesta versão simples
                    else:
                        executar_sql('update', dado, user['id'])
                
                # 2. Deletes
                ids_novos = mudancas['id'].dropna().tolist()
                ids_removidos = set(ids_originais) - set(ids_novos)
                
                for id_del in ids_removidos:
                    executar_sql('delete', {'id': id_del}, user['id'])
                
                st.toast("Dados atualizados!", icon="✅")
                time.sleep(1)
                st.rerun()

    else:
        st.info("Nenhuma movimentação encontrada.")

# =======================================================
# TELA 3: ANÁLISE GRÁFICA
# =======================================================
elif selected_nav == "📈 Análise":
    st.subheader("Raio-X Financeiro")
    
    if not df_total.empty:
        # Filtra mês atual automaticamente
        df_atual = df_total[df_total['data_dt'].dt.month == date.today().month]
        gastos = df_atual[df_atual['tipo'] != 'Receita']
        
        if not gastos.empty:
            # Gráfico de Rosca
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.6, 
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_traces(textinfo='percent+label')
            fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=300)
            st.plotly_chart(fig, use_container_width=True)
            
            # Top Gastos (Barra de Progresso)
            st.markdown("##### 🏆 Maiores Gastos")
            top_cats = gastos.groupby('categoria')['valor'].sum().sort_values(ascending=False)
            total_gasto_mes = gastos['valor'].sum()
            
            for cat, val in top_cats.items():
                pct = int((val / total_gasto_mes) * 100)
                st.markdown(f"**{cat}** — R$ {fmt_real(val)}")
                st.progress(pct)
        else:
            st.info("Sem gastos este mês para analisar.")
