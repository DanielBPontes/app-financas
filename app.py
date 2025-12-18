import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client, Client
from datetime import datetime, date, timedelta
import json
import google.generativeai as genai
import time

# --- 1. Configuração Mobile-First & Layout ---
st.set_page_config(
    page_title="AppFinanças",
    page_icon="💳",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- 2. CSS Otimizado e Correções de Layout ---
st.markdown("""
<style>
    /* Esconde elementos nativos desnecessários */
    section[data-testid="stSidebar"] {display: none !important;}
    .stAppHeader {display:none !important;} 
    .stDeployButton {display:none !important;}
    
    /* Ajuste do container principal para evitar corte lateral */
    .block-container {
        padding-top: 1rem !important; 
        padding-bottom: 5rem !important; 
        padding-left: 1rem !important; 
        padding-right: 1rem !important;
        max_width: 100% !important;
    }
    
    /* MENU DE NAVEGAÇÃO ESTILIZADO */
    div[role="radiogroup"] {
        display: flex; 
        flex-direction: row;
        justify-content: space-between;
        background-color: #1E1E1E; 
        padding: 5px; 
        border-radius: 16px; 
        margin-bottom: 20px;
        border: 1px solid #333;
    }
    div[role="radiogroup"] label {
        flex: 1;
        text-align: center; 
        background: transparent; border: none; 
        padding: 10px 5px; border-radius: 12px;
        cursor: pointer; color: #888; font-size: 0.95rem; font-weight: 500;
        transition: all 0.3s ease;
    }
    div[role="radiogroup"] label[data-checked="true"] {
        background-color: #00CC96 !important; color: #121212 !important;
        font-weight: 800; box-shadow: 0 4px 10px rgba(0, 204, 150, 0.3);
    }
    
    /* CARDS DE KPI */
    .kpi-card {
        background-color: #262730;
        padding: 15px;
        border-radius: 12px;
        border: 1px solid #333;
        text-align: center;
        box-shadow: 0 2px 4px rgba(0,0,0,0.2);
    }
    .kpi-title { font-size: 0.8rem; color: #aaa; margin-bottom: 5px; text-transform: uppercase; letter-spacing: 1px;}
    .kpi-value { font-size: 1.4rem; font-weight: bold; color: #fff; }

    /* Inputs e Botões */
    .stButton button { width: 100%; border-radius: 10px; font-weight: 600; height: 50px; }
    input { font-size: 16px !important; }
</style>
""", unsafe_allow_html=True)

# --- Funções Utilitárias ---
def fmt_real(valor):
    if valor is None or pd.isna(valor): return "0,00"
    return f"{float(valor):,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

def parse_brl_input(valor_str):
    """
    Tenta corrigir entradas bizarras como 20.000 (que o python lê como 20.0)
    se o usuário estiver pensando em português.
    """
    if isinstance(valor_str, (int, float)):
        return float(valor_str)
    try:
        # Se for string, remove formatações de milhar e ajusta decimal
        v = str(valor_str).replace("R$", "").strip()
        if "," in v and "." in v: # Formato 1.000,00
            v = v.replace(".", "").replace(",", ".")
        elif "," in v: # Formato 1000,00
            v = v.replace(",", ".")
        return float(v)
    except:
        return 0.0

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
    if tabela == 'goals':
        colunas_padrao = ['id', 'descricao', 'valor_alvo', 'valor_atual', 'data_limite', 'user_id']
    elif tabela == 'recurrent_expenses':
        colunas_padrao = ['id', 'descricao', 'valor_parcela', 'valor_total', 'parcelas_restantes', 'eh_infinito', 'dia_vencimento', 'user_id']
    else:
        colunas_padrao = ['id', 'descricao', 'valor', 'user_id', 'created_at']

    try:
        res = supabase.table(tabela).select("*").eq("user_id", user_id).execute()
        df = pd.DataFrame(res.data)
        
        if df.empty: df = pd.DataFrame(columns=colunas_padrao)
        for col in colunas_padrao:
            if col not in df.columns: df[col] = None

        # Tratamento de Tipos
        if tabela == 'goals':
            df['valor_alvo'] = pd.to_numeric(df['valor_alvo'], errors='coerce').fillna(0.0)
            df['valor_atual'] = pd.to_numeric(df['valor_atual'], errors='coerce').fillna(0.0)
            df['data_limite'] = pd.to_datetime(df['data_limite'], errors='coerce')
        elif tabela == 'recurrent_expenses':
            df['valor_parcela'] = pd.to_numeric(df['valor_parcela'], errors='coerce')
            df['eh_infinito'] = df['eh_infinito'].astype(bool)
            
        return df
    except Exception as e: return pd.DataFrame(columns=colunas_padrao)

def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty: 
            df['valor'] = pd.to_numeric(df['valor'])
            df['data'] = pd.to_datetime(df['data']).dt.date
        else: return pd.DataFrame(columns=['id', 'data', 'descricao', 'valor', 'categoria', 'tipo', 'user_id'])
        return df
    except: return pd.DataFrame()

def executar_sql(tabela, acao, dados, user_id):
    try:
        ref = supabase.table(tabela)
        if acao == 'insert':
            if 'id' in dados and pd.isna(dados['id']): del dados['id']
            dados['user_id'] = user_id
            ref.insert(dados).execute()
        elif acao == 'update':
            if not dados.get('id') or pd.isna(dados.get('id')): return False
            payload = {k: v for k, v in dados.items() if k not in ['user_id', 'created_at']}
            ref.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            ref.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro BD: {e}"); return False

# --- Agente IA (Chat) ---
def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    # Otimização: Mandar apenas colunas relevantes para economizar tokens
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['data', 'descricao', 'valor', 'categoria']].head(10).to_json(orient="records", date_format="iso")

    prompt = f"""
    Você é um assistente financeiro pessoal.
    Contexto Recente do usuário (JSON): {contexto}.
    Data Hoje: {date.today()}.
    
    Entrada do usuário: '{entrada}'.
    
    Instruções:
    1. Se for adicionar gasto/receita, retorne JSON estrito: {{ "acao": "insert", "dados": {{ "data": "YYYY-MM-DD", "valor": 0.00, "categoria": "Categoria (Ex: Alimentação, Lazer, Casa, Transporte, Investimento)", "descricao": "Curta", "tipo": "Despesa" ou "Receita" }}, "msg_ia": "Confirmação curta" }}
    2. Se for análise ou dúvida, responda como um consultor financeiro breve. Retorne: {{ "acao": "chat", "msg_ia": "Sua resposta aqui" }}
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        # Configuração para resposta JSON
        response = model.generate_content(prompt, generation_config={"response_mime_type": "application/json"})
        return json.loads(response.text)
    except Exception as e: return {"acao": "erro", "msg": f"Erro IA: {e}"}

def analisar_gastos_ia(df_mes):
    """Gera insights sobre o mês atual"""
    if not IA_AVAILABLE or df_mes.empty: return "Sem dados ou IA indisponível."
    
    csv_data = df_mes.to_csv(index=False)
    prompt = f"""
    Analise estes dados financeiros do mês (CSV):
    {csv_data}
    
    Seja breve e direto (estilo notificação de app de banco).
    1. Onde estou gastando demais?
    2. Uma sugestão para economizar.
    Use emojis. Máximo 3 linhas.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        res = model.generate_content(prompt)
        return res.text
    except: return "Não consegui analisar agora."

