import streamlit as st
import pandas as pd
import gspread
from google.oauth2.service_account import Credentials
from datetime import datetime
import time
import uuid

# --- Configuração da Página (Layout Wide) ---
st.set_page_config(
    page_title="Finanças Pro", 
    page_icon="💳", 
    layout="wide",
    initial_sidebar_state="collapsed"
)

# --- Estilização CSS Personalizada ---
st.markdown("""
<style>
    [data-testid="stMetricValue"] {
        font-size: 24px;
        color: #00CC96;
    }
    div.stButton > button {
        width: 100%;
    }
</style>
""", unsafe_allow_html=True)

# --- Gestão de Usuários (Em um app real, use um banco de dados ou Secrets) ---
USERS = {
    "admin": "1234",
    "usuario1": "senha1",
    "visitante": "0000"
}

# --- Funções de Backend ---
@st.cache_resource
def conectar_google_sheets():
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds_dict = st.secrets["gcp_service_account"]
    credentials = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    client = gspread.authorize(credentials)
    # Abre a planilha e a aba específica
    return client.open("Orcamento-Pessoal").worksheet("Dados")

def carregar_dados():
    sheet = conectar_google_sheets()
    data = sheet.get_all_records()
    df = pd.DataFrame(data)
    return df

def salvar_no_sheets(df_novo):
    """Reescreve a planilha com os dados atualizados (para edições)"""
    sheet = conectar_google_sheets()
    # Atualiza a planilha inteira (cuidado com grandes volumes de dados)
    sheet.clear()
    sheet.update([df_novo.columns.values.tolist()] + df_novo.values.tolist())

# --- Sistema de Login ---
def check_login():
    if 'logged_in' not in st.session_state:
        st.session_state['logged_in'] = False
        st.session_state['username'] = ''

    if not st.session_state['logged_in']:
        col1, col2, col3 = st.columns([1,2,1])
        with col2:
            st.title("🔒 Acesso Restrito")
            st.markdown("Faça login para gerenciar suas finanças.")
            username = st.text_input("Usuário")
            password = st.text_input("Senha", type="password")
            
            if st.button("Entrar"):
                if username in USERS and USERS[username] == password:
                    st.session_state['logged_in'] = True
                    st.session_state['username'] = username
                    st.rerun()
                else:
                    st.error("Usuário ou senha incorretos.")
        return False
    return True

