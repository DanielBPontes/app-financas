import streamlit as st
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
from supabase import create_client, Client
from datetime import datetime, date
import time
import google.generativeai as genai

# --- Configuração da Página e UX ---
st.set_page_config(
    page_title="Finanças Pro", 
    page_icon="💸", 
    layout="wide",
    initial_sidebar_state="expanded"
)

# --- CSS Personalizado ---
st.markdown("""
<style>
    [data-testid="stMetricValue"] { font-size: 26px; font-weight: 700; }
    div[data-testid="stMetric"]:nth-child(1) [data-testid="stMetricValue"] { color: #FF4B4B; }
    div[data-testid="stMetric"]:nth-child(2) [data-testid="stMetricValue"] { color: #00CC96; }
    .block-container { padding-top: 2rem; }
</style>
""", unsafe_allow_html=True)

# --- Conexões ---
@st.cache_resource
def init_connection():
    try:
        url = st.secrets["supabase"]["url"]
        key = st.secrets["supabase"]["key"]
        return create_client(url, key)
    except:
        return None

supabase: Client = init_connection()

try:
    if "gemini" in st.secrets:
        genai.configure(api_key=st.secrets["gemini"]["api_key"])
        IA_AVAILABLE = True
    else:
        IA_AVAILABLE = False
except:
    IA_AVAILABLE = False

# --- Funções Backend ---
def login_user(username, password):
    try:
        response = supabase.table("users").select("*").eq("username", username).eq("password", password).execute()
        return response.data[0] if response.data else None
    except:
        return None

def carregar_transacoes(user_id):
    try:
        # Carrega TUDO do usuário (o filtro de data será feito no Pandas para ser mais rápido na UI)
        response = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True).execute()
        df = pd.DataFrame(response.data)
        if not df.empty:
            df['data'] = pd.to_datetime(df['data']).dt.date
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except:
        return pd.DataFrame()

def salvar_transacao(user_id, data_gasto, categoria, descricao, valor, tipo, recorrente):
    data = {
        "user_id": user_id,
        "data": data_gasto.isoformat(),
        "categoria": categoria,
        "descricao": descricao,
        "valor": float(valor),
        "recorrente": recorrente,
    }
    supabase.table("transactions").insert(data).execute()

