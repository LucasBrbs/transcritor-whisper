import streamlit as st
import whisper
import os
import tempfile
import time
import threading
import glob
import gc
from pathlib import Path
from datetime import datetime, timedelta

# Configurar e gerenciar cache local
def configurar_cache():
    cache_dir = os.path.join(os.getcwd(), "whisper_cache")
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["WHISPER_CACHE_DIR"] = cache_dir
    return cache_dir

def limpar_sistema_automatico():
    """Sistema de limpeza automática inteligente de 24h"""
    arquivo_controle = os.path.join(os.getcwd(), ".ultima_limpeza_streamlit")
    agora = datetime.now()
    
    # Verificar se precisa limpar
    precisa_limpar = True
    if os.path.exists(arquivo_controle):
        with open(arquivo_controle, "r") as f:
            try:
                ultima_limpeza_str = f.read().strip()
                ultima_limpeza = datetime.fromisoformat(ultima_limpeza_str)
                if agora - ultima_limpeza < timedelta(hours=24):
                    precisa_limpar = False
            except:
                pass
    
    if precisa_limpar:
        arquivos_removidos = 0
        
        # 1. Limpar arquivos de transcrição antigos
        padroes_transcricao = ["*_transcricao.txt", "*_legendas.srt"]
        for padrao in padroes_transcricao:
            for arquivo in glob.glob(padrao):
                try:
                    # Remove arquivos de transcrição com mais de 24h
                    if time.time() - os.path.getctime(arquivo) > 86400:  # 24h
                        os.remove(arquivo)
                        arquivos_removidos += 1
                except:
                    pass
        
        # 2. Gerenciar cache do Whisper
        cache_dir = os.path.join(os.getcwd(), "whisper_cache")
        if os.path.exists(cache_dir):
            # Manter apenas os 2 modelos mais usados
            modelos = []
            for arquivo in os.listdir(cache_dir):
                if arquivo.endswith('.pt'):
                    caminho = os.path.join(cache_dir, arquivo)
                    modelos.append((arquivo, os.path.getmtime(caminho)))
            
            # Ordenar por uso mais recente
            modelos.sort(key=lambda x: x[1], reverse=True)
            
            # Remover modelos além dos 2 mais recentes
            for modelo, _ in modelos[2:]:
                try:
                    os.remove(os.path.join(cache_dir, modelo))
                    arquivos_removidos += 1
                except:
                    pass
        
        # 3. Limpar arquivos temporários
        temp_patterns = [
            "/tmp/tmp*",
            "/tmp/streamlit*", 
            os.path.join(tempfile.gettempdir(), "tmp*")
        ]
        
        for pattern in temp_patterns:
            for arquivo in glob.glob(pattern):
                try:
                    if os.path.isfile(arquivo) and time.time() - os.path.getctime(arquivo) > 3600:
                        os.remove(arquivo)
                        arquivos_removidos += 1
                except:
                    pass
        
        # Salvar timestamp da limpeza
        with open(arquivo_controle, "w") as f:
            f.write(agora.isoformat())
        
        return arquivos_removidos
    
    return 0

def limpar_cache_antigo():
    """Remove arquivos temporários antigos para evitar acúmulo"""
    return limpar_sistema_automatico()

def obter_info_cache():
    """Retorna informações sobre o cache do Whisper"""
    cache_dir = configurar_cache()
    modelos = []
    tamanho_total = 0
    
    if os.path.exists(cache_dir):
        for arquivo in os.listdir(cache_dir):
            if arquivo.endswith('.pt'):
                caminho = os.path.join(cache_dir, arquivo)
                tamanho = os.path.getsize(caminho) / (1024**2)  # MB
                modelos.append({
                    'nome': arquivo.replace('.pt', ''),
                    'tamanho': tamanho,
                    'arquivo': arquivo
                })
                tamanho_total += tamanho
    
    return modelos, tamanho_total



