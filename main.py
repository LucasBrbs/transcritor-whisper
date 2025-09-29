import whisper
import os
import subprocess
import sys
import time
import glob
from datetime import datetime, timedelta

def verificar_ffmpeg():
    """Verifica se o ffmpeg está disponível no sistema"""
    try:
        # Verificar primeiro no diretório local (bin/)
        local_ffmpeg = os.path.join(os.getcwd(), "bin", "ffmpeg")
        if os.path.exists(local_ffmpeg):
            subprocess.run([local_ffmpeg, '-version'], capture_output=True, check=True)
            return True
        
        # Verificar no sistema
        subprocess.run(['ffmpeg', '-version'], capture_output=True, check=True)
        return True
    except (subprocess.CalledProcessError, FileNotFoundError):
        return False

def limpar_sistema_24h():
    """Limpa arquivos e cache automaticamente a cada 24h"""
    arquivo_controle = os.path.join(os.getcwd(), ".ultima_limpeza")
    agora = datetime.now()
    
    # Verificar se precisa limpar
    precisa_limpar = True
    if os.path.exists(arquivo_controle):
        with open(arquivo_controle, "r") as f:
            ultima_limpeza_str = f.read().strip()
            try:
                ultima_limpeza = datetime.fromisoformat(ultima_limpeza_str)
                if agora - ultima_limpeza < timedelta(hours=24):
                    precisa_limpar = False
            except:
                pass
    
    if precisa_limpar:
        print("🧹 Executando limpeza automática de 24h...")
        
        # 1. Limpar arquivos de transcrição antigos
        arquivos_removidos = 0
        padroes = ["*_transcricao.txt", "*_legendas.srt"]
        for padrao in padroes:
            for arquivo in glob.glob(padrao):
                try:
                    os.remove(arquivo)
                    arquivos_removidos += 1
                except:
                    pass
        
        # 2. Limpar cache do Whisper (manter apenas base e tiny)
        cache_dir = os.path.join(os.getcwd(), "whisper_cache")
        if os.path.exists(cache_dir):
            modelos_manter = ["base.pt", "tiny.pt"]
            for arquivo in os.listdir(cache_dir):
                if arquivo.endswith('.pt') and arquivo not in modelos_manter:
                    try:
                        os.remove(os.path.join(cache_dir, arquivo))
                        arquivos_removidos += 1
                    except:
                        pass
        
        # 3. Limpar arquivos temporários
        temp_patterns = ["/tmp/tmp*", "/tmp/whisper*"]
        for pattern in temp_patterns:
            for arquivo in glob.glob(pattern):
                try:
                    if os.path.isfile(arquivo):
                        os.remove(arquivo)
                        arquivos_removidos += 1
                except:
                    pass
        
        # Salvar timestamp da limpeza
        with open(arquivo_controle, "w") as f:
            f.write(agora.isoformat())
        
        if arquivos_removidos > 0:
            print(f"✅ Limpeza concluída! {arquivos_removidos} arquivos removidos.")
        else:
            print("✅ Sistema já estava limpo!")
    
    return precisa_limpar

def configurar_ffmpeg():
    """Configura o ffmpeg local se não estiver disponível no sistema"""
    print("⚙️ Configurando ffmpeg...")
    
    # Verificar se já temos o binário local
    local_ffmpeg = os.path.join(os.getcwd(), "bin", "ffmpeg")
    if os.path.exists(local_ffmpeg):
        print("✅ FFmpeg local já configurado!")
        # Adicionar ao PATH para esta sessão
        bin_dir = os.path.join(os.getcwd(), "bin")
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
        return True
    
    print("💡 FFmpeg não encontrado. Use o binário já baixado na pasta 'bin/'")
    print("   ou instale manualmente com: brew install ffmpeg")
    return False