# --- Funções de IA ---
def gerar_relatorio_mensal_ia(df_mes, mes, ano):
    """Gera um relatório textual completo do mês"""
    if df_mes.empty:
        return "Sem dados para gerar relatório."
    
    resumo_cat = df_mes.groupby('categoria')['valor'].sum().to_string()
    total = df_mes['valor'].sum()
    maior_gasto = df_mes.loc[df_mes['valor'].idxmax()]
    
    prompt = f"""
    Atue como um analista financeiro pessoal. Escreva um Relatório Mensal para {mes}/{ano}.
    
    Dados do Mês:
    - Total Gasto: R$ {total}
    - Detalhe por Categoria:
    {resumo_cat}
    - Maior gasto único: {maior_gasto['descricao']} (R$ {maior_gasto['valor']})
    
    Estrutura do Relatório:
    1. **Resumo Executivo**: Visão geral do mês.
    2. **Análise de Categorias**: Onde o dinheiro foi mais concentrado.
    3. **Alerta**: Comentário sobre o maior gasto.
    4. **Veredito**: Se o mês foi equilibrado ou exagerado.
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except Exception as e:
        return f"Erro na IA: {e}"

def analisar_busca_especifica(query, df_busca):
    """Analisa um conjunto específico de gastos buscados (Ex: Brawl Stars)"""
    total = df_busca['valor'].sum()
    qtd = len(df_busca)
    
    prompt = f"""
    O usuário buscou por "{query}" e encontrou {qtd} transações totalizando R$ {total}.
    
    Analise esses gastos brevemente. Se for gasto supérfluo (jogos, ifood), dê um puxão de orelha engraçado. 
    Se for essencial, parabenize.
    Seja curto (2 linhas).
    """
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        response = model.generate_content(prompt)
        return response.text
    except:
        return "Análise indisponível."

# --- Calculadora BCB ---
def calcular_investimento_bcb(meses, taxa_mensal, aporte_mensal):
    taxa_dec = taxa_mensal / 100
    dados_evolucao = []
    saldo = 0
    total_aportado = 0
    for m in range(1, int(meses) + 1):
        total_aportado += aporte_mensal
        rendimento_mes = (saldo + aporte_mensal) * taxa_dec
        saldo = (saldo + aporte_mensal) + rendimento_mes
        dados_evolucao.append({
            "Mês": m, "Total Investido": round(total_aportado, 2),
            "Rendimento (Juros)": round(saldo - total_aportado, 2), "Saldo Total": round(saldo, 2)
        })
    return pd.DataFrame(dados_evolucao), saldo

# --- Login System ---
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    col1, col2, col3 = st.columns([1,1,1])
    with col2:
        st.title("🔒 Login")
        with st.form("login_form"):
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            if st.form_submit_button("Entrar"):
                if supabase:
                    user = login_user(username, password)
                    if user:
                        st.session_state['user'] = user
                        st.rerun()
                    else: st.error("Credenciais inválidas.")
                else: st.error("Erro Conexão.")
    st.stop()

# =======================================================
# APLICAÇÃO PRINCIPAL
# =======================================================

user = st.session_state['user']
df = carregar_transacoes(user['id'])

# --- SIDEBAR GLOBAL (Controle de Data) ---
with st.sidebar:
    st.image("https://cdn-icons-png.flaticon.com/512/4149/4149666.png", width=50)
    st.markdown(f"Olá, **{user['username']}**")
    st.divider()
    
    # Navegação
    menu = st.radio("Menu", ["Dashboard Mensal", "Busca & Relatórios", "Lançamentos", "Simulador Juros"])
    
    st.divider()
    st.markdown("📅 **Período de Análise**")
    
    # Seletores de Data Globais
    col_s1, col_s2 = st.columns(2)
    meses_dict = {1:"Jan", 2:"Fev", 3:"Mar", 4:"Abr", 5:"Mai", 6:"Jun", 7:"Jul", 8:"Ago", 9:"Set", 10:"Out", 11:"Nov", 12:"Dez"}
    
    mes_selecionado = col_s1.selectbox("Mês", list(meses_dict.keys()), format_func=lambda x: meses_dict[x], index=date.today().month - 1)
    ano_selecionado = col_s2.number_input("Ano", 2023, 2030, date.today().year)
    
    if st.button("Sair"):
        st.session_state['user'] = None
        st.rerun()

# Filtragem Global do DataFrame pelo Mês Selecionado
if not df.empty:
    df['data_dt'] = pd.to_datetime(df['data'])
    df_mes = df[(df['data_dt'].dt.month == mes_selecionado) & (df['data_dt'].dt.year == ano_selecionado)]
else:
    df_mes = pd.DataFrame()

# --- ABA 1: DASHBOARD MENSAL ---
if menu == "Dashboard Mensal":
    st.title(f"📊 Visão Geral: {meses_dict[mes_selecionado]}/{ano_selecionado}")
    
    if not df_mes.empty:
        total_gasto = df_mes['valor'].sum()
        budget = 2173.79 
        saldo_restante = budget - total_gasto
        
        # KPIs
        col1, col2, col3 = st.columns(3)
        col1.metric("Gastos no Mês", f"R$ {total_gasto:,.2f}", delta=f"{-total_gasto/budget*100:.1f}% do Budget", delta_color="inverse")
        col2.metric("Saldo Restante", f"R$ {saldo_restante:,.2f}")
        col3.metric("Lançamentos", len(df_mes))
        
        st.divider()
        
        # Gráficos
        c1, c2 = st.columns([1, 1])
        with c1:
            st.subheader("Categorias")
            gastos_cat = df_mes.groupby("categoria")['valor'].sum().reset_index()
            fig_pie = px.pie(gastos_cat, values='valor', names='categoria', hole=0.4, color_discrete_sequence=px.colors.qualitative.Pastel)
            st.plotly_chart(fig_pie, use_container_width=True)
            
        with c2:
            st.subheader("Dia a Dia")
            gastos_dia = df_mes.groupby("data")['valor'].sum().reset_index()
            fig_bar = px.bar(gastos_dia, x='data', y='valor', color='valor')
            st.plotly_chart(fig_bar, use_container_width=True)
            
    else:
        st.info(f"Nenhum dado encontrado para {meses_dict[mes_selecionado]}/{ano_selecionado}.")

# --- ABA 2: BUSCA & RELATÓRIOS (NOVO!) ---
elif menu == "Busca & Relatórios":
    st.title("🔎 Inteligência Financeira")
    
    tab_busca, tab_relatorio = st.tabs(["Busca Detalhada", "Gerar Relatório Mensal"])
    
    # --- SUB-ABA: BUSCA INTELIGENTE ---
    with tab_busca:
        st.markdown("Encontre gastos específicos por descrição (ex: 'Brawl Stars', 'Uber', 'Mercado').")
        
        c_busca1, c_busca2 = st.columns([3, 1])
        termo_busca = c_busca1.text_input("O que você procura?", placeholder="Digite aqui...")
        filtrar_todos = c_busca2.checkbox("Buscar em todo histórico?", value=True, help="Se desmarcado, busca apenas no mês selecionado na lateral.")
        
        if termo_busca and not df.empty:
            # Lógica de Filtro
            df_alvo = df if filtrar_todos else df_mes
            
            # Filtro Case Insensitive (Pandas)
            resultado = df_alvo[df_alvo['descricao'].str.contains(termo_busca, case=False, na=False)]
            
            if not resultado.empty:
                total_busca = resultado['valor'].sum()
                
                # Exibe métricas da busca
                m1, m2 = st.columns(2)
                m1.metric("Total Gasto", f"R$ {total_busca:.2f}")
                m2.metric("Ocorrências", len(resultado))
                
                st.subheader("Histórico Encontrado")
                st.dataframe(resultado[['data', 'categoria', 'descricao', 'valor']], use_container_width=True)
                
                # Feedback da IA sobre a busca específica
                if IA_AVAILABLE:
                    st.markdown("---")
                    st.markdown("### 🤖 Opinião da IA")
                    with st.spinner("Analisando esse hábito de gasto..."):
                        opiniao = analisar_busca_especifica(termo_busca, resultado)
                        st.info(opiniao)
            else:
                st.warning("Nenhum gasto encontrado com esse termo.")

    # --- SUB-ABA: RELATÓRIO MENSAL ---
    with tab_relatorio:
        st.markdown(f"### Relatório de Fechamento: {meses_dict[mes_selecionado]}/{ano_selecionado}")
        st.markdown("A IA analisará todos os dados do mês selecionado e gerará um documento de análise.")
        
        if st.button("📄 Gerar Relatório Agora", type="primary"):
            if not df_mes.empty:
                with st.spinner("Lendo seus dados e escrevendo relatório..."):
                    relatorio = gerar_relatorio_mensal_ia(df_mes, meses_dict[mes_selecionado], ano_selecionado)
                    
                    st.markdown("---")
                    st.markdown(relatorio)
                    
                    # Botão para baixar (gambiarra simples para txt)
                    st.download_button("Baixar Relatório (.txt)", relatorio, file_name=f"Relatorio_{mes_selecionado}_{ano_selecionado}.txt")
            else:
                st.error("Não há dados neste mês para gerar relatório.")

# --- ABA 3: LANÇAMENTOS ---
elif menu == "Lançamentos":
    st.title("🚀 Lançamento Rápido")

    # --- Configurações Iniciais ---
    CATEGORIAS = {
        "Alimentação": ["iFood/Delivery", "Mercado", "Restaurante", "Lanche/Café"],
        "Transporte": ["Uber/99", "Combustível", "Ônibus/Metrô", "Manutenção", "Estacionamento"],
        "Lazer": ["Jogos/Steam", "Cinema/Streaming", "Bar/Rolê", "Viagem", "Hobby"],
        "Saúde": ["Farmácia", "Médico/Dentista", "Academia", "Terapia"],
        "Investimentos": ["Aporte Mensal", "Cripto", "Reserva Emergência"],
        "Casa": ["Aluguel", "Luz/Água/Net", "Supermercado (Limpeza)", "Manutenção"],
        "Outros": [] 
    }

    if 'confirmacao_pendente' not in st.session_state:
        st.session_state['confirmacao_pendente'] = False
    
    # --- Função Auxiliar ---
    def limpar_valor(valor_str):
        if not valor_str: return 0.0
        v = valor_str.replace(',', '.')
        try: return float(v)
        except: return 0.0

    # --- Interface Clean ---
    with st.container(border=True):
        # 1. Valor e Tipo
        c_val, c_tipo = st.columns([1, 1])
        
        # ADICIONADO: key="novo_valor" para podermos limpar depois
        valor_texto = c_val.text_input("Valor (R$)", placeholder="Ex: 10 ou 15,90", key="novo_valor")
        valor_final = limpar_valor(valor_texto) 
        
        tipo_input = c_tipo.radio("Tipo", ["Despesa", "Receita"], horizontal=True, label_visibility="collapsed")

        # 2. Data
        data_sel = st.date_input("Data do Gasto", date.today())

        # 3. Categorias
        c_cat, c_sub = st.columns(2)
        cat_principal = c_cat.selectbox("Categoria", list(CATEGORIAS.keys()))
        
        categoria_final = cat_principal
        
        # Variável para controlar o input de "Outros"
        nome_outro = ""
        
        if cat_principal == "Outros":
            # ADICIONADO: key="nova_cat_outros"
            nome_outro = c_sub.text_input("Qual o gasto?", placeholder="Digite o nome...", key="nova_cat_outros")
            if nome_outro: categoria_final = nome_outro
        else:
            sub_cat = c_sub.selectbox("Detalhe", CATEGORIAS[cat_principal])
            categoria_final = sub_cat

        # 4. Descrição
        # ADICIONADO: key="nova_desc"
        descricao_input = st.text_input("Descrição (Opcional)", placeholder="Ex: Almoço com a equipe", key="nova_desc")

        st.markdown("---")

        # --- Lógica de Confirmação ---
        if not st.session_state['confirmacao_pendente']:
            if st.button("Verificar e Salvar", type="primary", use_container_width=True):
                if valor_final > 0:
                    st.session_state['confirmacao_pendente'] = True
                    st.rerun()
                else:
                    st.warning("⚠️ Digite um valor válido (ex: 10,50)")
        else:
            hora_atual = datetime.now().time()
            data_completa = datetime.combine(data_sel, hora_atual)
            
            st.info(f"💾 **Confirmar:** R$ {valor_final:.2f} em **{categoria_final}**?")
            st.caption(f"Data: {data_completa.strftime('%d/%m/%Y às %H:%M')}")
            
            col_conf1, col_conf2 = st.columns(2)
            with col_conf1:
                if st.button("✅ SIM, SALVAR", type="primary", use_container_width=True):
                    try:
                        desc_final = descricao_input if descricao_input else categoria_final
                        
                        salvar_transacao(
                            user['id'], 
                            data_completa, 
                            categoria_final, 
                            desc_final, 
                            valor_final, 
                            tipo_input, 
                            False 
                        )
                        st.toast(f"R$ {valor_final} salvo com sucesso!", icon="🚀")
                        
                        # --- O PULO DO GATO: LIMPEZA DOS CAMPOS ---
                        st.session_state['novo_valor'] = ""       # Limpa valor
                        st.session_state['nova_desc'] = ""        # Limpa descrição
                        st.session_state['nova_cat_outros'] = ""  # Limpa campo outros
                        st.session_state['confirmacao_pendente'] = False # Reseta botão
                        
                        time.sleep(0.5)
                        st.rerun()
                        
                    except Exception as e:
                        st.error(f"Erro: {e}")
            
            with col_conf2:
                if st.button("❌ Corrigir", use_container_width=True):
                    st.session_state['confirmacao_pendente'] = False
                    st.rerun()

    # --- Grid Rápido ---
    if not df_mes.empty:
        st.caption("Últimos lançamentos do mês:")
        st.dataframe(
            df_mes[['data', 'categoria', 'valor']].head(3),
            use_container_width=True,
            hide_index=True
        )

# --- ABA 4: SIMULADOR ---
elif menu == "Simulador Juros":
    st.title("📈 Calculadora BCB")
    # (Mantive seu código original da calculadora aqui para economizar espaço visual na resposta,
    # ele funcionará igual pois está dentro da função calcular_investimento_bcb)
    with st.container(border=True):
        c1, c2, c3 = st.columns(3)
        meses = c1.number_input("Meses", 1, 12, 12)
        taxa = c2.number_input("Taxa Mensal (%)", 0.01, 5.0, 0.85)
        aporte = c3.number_input("Aporte (R$)", 0.0, 10000.0, 200.0)
        
        if st.button("Simular"):
            df_calc, final = calcular_investimento_bcb(meses, taxa, aporte)
            st.metric("Resultado Final", f"R$ {final:,.2f}")
            st.plotly_chart(px.area(df_calc, x="Mês", y="Saldo Total"), use_container_width=True)