# =======================================================
# LOGIN
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    c1, c2, c3 = st.columns([1,2,1])
    with c2:
        st.markdown("<br><br><h1 style='text-align:center'>💳</h1>", unsafe_allow_html=True)
        st.markdown("<h3 style='text-align:center'>AppFinanças</h3>", unsafe_allow_html=True)
        with st.form("login_form"):
            u = st.text_input("Usuário")
            p = st.text_input("Senha", type="password")
            submitted = st.form_submit_button("Entrar", type="primary")
            if submitted:
                try:
                    resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                    if resp.data: 
                        st.session_state['user'] = resp.data[0]; 
                        st.rerun()
                    else: st.error("Login Inválido")
                except Exception as e: st.error(f"Erro Conexão: {e}")
    st.stop()

user = st.session_state['user']
# Carrega dados globais (últimas 300 transações para garantir histórico)
df_total = carregar_transacoes(user['id'], 300)

# =======================================================
# NAVEGAÇÃO
# =======================================================
# Usando icones mais modernos e nomes claros
selected_nav = st.radio(
    "Menu", 
    ["💬 Chat", "💳 Extrato", "📊 Dashboard", "🎯 Metas"], 
    label_visibility="collapsed",
    horizontal=True
)

# =======================================================
# 1. CHAT (IA)
# =======================================================
if selected_nav == "💬 Chat":
    st.markdown("### Assistente IA")
    if "msgs" not in st.session_state: st.session_state.msgs = [{"role": "assistant", "content": f"Olá! Me diga quanto gastou ou pergunte sobre suas finanças."}]
    
    # Container para histórico (scrollável)
    chat_container = st.container(height=400)
    with chat_container:
        for m in st.session_state.msgs:
            with st.chat_message(m["role"]): st.markdown(m["content"])

    # Se houver operação pendente (IA detectou gasto)
    if "op_pendente" in st.session_state and st.session_state.op_pendente:
        op = st.session_state.op_pendente
        d = op.get('dados', {})
        
        with st.container():
            st.info("Confirma o lançamento abaixo?")
            col_card, col_actions = st.columns([3, 1])
            with col_card:
                st.markdown(f"**{d.get('descricao')}** | R$ {fmt_real(d.get('valor', 0))}")
                st.caption(f"{d.get('categoria')} • {d.get('data')}")
            with col_actions:
                if st.button("✅", key="confirm_btn"):
                    executar_sql('transactions', 'insert', d, user['id'])
                    st.toast("Lançamento salvo!")
                    st.session_state.msgs.append({"role": "assistant", "content": "Salvo com sucesso! 📝"})
                    st.session_state.op_pendente = None
                    st.rerun()
                if st.button("❌", key="cancel_btn"):
                    st.session_state.op_pendente = None
                    st.rerun()

    # Input Area
    input_container = st.container()
    with input_container:
        texto = st.chat_input("Ex: 'Gastei 50 reais no mc donalds' ou 'Audio'")
        # Simulação de botão de áudio (Streamlit nativo para audio input está em beta/recente)
        audio = st.audio_input("Gravar Áudio", label_visibility="collapsed")
        
        prompt_final = None
        tipo = "texto"
        
        if texto: prompt_final = texto
        elif audio: prompt_final = audio; tipo = "audio"
        
        if prompt_final:
            st.session_state.msgs.append({"role": "user", "content": "🎤 Áudio enviado" if tipo == "audio" else prompt_final})
            
            with st.spinner("Processando..."):
                res = agente_financeiro_ia(prompt_final, df_total, tipo)
                
                if res.get('acao') == 'insert':
                    st.session_state.op_pendente = res
                    st.rerun() # Recarrega para mostrar a confirmação
                else:
                    st.session_state.msgs.append({"role": "assistant", "content": res.get('msg_ia', 'Não entendi.')})
                    st.rerun()