# Função para gerar arquivo SRT
def gerar_srt(resultado):
    """
    Gera conteúdo SRT (legendas) a partir do resultado da transcrição
    
    Args:
        resultado (dict): Resultado da transcrição do Whisper
    
    Returns:
        str: Conteúdo do arquivo SRT
    """
    srt_content = ""
    
    for i, segmento in enumerate(resultado["segments"], 1):
        inicio = segmento["start"]
        fim = segmento["end"]
        texto = segmento["text"].strip()
        
        # Converter tempo para formato SRT (HH:MM:SS,mmm)
        inicio_srt = f"{int(inicio//3600):02d}:{int((inicio%3600)//60):02d}:{int(inicio%60):02d},{int((inicio%1)*1000):03d}"
        fim_srt = f"{int(fim//3600):02d}:{int((fim%3600)//60):02d}:{int(fim%60):02d},{int((fim%1)*1000):03d}"
        
        srt_content += f"{i}\n"
        srt_content += f"{inicio_srt} --> {fim_srt}\n"
        srt_content += f"{texto}\n\n"
    
    return srt_content

# Função para carregar modelo com cache otimizado
@st.cache_resource(ttl=3600, max_entries=2)  # Cache por 1 hora, máximo 2 modelos
def carregar_modelo_whisper(modelo):
    """Carrega o modelo Whisper com cache para melhor performance"""
    cache_dir = configurar_cache()
    
    # Limpar cache antigo antes de carregar novo modelo
    limpar_cache_antigo()
    
    # Forçar garbage collection
    import gc
    gc.collect()
    
    return whisper.load_model(modelo, download_root=cache_dir)

# Função para liberar memória após transcrição
def liberar_memoria():
    """Libera memória não utilizada"""
    import gc
    gc.collect()
    
    # Limpar cache do Streamlit se necessário
    if len(st.session_state) > 10:
        keys_antigas = list(st.session_state.keys())[:-5]  # Manter apenas as 5 mais recentes
        for key in keys_antigas:
            if key not in ['modelo_cache', 'configuracao']:
                del st.session_state[key]

# Função para transcrever áudio com progresso realista
def transcrever_audio(arquivo_audio, modelo_nome, idioma="pt"):
    """Transcreve o arquivo de áudio usando o modelo Whisper selecionado"""
    
    # Criar containers para progresso
    progress_container = st.container()
    
    with progress_container:
        # Container customizado para progresso
        st.markdown('<div class="progress-container">', unsafe_allow_html=True)
        st.markdown('<div class="progress-title">🚀 PROCESSANDO TRANSCRIÇÃO</div>', unsafe_allow_html=True)
        
        # Containers para texto
        percentage_container = st.empty()
        status_container = st.empty()
        
        # Barra de progresso principal
        progress_bar = st.progress(0)
        
        # Fase 1: Inicializando (0-10%)
        for i in range(0, 11):
            progress_bar.progress(i)
            percentage_container.markdown(f'<div class="progress-percentage">{i}%</div>', unsafe_allow_html=True)
            status_container.markdown(f'<div class="progress-status">🔧 Inicializando sistema...</div>', unsafe_allow_html=True)
            time.sleep(0.1)
        
        # Fase 2: Carregando modelo (10-25%)
        for i in range(11, 26):
            progress_bar.progress(i)
            percentage_container.markdown(f'<div class="progress-percentage">{i}%</div>', unsafe_allow_html=True)
            status_container.markdown(f'<div class="progress-status">🤖 Carregando modelo {modelo_nome.upper()}...</div>', unsafe_allow_html=True)
            time.sleep(0.05)
        
        modelo = carregar_modelo_whisper(modelo_nome)
        
        # Fase 3: Preparando áudio (25-35%)
        for i in range(26, 36):
            progress_bar.progress(i)
            percentage_container.markdown(f'<div class="progress-percentage">{i}%</div>', unsafe_allow_html=True)
            status_container.markdown(f'<div class="progress-status">🎵 Analisando arquivo de áudio...</div>', unsafe_allow_html=True)
            time.sleep(0.08)
        
        # Fase 4: Processando transcrição (35-85%)
        status_container.markdown(f'<div class="progress-status">🎤 Transcrevendo áudio... Isso pode levar alguns minutos</div>', unsafe_allow_html=True)
        
        # Simular progresso da transcrição de forma mais realista
        import threading
        progresso_atual = [35]  # Lista para permitir modificação na thread
        
        def atualizar_progresso():
            while progresso_atual[0] < 85:
                progresso_atual[0] += 1
                progress_bar.progress(progresso_atual[0])
                percentage_container.markdown(f'<div class="progress-percentage">{progresso_atual[0]}%</div>', unsafe_allow_html=True)
                status_container.markdown(f'<div class="progress-status">🎤 Processando áudio... Analisando segmentos</div>', unsafe_allow_html=True)
                time.sleep(0.3)  # Progresso mais lento para parecer realista
        
        # Iniciar thread de progresso
        thread_progresso = threading.Thread(target=atualizar_progresso)
        thread_progresso.daemon = True
        thread_progresso.start()
        
        # Executar transcrição
        resultado = modelo.transcribe(arquivo_audio, language=idioma)
        
        # Parar thread de progresso
        progresso_atual[0] = 85
        
        # Fase 5: Processando resultados (85-95%)
        for i in range(86, 96):
            progress_bar.progress(i)
            percentage_container.markdown(f'<div class="progress-percentage">{i}%</div>', unsafe_allow_html=True)
            status_container.markdown(f'<div class="progress-status">📝 Organizando transcrição...</div>', unsafe_allow_html=True)
            time.sleep(0.1)
        
        # Fase 6: Finalizando (95-100%)
        for i in range(96, 101):
            progress_bar.progress(i)
            percentage_container.markdown(f'<div class="progress-percentage">{i}%</div>', unsafe_allow_html=True)
            status_container.markdown(f'<div class="progress-status">✨ Finalizando processo...</div>', unsafe_allow_html=True)
            time.sleep(0.1)
        
        # Mostrar conclusão
        percentage_container.markdown('<div class="progress-percentage">100%</div>', unsafe_allow_html=True)
        status_container.markdown('<div class="progress-status">🎉 Transcrição concluída com sucesso!</div>', unsafe_allow_html=True)
        
        # Fechar container customizado
        st.markdown('</div>', unsafe_allow_html=True)
        
        # Manter por alguns segundos antes de limpar
        time.sleep(3)
        progress_container.empty()
    
    # Liberar memória após transcrição
    liberar_memoria()
    
    # Incrementar contador de transcrições
    st.session_state.contador_transcricoes += 1
    
    return resultado