def gerar_srt(resultado, nome_arquivo):
    """
    Gera arquivo SRT (legendas) a partir do resultado da transcrição
    
    Args:
        resultado (dict): Resultado da transcrição do Whisper
        nome_arquivo (str): Nome base do arquivo (sem extensão)
    
    Returns:
        str: Caminho do arquivo SRT gerado
    """
    nome_srt = f"{nome_arquivo}.srt"
    
    with open(nome_srt, "w", encoding="utf-8") as f:
        for i, segmento in enumerate(resultado["segments"], 1):
            inicio = segmento["start"]
            fim = segmento["end"]
            texto = segmento["text"].strip()
            
            # Converter tempo para formato SRT (HH:MM:SS,mmm)
            inicio_srt = f"{int(inicio//3600):02d}:{int((inicio%3600)//60):02d}:{int(inicio%60):02d},{int((inicio%1)*1000):03d}"
            fim_srt = f"{int(fim//3600):02d}:{int((fim%3600)//60):02d}:{int(fim%60):02d},{int((fim%1)*1000):03d}"
            
            f.write(f"{i}\n")
            f.write(f"{inicio_srt} --> {fim_srt}\n")
            f.write(f"{texto}\n\n")
    
    return nome_srt

def transcrever_audio(caminho_audio, modelo="base", idioma="pt"):
    """
    Transcreve um arquivo de áudio usando o Whisper
    
    Args:
        caminho_audio (str): Caminho para o arquivo de áudio
        modelo (str): Modelo do Whisper a usar (tiny, base, small, medium, large)
        idioma (str): Código do idioma (pt para português, en para inglês, etc.)
    
    Returns:
        dict: Resultado da transcrição
    """
    
    # Configurar ffmpeg local se disponível
    bin_dir = os.path.join(os.getcwd(), "bin")
    if os.path.exists(bin_dir):
        os.environ["PATH"] = f"{bin_dir}:{os.environ.get('PATH', '')}"
    
    print(f"🤖 Carregando modelo Whisper '{modelo.upper()}'...")
    
    # Definir cache local para evitar problemas de permissão
    cache_dir = os.path.join(os.getcwd(), "whisper_cache")
    os.makedirs(cache_dir, exist_ok=True)
    os.environ["WHISPER_CACHE_DIR"] = cache_dir
    
    try:
        model = whisper.load_model(modelo, download_root=cache_dir)
        print(f"✅ Modelo '{modelo.upper()}' carregado com sucesso!")
        
        print(f"🎤 Transcrevendo arquivo: {os.path.basename(caminho_audio)}")
        resultado = model.transcribe(caminho_audio, language=idioma)
        
        return resultado
        
    except Exception as e:
        print(f"❌ Erro ao carregar modelo ou transcrever: {e}")
        raise
    
    return resultado