# =======================================================
# 2. EXTRATO (Corrigido Bug Lateral)
# =======================================================
elif selected_nav == "💳 Extrato":
    col_filtro1, col_filtro2 = st.columns(2)
    mes_atual = date.today().month
    ano_atual = date.today().year
    
    mes_sel = col_filtro1.selectbox("Mês", range(1,13), index=mes_atual-1)
    ano_sel = col_filtro2.number_input("Ano", 2023, 2030, value=ano_atual)

    if not df_total.empty:
        # Filtro de Data
        df_total['data_dt'] = pd.to_datetime(df_total['data'])
        mask = (df_total['data_dt'].dt.month == mes_sel) & (df_total['data_dt'].dt.year == ano_sel)
        df_mes = df_total[mask].copy().sort_values('data', ascending=False)
        
        # Resumo Rápido
        g = df_mes[df_mes['tipo'] == 'Despesa']['valor'].sum()
        r = df_mes[df_mes['tipo'] == 'Receita']['valor'].sum()
        s = r - g
        
        # Barra de Status Visual
        st.markdown(f"""
        <div style="display:flex; justify-content:space-between; padding: 10px; background: #262730; border-radius: 8px; margin-bottom: 15px;">
            <div style="color:#FF5252">📉 R$ {fmt_real(g)}</div>
            <div style="font-weight:bold; color:{'#00CC96' if s>=0 else '#FF5252'}">Saldo: R$ {fmt_real(s)}</div>
            <div style="color:#00CC96">📈 R$ {fmt_real(r)}</div>
        </div>
        """, unsafe_allow_html=True)

        # Editor de Dados (Ajustado para não bugar layout)
        # O segredo é não usar colunas aqui se a tela for pequena, ou usar container_width
        
        df_edit = df_mes[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']]
        
        mudancas = st.data_editor(
            df_edit,
            column_config={
                "id": None,
                "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                "descricao": st.column_config.TextColumn("Descrição", width="medium"),
                "valor": st.column_config.NumberColumn("Valor (R$)", format="%.2f", min_value=0.0),
                "categoria": st.column_config.SelectboxColumn("Cat.", options=["Alimentação", "Transporte", "Casa", "Lazer", "Saúde", "Educação", "Investimento", "Outros"]),
                "tipo": st.column_config.SelectboxColumn("Tipo", options=["Despesa", "Receita"])
            },
            hide_index=True,
            use_container_width=True, # Isso ajuda a preencher sem quebrar
            num_rows="dynamic",
            key="editor_extrato"
        )
        
        if st.button("💾 Salvar Alterações", type="primary"):
            # Lógica de Diff para salvar
            ids_orig = df_edit['id'].tolist()
            ids_new = []
            
            for i, row in mudancas.iterrows():
                d = row.to_dict()
                # Conversão de data segura
                if isinstance(d['data'], (date, datetime)): d['data'] = d['data'].strftime('%Y-%m-%d')
                else: d['data'] = str(d['data'])
                
                if pd.isna(d.get('id')): # Novo
                    if not d.get('tipo'): d['tipo'] = 'Despesa'
                    executar_sql('transactions', 'insert', d, user['id'])
                else: # Update
                    ids_new.append(d['id'])
                    executar_sql('transactions', 'update', d, user['id'])
            
            # Delete removidos
            if ids_new:
                removidos = set(ids_orig) - set(ids_new)
                for rid in removidos: executar_sql('transactions', 'delete', {'id': rid}, user['id'])
            
            st.toast("Dados atualizados!")
            time.sleep(1)
            st.rerun()
            
    else:
        st.info("Nenhuma transação encontrada.")

# =======================================================
# 3. DASHBOARD (ANÁLISE 2.0)
# =======================================================
elif selected_nav == "📊 Dashboard":
    st.markdown("### Visão Geral")
    
    if df_total.empty:
        st.warning("Adicione transações para ver o dashboard.")
    else:
        df_total['data_dt'] = pd.to_datetime(df_total['data'])
        df_chart = df_total[df_total['data_dt'].dt.month == date.today().month]
        
        # 1. KPIs no Topo (Estilo Fintech)
        col1, col2, col3 = st.columns(3)
        receita_mes = df_chart[df_chart['tipo'] == 'Receita']['valor'].sum()
        despesa_mes = df_chart[df_chart['tipo'] == 'Despesa']['valor'].sum()
        saldo_mes = receita_mes - despesa_mes
        
        col1.markdown(f"<div class='kpi-card'><div class='kpi-title'>Receitas</div><div class='kpi-value' style='color:#00CC96'>R$ {fmt_real(receita_mes)}</div></div>", unsafe_allow_html=True)
        col2.markdown(f"<div class='kpi-card'><div class='kpi-title'>Despesas</div><div class='kpi-value' style='color:#FF5252'>R$ {fmt_real(despesa_mes)}</div></div>", unsafe_allow_html=True)
        col3.markdown(f"<div class='kpi-card'><div class='kpi-title'>Saldo</div><div class='kpi-value'>R$ {fmt_real(saldo_mes)}</div></div>", unsafe_allow_html=True)
        
        st.markdown("---")
        
        # 2. Gráfico de Evolução (Bar Chart) - Mostra QUANDO gastou
        st.markdown("##### 📅 Evolução Diária")
        df_diario = df_chart[df_chart['tipo'] == 'Despesa'].groupby('data')['valor'].sum().reset_index()
        if not df_diario.empty:
            fig_bar = px.bar(df_diario, x='data', y='valor', text_auto='.2s', color_discrete_sequence=['#FF5252'])
            fig_bar.update_layout(
                paper_bgcolor='rgba(0,0,0,0)', plot_bgcolor='rgba(0,0,0,0)',
                font=dict(color="white"), margin=dict(l=0, r=0, t=10, b=20),
                xaxis_title=None, yaxis_title=None, showlegend=False,
                height=250
            )
            fig_bar.update_traces(textfont_size=12, textangle=0, textposition="outside", cliponaxis=False)
            st.plotly_chart(fig_bar, use_container_width=True)
        else: st.info("Sem despesas este mês.")

        # 3. Categorias (Donut Chart Melhorado)
        c_chart1, c_chart2 = st.columns([1, 1])
        with c_chart1:
            st.markdown("##### 🍕 Categorias")
            df_cat = df_chart[df_chart['tipo'] == 'Despesa'].groupby('categoria')['valor'].sum().reset_index()
            if not df_cat.empty:
                fig_pie = px.pie(df_cat, values='valor', names='categoria', hole=0.6, color_discrete_sequence=px.colors.qualitative.Pastel)
                fig_pie.update_layout(
                    paper_bgcolor='rgba(0,0,0,0)', 
                    font=dict(color="white"),
                    showlegend=False, margin=dict(t=0, b=0, l=0, r=0), height=250,
                    annotations=[dict(text=f"R$ {fmt_real(despesa_mes)}", x=0.5, y=0.5, font_size=15, showarrow=False)]
                )
                st.plotly_chart(fig_pie, use_container_width=True)
            else: st.caption("Sem dados.")

        # 4. Lista Top Gastos
        with c_chart2:
            st.markdown("##### 🏆 Top Gastos")
            top_gastos = df_chart[df_chart['tipo'] == 'Despesa'].sort_values('valor', ascending=False).head(4)
            for _, row in top_gastos.iterrows():
                st.markdown(f"""
                <div style="border-bottom: 1px solid #333; padding: 8px 0; display:flex; justify-content:space-between; font-size:0.9rem;">
                    <span>{row['descricao']}</span>
                    <span style="font-weight:bold;">R$ {fmt_real(row['valor'])}</span>
                </div>
                """, unsafe_allow_html=True)

        # 5. Botão de Insight IA
        st.markdown("<br>", unsafe_allow_html=True)
        if st.button("✨ Analisar Gastos com IA"):
            with st.spinner("Analisando seus padrões..."):
                insight = analisar_gastos_ia(df_chart[['data', 'descricao', 'valor', 'categoria', 'tipo']])
                st.success(insight)

# =======================================================
# 4. METAS & OBJETIVOS (Antigo Ajustes)
# =======================================================
elif selected_nav == "🎯 Metas":
    st.markdown("### Meus Objetivos")
    
    tab1, tab2 = st.tabs(["Metas de Curto/Longo Prazo", "Despesas Fixas"])
    
    with tab1:
        # Resolvendo o problema do Input: Criando um Form separado
        with st.expander("➕ Nova Meta (Adicionar)", expanded=False):
            with st.form("form_meta"):
                c1, c2 = st.columns(2)
                m_desc = c1.text_input("Nome da Meta", placeholder="Ex: Viagem Japão")
                m_data = c2.date_input("Prazo", value=date.today() + timedelta(days=365))
                
                c3, c4 = st.columns(2)
                # Input numérico nativo é melhor que tentar parsear texto manualmente no grid
                m_alvo = c3.number_input("Valor Alvo (R$)", min_value=0.0, step=100.0, format="%.2f")
                m_atual = c4.number_input("Já Guardado (R$)", min_value=0.0, step=100.0, format="%.2f")
                
                if st.form_submit_button("Criar Meta"):
                    if m_desc and m_alvo > 0:
                        executar_sql('goals', 'insert', {
                            'descricao': m_desc, 'valor_alvo': m_alvo, 
                            'valor_atual': m_atual, 'data_limite': str(m_data)
                        }, user['id'])
                        st.success("Meta criada!")
                        time.sleep(1); st.rerun()
                    else: st.warning("Preencha nome e valor alvo.")

        df_metas = carregar_dados_generico("goals", user['id'])
        
        # Visualização em Cards (Gamification)
        if not df_metas.empty:
            for _, row in df_metas.iterrows():
                progresso = 0
                if row['valor_alvo'] > 0:
                    progresso = min(1.0, row['valor_atual'] / row['valor_alvo'])
                
                st.markdown(f"""
                <div style="background:#262730; padding:15px; border-radius:12px; border:1px solid #444; margin-bottom:10px;">
                    <div style="display:flex; justify-content:space-between; margin-bottom:5px;">
                        <b style="font-size:1.1rem">{row['descricao']}</b>
                        <span style="color:#888">{int(progresso*100)}%</span>
                    </div>
                    <div style="width:100%; background:#444; height:8px; border-radius:4px; margin-bottom:10px;">
                        <div style="width:{progresso*100}%; background: linear-gradient(90deg, #00CC96, #00b887); height:8px; border-radius:4px;"></div>
                    </div>
                    <div style="display:flex; justify-content:space-between; font-size:0.9rem; color:#ccc;">
                        <span>Atual: R$ {fmt_real(row['valor_atual'])}</span>
                        <span>Alvo: R$ {fmt_real(row['valor_alvo'])}</span>
                    </div>
                </div>
                """, unsafe_allow_html=True)
            
            # Editor simples apenas para atualizar valores (menos propenso a erro de input que criar do zero)
            with st.expander("📝 Editar Valores das Metas"):
                st.info("Para alterar, edite abaixo.")
                edit_metas = st.data_editor(
                    df_metas[['id', 'descricao', 'valor_atual', 'valor_alvo']],
                    column_config={
                        "id": None,
                        "descricao": "Meta",
                        "valor_atual": st.column_config.NumberColumn("Guardado", format="R$ %.2f"),
                        "valor_alvo": st.column_config.NumberColumn("Alvo", format="R$ %.2f"),
                    },
                    hide_index=True, use_container_width=True, key="edit_metas_grid"
                )
                if st.button("Salvar Edições Metas"):
                     for i, row in edit_metas.iterrows():
                         executar_sql('goals', 'update', row.to_dict(), user['id'])
                     st.rerun()
        else:
            st.info("Nenhuma meta definida.")

    with tab2:
        st.caption("Contas que se repetem todo mês (Ex: Aluguel, Netflix, Parcelas).")
        df_rec = carregar_dados_generico("recurrent_expenses", user['id'])
        
        edit_rec = st.data_editor(
            df_rec,
            num_rows="dynamic",
            column_config={
                "id": None, "user_id": None, "created_at": None, "valor_total": None, "parcelas_restantes": None,
                "descricao": st.column_config.TextColumn("Nome"),
                "valor_parcela": st.column_config.NumberColumn("Valor", format="R$ %.2f", required=True),
                "dia_vencimento": st.column_config.NumberColumn("Dia Venc.", min_value=1, max_value=31),
                "eh_infinito": st.column_config.CheckboxColumn("Assinatura (Infinito)?", default=True)
            },
            hide_index=True, use_container_width=True, key="rec_editor"
        )
        
        if st.button("Salvar Fixos"):
             ids_orig = df_rec['id'].tolist() if not df_rec.empty else []
             ids_new = []
             for i, row in edit_rec.iterrows():
                 d = row.to_dict()
                 if pd.isna(d.get('id')): executar_sql('recurrent_expenses', 'insert', d, user['id'])
                 else: 
                     ids_new.append(d['id'])
                     executar_sql('recurrent_expenses', 'update', d, user['id'])
             
             for x in set(ids_orig) - set(ids_new):
                 executar_sql('recurrent_expenses', 'delete', {'id': x}, user['id'])
             st.success("Salvo!")
             time.sleep(1); st.rerun()

# Botão Sair no canto inferior
st.markdown("<br><hr>", unsafe_allow_html=True)
if st.button("Sair da Conta", type="secondary"):
    st.session_state.clear()
    st.rerun()