# Configuração da página
st.set_page_config(
    page_title="Transcritor de Áudio com Whisper",
    page_icon="🎤",
    layout="wide"
)

# Inicializar session state para controle de performance
if 'sessao_ativa' not in st.session_state:
    st.session_state.sessao_ativa = True
    st.session_state.contador_transcricoes = 0
    # Executar limpeza automática de 24h na inicialização
    arquivos_removidos = limpar_sistema_automatico()
    if arquivos_removidos > 0:
        st.session_state.limpeza_inicial = f"🧹 Limpeza automática: {arquivos_removidos} arquivos removidos"

# Limpar cache automaticamente após várias transcrições
if st.session_state.contador_transcricoes > 5:
    liberar_memoria()
    st.session_state.contador_transcricoes = 0

# CSS customizado para barra de progresso animada
st.markdown("""
<style>
    .progress-container {
        background: linear-gradient(90deg, #1e3c72, #2a5298);
        padding: 20px;
        border-radius: 15px;
        margin: 20px 0;
        box-shadow: 0 4px 15px rgba(0,0,0,0.1);
    }
    
    .progress-title {
        color: white;
        font-size: 1.5em;
        font-weight: bold;
        text-align: center;
        margin-bottom: 15px;
        text-shadow: 2px 2px 4px rgba(0,0,0,0.3);
    }
    
    .progress-status {
        color: #e0e0e0;
        font-size: 1.1em;
        text-align: center;
        margin: 10px 0;
        animation: pulse 2s infinite;
    }
    
    .progress-percentage {
        color: #00ff88;
        font-size: 2em;
        font-weight: bold;
        text-align: center;
        text-shadow: 0 0 10px rgba(0,255,136,0.5);
        animation: glow 2s ease-in-out infinite alternate;
    }
    
    @keyframes pulse {
        0% { opacity: 0.8; }
        50% { opacity: 1; }
        100% { opacity: 0.8; }
    }
    
    @keyframes glow {
        from { text-shadow: 0 0 10px rgba(0,255,136,0.5); }
        to { text-shadow: 0 0 20px rgba(0,255,136,0.8); }
    }
    
    .stProgress > div > div > div > div {
        background: linear-gradient(90deg, #00ff88, #00cc6a, #00ff88);
        background-size: 200% 100%;
        animation: shine 2s infinite;
    }
    
    @keyframes shine {
        0% { background-position: -200% 0; }
        100% { background-position: 200% 0; }
    }
</style>
""", unsafe_allow_html=True)

