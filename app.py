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

# --- 2. CSS "App Nativo" Otimizado (Do código Visual) ---
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
    
    /* INPUTS E BOTÕES */
    .stButton button { width: 100%; height: 50px; border-radius: 12px; font-weight: 600; }
    
    /* AJUSTE DO MICROFONE PARA FICAR DISCRETO */
    div[data-testid="stAudioInput"] { margin-top: -10px; margin-bottom: 10px; }
    div[data-testid="stAudioInput"] label { display: none; }

    /* CARDS DE CONFIRMAÇÃO E METAS */
    .app-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border: 1px solid #333; margin-bottom: 10px;
    }
    .budget-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border-left: 5px solid #00CC96; margin-bottom: 15px;
    }
    
    /* PROGRESSO */
    .stProgress > div > div > div > div { background-color: #00CC96; }
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
    """Formata float para BRL"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA (Lógica Robusta do Código Funcional) ---
def limpar_json(texto):
    """Remove formatação Markdown que a IA coloca"""
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
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if tipo_entrada == "audio":
            # Envio direto de bytes (Funcional)
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
# LOGIN & CONFIG
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    st.markdown("<br><h2 style='text-align:center'>🔒 Login</h2>", unsafe_allow_html=True)
    with st.form("login"):
        u = st.text_input("Usuário")
        p = st.text_input("Senha", type="password")
        if st.form_submit_button("Entrar"):
            try:
                resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                if resp.data: st.session_state['user'] = resp.data[0]; st.rerun()
                else: st.error("Login Inválido")
            except: st.error("Erro Conexão")
    st.stop()

user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 100)

with st.sidebar:
    st.header(f"Olá, {user.get('username')}")
    # Feature Visual: Meta de Gastos
    meta_mensal = st.number_input("Meta Mensal (R$)", value=3000.0, step=100.0)
    if st.button("Sair"): st.session_state.clear(); st.rerun()

# Navegação iOS Style
selected_nav = st.radio("Menu", ["💬 Chat", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# 1. CHAT (Lógica Funcional + Visual Bonito)
# =======================================================
if selected_nav == "💬 Chat":
    # Estados
    if "msgs" not in st.session_state: 
        st.session_state.msgs = [{"role": "assistant", "content": "Olá! Toque no microfone para registrar um gasto."}]
    if "op_pendente" not in st.session_state: st.session_state.op_pendente = None
    if "last_audio_id" not in st.session_state: st.session_state.last_audio_id = None

    # Histórico Visual
    for m in st.session_state.msgs:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    # Se não tem operação pendente, libera inputs
    if not st.session_state.op_pendente:
        
        # Sugestões Visuais (Buttons)
        c1, c2, c3 = st.columns(3)
        sugestao = None
        if c1.button("🍔 Almoço"): sugestao = "Almoço 30 reais"
        if c2.button("🚗 Uber"): sugestao = "Uber 15 reais"
        if c3.button("💰 Recebi"): sugestao = "Recebi 50 reais"

        # Inputs
        audio_val = st.audio_input("Falar", label_visibility="collapsed")
        text_val = st.chat_input("Ou digite...")

        final_input = None
        tipo = "texto"

        # Lógica de Prioridade (Botão > Texto > Áudio Novo)
        if sugestao:
            final_input = sugestao
            st.session_state.last_audio_id = audio_val # Ignora áudio parado
        elif text_val:
            final_input = text_val
            st.session_state.last_audio_id = audio_val # Ignora áudio parado
        elif audio_val:
            # Lógica Anti-Loop
            if audio_val != st.session_state.last_audio_id:
                final_input = audio_val
                tipo = "audio"
                st.session_state.last_audio_id = audio_val

        # Processamento
        if final_input:
            if tipo == "texto":
                st.session_state.msgs.append({"role": "user", "content": final_input})
            else:
                st.session_state.msgs.append({"role": "user", "content": "🎤 *Áudio Enviado...*"})

            with st.chat_message("assistant"):
                with st.spinner("Processando..."):
                    res = agente_financeiro_ia(final_input, df_total, tipo)
                    
                    if res.get('acao') == 'insert':
                        st.session_state.op_pendente = res
                        st.rerun()
                    elif res.get('acao') == 'erro':
                        st.error(f"Erro: {res.get('msg')}")
                    else:
                        msg = res.get('msg_ia', "Ok.")
                        st.markdown(msg)
                        st.session_state.msgs.append({"role": "assistant", "content": msg})

    # Tela de Confirmação (Visual Card Otimizado)
    if st.session_state.op_pendente:
        op = st.session_state.op_pendente
        d = op.get('dados', {})
        
        with st.container():
            st.markdown("### ⚠️ Confirmar Lançamento?")
            
            # Card CSS Bonito
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
                final = d.copy()
                final['user_id'] = user['id']
                if executar_sql('insert', final, user['id']):
                    st.toast("Salvo com sucesso!", icon="🎉")
                    st.session_state.msgs.append({"role": "assistant", "content": f"✅ Registrado: {d.get('descricao')}"})
                st.session_state.op_pendente = None
                time.sleep(1)
                st.rerun()
                
            if c2.button("❌ Cancelar", use_container_width=True):
                st.session_state.op_pendente = None
                st.rerun()

# =======================================================
# 2. EXTRATO (Visual Card + Lógica Data Editor Robusta)
# =======================================================
elif selected_nav == "💳 Extrato":
    
    # Filtros
    c_f1, c_f2 = st.columns([2, 1])
    filtro_mes = c_f1.selectbox("Mês", range(1,13), index=date.today().month-1)
    filtro_ano = c_f2.number_input("Ano", 2024, 2030, date.today().year)

    if not df_total.empty:
        # Preparação de Dados (Lógica Robusta do Código Funcional)
        df_view = df_total.copy()
        df_view['data_dt'] = pd.to_datetime(df_view['data'], errors='coerce')
        
        # Filtra Mês/Ano
        mask = (df_view['data_dt'].dt.month == filtro_mes) & (df_view['data_dt'].dt.year == filtro_ano)
        df_mes = df_view[mask].copy()

        # Cálculos para o Card de Meta
        gastos = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        receitas = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()

        # Visual Card de Meta (Do Código Visual)
        if meta_mensal > 0:
            perc = min(gastos / meta_mensal, 1.0)
            st.markdown(f"""
            <div class="budget-card">
                <span style="font-size:14px; color:#AAA;">Orçamento Mensal</span><br>
                <span style="font-size:20px; font-weight:bold;">R$ {fmt_real(gastos)}</span> 
                <span style="font-size:14px;"> / {fmt_real(meta_mensal)}</span>
            </div>
            """, unsafe_allow_html=True)
            st.progress(perc)
            if perc >= 1.0: st.error("🚨 Orçamento Atingido!")

        # Editor de Dados (Lógica Crítica para não quebrar datas)
        st.subheader("📝 Editar")
        
        df_edit = df_mes.copy()
        df_edit = df_edit.dropna(subset=['data_dt']) # Remove datas bugadas
        df_edit['data'] = df_edit['data_dt'].dt.date # Converte para Date Object (Essencial!)
        df_edit = df_edit[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values('data', ascending=False)

        mudancas = st.data_editor(
            df_edit,
            column_config={
                "id": None,
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Receita", "Despesa"]),
                "categoria": st.column_config.SelectboxColumn("Cat", options=["Alimentação", "Transporte", "Casa", "Lazer", "Outros"])
            },
            hide_index=True, use_container_width=True, num_rows="dynamic", key="grid_final"
        )

        if st.button("💾 Salvar Alterações", type="primary"):
            with st.spinner("Sincronizando..."):
                ids_orig = df_edit['id'].tolist()
                
                # Updates
                for i, row in mudancas.iterrows():
                    d = row.to_dict()
                    # Converte de volta para string YYYY-MM-DD para o Supabase
                    if isinstance(d['data'], (date, datetime)):
                        d['data'] = d['data'].strftime('%Y-%m-%d')
                    
                    if pd.isna(d['id']): pass # Ignora insert manual por enquanto
                    else: executar_sql('update', d, user['id'])
                
                # Deletes
                ids_new = mudancas['id'].dropna().tolist()
                for x in set(ids_orig) - set(ids_new):
                    executar_sql('delete', {'id': x}, user['id'])
                
                st.toast("Atualizado!")
                time.sleep(1)
                st.rerun()
    else:
        st.info("Sem dados.")

# =======================================================
# 3. ANÁLISE (Visual Limpo)
# =======================================================
elif selected_nav == "📈 Análise":
    st.subheader("Raio-X Financeiro")
    if not df_total.empty:
        df_a = df_total.copy()
        df_a['data_dt'] = pd.to_datetime(df_a['data'], errors='coerce')
        df_mes = df_a[df_a['data_dt'].dt.month == date.today().month]
        
        gastos = df_mes[df_mes['tipo'] != 'Receita']
        
        if not gastos.empty:
            # Gráfico Limpo (Do código Visual)
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.6, 
                         color_discrete_sequence=px.colors.qualitative.Set3)
            fig.update_traces(textinfo='percent+label')
            fig.update_layout(showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=300)
            st.plotly_chart(fig, use_container_width=True)
            
            # Lista Top Gastos
            st.markdown("##### 🏆 Maiores Gastos")
            top = gastos.groupby('categoria')['valor'].sum().sort_values(ascending=False)
            total_g = gastos['valor'].sum()
            
            for cat, val in top.items():
                pct = int((val/total_g)*100)
                st.markdown(f"**{cat}** — R$ {fmt_real(val)}")
                st.progress(pct)
        else:
            st.info("Sem gastos este mês.")
