import streamlit as st
import pandas as pd
import plotly.express as px
from supabase import create_client, Client
from datetime import datetime, date, timedelta
import time
import json
import google.generativeai as genai

# --- 1. Configuração Mobile-First ---
st.set_page_config(page_title="AppFinanças", page_icon="💳", layout="wide", initial_sidebar_state="collapsed")

# --- 2. CSS "App Nativo" Otimizado ---
st.markdown("""
<style>
    /* ESPAÇAMENTO E REMOÇÃO DE CABEÇALHO PADRÃO */
    .block-container {padding-top: 1rem !important; padding-bottom: 6rem !important;} 
    /* .stAppHeader {display:none !important;}  <-- REMOVIDO PARA EVITAR BUGS, MAS PODE MANTER SE QUISER */
    
    /* MENU DE NAVEGAÇÃO ESTILO iOS */
    div[role="radiogroup"] {
        flex-direction: row; justify-content: center; background-color: #1E1E1E;
        padding: 5px; border-radius: 12px; margin-bottom: 20px;
        overflow-x: auto; /* Permite rolagem se a tela for muito pequena */
    }
    div[role="radiogroup"] label {
        background: transparent; border: none; padding: 10px 10px; border-radius: 8px;
        text-align: center; flex-grow: 1; cursor: pointer; color: #888; white-space: nowrap;
    }
    div[role="radiogroup"] label[data-checked="true"] {
        background-color: #00CC96 !important; color: #000 !important;
        font-weight: bold; box-shadow: 0 2px 5px rgba(0,0,0,0.2);
    }
    
    /* INPUTS E BOTÕES */
    .stButton button { width: 100%; height: 50px; border-radius: 12px; font-weight: 600; }
    
    /* CARDS */
    .app-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border: 1px solid #333; margin-bottom: 10px;
    }
    .budget-card {
        background-color: #262730; padding: 15px; border-radius: 12px;
        border-left: 5px solid #00CC96; margin-bottom: 15px;
    }
    
    /* TEXTO PEQUENO EM INPUTS */
    .stNumberInput label, .stTextInput label, .stDateInput label { font-size: 0.8rem; }
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
def carregar_dados_generico(tabela, user_id):
    try:
        res = supabase.table(tabela).select("*").eq("user_id", user_id).execute()
        return pd.DataFrame(res.data)
    except: return pd.DataFrame()

def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except: return pd.DataFrame()

def executar_sql(tabela, acao, dados, user_id):
    try:
        ref = supabase.table(tabela)
        if acao == 'insert':
            if 'id' in dados and (pd.isna(dados['id']) or dados['id'] == ''): del dados['id']
            dados['user_id'] = user_id
            ref.insert(dados).execute()
        elif acao == 'update':
            if not dados.get('id'): return False
            payload = {k: v for k, v in dados.items() if k not in ['user_id', 'created_at']}
            ref.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            ref.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro SQL ({tabela}): {e}"); return False

def fmt_real(valor):
    if pd.isna(valor): return "0,00"
    return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA ---
def limpar_json(texto):
    texto = texto.replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['data', 'descricao', 'valor', 'categoria']].head(5).to_json(orient="records")

    prompt = f"""
    Atue como extrator de dados financeiros. Hoje: {date.today()}. Histórico: {contexto}
    Identifique: Valor (float), Descrição, Categoria, Tipo (Receita/Despesa). Data (padrão hoje).
    JSON APENAS: {{ "acao": "insert", "dados": {{ "data": "YYYY-MM-DD", "valor": 0.00, "categoria": "Outros", "descricao": "Item", "tipo": "Despesa" }}, "msg_ia": "Texto curto" }}
    """
    try:
        model = genai.GenerativeModel('gemini-flash-latest')
        if tipo_entrada == "audio":
            response = model.generate_content([prompt, {"mime_type": "audio/wav", "data": entrada.getvalue()}], generation_config={"response_mime_type": "application/json"})
        else:
            full_prompt = f"{prompt}\nEntrada: '{entrada}'"
            response = model.generate_content(full_prompt, generation_config={"response_mime_type": "application/json"})
        return limpar_json(response.text)
    except Exception as e:
        return {"acao": "erro", "msg": f"Erro: {str(e)}"}

def coach_financeiro(df_gastos, df_metas, df_fixos):
    if not IA_AVAILABLE: return "IA Indisponível."
    resumo = df_gastos.groupby('categoria')['valor'].sum().to_dict()
    metas = df_metas.to_dict(orient='records') if not df_metas.empty else "Sem metas"
    fixos = df_fixos['valor'].sum() if not df_fixos.empty else 0
    prompt = f"Analise como coach financeiro curto. Gastos Mês: {resumo}. Metas: {metas}. Fixos: {fixos}. Dê 1 conselho e 1 alerta."
    model = genai.GenerativeModel('gemini-flash-latest')
    return model.generate_content(prompt).text

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
            try:
                resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                if resp.data: st.session_state['user'] = resp.data[0]; st.rerun()
                else: st.error("Inválido")
            except: st.error("Erro Conexão")
    st.stop()

user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 200)

# =======================================================
# MENU PRINCIPAL (Agora com 4 opções)
# =======================================================
selected_nav = st.radio("Nav", ["💬 Chat", "💳 Extrato", "📈 Análise", "⚙️ Ajustes"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# 1. CHAT
# =======================================================
if selected_nav == "💬 Chat":
    if "msgs" not in st.session_state: st.session_state.msgs = [{"role": "assistant", "content": "Olá! O que vamos registrar?"}]
    if "op_pendente" not in st.session_state: st.session_state.op_pendente = None
    if "last_audio_id" not in st.session_state: st.session_state.last_audio_id = None

    for m in st.session_state.msgs:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if not st.session_state.op_pendente:
        c1, c2, c3 = st.columns(3)
        sugestao = None
        if c1.button("🍔 Almoço"): sugestao = "Almoço 35 reais"
        if c2.button("🚗 Uber"): sugestao = "Uber 20 reais"
        if c3.button("💰 Recebi"): sugestao = "Recebi 100 reais"

        audio_val = st.audio_input("Falar", label_visibility="collapsed")
        text_val = st.chat_input("Digitar...")
        
        final_input, tipo = None, "texto"
        if sugestao: final_input = sugestao; st.session_state.last_audio_id = audio_val
        elif text_val: final_input = text_val; st.session_state.last_audio_id = audio_val
        elif audio_val and audio_val != st.session_state.last_audio_id:
            final_input = audio_val; tipo = "audio"; st.session_state.last_audio_id = audio_val

        if final_input:
            st.session_state.msgs.append({"role": "user", "content": final_input if tipo=="texto" else "🎤 *Áudio enviado*"})
            with st.chat_message("assistant"):
                with st.spinner("..."):
                    res = agente_financeiro_ia(final_input, df_total, tipo)
                    if res.get('acao') == 'insert': st.session_state.op_pendente = res; st.rerun()
                    elif res.get('acao') == 'erro': st.error(res.get('msg'))
                    else: st.markdown(res.get('msg_ia')); st.session_state.msgs.append({"role": "assistant", "content": res.get('msg_ia')})

    if st.session_state.op_pendente:
        d = st.session_state.op_pendente.get('dados', {})
        st.markdown(f"""
        <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
            <b>{d.get('descricao')}</b><br>
            <span style="font-size:1.5em">R$ {fmt_real(d.get('valor', 0))}</span><br>
            <small>{d.get('categoria')} • {d.get('data')}</small>
        </div>""", unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmar", type="primary", use_container_width=True):
            executar_sql('transactions', 'insert', d, user['id'])
            st.toast("Salvo!"); st.session_state.op_pendente = None; st.rerun()
        if c2.button("❌ Cancelar", use_container_width=True):
            st.session_state.op_pendente = None; st.rerun()

# =======================================================
# 2. EXTRATO
# =======================================================
elif selected_nav == "💳 Extrato":
    c1, c2 = st.columns([2, 1])
    mes = c1.selectbox("Mês", range(1,13), index=date.today().month-1)
    ano = c2.number_input("Ano", 2024, 2030, date.today().year)

    if not df_total.empty:
        df_v = df_total.copy()
        df_v['data_dt'] = pd.to_datetime(df_v['data'], errors='coerce')
        df_mes = df_v[(df_v['data_dt'].dt.month == mes) & (df_v['data_dt'].dt.year == ano)].copy()
        
        # Meta e Fixos
        meta_val = st.session_state.get('meta_mensal', 3000.0)
        df_fixos = carregar_dados_generico("recurrent_expenses", user['id'])
        fixos_val = df_fixos['valor'].sum() if not df_fixos.empty else 0
        gastos_var = df_mes[df_mes['tipo']!='Receita']['valor'].sum()
        
        total_previsto = gastos_var + fixos_val
        perc = min(total_previsto/meta_val, 1.0) if meta_val > 0 else 0
        
        st.markdown(f"""
        <div class="budget-card">
            <div style="display:flex; justify-content:space-between"><span>Variável</span><b>R$ {fmt_real(gastos_var)}</b></div>
            <div style="display:flex; justify-content:space-between; color:#888"><span>+ Fixos</span><span>R$ {fmt_real(fixos_val)}</span></div>
            <hr style="border-color:#444">
            <div style="display:flex; justify-content:space-between"><span>Total</span><b>R$ {fmt_real(total_previsto)} / {fmt_real(meta_val)}</b></div>
        </div>""", unsafe_allow_html=True)
        st.progress(perc)

        # Edição
        st.subheader("📝 Lançamentos")
        df_edit = df_mes.copy()
        df_edit['data'] = df_edit['data_dt'].dt.date
        df_edit = df_edit[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values('data', ascending=False)
        
        mudancas = st.data_editor(df_edit, column_config={
            "id": None, "valor": st.column_config.NumberColumn(format="R$ %.2f"),
            "data": st.column_config.DateColumn(format="DD/MM/YYYY"),
            "tipo": st.column_config.SelectboxColumn(options=["Receita", "Despesa"]),
            "categoria": st.column_config.SelectboxColumn(options=["Alimentação", "Transporte", "Casa", "Lazer", "Investimento", "Outros"])
        }, hide_index=True, use_container_width=True, num_rows="dynamic", key="grid1")
        
        if st.button("💾 Atualizar", type="primary"):
            orig = df_edit['id'].tolist()
            for i, row in mudancas.iterrows():
                d = row.to_dict()
                if isinstance(d['data'], (date, datetime)): d['data'] = d['data'].strftime('%Y-%m-%d')
                if pd.isna(d['id']): pass
                else: executar_sql('transactions', 'update', d, user['id'])
            novos = mudancas['id'].dropna().tolist()
            for x in set(orig) - set(novos): executar_sql('transactions', 'delete', {'id': x}, user['id'])
            st.rerun()
    else: st.info("Sem dados.")

# =======================================================
# 3. ANÁLISE
# =======================================================
elif selected_nav == "📈 Análise":
    st.subheader("Raio-X")
    c1, c2 = st.columns(2)
    periodo = c1.selectbox("Período", ["Mês Atual", "Últimos 3 Meses", "Ano"])
    
    if not df_total.empty:
        df_a = df_total.copy()
        df_a['data_dt'] = pd.to_datetime(df_a['data'], errors='coerce')
        if periodo == "Mês Atual": df_f = df_a[df_a['data_dt'].dt.month == date.today().month]
        elif periodo == "Ano": df_f = df_a[df_a['data_dt'].dt.year == date.today().year]
        else: df_f = df_a[df_a['data_dt'] >= pd.to_datetime(date.today()-timedelta(days=90))]
        
        gastos = df_f[df_f['tipo']!='Receita']
        cat_foco = c2.selectbox("Filtrar", ["Todas"] + list(gastos['categoria'].unique()))
        
        if not gastos.empty:
            if st.button("🤖 Insight IA", use_container_width=True):
                m = carregar_dados_generico("goals", user['id'])
                f = carregar_dados_generico("recurrent_expenses", user['id'])
                st.info(coach_financeiro(gastos, m, f))
            
            c_gf, c_ls = st.columns([1.2, 1])
            df_g = gastos if cat_foco == "Todas" else gastos[gastos['categoria']==cat_foco]
            
            with c_gf:
                fig = px.pie(df_g, values='valor', names='categoria', hole=0.7, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig.update_layout(showlegend=False, margin=dict(t=0,b=0,l=0,r=0), height=220, paper_bgcolor='rgba(0,0,0,0)')
                fig.add_annotation(text=f"R$ {fmt_real(df_g['valor'].sum())}", showarrow=False, font_size=16)
                st.plotly_chart(fig, use_container_width=True)
            
            with c_ls:
                st.markdown("##### Ranking")
                rank = df_g.groupby('categoria')['valor'].sum().sort_values(ascending=False)
                tot = df_g['valor'].sum()
                for cat, val in rank.items():
                    pct = val/tot
                    st.markdown(f"<div style='font-size:0.9em; display:flex; justify-content:space-between'><span>{cat}</span><span>{int(pct*100)}%</span></div>", unsafe_allow_html=True)
                    st.progress(pct)
            
            st.markdown("---")
            st.subheader("🎯 Metas")
            df_m = carregar_dados_generico("goals", user['id'])
            if not df_m.empty:
                for _, m in df_m.iterrows():
                    p = min(m['valor_atual']/m['valor_alvo'], 1.0)
                    st.markdown(f"<small>{m['descricao']} (R$ {fmt_real(m['valor_atual'])} / {fmt_real(m['valor_alvo'])})</small>", unsafe_allow_html=True)
                    st.progress(p)
            else: st.caption("Configure suas metas em Ajustes.")
        else: st.info("Sem gastos.")

# =======================================================
# 4. AJUSTES (NOVO LUGAR PARA METAS E RECORRENTES)
# =======================================================
elif selected_nav == "⚙️ Ajustes":
    st.header("Configurações")
    
    st.session_state['meta_mensal'] = st.number_input("Limite de Gastos (Meta Mensal)", value=st.session_state.get('meta_mensal', 3000.0), step=100.0)
    
    with st.expander("🔄 Contas Fixas (Recorrentes)", expanded=True):
        st.caption("Ex: Aluguel, Internet, Netflix")
        df_rec = carregar_dados_generico("recurrent_expenses", user['id'])
        ed_rec = st.data_editor(df_rec, num_rows="dynamic", column_config={
            "id": None, "user_id": None, "created_at": None,
            "descricao": "Nome", "valor": st.column_config.NumberColumn("R$", format="%.2f"),
            "dia_vencimento": st.column_config.NumberColumn("Dia Venc.", min_value=1, max_value=31)
        }, key="ed_rec")
        
        if st.button("Salvar Fixos"):
            orig = df_rec['id'].tolist() if not df_rec.empty else []
            for i, row in ed_rec.iterrows():
                d = row.to_dict()
                if pd.isna(d.get('id')): executar_sql('recurrent_expenses', 'insert', d, user['id'])
                else: executar_sql('recurrent_expenses', 'update', d, user['id'])
            novos = ed_rec['id'].dropna().tolist()
            for x in set(orig) - set(novos): executar_sql('recurrent_expenses', 'delete', {'id': x}, user['id'])
            st.toast("Fixos salvos!")
            time.sleep(1); st.rerun()

    with st.expander("🎯 Metas & Sonhos", expanded=False):
        st.caption("Ex: Viagem, Carro Novo")
        df_metas = carregar_dados_generico("goals", user['id'])
        ed_metas = st.data_editor(df_metas, num_rows="dynamic", column_config={
            "id": None, "user_id": None, "created_at": None,
            "descricao": "Meta", "valor_alvo": st.column_config.NumberColumn("Alvo", format="%.2f"),
            "valor_atual": st.column_config.NumberColumn("Já Tenho", format="%.2f"),
            "data_limite": st.column_config.DateColumn("Prazo")
        }, key="ed_metas")
        
        if st.button("Salvar Metas"):
            orig = df_metas['id'].tolist() if not df_metas.empty else []
            for i, row in ed_metas.iterrows():
                d = row.to_dict()
                if isinstance(d.get('data_limite'), (date, datetime)): d['data_limite'] = d['data_limite'].strftime('%Y-%m-%d')
                if pd.isna(d.get('id')): executar_sql('goals', 'insert', d, user['id'])
                else: executar_sql('goals', 'update', d, user['id'])
            novos = ed_metas['id'].dropna().tolist()
            for x in set(orig) - set(novos): executar_sql('goals', 'delete', {'id': x}, user['id'])
            st.toast("Metas salvas!")
            time.sleep(1); st.rerun()
            
    if st.button("Sair da Conta"): st.session_state.clear(); st.rerun()