# Título principal
st.title("🎤 Transcritor de Áudio com Whisper")
st.markdown("**🔄 Sistema com auto-limpeza de 24h - sempre rápido e leve!**")
st.markdown("**Converta seus arquivos de áudio em texto (TXT) e legendas (SRT)!**")

# Informações dos modelos em formato compacto
st.info("""
🤖 **Guia Rápido dos Modelos:**
• **Tiny**: Rápido, precisão básica • **Base**: Balanceado (recomendado) • **Small**: Boa precisão  
• **Medium**: Excelente para áudio complexo • **Large**: Máxima precisão
""")

# Interface principal
st.header("📁 Selecione seu arquivo de áudio")

# Upload de arquivo com validação
arquivo_uploaded = st.file_uploader(
    "Escolha um arquivo de áudio:",
    type=['mp3', 'wav', 'm4a', 'flac', 'ogg', 'wma'],
    help="Formatos suportados: MP3, WAV, M4A, FLAC, OGG, WMA (máx. 200MB)"
)

# Validação do arquivo
if arquivo_uploaded is not None:
    # Verificar tamanho do arquivo (máximo 200MB)
    max_size = 200 * 1024 * 1024  # 200MB em bytes
    if arquivo_uploaded.size > max_size:
        st.error(f"❌ Arquivo muito grande! Tamanho máximo: 200MB. Seu arquivo: {arquivo_uploaded.size / (1024*1024):.1f}MB")
        st.stop()
    
    # Verificar se o nome do arquivo é válido
    if not arquivo_uploaded.name or len(arquivo_uploaded.name) == 0:
        st.error("❌ Nome do arquivo inválido!")
        st.stop()

st.header("⚙️ Configurações")

# Seletor de modelo
modelo_selecionado = st.selectbox(
    "Escolha o modelo Whisper:",
    ["tiny", "base", "small", "medium", "large"],
    index=1,  # base como padrão
    help="Modelos maiores são mais precisos, mas mais lentos"
)



# Seletor de idioma
idioma_selecionado = st.selectbox(
    "Idioma do áudio:",
    [
        ("pt", "Português 🇧🇷"),
        ("en", "Inglês 🇺🇸"),
        ("es", "Espanhol 🇪🇸"),
        ("fr", "Francês 🇫🇷"),
        ("it", "Italiano 🇮🇹"),
        ("de", "Alemão 🇩🇪"),
        ("auto", "Detectar automaticamente 🌐")
    ],
    format_func=lambda x: x[1],
    help="Escolha o idioma do áudio ou deixe em 'Detectar automaticamente'"
)

