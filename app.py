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

# --- 2. CSS "App Nativo" (Visual Rico do Código 1) ---
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

    /* CARD DE META (ORÇAMENTO) */
    .budget-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border-left: 5px solid #00CC96; margin-bottom: 15px;
    }

    /* MICROFONE DISCRETO */
    div[data-testid="stAudioInput"] { margin-top: -10px; margin-bottom: 10px; }
    div[data-testid="stAudioInput"] label { display: none; }
    
    /* BOTÕES */
    .stButton button { width: 100%; height: 50px; border-radius: 12px; font-weight: 600; }
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
def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df['data_dt'] = pd.to_datetime(df['data'], errors='coerce')
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except Exception as e:
        return pd.DataFrame()

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

def fmt_real(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA (Lógica Robusta do Código 2 com Limpeza JSON) ---
def limpar_json(texto):
    """Remove formatação Markdown que a IA as vezes coloca"""
    texto = texto.replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['data', 'descricao', 'valor', 'categoria']].head(5).to_json(orient="records")

    prompt = f"""
    Atue como um extrator de dados financeiros.
    Hoje: {date.today()}.
    Histórico Recente: {contexto}
    
    INSTRUÇÕES:
    1. Identifique: Valor (float com ponto), Descrição, Categoria, Tipo (Receita/Despesa).
    2. Data: Se não citada, use hoje ({date.today()}).
    3. Responda APENAS o JSON puro, sem markdown.
    
    FORMATO JSON ESPERADO:
    {{
        "acao": "insert",
        "dados": {{
            "data": "YYYY-MM-DD",
            "valor": 0.00,
            "categoria": "Outros",
            "descricao": "Item",
            "tipo": "Despesa"
        }},
        "msg_ia": "Confirmação curta"
    }}
    """
    
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        
        if tipo_entrada == "audio":
            # Usa Bytes direto (Sem tempfile para evitar erros de permissão/cloud)
            response = model.generate_content(
                [prompt, {"mime_type": "audio/wav", "data": entrada.getvalue()}, "Extraia o JSON desta fala."],
                generation_config={"response_mime_type": "application/json"}
            )
        else:
            full_prompt = f"{prompt}\nEntrada do Usuário: '{entrada}'"
            response = model.generate_content(full_prompt, generation_config={"response_mime_type": "application/json"})
            
        return limpar_json(response.text)

    except Exception as e:
        return {"acao": "erro", "msg": f"Erro ao processar: {str(e)}"}

# =======================================================
# LOGIN & SIDEBAR
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None
if not st.session_state['user']:
    with st.form("login"):
        st.write("Login Finanças")
        u = st.text_input("User")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Entrar"):
            try:
                resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                if resp.data: st.session_state['user'] = resp.data[0]; st.rerun()
                else: st.error("Inválido")
            except: st.error("Erro Conexão")
    st.stop()

user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 100)

with st.sidebar:
    st.header("⚙️ Ajustes")
    # Meta recuperada do Código 1
    meta_mensal = st.number_input("Meta de Gastos (Mês)", value=3000.0, step=100.0)
    if st.button("Sair"): st.session_state.clear(); st.rerun()