def main():
    print("=== Transcritor de Áudio com Whisper ===\n")
    
    # Executar limpeza automática de 24h
    limpar_sistema_24h()
    
    # Verificar se ffmpeg está disponível
    if not verificar_ffmpeg():
        print("⚠️  FFmpeg não encontrado no sistema.")
        resposta = input("Deseja tentar configurar automaticamente? (s/n): ").lower()
        
        if resposta == 's':
            if not configurar_ffmpeg():
                print("❌ Não foi possível configurar o ffmpeg automaticamente.")
                print("📖 Instruções manuais:")
                print("   1. Instale o Homebrew: /bin/bash -c \"$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)\"")
                print("   2. Execute: brew install ffmpeg")
                print("   3. Execute este script novamente")
                return
        else:
            print("❌ FFmpeg é necessário para processar arquivos de áudio.")
            return
    
    # Solicitar arquivo de áudio
    print("📁 Selecione o arquivo de áudio para transcrição:")
    print("   • Formatos suportados: MP3, WAV, M4A, FLAC, OGG, WMA")
    print("   • Coloque o arquivo na pasta do projeto ou use caminho completo\n")
    
    arquivo_audio = input("📂 Digite o nome/caminho do arquivo de áudio: ").strip()
    
    if not arquivo_audio:
        print("❌ Nenhum arquivo especificado.")
        print("\n💡 Como usar:")
        print("   1. Coloque um arquivo de áudio na pasta do projeto")
        print("   2. Execute novamente: python main.py")
        print("   3. Digite o nome do arquivo (ex: audio.mp3)")
        return
    
    if not os.path.exists(arquivo_audio):
        print(f"❌ Arquivo '{arquivo_audio}' não encontrado.")
        print("💡 Verifique se:")
        print("   • O nome do arquivo está correto")
        print("   • O arquivo está na pasta do projeto")
        print("   • Você digitou a extensão (.mp3, .wav, etc.)")
        return
    
    try:
        # Mostrar informações do arquivo
        tamanho_mb = os.path.getsize(arquivo_audio) / (1024 * 1024)
        print(f"\n📊 Arquivo selecionado: {os.path.basename(arquivo_audio)}")
        print(f"📏 Tamanho: {tamanho_mb:.1f} MB")
        
        # Escolher modelo
        print("\n🤖 Escolha o modelo Whisper:")
        print("   • tiny   - Rápido, precisão básica (~39MB)")
        print("   • base   - Balanceado, recomendado (~74MB)")
        print("   • small  - Boa precisão (~244MB)")
        print("   • medium - Excelente para áudio complexo (~769MB)")
        print("   • large  - Máxima precisão (~1550MB)")
        
        modelo = input("\n🎯 Digite o modelo [base]: ").strip().lower() or "base"
        
        if modelo not in ['tiny', 'base', 'small', 'medium', 'large']:
            print(f"⚠️  Modelo '{modelo}' inválido. Usando 'base'.")
            modelo = "base"
        
        print(f"\n🚀 Iniciando transcrição com modelo '{modelo.upper()}'...")
        print("⏳ Isso pode levar alguns minutos dependendo do tamanho do arquivo...\n")
        
        # Transcrever
        import time
        inicio_tempo = time.time()
        resultado = transcrever_audio(arquivo_audio, modelo=modelo)
        tempo_total = time.time() - inicio_tempo
        
        # Mostrar resultados
        print(f"\n🎉 Transcrição concluída em {tempo_total:.1f} segundos!")
        print("\n" + "="*60)
        print("📝 TRANSCRIÇÃO COMPLETA:")
        print("="*60)
        print(resultado["text"])
        
        print("\n" + "="*60)
        print("⏰ TRANSCRIÇÃO POR SEGMENTOS:")
        print("="*60)
        
        for i, segmento in enumerate(resultado["segments"], 1):
            inicio = int(segmento["start"])
            fim = int(segmento["end"])
            texto = segmento["text"].strip()
            print(f"{i:2d}. [{inicio//60:02d}:{inicio%60:02d} - {fim//60:02d}:{fim%60:02d}] {texto}")
        
        # Salvar transcrições em arquivos TXT e SRT
        nome_base = os.path.splitext(arquivo_audio)[0]
        nome_txt = f"{nome_base}_transcricao.txt"
        
        # Salvar arquivo TXT
        with open(nome_txt, "w", encoding="utf-8") as f:
            f.write(f"Transcrição de: {os.path.basename(arquivo_audio)}\n")
            f.write(f"Modelo usado: {modelo.upper()}\n")
            f.write(f"Idioma detectado: {resultado.get('language', 'N/A')}\n")
            f.write(f"Tempo de processamento: {tempo_total:.1f}s\n")
            f.write("-" * 50 + "\n\n")
            f.write(resultado["text"])
        
        # Salvar arquivo SRT (legendas)
        nome_srt = gerar_srt(resultado, f"{nome_base}_legendas")
        
        print(f"\n✅ Arquivos salvos:")
        print(f"   📄 Transcrição TXT: {nome_txt}")
        print(f"   🎬 Legendas SRT: {nome_srt}")
        print(f"📊 Estatísticas: {len(resultado['segments'])} segmentos, {len(resultado['text'].split())} palavras")
        
    except KeyboardInterrupt:
        print("\n⚠️ Processo interrompido pelo usuário.")
    except Exception as e:
        print(f"\n❌ Erro durante a transcrição: {e}")
        print("💡 Dicas:")
        print("   • Verifique se o arquivo não está corrompido")
        print("   • Tente usar um modelo menor (tiny/base)")
        print("   • Certifique-se de que há espaço suficiente em disco")

if __name__ == "__main__":
    main()