# Área de processamento
if arquivo_uploaded is not None and arquivo_uploaded.size <= 200 * 1024 * 1024:
    st.success(f"✅ Arquivo carregado: **{arquivo_uploaded.name}**")
    
    # Mostrar informações do arquivo
    col1, col2, col3 = st.columns(3)
    with col1:
        st.metric("📁 Arquivo", arquivo_uploaded.name)
    with col2:
        st.metric("📊 Tamanho", f"{arquivo_uploaded.size / (1024*1024):.1f} MB")
    with col3:
        st.metric("🎛️ Modelo", modelo_selecionado.upper())
    
    # Botão para processar
    if st.button("🚀 Iniciar Transcrição", type="primary", use_container_width=True):
        try:
            # Salvar arquivo temporário
            with tempfile.NamedTemporaryFile(delete=False, suffix=Path(arquivo_uploaded.name).suffix) as tmp_file:
                tmp_file.write(arquivo_uploaded.getvalue())
                caminho_temp = tmp_file.name
            
            # Configurar idioma
            idioma_codigo = idioma_selecionado[0] if idioma_selecionado[0] != "auto" else None
            
            # Processar transcrição
            inicio_tempo = time.time()
            resultado = transcrever_audio(caminho_temp, modelo_selecionado, idioma_codigo)
            tempo_processamento = time.time() - inicio_tempo
            
            # Limpar arquivo temporário
            os.unlink(caminho_temp)
            
            # Mostrar resultados
            st.success(f"✅ Transcrição concluída em {tempo_processamento:.1f} segundos!")
            
            # Área de resultados
            st.header("📄 Resultados da Transcrição")
            
            # Tabs para diferentes visualizações
            tab1, tab2, tab3 = st.tabs(["🔤 Texto Completo", "⏰ Por Segmentos", "📊 Estatísticas"])
            
            with tab1:
                st.subheader("Transcrição Completa")
                texto_completo = resultado["text"].strip()
                st.text_area(
                    "Texto transcrito:",
                    texto_completo,
                    height=400,
                    help="Você pode copiar este texto ou fazer download abaixo"
                )
                
                # Botões de download
                col1, col2 = st.columns(2)
                
                with col1:
                    st.download_button(
                        label="⬇️ Baixar Transcrição (TXT)",
                        data=texto_completo,
                        file_name=f"{Path(arquivo_uploaded.name).stem}_transcricao.txt",
                        mime="text/plain"
                    )
                
                with col2:
                    # Gerar conteúdo SRT
                    srt_content = gerar_srt(resultado)
                    st.download_button(
                        label="🎬 Baixar Legendas (SRT)",
                        data=srt_content,
                        file_name=f"{Path(arquivo_uploaded.name).stem}_legendas.srt",
                        mime="text/plain"
                    )
            
            with tab2:
                st.subheader("Transcrição por Segmentos")
                
                # Criar texto formatado com timestamps
                texto_segmentos = ""
                for i, segmento in enumerate(resultado["segments"], 1):
                    inicio = int(segmento["start"])
                    fim = int(segmento["end"])
                    texto = segmento["text"].strip()
                    
                    # Mostrar no Streamlit
                    with st.expander(f"Segmento {i}: [{inicio//60:02d}:{inicio%60:02d} - {fim//60:02d}:{fim%60:02d}]"):
                        st.write(texto)
                    
                    # Adicionar ao texto para download
                    texto_segmentos += f"{i:2d}. [{inicio//60:02d}:{inicio%60:02d} - {fim//60:02d}:{fim%60:02d}] {texto}\n"
                
                # Botões de download dos segmentos
                col1, col2 = st.columns(2)
                
                with col1:
                    st.download_button(
                        label="⬇️ Baixar Segmentos (TXT)",
                        data=texto_segmentos,
                        file_name=f"{Path(arquivo_uploaded.name).stem}_segmentos.txt",
                        mime="text/plain"
                    )
                
                with col2:
                    # Gerar conteúdo SRT para segmentos
                    srt_content = gerar_srt(resultado)
                    st.download_button(
                        label="🎬 Baixar Legendas (SRT)",
                        data=srt_content,
                        file_name=f"{Path(arquivo_uploaded.name).stem}_legendas.srt",
                        mime="text/plain"
                    )
            
            with tab3:
                st.subheader("Estatísticas da Transcrição")
                
                col1, col2, col3, col4 = st.columns(4)
                
                with col1:
                    st.metric("⏱️ Duração", f"{len(resultado['segments'])} segmentos")
                
                with col2:
                    duracao_total = resultado["segments"][-1]["end"] if resultado["segments"] else 0
                    st.metric("🕐 Tempo Total", f"{int(duracao_total//60):02d}:{int(duracao_total%60):02d}")
                
                with col3:
                    palavras = len(texto_completo.split())
                    st.metric("💬 Palavras", f"{palavras}")
                
                with col4:
                    st.metric("⚡ Processamento", f"{tempo_processamento:.1f}s")
                
                # Informações adicionais
                st.write("**Detalhes técnicos:**")
                st.write(f"• Modelo usado: **{modelo_selecionado.upper()}**")
                st.write(f"• Idioma detectado: **{resultado.get('language', 'N/A')}**")
                st.write(f"• Arquivo processado: **{arquivo_uploaded.name}**")
        
        except Exception as e:
            st.error(f"❌ Erro durante a transcrição: {str(e)}")
            st.write("💡 Possíveis soluções:")
            st.write("• **Erro 403**: Arquivo muito grande ou com nome inválido - tente renomear sem caracteres especiais")
            st.write("• **Arquivo corrompido**: Verifique se o arquivo não está danificado")
            st.write("• **Formato não suportado**: Use MP3, WAV, M4A, FLAC, OGG ou WMA")
            st.write("• **Memória insuficiente**: Tente usar um modelo menor (tiny ou base)")
            st.write("• **Tamanho**: Arquivos devem ter no máximo 200MB")

