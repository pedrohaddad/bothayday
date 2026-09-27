# HayDayBot — automação de Hay Day para Windows (MEmu / MuMu)

Bot com interface gráfica que controla o Hay Day rodando em um emulador Android via **ADB**
e reconhece a tela por **template matching (OpenCV)**. Ele planta trigo, espera crescer, colhe,
coloca à venda na banca, cria anúncios e recolhe o dinheiro, em ciclo contínuo.

> 📘 **Primeira vez? Siga o [GUIA_PASSO_A_PASSO.md](GUIA_PASSO_A_PASSO.md)**: o que fazer e onde fazer, do download até o bot rodando.

> ⚠️ **Aviso:** automatizar o Hay Day viola os Termos de Serviço da Supercell e pode levar ao
> banimento da conta. Use por sua conta e risco, de preferência em uma conta secundária.

---

## Sumário
1. [Como funciona](#1-como-funciona)
2. [Instalação (passo a passo)](#2-instalação-passo-a-passo)
3. [Configurar o emulador](#3-configurar-o-emulador)
4. [Preparar o jogo](#4-preparar-o-jogo)
5. [Criar os templates (OBRIGATÓRIO)](#5-criar-os-templates-obrigatório)
6. [Usar a interface](#6-usar-a-interface)
7. [Configurações (config.json)](#7-configurações-configjson)
8. [Segurança e tratamento de erros](#8-segurança-e-tratamento-de-erros)
9. [Gerar o executável (HayDayBot.exe)](#9-gerar-o-executável-haydaybotexe)
10. [Limitações conhecidas](#10-limitações-conhecidas)
11. [Solução de problemas](#11-solução-de-problemas)
12. [Estrutura do projeto](#12-estrutura-do-projeto)

---

## 1. Como funciona

O bot é uma **máquina de estados**:

```
IDLE → CONNECTING → OPEN_GAME → CHECK_FIELD ─┬─► HARVEST ─► SELL ─► ADVERTISE ─► COLLECT_MONEY ─► CHECK_FIELD ...
                                             ├─► PLANT ─► WAIT_GROWTH ─► HARVEST
                                             └─► WAIT_GROWTH
                         (qualquer falha repetida) ─► RECOVER ─► CHECK_FIELD / OPEN_GAME / CONNECTING
```

| Estado | O que faz |
|---|---|
| **CONNECTING** | Verifica o adb, lista dispositivos, faz `adb connect` se preciso, abre o emulador se não houver nenhum (opcional), espera o Android iniciar e testa um screenshot. O ID do dispositivo **não é fixo**: se o configurado não existir, usa o primeiro online. |
| **OPEN_GAME** | Confere se o Hay Day está instalado e em primeiro plano; abre o jogo e espera a fazenda aparecer (fechando avisos de carregamento/reconexão). |
| **CHECK_FIELD** | Garante que está na fazenda e conta campos vazios / prontos / crescendo. |
| **PLANT** | Toca num campo vazio, localiza o ícone do trigo e **arrasta** sobre todos os campos vazios. Confirma na tela quantos foram plantados. |
| **WAIT_GROWTH** | Verifica a cada `check_interval` s se o trigo ficou pronto (não fica parado às cegas). Aproveita a espera para recolher vendas. |
| **HARVEST** | Toca num campo pronto, pega a foice e arrasta sobre os prontos. Confirma visualmente a colheita e não insiste em campos que não responderam. |
| **SELL** | Abre a banca, coleta vendas, encontra caixote vazio, escolhe o trigo, quantidade, preço, marca "anunciar" (se disponível) e coloca à venda. |
| **ADVERTISE** | Se o anúncio não foi feito na venda, tenta anunciar um caixote já à venda. Se estiver em cooldown, segue em frente. |
| **COLLECT_MONEY** | Abre a banca, toca apenas nos caixotes **reconhecidos** como vendidos e volta à fazenda. |
| **RECOVER** | Estado seguro: fecha janelas conhecidas, aperta VOLTAR, reabre/reinicia o jogo ou reconecta o ADB. |

Antes de **toda** ação o bot tira um screenshot, procura o elemento e só toca no centro dele se
ele foi encontrado. Não há cliques em coordenadas fixas do jogo.

---

## 2. Instalação (passo a passo)

1. **Baixe o projeto** (botão *Code → Download ZIP* no GitHub) e extraia, ex.: `C:\HayDayBot`.
2. **Instale o Python 3.10 ou superior**: <https://www.python.org/downloads/> — marque
   **“Add python.exe to PATH”**.
3. **Instale as dependências**: dê dois cliques em **`install.bat`** (cria `.venv` e instala
   `opencv-python-headless`, `numpy`, `Pillow`, `keyboard`).
4. **Abra o MEmu** (ou MuMu) e **abra o Hay Day** até a fazenda aparecer.
5. **Execute o bot**: dois cliques em **`run.bat`** (ou `python main.py`).
6. Na aba **Conexão**, informe o **caminho do adb.exe**, clique em **CONECTAR** e depois em
   **TESTAR ADB**. O indicador fica 🟢 *Conectado*.
7. Crie os templates (seção 5), ajuste as configurações e clique em **INICIAR BOT**.

> Alternativa sem Python: gere o `HayDayBot.exe` com `build.bat` (seção 9) e distribua a pasta `dist\`.

---

## 3. Configurar o emulador

### MEmu
- **adb.exe:** `C:\Program Files\Microvirt\MEmu\adb.exe`
- **Executável:** `C:\Program Files\Microvirt\MEmu\MEmu.exe`
- **Dispositivo:** `127.0.0.1:21503` (2ª instância `21513`, 3ª `21523`…)
- Em *Configurações do MEmu → Exibição*: **Tablet 1280x720, DPI 240** (recomendado).

### MuMu Player 12
- **adb.exe:** `C:\Program Files\Netease\MuMuPlayer-12.0\shell\adb.exe`
  (em versões novas pode estar em `...\nx_main\adb.exe`)
- **Dispositivo:** `127.0.0.1:16384` (2ª instância `16416`, …). Ative o ADB nas configurações do MuMu se necessário.
- Resolução **1280x720**, DPI 240.

### MuMu 6 / MuMu X
- **Dispositivo:** `127.0.0.1:7555`.

**Dicas importantes**
- Use **sempre o adb.exe do próprio emulador**. Dois adb de versões diferentes derrubam o
  servidor um do outro (“adb server version doesn't match”).
- O botão **Procurar emuladores** tenta `adb connect` em todas as portas conhecidas.
- Se o campo *Dispositivo* ficar vazio, o bot usa o primeiro dispositivo online.
- O campo *Argumentos do emulador* é opcional (ex.: `MEmu_1` para abrir uma instância específica
  com `MEmu.exe MEmu_1`).

---

## 4. Preparar o jogo

O reconhecimento só enxerga o que está **na tela**. Antes de iniciar:

1. Afaste o zoom (pinça) e posicione a câmera para que **todos os campos de trigo e a banca
   (Roadside Shop)** fiquem visíveis ao mesmo tempo, sem janelas abertas.
2. Mantenha os campos **agrupados** (ex.: 3x3). O bot arrasta a semente/foice por eles numa
   linha em zigue-zague.
3. Não mova a câmera enquanto o bot roda (os templates encontram os campos em qualquer posição,
   mas campos fora da tela não existem para o bot).
4. Tenha trigo no silo para replantar (o Hay Day oferece comprar com diamantes quando falta —
   **o bot nunca toca em botões de compra**; ele fecha a janela).

---

## 5. Criar os templates (OBRIGATÓRIO)

Os templates são recortes **.png** de screenshots do **seu** emulador. Eles não vêm prontos
porque dependem da resolução, do idioma e da versão do jogo.

### Fluxo recomendado (tudo pela interface)
1. Deixe o jogo na tela desejada (ex.: fazenda com campos vazios).
2. Clique em **CAPTURAR TELA** → salva em `screenshots/`.
3. Aba **Templates → Recortar template…** → escolha a **categoria**, arraste o mouse sobre o
   elemento e clique em **Salvar recorte** (salva em `templates/<categoria>/`).
4. Aba **Templates → Testar detecção…** → escolha a categoria e clique em **Testar**. Deve
   aparecer um retângulo em cada elemento. A janela mostra a **maior pontuação** para ajudar a
   escolher o limiar.
5. Repita para cada pasta. Você também pode copiar/substituir `.png` direto nas pastas: o bot
   recarrega automaticamente (não precisa reiniciar).

### O que colocar em cada pasta

| Pasta | Tipo | Screenshot / o que recortar |
|---|---|---|
| `farm/` | **OBRIGATÓRIO** | Fazenda sem janelas abertas. Recorte um **ícone fixo do HUD** que só existe na fazenda, ex.: engrenagem de configurações ou botão da loja/caminhão no canto. **Não** use números (moedas/XP). |
| `wheat_empty/` | **OBRIGATÓRIO** | Campo **vazio** (terra arada marrom). Recorte só o **miolo** da terra (~60×40 px), sem bordas de grama. |
| `wheat_ready/` | **OBRIGATÓRIO** | Campo com **trigo maduro dourado**. Recorte o miolo do trigo. |
| `wheat_growing/` | opcional | Campo com **brotos verdes** (só para contar campos). |
| `seed_wheat/` | **OBRIGATÓRIO** | Toque num campo vazio → aparece o menu com sementes. Recorte o **ícone do trigo** desse menu. |
| `sickle/` | **OBRIGATÓRIO** | Toque num campo pronto → recorte o **ícone da foice**. |
| `back/` | **OBRIGATÓRIO** | Botões de **fechar (X vermelho)** das janelas. Coloque várias variações. |
| `shop/` | p/ vender/coletar | A **banca de beira de estrada** vista na fazenda (telhado/placa). |
| `shop_screen/` | recomendado | Banca aberta: recorte o **título/faixa** da janela da banca. |
| `shop_empty_slot/` | p/ vender | Banca aberta: um **caixote vazio**. |
| `collect/` | p/ coletar | Banca aberta: um **caixote vendido** (com moedas). |
| `shop_on_sale/` | opcional | Banca aberta: caixote com produto **à venda** (não vendido). |
| `sell_item_wheat/` | p/ vender | Toque num caixote vazio → janela de venda: recorte o **ícone do trigo** na lista de itens. |
| `silo_tab/` | opcional | Aba do **silo** na janela de venda, se o trigo não aparecer direto. |
| `sell/` | p/ vender | Botão **“Colocar à venda”** da janela de venda. |
| `qty_plus/`, `qty_minus/` | opcional | Botões **+ / −** da quantidade. |
| `price_max/` | opcional | Botão de **preço máximo** (seta). |
| `price_plus/`, `price_minus/` | opcional | Botões **+ / −** do preço. |
| `advertise/` | opcional | A opção **“Anunciar”** disponível (caixinha desmarcada) na janela de venda **e/ou** o botão **“Criar anúncio”** que aparece ao tocar num caixote à venda. |
| `advertise_cooldown/` | opcional | A opção de anúncio **em espera** (com relógio). |
| `confirm/` | opcional | Botões **OK/Sim** que aparecem depois de criar um anúncio. **Nunca** recorte botões que gastam diamantes. |
| `continue/` | opcional | Botões inofensivos: “Continuar”, OK de subir de nível etc. |
| `silo_full/` | opcional | Aviso de **silo cheio** (o bot vai vender imediatamente). |
| `reconnect/` | opcional | Botão **“Tentar novamente/Recarregar”** da tela de conexão perdida. |

Cada pasta tem um `LEIA-ME.txt` com a mesma explicação.

### Como o reconhecimento lida com o jogo real

Entre dois screenshots do Hay Day muita coisa muda mesmo sem mexer em nada, e o
`TM_CCOEFF_NORMED` puro derrubava a pontuação de um template perfeito para 0,5–0,75:

| O que muda no jogo | Efeito no matching puro | Como o detector trata |
|---|---|---|
| **Zoom da câmera** (o jogo redefine ao abrir; a pinça muda) | campos/banca/casa ficam 10–25% maiores ou menores → 0,50–0,78 | **Calibração automática de zoom**: mede a escala da cena (0,6x–1,6x) combinando todos os elementos do mundo visíveis (texturas repetitivas como o solo sozinhas enganam) e aplica a todos eles. Roda ao encontrar a fazenda pela 1ª vez e quando campos/fazenda somem. Botões/menus (UI) não mudam com o zoom. |
| **Posição da câmera em subpixel** (reamostragem bilinear) | texturas finas (sulcos, trigo) → 0,74–0,93 | Tela e template são **suavizados** (`match_blur`) antes da comparação. |
| **Animação** (o trigo balança com o vento) | 0,57–0,77 com um único recorte | Suavização + **vários quadros da animação** na mesma pasta (o *Recortar template* captura sozinho). |
| **Janela aberta por cima** (a fazenda fica escurecida) | CCOEFF ignora brilho → a fazenda era "encontrada" com popup aberto | **Verificação de cor/brilho** (`color_tolerance`) de cada candidato. |

Resultado nos testes (`tests/test_detection.py`): elementos reais ≥ 0,82–0,99 em todos esses
casos e regiões erradas ≤ ~0,5, então o **limiar 0,80 continua valendo** (não é preciso baixá-lo).

Na aba *Templates → Testar detecção* (usa exatamente o mesmo detector do bot) a mensagem
explica o resultado: melhor pontuação, escala testada, se algo foi rejeitado por cor/brilho
e qual zoom faria o elemento aparecer. O botão **Calibrar zoom** aplica a calibração.

### Dicas para templates que funcionam
- Recorte **na mesma resolução** configurada em `template_resolution` (padrão `1280x720`).
  Se o emulador tiver outra resolução, o bot escala os templates automaticamente, mas a precisão cai.
- Recortes **pequenos e característicos** funcionam melhor que grandes. Evite incluir fundo
  que muda (grama, animais, sombras, números).
- Coloque **várias imagens** na mesma pasta para variações (dia/noite, selecionado/não selecionado).
- **Elementos animados** (`wheat_ready`, `wheat_growing`): no *Recortar template* deixe
  "Quadros extras da animação" em 5 (já vem assim para essas pastas; são capturados ao longo de ~4 s para cobrir um ciclo inteiro do balanço). Ele captura mais telas e
  salva o mesmo retângulo como `nome_q1.png`, `nome_q2.png`… Não mexa na câmera enquanto isso.
- Para `farm`, prefira um **ícone fixo do HUD** (não muda com o zoom). Uma construção também
  funciona, graças à calibração de zoom, mas é menos estável.
- Depois de salvar, o recortador faz um **autoteste** na própria imagem (deve dar ~1,00 ✔).
- PNG com **transparência**: as áreas transparentes são ignoradas na comparação.
- **Limiar** (`match_threshold`, padrão 0.80): se o elemento não é encontrado, baixe (0.70–0.75);
  se aparecem falsos positivos, suba. Use `thresholds` para ajustar por pasta, ex.:
  `{"wheat_ready": 0.75, "back": 0.85}`.
- `wheat_empty` **não pode** casar com campos plantados/crescendo — teste com um screenshot
  que tenha os dois tipos.

---

## 6. Usar a interface

**Status:** 🟢 Conectado · 🟡 Executando · 🔴 Erro · ⚪ Parado

**Botões**
| Botão | Ação |
|---|---|
| **CONECTAR** | Inicia o servidor adb, conecta ao dispositivo (ou procura emuladores), seleciona o dispositivo e testa um screenshot. |
| **INICIAR BOT** | Salva as configurações e inicia o ciclo. Avisa se faltarem templates obrigatórios. |
| **PARAR BOT** | Parada imediata (também **F8**, mesmo com o emulador em foco). |
| **TESTAR ADB** | Versão do adb, lista de dispositivos, resolução, **toque de teste** (no ponto `test_tap_point`, padrão canto superior esquerdo), screenshot, app em primeiro plano e suporte a arrasto contínuo. |
| **CAPTURAR TELA** | Salva um screenshot em `screenshots/` para criar templates. |
| **ABRIR TEMPLATES** | Abre a pasta `templates/` no Explorer. |

**Painel:** campos encontrados/plantados/colhidos, quantidade vendida, anúncios, dinheiro
coletado (nº de vendas recolhidas + estimativa de moedas), tempo de execução, estado atual,
trigo estimado, última ação, último erro e log ao vivo.

**Abas:** *Conexão* (adb, emulador, dispositivo, resolução, tempo entre ações), *Configurações*
(todas as opções do `config.json`), *Templates* (status de cada pasta, recortar e testar).

Exemplo de log:
```
[12:31:04] ADB conectado (127.0.0.1:21503, 1280x720)
[12:31:07] Hay Day encontrado
[12:31:10] Campos encontrados: 9 (vazios 9, prontos 0, crescendo 0)
[12:31:11] Plantando trigo
[12:31:16] 9 campos plantados
[12:33:20] Trigo pronto (9 campos)
[12:33:21] Colhendo
[12:33:25] 9 campos colhidos
[12:33:30] Abrindo loja
[12:33:34] Produto colocado à venda (10x trigo)
[12:33:38] Anúncio realizado
```
Os logs completos ficam em `logs/haydaybot_AAAAMMDD.log`.

---

## 7. Configurações (config.json)

Tudo pode ser alterado pela interface (aba *Configurações*). Principais chaves:

| Chave | Padrão | Descrição |
|---|---|---|
| `adb_path` | MEmu | Caminho do `adb.exe`. |
| `emulator_path` / `emulator_args` | MEmu | Executável do emulador (aberto automaticamente se nenhum dispositivo estiver online). |
| `device` | `""` | Endereço/ID ADB. Vazio = primeiro online. |
| `resolution` / `template_resolution` | `1280x720` | Resolução esperada e resolução em que os templates foram recortados. |
| `crop` | `wheat` | Cultura (atualmente trigo). |
| `growth_time` | 120 | Tempo de crescimento do trigo (s). |
| `max_wait_growth` | 900 | Espera máxima antes de reavaliar os campos. |
| `initial_wheat_stock` | 20 | Quanto trigo há no silo ao iniciar (estimativa). |
| `keep_reserve` | 20 | Trigo que **nunca** é vendido (para replantar). Deve ser ≥ nº de campos. |
| `sell_enabled` | true | Vender na banca. |
| `min_sell_qty` / `max_sell_qty` | 10 / 10 | Quantidade mínima para criar uma venda / máxima por caixote. |
| `sell_qty_start` | 1 | Quantidade que a janela mostra ao abrir (para calcular os cliques no +). |
| `price_mode` | `max` | `default` (preço sugerido), `max` (botão preço máximo), `plus`/`minus` (N cliques). |
| `price_clicks` | 0 | Cliques em +/− preço nos modos `plus`/`minus`. |
| `max_listings_per_cycle` | 2 | Caixotes colocados à venda por ciclo. |
| `advertise_enabled` / `advertise_interval` | true / 300 | Anunciar e intervalo mínimo entre anúncios (s). |
| `collect_money_enabled` / `collect_interval` | true / 120 | Recolher vendas e intervalo entre verificações (s). |
| `coins_per_sale_estimate` | 0 | Só para a estatística “dinheiro coletado”. |
| `check_interval` | 5 | Intervalo de verificação (s). |
| `action_delay` | 0.5 | Tempo entre ações (s). |
| `max_retries` | 3 | Tentativas por etapa antes de ir ao estado seguro. |
| `step_timeout` | 120 | Timeout de cada etapa (s). |
| `max_recoveries` | 6 | Recuperações seguidas sem progresso antes de parar com erro. |
| `restart_game_after_failures` | 3 | Falhas de recuperação antes de reiniciar o Hay Day. |
| `freeze_timeout` | 180 | Tela idêntica por mais que isso = emulador travado → reinicia o jogo (0 desliga). |
| `max_same_spot_taps` | 6 | Máximo de toques no mesmo ponto em 60 s (anti-loop). |
| `action_retries` | 2 | Passagens extras de plantio/colheita para as plantações que não mudaram na tela. |
| `confirm_timeout` | 2.5 | Tempo máximo esperando o jogo responder a um clique (ex.: o menu abrir). |
| `tap_hold_ms` / `retry_tap_hold_ms` | 0 / 90 | Duração do toque normal / da nova tentativa quando o clique não foi confirmado. |
| `screenshot_on_error` | true | Salva screenshot em `screenshots/errors/` a cada erro. |
| `hotkey` | `F8` | Tecla de parada de emergência. |
| `match_threshold` / `thresholds` / `scales` | 0.80 / {} / [1.0] | Reconhecimento de imagem. |
| `match_blur` | 2.0 | Suavização antes do matching (tolera animação e subpixel). Proporcional à resolução (vale para 640 px de largura). 0 desliga. |
| `color_tolerance` | 30 | Diferença máxima de cor média (0–255) entre template e candidato. Rejeita a fazenda escurecida atrás de janelas. |
| `auto_zoom` / `zoom_range` | true / [0.6, 1.6] | Calibração automática do zoom da câmera para campos, trigo, banca e `farm`. |
| `drag_mode` | `auto` | `motionevent` (arrasto contínuo por todos os campos), `swipe` (campo a campo) ou `auto`. |
| `drag_hold`, `drag_step_px`, `swipe_duration_ms` | 0.25 / 40 / 400 | Ajuste fino do arrasto. |

---

## 8. Segurança e tratamento de erros

- **START / STOP / F8**: a parada mata na hora o comando adb em andamento e solta um toque
  pendente. A tecla F8 é global (biblioteca `keyboard`); se ela não puder ser registrada, F8
  funciona com a janela do bot em foco e o log avisa.
- **Limite de tentativas** por etapa, **timeout** por etapa, e limite global de falhas seguidas.
- **Anti-loop:** nenhum ponto pode ser tocado mais de `max_same_spot_taps` vezes em 60 s; trigos
  que não respondem à colheita ficam em espera por 3 minutos (não para sempre) enquanto o bot
  continua plantando; caixotes que não coletam não são repetidos.
- **Ações confirmadas na tela:** um clique só conta como feito quando o jogo responde (ex.: o menu
  da semente/foice abre). Depois de cada arrasto o bot confere plantação por plantação e repete
  só as que não mudaram, em posições recalculadas (`action_retries` passagens extras).
- **Nunca toca sem ter encontrado o template.** Se um botão não é encontrado, o bot espera,
  tenta voltar ou vai para o estado seguro.
- **Nunca toca em botões de compra/diamantes**: em telas inesperadas só usa `reconnect`,
  `continue`, `back` e a tecla VOLTAR do Android.
- **Screenshot automático** em `screenshots/errors/` e **log** de todas as ações.

Como cada situação é tratada:

| Situação | Comportamento |
|---|---|
| ADB desconectado / conexão perdida | Erro ADB → estado CONNECTING: reconecta (`adb connect`/busca de portas), abre o emulador se configurado; se não conseguir após `max_retries`, para com 🔴 Erro. |
| Emulador travado | Timeout em comandos adb → reconexão; tela idêntica por `freeze_timeout` → reinicia o Hay Day. |
| Jogo fechado / outro app na frente | Detectado pelo app em primeiro plano → OPEN_GAME reabre o jogo. |
| Jogo não instalado | Erro fatal com mensagem clara. |
| Tela errada / janela inesperada | Fecha avisos conhecidos, aperta VOLTAR; se não voltar à fazenda → RECOVER → reinicia o jogo após `restart_game_after_failures`. |
| Botão/template não encontrado | Não clica; espera, tenta de novo (`max_retries`) e vai para o estado seguro. |
| Pasta de template vazia | Aviso único no log; recursos opcionais são pulados, obrigatórios levam a erro (sem cliques às cegas). |
| Trigo ainda não pronto | WAIT_GROWTH verifica periodicamente até `max_wait_growth`. |
| Loja cheia | Log “Loja cheia”, venda adiada, ciclo continua. |
| Sem trigo suficiente | Respeita `keep_reserve`/`min_sell_qty`; se o trigo não aparece na janela de venda, fecha e segue. |
| Silo cheio (template `silo_full`) | Fecha o aviso e vai vender. |
| Anúncio indisponível / em cooldown | Log e continua as outras tarefas; tenta de novo depois. |
| Venda ainda não concluída | “Nenhuma venda concluída ainda” e volta à fazenda. |
| Muitas recuperações sem progresso | Para com 🔴 Erro (evita rodar para sempre em estado ruim). |

---

## 9. Gerar o executável (HayDayBot.exe)

Dê dois cliques em **`build.bat`**. Ele instala o PyInstaller e gera:

```
dist\
  HayDayBot.exe
  config.json
  templates\      (suas pastas de templates)
  screenshots\
  logs\
```

Distribua a **pasta `dist` inteira**: `config.json`, `templates`, `screenshots` e `logs` ficam
ao lado do `.exe` e continuam editáveis. (Antivírus às vezes desconfiam de executáveis do
PyInstaller e da biblioteca de teclado global; adicione uma exceção se necessário.)

---

## 10. Limitações conhecidas

- **Templates são obrigatórios**: o bot não vem com imagens do jogo (dependem da sua resolução,
  idioma e versão). Siga a seção 5.
- **Preço exato**: ler o número do preço exigiria OCR. O bot oferece `default`, `max` (botão de
  preço máximo) ou N cliques em +/−.
- **Estoque de trigo** é **estimado** (colhido × 2 − plantado − vendido). Ajuste
  `initial_wheat_stock` ao iniciar. Se o trigo não aparece na janela de venda, o bot entende
  que acabou.
- **Câmera**: o bot não move a câmera; campos e banca precisam estar visíveis.
- `input motionevent` (arrasto contínuo) existe no Android 7+ do MEmu/MuMu. Em versões sem
  suporte o bot usa `swipe` campo a campo (mais lento, mas funciona).

---

## 11. Solução de problemas

| Problema | Solução |
|---|---|
| “adb não encontrado” | Confira o caminho do `adb.exe` na aba Conexão. |
| Nenhum dispositivo | Abra o emulador, clique em **Procurar emuladores** ou digite `127.0.0.1:21503` e clique **adb connect**. |
| “adb server version doesn't match” | Feche outros programas com adb (Android Studio, outro emulador) e use o adb do próprio emulador. |
| Dispositivo `unauthorized`/`offline` | Reinicie o emulador; em MuMu ative o ADB nas configurações. |
| Campos/fazenda não encontrados | Use **Testar detecção** com um screenshot atual e leia a mensagem: se indicar outro zoom, clique **Calibrar zoom**; se indicar rejeição por cor/brilho, há uma janela aberta. O log do `OPEN_GAME` mostra o mesmo diagnóstico. |
| Trigo pronto oscila entre achado/não achado | Recorte de novo com 5 quadros extras da animação. |
| Planta/colhe só alguns campos | Aumente `drag_hold`, reduza `drag_step_px` ou use `drag_mode = swipe`. |
| Clica em coisa errada | Suba o limiar da pasta em `thresholds` ou recorte uma área mais característica. |
| F8 não funciona com o emulador em foco | Execute o bot como administrador (a biblioteca `keyboard` pode precisar) ou use o botão PARAR. |
| Parou com erro | Veja o **Último erro**, o log em `logs/` e o screenshot em `screenshots/errors/`. |

---

## 12. Estrutura do projeto

```
HayDayBot/
├── main.py              # ponto de entrada (abre a interface)
├── gui.py               # interface Tkinter (painel, conexão, configurações, templates)
├── template_tools.py    # janelas "Recortar template" e "Testar detecção"
├── bot.py               # lógica do Hay Day (estados, plantar, colher, vender, anunciar, coletar)
├── state_machine.py     # máquina de estados: tentativas, timeouts, estado seguro
├── adb_controller.py    # ADB: dispositivos, conexão, toque, arrasto, screenshot, apps
├── screen.py            # captura/gravação de screenshots e detecção de tela congelada
├── image_detector.py    # template matching OpenCV + biblioteca de templates (recarga automática)
├── config.py            # leitura/validação/gravação do config.json
├── logger_setup.py      # logs em arquivo + painel
├── config.json
├── requirements.txt
├── install.bat          # cria .venv e instala dependências
├── run.bat              # abre o bot
├── build.bat            # gera dist\HayDayBot.exe
├── run_tests.bat        # roda os testes automatizados
├── templates/           # uma pasta por elemento do jogo (com LEIA-ME.txt)
├── screenshots/         # capturas (e errors/ para erros)
├── logs/
└── tests/               # testes + simulador de Hay Day (fake_game.py)
```

### Testes
`run_tests.bat` (ou `python -m pytest -q tests`) executa testes do detector, da máquina de
estados e do **ciclo completo contra um Hay Day simulado** (plantar → colher → vender →
anunciar → coletar), incluindo janela inesperada, jogo fechado, conexão perdida, loja cheia,
template ausente (tem que parar com erro, sem cliques infinitos) e parada imediata.
