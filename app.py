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

# --- 2. CSS "App Nativo" Otimizado ---
st.markdown("""
<style>
    /* RESET E ESPAÇAMENTO */
    .stAppHeader {display:none !important;} 
    .block-container {padding-top: 1rem !important; padding-bottom: 6rem !important;} 
    
    /* MENU DE NAVEGAÇÃO */
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
    
    /* SUGESTÕES DE CHAT */
    .stButton button { width: 100%; border-radius: 12px; font-weight: 600; }
    
    /* MICROFONE DISCRETO (Hack CSS) */
    div[data-testid="stAudioInput"] { margin-top: -10px; margin-bottom: 10px; }
    div[data-testid="stAudioInput"] label { display: none; } /* Esconde texto 'Label' */
    
    /* CARDS */
    .app-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border: 1px solid #333; margin-bottom: 10px;
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
            # Converte para datetime para manipulação, mas mantém string para visualização simples se precisar
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
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA (Robusto) ---
def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA não configurada"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['id', 'data', 'descricao', 'valor', 'categoria']].head(10).to_json(orient="records")

    prompt_base = f"""
    Atue como um Assistente Financeiro. Hoje: {date.today()}.
    Histórico: {contexto}
    
    SEU OBJETIVO: Extrair transações financeiras.
    Regra 1: Valores float com PONTO (Ex: 13.50).
    Regra 2: Se não entender o áudio ou texto, retorne acao: "erro".
    
    Retorne JSON ESTRITO:
    {{
        "acao": "insert" | "update" | "delete" | "pergunta" | "erro",
        "dados": {{
            "id": int (opcional), "data": "YYYY-MM-DD", "valor": float,
            "categoria": "Alimentação"|"Transporte"|"Lazer"|"Casa"|"Receita"|"Outros",
            "descricao": "Resumo curto", "tipo": "Receita" ou "Despesa"
        }},
        "msg_ia": "Resposta curta para o usuário"
    }}
    """

    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if tipo_entrada == "audio":
            # Envia bytes do áudio
            audio_bytes = entrada.getvalue()
            response = model.generate_content(
                [prompt_base, {"mime_type": "audio/wav", "data": audio_bytes}, "Transcreva e extraia a transação."],
                generation_config={"response_mime_type": "application/json"}
            )
        else:
            full_prompt = f"{prompt_base}\nUsuário disse: '{entrada}'"
            response = model.generate_content(full_prompt, generation_config={"response_mime_type": "application/json"})
            
        return json.loads(response.text)
    except Exception as e: return {"acao": "erro", "msg": f"Erro processamento: {str(e)}"}

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
# LÓGICA PRINCIPAL
# =======================================================
user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 100)

with st.sidebar:
    st.write(f"Usuário: {user['username']}")
    meta_mensal = st.number_input("Meta Mensal", value=3000.0)
    if st.button("Sair"): st.session_state.clear(); st.rerun()

selected_nav = st.radio("Menu", ["💬 Chat", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# TELA 1: CHAT IA (Com Correção de Loop de Áudio)
# =======================================================
if selected_nav == "💬 Chat":
    # Inicialização de Variáveis de Estado
    if "messages" not in st.session_state: st.session_state.messages = []
    if "pending_op" not in st.session_state: st.session_state.pending_op = None
    
    # [CORREÇÃO LOOP] Variável para armazenar o ÚLTIMO áudio processado
    if "last_processed_audio_val" not in st.session_state: st.session_state.last_processed_audio_val = None

    # Exibe Histórico
    for msg in st.session_state.messages:
        with st.chat_message(msg["role"]):
            st.markdown(msg["content"])

    # Área de Input (Só mostra se não estiver aguardando confirmação)
    if not st.session_state.pending_op:
        
        # 1. Botões de Sugestão (Prioridade Alta)
        col_s1, col_s2, col_s3 = st.columns(3)
        clicked_suggestion = None
        if col_s1.button("🍔 Almoço"): clicked_suggestion = "Gastei 30,00 com almoço"
        if col_s2.button("🚗 Uber"): clicked_suggestion = "Gastei 15,00 Uber"
        if col_s3.button("💰 Recebi"): clicked_suggestion = "Recebi 100,00 Pix"

        # 2. Áudio Input (Prioridade Média)
        audio_val = st.audio_input("Falar", label_visibility="collapsed")
        
        # 3. Texto Input (Prioridade Baixa)
        text_val = st.chat_input("Digite aqui...")

        # Lógica de Decisão (Quem processar?)
        final_input = None
        final_type = None

        if clicked_suggestion:
            final_input = clicked_suggestion
            final_type = "texto"
            # Se clicou botão, invalida o áudio atual para não processar por engano
            st.session_state.last_processed_audio_val = audio_val 

        elif text_val:
            final_input = text_val
            final_type = "texto"
            st.session_state.last_processed_audio_val = audio_val

        elif audio_val:
            # [CORREÇÃO LOOP] Verifica se esse áudio JÁ FOI processado
            if audio_val != st.session_state.last_processed_audio_val:
                final_input = audio_val
                final_type = "audio"
                # Marca como processado IMEDIATAMENTE
                st.session_state.last_processed_audio_val = audio_val
                st.session_state.messages.append({"role": "user", "content": "🎤 *Áudio enviado...*"})
            else:
                # É o mesmo áudio que ficou no componente após o rerun. Ignora.
                pass

        # Executa IA se tiver input válido
        if final_input:
            if final_type == "texto":
                 st.session_state.messages.append({"role": "user", "content": final_input})

            with st.chat_message("assistant"):
                with st.spinner("Processando..."):
                    res = agente_financeiro_ia(final_input, df_total, final_type)
                    
                    if res['acao'] in ['insert', 'update', 'delete']:
                        st.session_state.pending_op = res
                        st.rerun() # Recarrega para mostrar confirmação
                    elif res['acao'] == 'erro':
                        st.warning("Não entendi o áudio/texto. Tente novamente.")
                    else:
                        msg = res.get('msg_ia', "Não entendi.")
                        st.markdown(msg)
                        st.session_state.messages.append({"role": "assistant", "content": msg})

    # Tela de Confirmação (Pendente)
    if st.session_state.pending_op:
        op = st.session_state.pending_op
        d = op['dados']
        acao = op['acao'].upper()
        
        with st.container():
            st.warning(f"⚠️ CONFIRMAR: {acao}")
            
            val_fmt = fmt_real(d.get('valor', 0))
            st.markdown(f"""
            <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
                <div class="card-title">{d.get('descricao', 'Sem descrição')}</div>
                <div class="card-amount">R$ {val_fmt}</div>
                <div class="card-meta">{d.get('categoria')} • {d.get('data')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            if c1.button("✅ Confirmar", type="primary"):
                dados_finais = d.copy()
                dados_finais['user_id'] = user['id']
                if executar_sql(op['acao'], dados_finais, user['id']):
                    st.toast("Sucesso!")
                    st.session_state.messages.append({"role": "assistant", "content": f"✅ {acao} realizado."})
                st.session_state.pending_op = None
                time.sleep(1)
                st.rerun()
            
            if c2.button("❌ Cancelar"):
                st.session_state.pending_op = None
                st.rerun()

# =======================================================
# TELA 2: EXTRATO (Com Correção do Data Editor)
# =======================================================
elif selected_nav == "💳 Extrato":
    c1, c2 = st.columns([2,1])
    mes = c1.selectbox("Mês", range(1,13), index=date.today().month-1)
    ano = c2.number_input("Ano", 2024, 2030, date.today().year)

    if not df_total.empty:
        mask = (df_total['data_dt'].dt.month == mes) & (df_total['data_dt'].dt.year == ano)
        df_mes = df_total[mask].copy()
        
        rec = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        desp = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        
        # Meta Visual
        if meta_mensal > 0:
            pg = min(desp/meta_mensal, 1.0)
            st.caption(f"Meta: {fmt_real(desp)} / {fmt_real(meta_mensal)}")
            st.progress(pg)

        c_a, c_b = st.columns(2)
        c_a.metric("Entrou", f"R$ {fmt_real(rec)}")
        c_b.metric("Saiu", f"R$ {fmt_real(desp)}", delta_color="inverse")

        st.divider()
        st.subheader("📝 Editar Lançamentos")
        
        # [CORREÇÃO ERRO TABELA]
        # Preparamos os dados para o Editor garantindo que DATA seja objeto DATE, não string
        df_edit = df_mes.copy()
        # Converte para datetime e extrai apenas a data (date object)
        df_edit['data'] = pd.to_datetime(df_edit['data']).dt.date 
        
        # Seleciona colunas e ordena
        df_edit = df_edit[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values('data', ascending=False)

        mudancas = st.data_editor(
            df_edit,
            column_config={
                "id": None,
                "valor": st.column_config.NumberColumn("R$", format="R$ %.2f", min_value=0.0),
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"), # Agora funciona pois recebe Date Objects
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Receita", "Despesa"], required=True),
                "categoria": st.column_config.SelectboxColumn("Categ.", options=["Alimentação", "Transporte", "Casa", "Lazer", "Outros"])
            },
            hide_index=True, use_container_width=True, num_rows="dynamic", key="grid_editor"
        )

        if st.button("💾 Salvar Alterações"):
            with st.spinner("Salvando..."):
                ids_orig = df_mes['id'].tolist()
                
                # Detecta inserções e updates
                for i, row in mudancas.iterrows():
                    d = row.to_dict()
                    
                    # [IMPORTANTE] Converter Date Object de volta para String YYYY-MM-DD para o Supabase
                    if isinstance(d['data'], (date, datetime)):
                        d['data'] = d['data'].strftime('%Y-%m-%d')
                    
                    if pd.isna(d['id']): 
                        # É um novo item inserido pela tabela? (Opcional: implementar insert se quiser)
                        pass 
                    else:
                        executar_sql('update', d, user['id'])
                
                # Detecta deleções
                ids_novos = mudancas['id'].dropna().tolist()
                removidos = set(ids_orig) - set(ids_novos)
                for id_rem in removidos:
                    executar_sql('delete', {'id': id_rem}, user['id'])
                
                st.toast("Atualizado com sucesso!")
                time.sleep(1)
                st.rerun()
    else: 
        st.info("Nenhuma transação neste período.")

# =======================================================
# TELA 3: ANÁLISE
# =======================================================
elif selected_nav == "📈 Análise":
    st.subheader("Gráficos")
    if not df_total.empty:
        df_atual = df_total[df_total['data_dt'].dt.month == date.today().month]
        gastos = df_atual[df_atual['tipo'] != 'Receita']
        
        if not gastos.empty:
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.6)
            st.plotly_chart(fig, use_container_width=True)
            
            top = gastos.groupby('categoria')['valor'].sum().sort_values(ascending=False)
            for c, v in top.items():
                st.write(f"**{c}**: R$ {fmt_real(v)}")
                st.progress(int((v/gastos['valor'].sum())*100))
        else: st.info("Sem gastos este mês.")
