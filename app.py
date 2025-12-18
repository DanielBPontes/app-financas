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

# --- 2. CSS Otimizado ---
st.markdown("""
<style>
    .stAppHeader {display:none !important;} 
    .block-container {padding-top: 1rem !important; padding-bottom: 6rem !important;} 
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
    .stButton button { width: 100%; border-radius: 12px; font-weight: 600; }
    /* Ajuste Microfone */
    div[data-testid="stAudioInput"] { margin-top: -10px; margin-bottom: 10px; }
    div[data-testid="stAudioInput"] label { display: none; }
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

# --- Funções ---
def carregar_transacoes(user_id, limite=None):
    try:
        query = supabase.table("transactions").select("*").eq("user_id", user_id).order("data", desc=True)
        if limite: query = query.limit(limite)
        res = query.execute()
        df = pd.DataFrame(res.data)
        if not df.empty:
            # Conversão segura para datetime
            df['data_dt'] = pd.to_datetime(df['data'], errors='coerce')
            df['valor'] = pd.to_numeric(df['valor'])
        return df
    except Exception as e:
        print(f"Erro ao carregar: {e}")
        return pd.DataFrame()

def executar_sql(acao, dados, user_id):
    try:
        tabela = supabase.table("transactions")
        if acao == 'insert':
            if 'id' in dados: del dados['id']
            tabela.insert(dados).execute()
        elif acao == 'update':
            if not dados.get('id'): return False
            # Remove chaves inválidas para update
            payload = {k: v for k, v in dados.items() if k in ['valor', 'descricao', 'categoria', 'data', 'tipo']}
            tabela.update(payload).eq("id", dados['id']).eq("user_id", user_id).execute()
        elif acao == 'delete':
            tabela.delete().eq("id", dados['id']).eq("user_id", user_id).execute()
        return True
    except Exception as e:
        st.error(f"Erro SQL: {e}"); return False

def fmt_real(valor):
    return f"{valor:,.2f}".replace(",", "X").replace(".", ",").replace("X", ".")

# --- Agente IA Robusto ---
def agente_financeiro_ia(entrada, df_contexto, tipo_entrada="texto"):
    if not IA_AVAILABLE: return {"acao": "erro", "msg": "IA Off"}
    
    # Contexto limitado para economizar tokens e evitar confusão
    contexto = "[]"
    if not df_contexto.empty:
        contexto = df_contexto[['id', 'data', 'descricao', 'valor', 'categoria']].head(5).to_json(orient="records")

    prompt = f"""
    Contexto Financeiro: {contexto}
    Hoje: {date.today()}.
    
    TAREFA: Analise o input do usuário e extraia uma transação financeira.
    1. Se for texto como "Almoço 30", assuma "Despesa".
    2. Valores decimais USE PONTO (Ex: 30.50).
    3. Responda APENAS JSON.
    
    Input Usuário:
    """
    
    try:
        model = genai.GenerativeModel('gemini-1.5-flash')
        
        if tipo_entrada == "audio":
            audio_bytes = entrada.getvalue()
            # Prompt específico para áudio
            response = model.generate_content(
                [prompt, {"mime_type": "audio/wav", "data": audio_bytes}, "Transcreva e extraia o JSON."],
                generation_config={"response_mime_type": "application/json"}
            )
        else:
            full_prompt = f"{prompt} '{entrada}'"
            response = model.generate_content(full_prompt, generation_config={"response_mime_type": "application/json"})
            
        result = json.loads(response.text)
        
        # Validação básica do JSON retornado
        if "dados" not in result or "acao" not in result:
             # Tentativa de correção se a IA errar a estrutura
             return {"acao": "erro", "msg": "Estrutura inválida da IA"}
             
        return result

    except Exception as e:
        print(f"ERRO IA: {e}") # Debug no console
        return {"acao": "erro", "msg": f"Erro ao processar: {str(e)}"}

# =======================================================
# APP
# =======================================================
if 'user' not in st.session_state: st.session_state['user'] = None

if not st.session_state['user']:
    with st.form("login"):
        st.write("Login Finanças")
        u = st.text_input("User")
        p = st.text_input("Pass", type="password")
        if st.form_submit_button("Entrar"):
            try:
                # Login Simplificado para teste (ajuste conforme sua tabela users)
                resp = supabase.table("users").select("*").eq("username", u).eq("password", p).execute()
                if resp.data: st.session_state['user'] = resp.data[0]; st.rerun()
                else: st.error("Inválido")
            except: st.error("Erro Conexão")
    st.stop()

user = st.session_state['user']
df_total = carregar_transacoes(user['id'], 100)

with st.sidebar:
    if st.button("Sair"): st.session_state.clear(); st.rerun()

# Navegação
nav = st.radio("Menu", ["Chat", "Extrato", "Análise"], label_visibility="collapsed")
st.markdown("---")

# =======================================================
# 1. CHAT (Correção de Loop)
# =======================================================
if nav == "Chat":
    if "msgs" not in st.session_state: st.session_state.msgs = []
    if "op_pendente" not in st.session_state: st.session_state.op_pendente = None
    
    # Chave única para o audio input baseada em timestamp para resetar se necessário
    if "audio_key" not in st.session_state: st.session_state.audio_key = 0

    # Histórico
    for m in st.session_state.msgs:
        with st.chat_message(m["role"]): st.markdown(m["content"])

    if not st.session_state.op_pendente:
        # Sugestões
        c1, c2, c3 = st.columns(3)
        btn_almoco = c1.button("🍔 Almoço")
        btn_uber = c2.button("🚗 Uber")
        btn_pix = c3.button("💰 Recebi")

        # Inputs
        # Importante: A ordem de checagem define a prioridade
        audio_val = st.audio_input("Falar", label_visibility="collapsed", key=f"audio_{st.session_state.audio_key}")
        text_val = st.chat_input("Digite...")

        input_final = None
        tipo_final = None

        # Lógica de Prioridade: Botão > Texto > Áudio Novo
        if btn_almoco: 
            input_final = "Almoço 30 reais"; tipo_final = "texto"
        elif btn_uber:
            input_final = "Uber 15 reais"; tipo_final = "texto"
        elif btn_pix:
            input_final = "Recebi pix 50 reais"; tipo_final = "texto"
        elif text_val:
            input_final = text_val; tipo_final = "texto"
        elif audio_val:
            # Verifica se este audio já foi processado nesta sessão
            if "last_audio" not in st.session_state or st.session_state.last_audio != audio_val:
                input_final = audio_val
                tipo_final = "audio"
                st.session_state.last_audio = audio_val # Marca como lido
            
        # Processamento
        if input_final:
            if tipo_final == "texto":
                st.session_state.msgs.append({"role": "user", "content": input_final})
            else:
                st.session_state.msgs.append({"role": "user", "content": "🎤 *Áudio enviado*"})

            with st.chat_message("assistant"):
                with st.spinner("Pensando..."):
                    res = agente_financeiro_ia(input_final, df_total, tipo_final)
                    
                    if res['acao'] in ['insert', 'update', 'delete']:
                        st.session_state.op_pendente = res
                        st.rerun()
                    elif res['acao'] == 'erro':
                        msg = f"Erro: {res.get('msg')}"
                        st.error(msg)
                        st.session_state.msgs.append({"role": "assistant", "content": msg})
                    else:
                        msg = res.get('msg_ia', str(res))
                        st.markdown(msg)
                        st.session_state.msgs.append({"role": "assistant", "content": msg})

    # Confirmação
    if st.session_state.op_pendente:
        op = st.session_state.op_pendente
        d = op.get('dados', {})
        
        with st.container():
            st.info(f"CONFIRMAR: {op.get('acao')}")
            st.code(f"{d.get('descricao')} | R$ {d.get('valor')}")
            
            c1, c2 = st.columns(2)
            if c1.button("✅ Sim", type="primary"):
                final = d.copy()
                final['user_id'] = user['id']
                if executar_sql(op['acao'], final, user['id']):
                    st.toast("Sucesso!")
                    st.session_state.msgs.append({"role": "assistant", "content": "✅ Feito!"})
                st.session_state.op_pendente = None
                # Incrementa key do audio para "limpar" o componente visualmente
                st.session_state.audio_key += 1 
                time.sleep(1)
                st.rerun()
                
            if c2.button("❌ Não"):
                st.session_state.op_pendente = None
                st.rerun()

# =======================================================
# 2. EXTRATO (Correção Data Editor)
# =======================================================
elif nav == "Extrato":
    st.subheader("Extrato")
    
    if not df_total.empty:
        # Prepara dados para o editor
        # 1. Copia o DF
        df_edit = df_total.copy()
        
        # 2. Garante que é Datetime
        df_edit['data'] = pd.to_datetime(df_edit['data'], errors='coerce')
        
        # 3. Remove datas inválidas (NaT) para não quebrar o editor
        df_edit = df_edit.dropna(subset=['data'])
        
        # 4. Converte para DATE OBJECT (O segredo para não dar erro no DateColumn)
        df_edit['data'] = df_edit['data'].dt.date
        
        # 5. Seleciona colunas
        df_edit = df_edit[['id', 'data', 'descricao', 'valor', 'categoria', 'tipo']]

        try:
            mudancas = st.data_editor(
                df_edit,
                column_config={
                    "id": None,
                    "valor": st.column_config.NumberColumn("Valor", format="R$ %.2f"),
                    "data": st.column_config.DateColumn("Data", format="DD/MM/YYYY"),
                    "tipo": st.column_config.SelectboxColumn("Tipo", options=["Receita", "Despesa"]),
                    "categoria": st.column_config.SelectboxColumn("Cat", options=["Alimentação", "Transporte", "Casa", "Lazer", "Outros"])
                },
                hide_index=True,
                use_container_width=True,
                num_rows="dynamic",
                key="editor_main"
            )

            if st.button("Salvar Alterações"):
                with st.spinner("Salvando..."):
                    # Processa Updates
                    ids_orig = df_edit['id'].tolist()
                    
                    for i, row in mudancas.iterrows():
                        d = row.to_dict()
                        # Converte de volta para string YYYY-MM-DD para o Supabase
                        if isinstance(d['data'], (date, datetime)):
                            d['data'] = d['data'].strftime('%Y-%m-%d')
                            
                        if pd.isna(d['id']): 
                            # Lógica para insert via tabela (simplificada: ignorar ou tratar depois)
                            pass
                        else:
                            executar_sql('update', d, user['id'])
                    
                    # Processa Deletes
                    ids_new = mudancas['id'].dropna().tolist()
                    deleted = set(ids_orig) - set(ids_new)
                    for idx in deleted:
                        executar_sql('delete', {'id': idx}, user['id'])
                        
                    st.toast("Salvo!")
                    time.sleep(1)
                    st.rerun()
                    
        except Exception as e:
            st.error(f"Erro ao renderizar tabela: {e}")
            st.write(df_edit.head()) # Mostra dados brutos para debug
    else:
        st.info("Sem dados.")

# =======================================================
# 3. ANÁLISE
# =======================================================
elif nav == "Análise":
    if not df_total.empty:
        df_atual = df_total.copy()
        # Filtro simples
        gastos = df_atual[df_atual['tipo'] != 'Receita']
        if not gastos.empty:
            fig = px.pie(gastos, values='valor', names='categoria', hole=0.5)
            st.plotly_chart(fig, use_container_width=True)
