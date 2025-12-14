import streamlit as st
import pandas as pd
import gspread
from oauth2client.service_account import ServiceAccountCredentials
from datetime import datetime

# --- Configuração da Página ---
st.set_page_config(page_title="Controle Financeiro", page_icon="💰")

# --- Conexão com Google Sheets (Versão Cloud) ---
def conectar_google_sheets():
    # Define o escopo de permissões
    scope = ["https://spreadsheets.google.com/feeds", "https://www.googleapis.com/auth/drive"]
    
    # --- MUDANÇA AQUI: Lê do st.secrets em vez do arquivo json ---
    # O Streamlit Cloud vai injetar essas credenciais de forma segura
    creds_dict = st.secrets["gcp_service_account"]
    creds = ServiceAccountCredentials.from_json_keyfile_dict(creds_dict, scope)
    
    client = gspread.authorize(creds)
    
    # Abre a planilha (Certifique-se que o nome é EXATO)
    sheet = client.open("Orcamento-Pessoal").worksheet("Dados") 
    return sheet

# --- Título ---
st.title("📱 Lançamento de Gastos")

# --- Formulário de Entrada ---
with st.form("entry_form", clear_on_submit=True):
    
    col1, col2 = st.columns(2)
    
    with col1:
        data_gasto = st.date_input("Data", datetime.now())
        valor = st.number_input("Valor (R$)", min_value=0.0, format="%.2f", step=1.0)
        
    with col2:
        categoria = st.selectbox(
            "Categoria", 
            ["Alimentação/iFood", "Transporte/Uber", "Lazer", "Mercado", "Assinaturas", "Farmácia", "Outros"]
        )
        descricao = st.text_input("Descrição (Ex: Pizza, Uber p/ facul)")
    
    submitted = st.form_submit_button("💾 Salvar Gasto")

    if submitted:
        if valor > 0:
            try:
                # Conecta e Salva
                sheet = conectar_google_sheets()
                
                # Formata a data para dia/mês/ano
                data_formatada = data_gasto.strftime("%d/%m/%Y")
                
                # Adiciona a linha na planilha
                sheet.append_row([data_formatada, categoria, descricao, valor])
                
                st.success(f"✅ Sucesso! R$ {valor} em {categoria} registrado.")
                
                # Efeito visual apenas se der certo
                st.balloons()
                
            except Exception as e:
                st.error(f"Erro ao salvar. Verifique a conexão: {e}")
        else:
            st.warning("⚠️ O valor precisa ser maior que zero.")

# --- Visualização Rápida (Opcional) ---
try:
    if st.checkbox("Ver últimos lançamentos"):
        sheet = conectar_google_sheets()
        dados = sheet.get_all_records()
        df = pd.DataFrame(dados)
        st.dataframe(df.tail(5))
except:
    pass