nav = st.radio("Menu", ["💬 Chat", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# 1. CHAT (Lógica Código 2 + Visual Código 1)
# =======================================================
if nav == "💬 Chat":
    if "msgs" not in st.session_state: st.session_state.msgs = []
    if "op_pendente" not in st.session_state: st.session_state.op_pendente = None
    if "last_audio_id" not in st.session_state: st.session_state.last_audio_id = None

    # Histórico
    for m in st.session_state.msgs:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if not st.session_state.op_pendente:
        # Sugestões (Visual Código 1)
        c1, c2, c3 = st.columns(3)
        sugestao = None
        if c1.button("🍔 Almoço"): sugestao = "Almoço 30 reais"
        if c2.button("🚗 Uber"): sugestao = "Uber 15 reais"
        if c3.button("💰 Recebi"): sugestao = "Recebi 50 reais"

        # Inputs (Lógica Robusta Anti-Loop)
        audio_val = st.audio_input("Falar", label_visibility="collapsed")
        text_val = st.chat_input("Digite...")

        final_input = None
        tipo = "texto"

        if sugestao:
            final_input = sugestao
            st.session_state.last_audio_id = audio_val # Ignora áudio parado
        elif text_val:
            final_input = text_val
            st.session_state.last_audio_id = audio_val # Ignora áudio parado
        elif audio_val:
            # Só processa se o áudio for NOVO
            if audio_val != st.session_state.last_audio_id:
                final_input = audio_val
                tipo = "audio"
                st.session_state.last_audio_id = audio_val

        if final_input:
            if tipo == "texto":
                st.session_state.msgs.append({"role": "user", "content": final_input})
            else:
                st.session_state.msgs.append({"role": "user", "content": "🎤 *Áudio Enviado*"})

            with st.chat_message("assistant"):
                with st.spinner("Processando..."):
                    res = agente_financeiro_ia(final_input, df_total, tipo)
                    
                    if res.get('acao') == 'insert':
                        st.session_state.op_pendente = res
                        st.rerun()
                    elif res.get('acao') == 'erro':
                        st.error(f"IA: {res.get('msg')}")
                    else:
                        st.markdown(res.get('msg_ia', "Não entendi."))

    # Confirmação (Visual Bonito do Código 1)
    if st.session_state.op_pendente:
        op = st.session_state.op_pendente
        d = op.get('dados', {})
        val_fmt = fmt_real(d.get('valor', 0))
        
        with st.container():
            st.info("CONFIRMAR LANÇAMENTO?")
            # Card HTML Rico (Código 1)
            st.markdown(f"""
            <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
                <div class="card-title">{d.get('descricao', 'Sem descrição')}</div>
                <div class="card-amount">R$ {val_fmt}</div>
                <div class="card-meta">{d.get('categoria')} • {d.get('data')}</div>
            </div>
            """, unsafe_allow_html=True)
            
            c1, c2 = st.columns(2)
            if c1.button("✅ Confirmar", type="primary"):
                final = d.copy()
                final['user_id'] = user['id']
                if executar_sql('insert', final, user['id']):
                    st.toast("Salvo!")
                    st.session_state.msgs.append({"role": "assistant", "content": "✅ Salvo."})
                st.session_state.op_pendente = None
                time.sleep(1)
                st.rerun()
            if c2.button("❌ Cancelar"):
                st.session_state.op_pendente = None
                st.rerun()

# =======================================================
# 2. EXTRATO (Meta do Código 1 + Correção Data do Código 2)
# =======================================================
elif nav == "💳 Extrato":
    st.subheader("Extrato")
    
    # Filtros
    c_f1, c_f2 = st.columns([2, 1])
    mes = c_f1.selectbox("Mês", range(1,13), index=date.today().month-1)
    ano = c_f2.number_input("Ano", 2024, 2030, date.today().year)

    if not df_total.empty:
        # Prepara dados
        df_g = df_total.copy()
        df_g['data_dt'] = pd.to_datetime(df_g['data'], errors='coerce')
        mask = (df_g['data_dt'].dt.month == mes) & (df_g['data_dt'].dt.year == ano)
        df_mes = df_g[mask].copy()

        # Resumo
        rec = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        desp = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()

        # --- FEATURE: PROGRESSO DA META (Recuperado do Cód 1) ---
        if meta_mensal > 0:
            perc = min(desp / meta_mensal, 1.0)
            st.markdown(f"""
            <div class="budget-card">
                <span style="font-size:14px; color:#AAA;">Orçamento</span><br>
                <span style="font-size:20px; font-weight:bold;">R$ {fmt_real(desp)}</span> 
                <span style="font-size:14px;"> / {fmt_real(meta_mensal)}</span>
            </div>
            """, unsafe_allow_html=True)
            st.progress(perc)
            if perc >= 1.0: st.error("🚨 Orçamento Estourado!")

        c1, c2 = st.columns(2)
        c1.metric("Entradas", f"R$ {fmt_real(rec)}")
        c2.metric("Saídas", f"R$ {fmt_real(desp)}", delta_color="inverse")

        st.divider()
        st.caption("Edite valores diretamente na tabela:")

        # --- EDITOR BLINDADO (Lógica do Cód 2) ---
        # 1. Limpa datas inválidas
        df_edit = df_mes.dropna(subset=['data_dt']).copy()
        # 2. Converte para DATE OBJECT (Essencial para não travar)
        df_edit['data'] = df_edit['data_dt'].dt.date
        
        df_edit = df_edit[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values(by='data', ascending=False)

        try:
            mudancas = st.data_editor(
                df_edit,
                column_config={
                    "id": None,
                    "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f", step=0.1),
                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Receita", "Despesa"]),
                    "categoria": st.column_config.SelectboxColumn("Cat", options=["Alimentação", "Transporte", "Casa", "Lazer", "Outros"])
                },
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                key="editor_final"
            )

            if st.button("Salvar Edições", type="primary"):
                with st.spinner("Sincronizando..."):
                    ids_orig = df_edit['id'].tolist()
                    
                    for i, row in mudancas.iterrows():
                        d = row.to_dict()
                        # REVERSÃO: Date Object -> String para Supabase
                        if isinstance(d['data'], (date, datetime)):
                            d['data'] = d['data'].strftime('%Y-%m-%d')
                            
                        if pd.isna(d['id']): pass 
                        else: executar_sql('update', d, user['id'])
                    
                    ids_new = mudancas['id'].dropna().tolist()
                    for id_del in set(ids_orig) - set(ids_new):
                        executar_sql('delete', {'id': id_del}, user['id'])
                        
                    st.toast("Atualizado!")
                    time.sleep(1)
                    st.rerun()
        except Exception as e:
            st.error(f"Erro tabela: {e}")
    else:
        st.info("Sem dados.")

# =======================================================
# 3. ANÁLISE
# =======================================================
elif nav == "📈 Análise":
    st.subheader("Raio-X")
    if not df_total.empty:
        df_g = df_total.copy()
        df_g['data_dt'] = pd.to_datetime(df_g['data'], errors='coerce')
        df_mes = df_g[df_g['data_dt'].dt.month == date.today().month]
        
        gastos = df_mes[df_mes['tipo'] != 'Receita']
        if not gastos.empty:
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.5,
                         color_discrete_sequence=px.colors.qualitative.Set3)
            st.plotly_chart(fig, use_container_width=True)
            
            total = gastos['valor'].sum()
            st.metric("Total Gasto (Mês)", f"R$ {fmt_real(total)}")
        else:
            st.info("Sem gastos este mês.")

