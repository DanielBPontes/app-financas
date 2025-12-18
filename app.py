import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
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

    /* METRICS CUSTOMIZADAS */
    div[data-testid="metric-container"] {
        background-color: #1E1E1E;
        padding: 10px;
        border-radius: 10px;
        border: 1px solid #333;
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

# --- Backend Functions (Expandido para Metas/Recorrentes) ---
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
    except Exception as e:
        return pd.DataFrame()

def executar_sql(tabela, acao, dados, user_id):
    try:
        ref = supabase.table(tabela)
        if acao == 'insert':
            if 'id' in dados and pd.isna(dados['id']): del dados['id']
            dados['user_id'] = user_id
            ref.insert(dados).execute()
        elif acao == 'update':
            if not dados.get('id'): return False
            # Remove chaves nulas ou indesejadas
            payload = {k: v for k, v in dados.items() if k not in ['user_id', 'created_at']}
            ref.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            ref.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro SQL ({tabela}): {e}"); return False

def fmt_real(valor):
    """Formata float para BRL"""
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA (Lógica Robusta) ---
def limpar_json(texto):
    texto = texto.replace("```json", "").replace("```", "").strip()
    return json.loads(texto)

def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['data', 'descricao', 'valor', 'categoria']].head(5).to_json(orient="records")

    prompt = f"""
    Atue como um extrator de dados financeiros.
    Hoje: {date.today()}. Histórico: {contexto}
    INSTRUÇÕES:
    1. Identifique: Valor (float), Descrição, Categoria, Tipo (Receita/Despesa).
    2. Data: Se não citada, use hoje.
    3. Responda APENAS JSON.
    FORMATO JSON:
    {{ "acao": "insert", "dados": {{ "data": "YYYY-MM-DD", "valor": 0.00, "categoria": "Outros", "descricao": "Item", "tipo": "Despesa" }}, "msg_ia": "Confirmação curta" }}
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
    """Gera insights sobre a saúde financeira"""
    if not IA_AVAILABLE: return "IA Indisponível."
    
    resumo_gastos = df_gastos.groupby('categoria')['valor'].sum().to_dict()
    metas_txt = df_metas.to_dict(orient='records') if not df_metas.empty else "Sem metas"
    fixos_txt = df_fixos['valor'].sum() if not df_fixos.empty else 0
    
    prompt = f"""
    Atue como um consultor financeiro pessoal direto e empático.
    DADOS DO USUÁRIO (Mês Atual):
    - Gastos por Categoria: {resumo_gastos}
    - Metas de Poupança/Sonhos: {metas_txt}
    - Total Gastos Fixos Recorrentes: R$ {fixos_txt}
    
    Tarefa: Analise os gastos em relação às metas e fixos. Dê 1 conselho prático e 1 alerta se houver algo fora do padrão. Seja breve (máx 3 linhas).
    """
    model = genai.GenerativeModel('gemini-flash-latest')
    res = model.generate_content(prompt)
    return res.text

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
df_total = carregar_transacoes(user['id'], 200)

# --- SIDEBAR (Configurações Avançadas) ---
with st.sidebar:
    st.header(f"Olá, {user.get('username')}")
    
    st.markdown("### ⚙️ Planejamento")
    meta_mensal = st.number_input("Limite de Gastos (R$)", value=3000.0, step=100.0)

    # 1. Gestão de Recorrentes
    with st.expander("🔄 Gastos Fixos/Recorrentes"):
        st.caption("Aluguel, Assinaturas, Parcelas...")
        df_recorrente = carregar_dados_generico("recurrent_expenses", user['id'])
        
        edit_recorrente = st.data_editor(
            df_recorrente, 
            num_rows="dynamic", 
            column_config={
                "id": None, "user_id": None, "created_at": None,
                "descricao": "Nome",
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                "dia_vencimento": st.column_config.NumberColumn("Dia", min_value=1, max_value=31)
            },
            key="editor_recorrente"
        )
        if st.button("Salvar Fixos"):
            # Sincronização Simplificada (Delete All + Insert All seria mais fácil, mas vamos de Update)
            ids_orig = df_recorrente['id'].tolist() if not df_recorrente.empty else []
            # Updates/Inserts
            for i, row in edit_recorrente.iterrows():
                d = row.to_dict()
                if pd.isna(d.get('id')): executar_sql('recurrent_expenses', 'insert', d, user['id'])
                else: executar_sql('recurrent_expenses', 'update', d, user['id'])
            # Deletes
            ids_new = edit_recorrente['id'].dropna().tolist()
            for x in set(ids_orig) - set(ids_new):
                executar_sql('recurrent_expenses', 'delete', {'id': x}, user['id'])
            st.rerun()

    # 2. Gestão de Metas
    with st.expander("🎯 Metas & Sonhos"):
        st.caption("Viagem, Carro, Reserva...")
        df_metas = carregar_dados_generico("goals", user['id'])
        
        edit_metas = st.data_editor(
            df_metas,
            num_rows="dynamic",
            column_config={
                "id": None, "user_id": None, "created_at": None,
                "descricao": "Meta",
                "valor_alvo": st.column_config.NumberColumn("Alvo", format="R$ %.2f"),
                "valor_atual": st.column_config.NumberColumn("Guardado", format="R$ %.2f"),
                "data_limite": st.column_config.DateColumn("Prazo")
            },
            key="editor_metas"
        )
        if st.button("Salvar Metas"):
             # Lógica similar de sync
            ids_orig = df_metas['id'].tolist() if not df_metas.empty else []
            for i, row in edit_metas.iterrows():
                d = row.to_dict()
                if isinstance(d.get('data_limite'), (date, datetime)): d['data_limite'] = d['data_limite'].strftime('%Y-%m-%d')
                if pd.isna(d.get('id')): executar_sql('goals', 'insert', d, user['id'])
                else: executar_sql('goals', 'update', d, user['id'])
            ids_new = edit_metas['id'].dropna().tolist()
            for x in set(ids_orig) - set(ids_new):
                executar_sql('goals', 'delete', {'id': x}, user['id'])
            st.rerun()

    if st.button("Sair"): st.session_state.clear(); st.rerun()

# Navegação iOS Style
selected_nav = st.radio("Menu", ["💬 Chat", "💳 Extrato", "📈 Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# 1. CHAT (Mantido igual, funciona bem)
# =======================================================
if selected_nav == "💬 Chat":
    if "msgs" not in st.session_state: st.session_state.msgs = [{"role": "assistant", "content": "Olá! Registre um gasto ou receita."}]
    if "op_pendente" not in st.session_state: st.session_state.op_pendente = None
    if "last_audio_id" not in st.session_state: st.session_state.last_audio_id = None

    for m in st.session_state.msgs:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if not st.session_state.op_pendente:
        c1, c2, c3 = st.columns(3)
        sugestao = None
        if c1.button("🍔 Almoço"): sugestao = "Almoço 35 reais"
        if c2.button("🚗 Uber"): sugestao = "Uber 20 reais"
        if c3.button("💵 Salário"): sugestao = "Recebi salario 3500"

        audio_val = st.audio_input("Falar", label_visibility="collapsed")
        text_val = st.chat_input("Ou digite...")
        
        final_input, tipo = None, "texto"
        if sugestao: final_input = sugestao; st.session_state.last_audio_id = audio_val
        elif text_val: final_input = text_val; st.session_state.last_audio_id = audio_val
        elif audio_val and audio_val != st.session_state.last_audio_id:
            final_input = audio_val; tipo = "audio"; st.session_state.last_audio_id = audio_val

        if final_input:
            if tipo == "texto": st.session_state.msgs.append({"role": "user", "content": final_input})
            else: st.session_state.msgs.append({"role": "user", "content": "🎤 *Áudio...*"})
            
            with st.chat_message("assistant"):
                with st.spinner("Analisando..."):
                    res = agente_financeiro_ia(final_input, df_total, tipo)
                    if res.get('acao') == 'insert':
                        st.session_state.op_pendente = res; st.rerun()
                    elif res.get('acao') == 'erro': st.error(res.get('msg'))
                    else: st.markdown(res.get('msg_ia')); st.session_state.msgs.append({"role": "assistant", "content": res.get('msg_ia')})

    if st.session_state.op_pendente:
        op = st.session_state.op_pendente
        d = op.get('dados', {})
        st.markdown(f"""
        <div class="app-card" style="border-left: 5px solid {'#00CC96' if d.get('tipo')=='Receita' else '#FF4B4B'};">
            <h3>{d.get('descricao')}</h3>
            <h2>R$ {fmt_real(d.get('valor', 0))}</h2>
            <p>{d.get('categoria')} • {d.get('data')}</p>
        </div>
        """, unsafe_allow_html=True)
        c1, c2 = st.columns(2)
        if c1.button("✅ Confirmar", type="primary", use_container_width=True):
            final = d.copy()
            executar_sql('transactions', 'insert', final, user['id'])
            st.toast("Salvo!"); st.session_state.op_pendente = None; st.rerun()
        if c2.button("❌ Cancelar", use_container_width=True):
            st.session_state.op_pendente = None; st.rerun()

# =======================================================
# 2. EXTRATO (Com indicação de fixos)
# =======================================================
elif selected_nav == "💳 Extrato":
    c_f1, c_f2 = st.columns([2, 1])
    filtro_mes = c_f1.selectbox("Mês", range(1,13), index=date.today().month-1)
    filtro_ano = c_f2.number_input("Ano", 2024, 2030, date.today().year)

    if not df_total.empty:
        df_view = df_total.copy()
        df_view['data_dt'] = pd.to_datetime(df_view['data'], errors='coerce')
        mask = (df_view['data_dt'].dt.month == filtro_mes) & (df_view['data_dt'].dt.year == filtro_ano)
        df_mes = df_view[mask].copy()

        # Resumo Financeiro
        gastos = df_mes[df_mes['tipo'] != 'Receita']['valor'].sum()
        
        # Incorporando previsão de fixos no cálculo
        df_fixos = carregar_dados_generico("recurrent_expenses", user['id'])
        total_fixo = df_fixos['valor'].sum() if not df_fixos.empty else 0
        
        # Display Card
        st.markdown(f"""
        <div class="budget-card">
            <div style="display:flex; justify-content:space-between">
                <span>Gasto Variável</span>
                <span><b>R$ {fmt_real(gastos)}</b></span>
            </div>
            <div style="display:flex; justify-content:space-between; color:#888; font-size:0.9em">
                <span>+ Fixos (Est.)</span>
                <span>R$ {fmt_real(total_fixo)}</span>
            </div>
            <hr style="margin:5px 0; border-color:#444">
             <div style="display:flex; justify-content:space-between">
                <span>Total Previsto</span>
                <span>R$ {fmt_real(gastos + total_fixo)} / {fmt_real(meta_mensal)}</span>
            </div>
        </div>
        """, unsafe_allow_html=True)
        
        perc = min((gastos + total_fixo) / meta_mensal, 1.0) if meta_mensal > 0 else 0
        st.progress(perc)

        # Editor
        st.subheader("📝 Lançamentos")
        df_edit = df_mes.copy()
        df_edit['data'] = df_edit['data_dt'].dt.date
        df_edit = df_edit[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']].sort_values('data', ascending=False)

        mudancas = st.data_editor(
            df_edit,
            column_config={
                "id": None,
                "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Receita", "Despesa"]),
                "categoria": st.column_config.SelectboxColumn("Cat", options=["Alimentação", "Transporte", "Casa", "Lazer", "Investimento", "Outros"])
            },
            hide_index=True, use_container_width=True, num_rows="dynamic", key="grid_final"
        )

        if st.button("💾 Atualizar Extrato", type="primary"):
            ids_orig = df_edit['id'].tolist()
            for i, row in mudancas.iterrows():
                d = row.to_dict()
                if isinstance(d['data'], (date, datetime)): d['data'] = d['data'].strftime('%Y-%m-%d')
                if pd.isna(d['id']): pass 
                else: executar_sql('transactions', 'update', d, user['id'])
            ids_new = mudancas['id'].dropna().tolist()
            for x in set(ids_orig) - set(ids_new):
                executar_sql('transactions', 'delete', {'id': x}, user['id'])
            st.rerun()
    else: st.info("Sem dados.")

# =======================================================
# 3. ANÁLISE (NOVO LAYOUT & FUNÇÕES)
# =======================================================
elif selected_nav == "📈 Análise":
    st.subheader("Raio-X Financeiro")
    
    # --- A. Filtros Superiores ---
    col_f1, col_f2 = st.columns([2, 2])
    periodo = col_f1.selectbox("📅 Período", ["Mês Atual", "Últimos 3 Meses", "Ano Todo"])
    
    # Preparação dos dados para análise
    if not df_total.empty:
        df_a = df_total.copy()
        df_a['data_dt'] = pd.to_datetime(df_a['data'], errors='coerce')
        
        if periodo == "Mês Atual":
            df_filtrado = df_a[df_a['data_dt'].dt.month == date.today().month]
        elif periodo == "Últimos 3 Meses":
            data_cort = pd.to_datetime(date.today() - timedelta(days=90))
            df_filtrado = df_a[df_a['data_dt'] >= data_cort]
        else:
            df_filtrado = df_a[df_a['data_dt'].dt.year == date.today().year]
            
        gastos_analise = df_filtrado[df_filtrado['tipo'] != 'Receita']
        
        # Seletor de Categoria Inteligente
        categorias_disp = ["Todas"] + list(gastos_analise['categoria'].unique())
        cat_foco = col_f2.selectbox("🔍 Foco em Categoria", categorias_disp)

        if not gastos_analise.empty:
            
            # --- B. Insights IA ---
            if st.button("🤖 Analisar Saúde Financeira com IA", use_container_width=True):
                df_metas_load = carregar_dados_generico("goals", user['id'])
                df_fixos_load = carregar_dados_generico("recurrent_expenses", user['id'])
                with st.spinner("Consultando consultor virtual..."):
                    insight = coach_financeiro(gastos_analise, df_metas_load, df_fixos_load)
                    st.info(f"💡 **Insight IA:** {insight}")

            st.markdown("---")

            # --- C. Layout Visual (Estilo Imagem) ---
            # Coluna 1: Gráfico Donut | Coluna 2: Lista Detalhada
            c_chart, c_list = st.columns([1.2, 1])
            
            with c_chart:
                # Filtragem para gráfico
                df_chart = gastos_analise if cat_foco == "Todas" else gastos_analise[gastos_analise['categoria'] == cat_foco]
                
                if not df_chart.empty:
                    # Gráfico Donut Melhorado
                    fig = px.pie(df_chart, values='valor', names='categoria', hole=0.7,
                                 color_discrete_sequence=px.colors.qualitative.Pastel)
                    fig.update_traces(textposition='inside', textinfo='percent')
                    fig.update_layout(
                        showlegend=False, 
                        margin=dict(t=0, b=0, l=0, r=0), 
                        height=250,
                        paper_bgcolor='rgba(0,0,0,0)',
                        plot_bgcolor='rgba(0,0,0,0)',
                        annotations=[dict(text=f"R$ {fmt_real(df_chart['valor'].sum())}", x=0.5, y=0.5, font_size=18, showarrow=False)]
                    )
                    st.plotly_chart(fig, use_container_width=True)
                else:
                    st.warning("Sem dados para este filtro.")

            with c_list:
                st.markdown("##### 🏆 Ranking de Gastos")
                # Agrupamento
                if cat_foco == "Todas":
                    ranking = gastos_analise.groupby('categoria')['valor'].sum().sort_values(ascending=False)
                    total_g = gastos_analise['valor'].sum()
                    
                    for cat, val in ranking.items():
                        pct = (val / total_g)
                        st.markdown(f"""
                        <div style="margin-bottom: 5px;">
                            <div style="display:flex; justify-content:space-between; font-size:0.9em;">
                                <span>{cat}</span>
                                <span>{int(pct*100)}%</span>
                            </div>
                            <div style="background-color:#333; height:6px; border-radius:3px; width:100%;">
                                <div style="background-color:{'#00CC96' if cat == 'Investimento' else '#5D5FEF'}; height:6px; border-radius:3px; width:{pct*100}%;"></div>
                            </div>
                            <div style="text-align:right; font-size:0.8em; color:#CCC">R$ {fmt_real(val)}</div>
                        </div>
                        """, unsafe_allow_html=True)
                else:
                    # Detalhamento da categoria específica
                    itens = gastos_analise[gastos_analise['categoria'] == cat_foco].sort_values('valor', ascending=False).head(5)
                    st.markdown(f"**Top itens em {cat_foco}:**")
                    for _, row in itens.iterrows():
                         st.markdown(f"• {row['descricao']}: **R$ {fmt_real(row['valor'])}**")

            # --- D. Metas vs Realidade ---
            st.markdown("### 🎯 Progresso das Metas")
            df_metas_view = carregar_dados_generico("goals", user['id'])
            if not df_metas_view.empty:
                for _, meta in df_metas_view.iterrows():
                    progresso = meta['valor_atual'] / meta['valor_alvo']
                    cor = "#00CC96" if progresso >= 1 else "#F2C94C"
                    st.markdown(f"""
                    <div style="background:#262730; padding:10px; border-radius:8px; margin-bottom:8px;">
                        <div style="display:flex; justify-content:space-between">
                            <span>{meta['descricao']}</span>
                            <span>{int(progresso*100)}%</span>
                        </div>
                        <progress value="{progresso}" max="1" style="width:100%; height:8px; accent-color: {cor}"></progress>
                        <small style="color:#888">R$ {fmt_real(meta['valor_atual'])} de R$ {fmt_real(meta['valor_alvo'])}</small>
                    </div>
                    """, unsafe_allow_html=True)
            else:
                st.info("Cadastre metas na barra lateral.")
                
        else:
            st.info("Nenhum gasto registrado neste período.")