else:
    st.info("👆 Faça upload de um arquivo de áudio para começar!")
    
    # Exemplo de uso
    st.header("📖 Como usar")
    st.write("1. 📁 Selecione seu arquivo • 2. ⚙️ Escolha o modelo • 3. 🚀 Clique em 'Iniciar' • 4. ⬇️ Baixe TXT + SRT")
    
    st.header("📄 Formatos de saída")
    col1, col2 = st.columns(2)
    with col1:
        st.write("**📄 TXT** - Texto puro da transcrição")
    with col2:
        st.write("**🎬 SRT** - Legendas com timestamps")

# Sidebar com informações do sistema
with st.sidebar:
    st.header("📊 Informações do Sistema")
    
    # Informações do cache
    modelos, tamanho_total = obter_info_cache()
    
    st.subheader("🗂️ Cache dos Modelos")
    if modelos:
        for modelo in modelos:
            st.write(f"• **{modelo['nome']}**: {modelo['tamanho']:.1f} MB")
        st.write(f"**Total**: {tamanho_total:.1f} MB")
        
        # Aviso se o cache está muito grande
        if tamanho_total > 1000:  # > 1GB
            st.warning("⚠️ Cache grande! Considere usar apenas 1-2 modelos.")
    else:
        st.write("Nenhum modelo baixado ainda")
    
    # Informações sobre limpeza automática
    arquivo_controle = os.path.join(os.getcwd(), ".ultima_limpeza_streamlit")
    if os.path.exists(arquivo_controle):
        with open(arquivo_controle, "r") as f:
            try:
                ultima_limpeza_str = f.read().strip()
                ultima_limpeza = datetime.fromisoformat(ultima_limpeza_str)
                proxima_limpeza = ultima_limpeza + timedelta(hours=24)
                tempo_restante = proxima_limpeza - datetime.now()
                
                if tempo_restante.total_seconds() > 0:
                    horas = int(tempo_restante.total_seconds() // 3600)
                    st.info(f"⏰ Próxima limpeza automática em: {horas}h")
                else:
                    st.warning("🔄 Limpeza automática pendente...")
            except:
                pass
    
    # Botões de limpeza
    col1, col2 = st.columns(2)
    with col1:
        if st.button("🧹 Limpeza Manual"):
            arquivos_removidos = limpar_cache_antigo()
            liberar_memoria()
            st.success(f"✅ {arquivos_removidos} arquivos removidos")
            st.rerun()
    
    with col2:
        if st.button("🔄 Reset Total"):
            # Reset completo: cache + transcrições + session state
            arquivos_removidos = limpar_sistema_automatico()
            cache_dir = os.path.join(os.getcwd(), "whisper_cache")
            if os.path.exists(cache_dir):
                for arquivo in os.listdir(cache_dir):
                    try:
                        os.remove(os.path.join(cache_dir, arquivo))
                        arquivos_removidos += 1
                    except:
                        pass
            
            # Limpar session state
            for key in list(st.session_state.keys()):
                del st.session_state[key]
            
            st.success(f"🔄 Reset completo! {arquivos_removidos} arquivos removidos")
            st.rerun()
    
    # Informações de otimização
    st.subheader("⚡ Sistema de Auto-Limpeza")
    st.write("🕐 **Limpeza automática a cada 24h**")
    st.write("✅ Remove transcrições antigas")
    st.write("✅ Mantém apenas 2 modelos Whisper")
    st.write("✅ Limpa arquivos temporários")
    st.write("✅ Garbage collection automático")
    st.write("🔄 Reset manual disponível")
    
    # Dicas de performance
    st.subheader("💡 Sistema Sempre Limpo")
    st.write("🔄 **Auto-reset a cada 24h** - nunca fica pesado!")
    st.write("🗑️ **Arquivos antigos removidos** automaticamente")
    st.write("⚡ **Apenas modelos recentes** mantidos em cache")
    st.write("🧹 **Limpeza manual** quando necessário")
    st.write("📊 **Monitoramento** em tempo real")
    
    # Mostrar se houve limpeza inicial
    if hasattr(st.session_state, 'limpeza_inicial'):
        st.success(st.session_state.limpeza_inicial)
        del st.session_state.limpeza_inicial

# Footer
st.markdown("---")
st.markdown("🤖 **Desenvolvido com Whisper (OpenAI) + Streamlit**")