# --- App Principal ---
def main_app():
    # Sidebar com informações do usuário
    with st.sidebar:
        st.write(f"Olá, **{st.session_state['username']}** 👋")
        if st.button("Sair / Logout"):
            st.session_state['logged_in'] = False
            st.rerun()
    
    st.title("💳 Painel Financeiro")

    # Carregar dados
    try:
        df = carregar_dados()
    except Exception as e:
        st.error("Erro ao conectar no Google Sheets. Verifique as colunas.")
        st.stop()

    # Filtra dados APENAS do usuário logado (Segurança)
    # Se o DataFrame estiver vazio ou sem a coluna, trata o erro
    if 'Usuario' in df.columns and not df.empty:
        df_user = df[df['Usuario'] == st.session_state['username']].copy()
    else:
        # Cria estrutura vazia se for o primeiro acesso
        df_user = pd.DataFrame(columns=['ID', 'Data', 'Usuario', 'Categoria', 'Descricao', 'Valor', 'Recorrente'])

    # Converter coluna de Data para datetime para permitir filtros
    if not df_user.empty:
        df_user['Data'] = pd.to_datetime(df_user['Data'], format="%d/%m/%Y", errors='coerce')

    # --- Abas de Navegação ---
    tab1, tab2, tab3 = st.tabs(["📊 Dashboard & Gastos", "📝 Lançar Novo", "🔁 Recorrentes"])

    # --- ABA 1: Dashboard e Edição ---
    with tab1:
        # Métricas (Cards)
        col1, col2, col3 = st.columns(3)
        
        mes_atual = datetime.now().month
        ano_atual = datetime.now().year
        
        # Filtra mês atual
        if not df_user.empty:
            df_mes = df_user[
                (df_user['Data'].dt.month == mes_atual) & 
                (df_user['Data'].dt.year == ano_atual)
            ]
            total_mes = df_mes['Valor'].sum()
            total_geral = df_user['Valor'].sum()
            qtd_gastos = len(df_mes)
        else:
            total_mes = 0.0
            total_geral = 0.0
            qtd_gastos = 0

        col1.metric("Gastos este Mês", f"R$ {total_mes:.2f}")
        col2.metric("Total Acumulado", f"R$ {total_geral:.2f}")
        col3.metric("Lançamentos (Mês)", f"{qtd_gastos}")

        st.divider()
        
        st.subheader("📋 Seus Lançamentos (Editável)")
        st.info("💡 Clique duas vezes em uma célula para editar. Pressione 'Enter' e depois clique em 'Salvar Alterações'.")

        # Exibe editor de dados
        # Formatamos a data para string para exibição/edição correta no editor
        if not df_user.empty:
            df_display = df_user.sort_values(by='Data', ascending=False).copy()
            df_display['Data'] = df_display['Data'].dt.strftime("%d/%m/%Y")
        else:
            df_display = df_user

        edited_df = st.data_editor(
            df_display,
            num_rows="dynamic", # Permite adicionar/remover linhas
            column_config={
                "Valor": st.column_config.NumberColumn(format="R$ %.2f"),
                "Recorrente": st.column_config.CheckboxColumn(default=False),
                "Usuario": st.column_config.TextColumn(disabled=True), # Bloqueia edição do dono
                "ID": st.column_config.TextColumn(disabled=True)
            },
            hide_index=True,
            use_container_width=True,
            key="editor_gastos"
        )

        # Botão para persistir as edições no Google Sheets
        if st.button("💾 Salvar Alterações na Tabela"):
            with st.spinner("Sincronizando com Google Sheets..."):
                try:
                    # Precisamos mesclar os dados editados do usuário com os dados dos OUTROS usuários
                    # 1. Carrega tudo do banco original
                    df_full = carregar_dados()
                    
                    # 2. Remove os dados antigos DESTE usuário
                    df_others = df_full[df_full['Usuario'] != st.session_state['username']]
                    
                    # 3. Prepara os dados editados (re-adiciona o usuário se foi perdido e arruma IDs novos)
                    edited_df['Usuario'] = st.session_state['username']
                    
                    # Gera IDs para linhas novas que não tenham
                    for index, row in edited_df.iterrows():
                        if pd.isna(row['ID']) or row['ID'] == "":
                            edited_df.at[index, 'ID'] = str(uuid.uuid4())[:8]

                    # 4. Concatena
                    df_final = pd.concat([df_others, edited_df], ignore_index=True)
                    
                    # 5. Salva
                    salvar_no_sheets(df_final)
                    st.success("Tabela atualizada com sucesso!")
                    time.sleep(1)
                    st.rerun()
                except Exception as e:
                    st.error(f"Erro ao salvar: {e}")

    # --- ABA 2: Formulário de Lançamento ---
    with tab2:
        st.subheader("Novo Gasto")
        with st.form("entry_form", clear_on_submit=True):
            col1, col2 = st.columns(2)
            with col1:
                data_gasto = st.date_input("Data", datetime.now())
                valor = st.number_input("Valor (R$)", min_value=0.01, format="%.2f", step=10.0)
            with col2:
                categoria = st.selectbox("Categoria", ["Alimentação", "Transporte", "Moradia", "Lazer", "Assinaturas", "Saúde", "Outros"])
                descricao = st.text_input("Descrição")
            
            is_recorrente = st.checkbox("É um pagamento recorrente/fixo?")
            
            submitted = st.form_submit_button("Lançar Despesa")
            
            if submitted:
                try:
                    sheet = conectar_google_sheets()
                    data_formatada = data_gasto.strftime("%d/%m/%Y")
                    novo_id = str(uuid.uuid4())[:8]
                    
                    # Ordem exata das colunas: ID, Data, Usuario, Categoria, Descricao, Valor, Recorrente
                    linha = [
                        novo_id,
                        data_formatada,
                        st.session_state['username'],
                        categoria,
                        descricao,
                        valor,
                        "Sim" if is_recorrente else "Não"
                    ]
                    
                    sheet.append_row(linha)
                    st.toast(f"Gasto de R$ {valor} salvo!", icon="✅")
                    time.sleep(1) # Espera propagar
                    st.rerun() # Atualiza a tabela na outra aba
                    
                except Exception as e:
                    st.error(f"Erro: {e}")

    # --- ABA 3: Recorrentes (Visualização) ---
    with tab3:
        st.subheader("🔁 Pagamentos Fixos")
        if not df_user.empty:
            recorrentes = df_user[df_user['Recorrente'] == "Sim"]
            if not recorrentes.empty:
                st.dataframe(
                    recorrentes[['Categoria', 'Descricao', 'Valor']], 
                    use_container_width=True,
                    hide_index=True
                )
                
                total_fixo = recorrentes['Valor'].sum()
                st.info(f"Seus custos fixos somam: **R$ {total_fixo:.2f}**")
            else:
                st.write("Nenhum pagamento marcado como recorrente.")
        else:
            st.write("Sem dados.")

# --- Execução ---
if __name__ == "__main__":
    if check_login():
        main_app()
