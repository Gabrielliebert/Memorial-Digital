# Sistema de Memorial Digital 🎓✨

Gerador automatizado de memoriais digitais acadêmicos a partir de currículos Lattes usando IA Generativa (Google Gemini API).

Este sistema visa extrair as rotinas e a história de um pesquisador brasileiro e transformá-la automaticamente num texto altamente biográfico, memorial e narrativo na primeira pessoa. Especialmente arquitetado como projeto do PIBIC 2025/2026.

## 🚀 Arquitetura e Fluxo

O sistema foi estruturado em isoladas camadas de pipeline em um sistema não-bloqueante via Threads:
1. **Scraping (`modules/scraper.py`)**: Utiliza o poder do Playwright de forma visual (permitindo que usuário interaja ativamente com o reCAPTCHA da plataforma Lattes) acessando os dados com confiabilidade.
2. **Parsing (`modules/parser.py`)**: Valida o HTML cru usando `BeautifulSoup4` para seccionar a taxonomia estrutural de um Lattes, criando o JSON do usuário independentemente de falhas menores da árvore do portal CNPq.
3. **Gerador (Gemini) (`modules/generator.py`)**: Envia um prompt rigoroso para os modelos de fronteira do Google, extraindo o texto de natureza textual-memorial. 

## 🛡️ Destaques do Projeto 

* **Anti-Alucinação Inteligente:** Foi implementada uma forte diretriz no System Prompt proibindo explicitamente o modelo de inferir datas e produções falsas. E também, valida-se o retorno iterando pelos anos relatados para auditar as criações via `_validar_resultado()`!
* **High-Context Processing Window:** Com atualizações da janela de contexto para +1M de tokens, os limites truncados foram ajustados no `config.py` permitindo memoriais profundos e riquíssimos.
* **Resiliência e Fallback Embutidos (`generator.py`)**: Caso a API retorne restrições de requisições `429` (Rate limits) ou overload `503`, há Retry e Backoff Exponencial antes de repassar a inferência a um modelo mais leve da Família Flash ou Flash-Lite de modo imperceptível. 
* **WAL-mode (Write-Ahead Logging)**: A base em SQLite possibilita que threads múltiplas não gerem "Database Locked" ou causem latência durante o andamento da requisição HTTP.

## 📦 Como rodar

Instale os requerimentos:
```bash
pip install -r requirements.txt
playwright install
```

Configure o arquivo `.env` para apontar ao seu projeto de Google AI Studio:
```env
GEMINI_API_KEY="..."
```

E inicie o servidor:
```bash
python app.py
```

Você acessar a porta gerada localmente pelo servidor Flask!
Aproveite o pipeline modular com rastreabilidade nos Memoriais construídos!
