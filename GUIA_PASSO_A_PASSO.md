# HayDayBot — Guia passo a passo (do zero até o bot rodando)

Este guia diz **o que fazer** e **onde fazer**, na ordem certa. Siga as etapas uma de cada vez.
Cada etapa termina com um **✅ Confira**: só avance quando a conferência der certo.

> Onde cada coisa acontece:
> - 🪟 **Windows** (Explorer, navegador, instaladores)
> - 📱 **MEmu** (o emulador) e **Hay Day** (o jogo dentro dele)
> - 🤖 **HayDayBot** (a janela do bot, com as abas *Painel*, *Conexão*, *Configurações* e *Templates*)

---

## Sumário

- [Etapa 1 — Baixar o projeto](#etapa-1--baixar-o-projeto) 🪟
- [Etapa 2 — Instalar o Python](#etapa-2--instalar-o-python) 🪟
- [Etapa 3 — Instalar as dependências do bot](#etapa-3--instalar-as-dependências-do-bot) 🪟
- [Etapa 4 — Configurar o MEmu](#etapa-4--configurar-o-memu) 📱
- [Etapa 5 — Preparar a fazenda no Hay Day](#etapa-5--preparar-a-fazenda-no-hay-day) 📱
- [Etapa 6 — Abrir o bot e conectar ao MEmu](#etapa-6--abrir-o-bot-e-conectar-ao-memu) 🤖
- [Etapa 7 — Ajustar a resolução dos templates](#etapa-7--ajustar-a-resolução-dos-templates) 🤖
- [Etapa 8 — Criar os templates (a parte mais importante)](#etapa-8--criar-os-templates-a-parte-mais-importante) 📱 + 🤖
- [Etapa 9 — Testar a detecção](#etapa-9--testar-a-detecção) 🤖
- [Etapa 10 — Configurar plantio e venda](#etapa-10--configurar-plantio-e-venda) 🤖
- [Etapa 11 — Iniciar o bot](#etapa-11--iniciar-o-bot) 🤖
- [Etapa 12 — Acompanhar e parar](#etapa-12--acompanhar-e-parar) 🤖
- [Atualizar o bot sem perder seus templates](#atualizar-o-bot-sem-perder-seus-templates) 🪟
- [Gerar o HayDayBot.exe (opcional)](#gerar-o-haydaybotexe-opcional) 🪟
- [Problemas comuns e o que fazer](#problemas-comuns-e-o-que-fazer)
- [Como me pedir ajuda com informações úteis](#como-me-pedir-ajuda-com-informações-úteis)

---

## Etapa 1 — Baixar o projeto

**Onde:** 🪟 navegador.

1. Abra a página do repositório no GitHub: `github.com/pedrohaddad/bothayday`.
2. Logo acima da lista de arquivos, no seletor de branch, escolha
   **`claude/hay-day-automation-bot-74ov9f`**.
3. Clique no botão verde **`<> Code`** → **Download ZIP**.
4. No Explorer, clique com o botão direito no ZIP baixado → **Extrair tudo...**.
5. Extraia para uma pasta **sem acentos e sem espaços**, por exemplo:
   ```
   C:\HayDayBot
   ```
   Dentro dela devem aparecer arquivos como `main.py`, `install.bat`, `run.bat`, `README.md` e a pasta `templates`.

> Se o Windows extrair como `C:\HayDayBot\bothayday-claude-...\main.py`, mova o conteúdo de dentro
> da subpasta para `C:\HayDayBot`, para ficar `C:\HayDayBot\main.py`.

✅ **Confira:** existe o arquivo `C:\HayDayBot\install.bat`.

---

## Etapa 2 — Instalar o Python

**Onde:** 🪟 navegador + instalador.

1. Acesse <https://www.python.org/downloads/> e baixe o **Python 3.12** (ou qualquer 3.10+).
2. Execute o instalador.
3. **Na primeira tela, MARQUE a caixa “Add python.exe to PATH”** (fica embaixo). Isso é essencial.
4. Clique em **Install Now** e espere terminar.

✅ **Confira:** abra o menu Iniciar, digite `cmd`, abra o *Prompt de Comando* e digite:
```
python --version
```
Deve aparecer algo como `Python 3.12.x`. Se aparecer um erro ou abrir a Microsoft Store,
reinstale o Python marcando a caixa do PATH.

---

## Etapa 3 — Instalar as dependências do bot

**Onde:** 🪟 Explorer, na pasta `C:\HayDayBot`.

1. Dê **dois cliques em `install.bat`**.
2. Uma janela preta vai abrir e instalar tudo (OpenCV, NumPy, Pillow, keyboard). Leva de 1 a 5 minutos.
3. No final aparece: `Instalacao concluida. Execute run.bat para abrir o HayDayBot.` Aperte uma tecla para fechar.

> Se o Windows mostrar “O Windows protegeu o computador”, clique em **Mais informações → Executar assim mesmo**.

✅ **Confira:** apareceu a pasta `C:\HayDayBot\.venv`.

---

## Etapa 4 — Configurar o MEmu

**Onde:** 📱 MEmu.

1. Abra o **MEmu**.
2. Clique no ícone de **engrenagem (Configurações)**, na barra lateral direita do MEmu.
3. Aba **Exibição** (ou *Display*):
   - **Resolução:** escolha uma e **nunca mais mude** depois de criar os templates.
     - Recomendado: **Tablet 1280x720** com **DPI 240** (os elementos ficam maiores e a detecção é mais precisa).
     - Se você já criou templates em **640x480**, pode continuar com 640x480. Mas se mudar a
       resolução, terá que refazer os templates.
4. Clique em **Salvar** e reinicie o MEmu se ele pedir.
5. Anote onde o MEmu está instalado. O normal é:
   ```
   C:\Program Files\Microvirt\MEmu\
   ```
   Dentro dessa pasta existem o **`adb.exe`** e o **`MEmu.exe`**, que você vai usar na Etapa 6.

> Não precisa ativar root nem nada especial: o MEmu já deixa o ADB ligado na porta `127.0.0.1:21503`.

✅ **Confira:** o arquivo `C:\Program Files\Microvirt\MEmu\adb.exe` existe (veja pelo Explorer).

---

## Etapa 5 — Preparar a fazenda no Hay Day

**Onde:** 📱 Hay Day, dentro do MEmu.

O bot **só enxerga o que está na tela**. Ele não move a câmera.

1. Abra o **Hay Day** e espere a fazenda carregar.
2. Feche qualquer janela aberta (ofertas, avisos, pedidos).
3. **Posicione a câmera** (arraste com o mouse) e ajuste o zoom (roda do mouse ou pinça) de modo que
   **apareçam ao mesmo tempo, sem nada por cima**:
   - **todos os campos de trigo** que o bot vai usar;
   - a **banca de beira de estrada** (*Roadside Shop*), se quiser que o bot venda e colete dinheiro.
4. Deixe os campos **juntos**, de preferência em bloco (ex.: 3x3). Se estiverem espalhados, mova-os
   no modo de edição do jogo.
5. Garanta que há **trigo no silo** para replantar (pelo menos o número de campos).

> O zoom não precisa ser exatamente o mesmo toda vez: o bot descobre o zoom sozinho. Mas campos
> fora da tela não existem para ele.

✅ **Confira:** com um olhar você vê todos os campos e a banca, sem nenhuma janela aberta.

---

## Etapa 6 — Abrir o bot e conectar ao MEmu

**Onde:** 🪟 Explorer → 🤖 HayDayBot, aba **Conexão**.

1. Em `C:\HayDayBot`, dê **dois cliques em `run.bat`**. A janela **HayDayBot** abre.
2. Clique na aba **Conexão**.
3. Preencha:

   | Campo | O que colocar |
   |---|---|
   | **Caminho do adb.exe** | `C:\Program Files\Microvirt\MEmu\adb.exe` (use **Procurar...** para escolher) |
   | **Executável do emulador (MEmu/MuMu)** | `C:\Program Files\Microvirt\MEmu\MEmu.exe` |
   | **Argumentos do emulador (opcional)** | deixe vazio |
   | **Dispositivo ADB** | `127.0.0.1:21503` (ou deixe vazio para o bot achar sozinho) |
   | **Resolução do emulador** | a mesma da Etapa 4, ex.: `1280x720` ou `640x480` |
   | **Tempo entre ações (s)** | `0.5` (aumente para `0.8` se o PC for lento) |

4. Clique em **Salvar configurações**.
5. Clique no botão grande **CONECTAR** (no topo).
6. Depois clique em **TESTAR ADB**. Aparece uma janela com uma lista de ✔.

✅ **Confira:**
- a bolinha no topo fica **verde (Conectado)**;
- na aba Conexão aparece `Conexão: OK — 127.0.0.1:21503 (LARGURAxALTURA)`;
- no TESTAR ADB aparece `✔ Hay Day em primeiro plano`.

> Se não conectar: clique em **Procurar emuladores** (ao lado do campo Dispositivo) e depois em
> **CONECTAR** de novo. Veja também [Problemas comuns](#problemas-comuns-e-o-que-fazer).

---

## Etapa 7 — Ajustar a resolução dos templates

**Onde:** 🤖 aba **Configurações**, seção **Reconhecimento de imagem**.

1. Olhe o tamanho mostrado na conferência da Etapa 6 (ex.: `1280x720` ou `640x480`).
2. No campo **“Resolução em que os templates foram recortados”**, coloque **exatamente esse valor**.
3. Deixe os outros campos dessa seção como estão:
   - Limiar padrão: `0.8`
   - Escalas extras: `1.0`
   - Suavização: `2.0`
   - Tolerância de cor/brilho: `30`
   - Detectar o zoom da câmera automaticamente: **marcado**
   - Faixa de zoom: `0.6, 1.6`
4. Role até o fim e clique em **Salvar configurações**.

✅ **Confira:** a resolução do emulador (aba Conexão) e a “Resolução em que os templates foram
recortados” (aba Configurações) são iguais.

---

## Etapa 8 — Criar os templates (a parte mais importante)

Template = um **recorte pequeno** de um screenshot do jogo, que o bot usa para reconhecer aquele
elemento. Você vai criar cada um pela própria janela do bot.

### Como recortar (vale para todos)

**Onde:** 📱 Hay Day (deixar a tela certa) → 🤖 aba **Templates**.

1. 📱 No Hay Day, deixe aberta a **tela indicada na tabela abaixo**.
2. 🤖 No bot, clique em **CAPTURAR TELA** (botão do topo).
3. 🤖 Vá na aba **Templates** e clique em **Recortar template...**. Abre uma janela com o screenshot.
4. No topo dessa janela:
   - **Categoria:** escolha a pasta (ex.: `wheat_empty`). Embaixo aparece a explicação do que recortar.
   - **Nome:** pode deixar vazio (o bot dá um nome).
   - **Quadros extras da animação:** deixe como veio (**5** para `wheat_ready` e `wheat_growing`, **0** para o resto).
5. **Arraste o mouse** sobre o elemento para desenhar o retângulo verde. Embaixo aparece a prévia.
6. Clique em **Salvar recorte**.
   - Se houver quadros de animação, **não mexa em nada por ~5 segundos** enquanto o bot captura.
7. Leia a mensagem da janela: deve aparecer **`Autoteste nesta imagem: 0.9x ✔`**.
   - Se aparecer ✘, apague o arquivo (botão **Abrir pasta selecionada** na aba Templates) e recorte de novo.
8. Para o próximo template, deixe a nova tela no jogo e clique em **Capturar nova** na própria janela de recorte.

### Regras de ouro do recorte

- ✂️ **Pequeno e característico:** de 25 a 80 pixels. Nem o elemento inteiro com fundo, nem um pedacinho sem forma.
- 🚫 **Nada que muda:** números (moedas, XP, quantidades), animais, nuvens, sombras.
- 🟫 **Campos:** recorte o **miolo** do campo (a terra ou o trigo), sem a grama em volta.
- 🔘 **Botões:** recorte o botão inteiro com uma margem mínima.
- ➕ **Variações:** pode salvar mais de um recorte na mesma categoria (ex.: X de janelas diferentes).
- 💎 **Nunca** crie template de botões que gastam **diamantes**.

### Lista do que recortar, em ordem

Faça na ordem, pois ela segue as telas do jogo.

#### A) Tela: fazenda, sem nenhuma janela aberta

| Categoria | O que recortar | Obrigatório? |
|---|---|---|
| `farm` | Um **ícone fixo do HUD** que só aparece na fazenda (ex.: a engrenagem de configurações ou o ícone da loja/caminhão no canto). **Não** recorte o contador de moedas/XP. | ✅ Sim |
| `wheat_empty` | O **miolo de um campo vazio** (terra marrom arada). Colha/plante antes para ter um campo vazio na tela. | ✅ Sim |
| `wheat_ready` | O **miolo de um campo com trigo maduro** (dourado). Deixe **5 quadros extras**. | ✅ Sim |
| `wheat_growing` | O miolo de um campo com trigo **crescendo** (verde). Deixe 5 quadros extras. | Opcional |
| `shop` | A **banca de beira de estrada** vista na fazenda (o toldo/placa). | Para vender/coletar |

#### B) Tela: menu de sementes

📱 Toque **uma vez** num **campo vazio**. Aparece o menu com as sementes. Então capture.

| Categoria | O que recortar | Obrigatório? |
|---|---|---|
| `seed_wheat` | O **ícone do trigo** dentro desse menu. | ✅ Sim |

#### C) Tela: menu da foice

📱 Toque **uma vez** num **campo com trigo pronto**. Aparece a foice. Então capture.

| Categoria | O que recortar | Obrigatório? |
|---|---|---|
| `sickle` | O **ícone da foice**. | ✅ Sim |

#### D) Tela: banca aberta

📱 Toque na **banca**. Abre a janela com os caixotes. Então capture.

| Categoria | O que recortar | Obrigatório? |
|---|---|---|
| `back` | O **X vermelho de fechar** a janela. (Recorte também o X de outras janelas que aparecerem.) | ✅ Sim |
| `shop_screen` | O **título/faixa superior** da janela da banca. | Recomendado |
| `shop_empty_slot` | Um **caixote vazio** (espaço livre para vender). | Para vender |
| `collect` | Um **caixote vendido** (com moedas). *Só aparece depois de uma venda.* | Para coletar |
| `shop_on_sale` | Um caixote com produto **à venda** (ainda não vendido). | Opcional |

#### E) Tela: janela de venda

📱 Na banca, toque num **caixote vazio**. Abre a janela de venda. Então capture.

| Categoria | O que recortar | Obrigatório? |
|---|---|---|
| `sell_item_wheat` | O **ícone do trigo** na lista de itens (lado esquerdo). | Para vender |
| `sell` | O botão **“Colocar à venda”**. | Para vender |
| `qty_plus` / `qty_minus` | Os botões **+ / −** da quantidade. | Opcional |
| `price_max` | O botão de **preço máximo** (seta). | Opcional |
| `price_plus` / `price_minus` | Os botões **+ / −** do preço. | Opcional |
| `advertise` | A caixinha **“Anunciar”** desmarcada. | Para anunciar |
| `advertise_cooldown` | A opção de anúncio **esperando** (com relógio). | Opcional |
| `silo_tab` | A aba do **silo**, se o trigo não aparecer direto. | Opcional |

📱 Depois feche a janela de venda pelo X, **sem vender** (ou venda de verdade, se quiser).

#### F) Telas que aparecem às vezes (faça quando surgirem)

| Categoria | Quando aparece | O que recortar |
|---|---|---|
| `advertise` (mais um) | Tocar num caixote **à venda** | O botão **“Criar anúncio”** |
| `confirm` | Depois de criar anúncio | O botão **OK/Sim** (nunca um que gasta diamante) |
| `continue` | Subir de nível, avisos | O botão **Continuar/OK** |
| `silo_full` | Silo cheio | O título/ícone do aviso |
| `reconnect` | Conexão perdida | O botão **Tentar novamente** |

✅ **Confira:** na aba **Templates**, clique em **Atualizar lista**. Todas as linhas **OBRIGATÓRIO**
devem estar **verdes** e com **Imagens ≥ 1**. As vermelhas ainda faltam.

---

## Etapa 9 — Testar a detecção

**Onde:** 📱 Hay Day → 🤖 aba **Templates** → **Testar detecção...**

Esta janela usa **exatamente o mesmo detector do bot**.

1. 📱 Deixe a fazenda na tela, sem janelas.
2. 🤖 Clique em **Testar detecção...** e depois em **Capturar nova** (pega a tela atual).
3. Clique em **Calibrar zoom**. Deve aparecer algo como `zoom da câmera: 1.00x | wheat_empty: 3 (0.98) | ...`.
4. Escolha cada categoria na caixa **Categoria** e clique em **Testar**:
   - `farm` → **1** retângulo no ícone certo;
   - `wheat_empty` → um retângulo em **cada** campo vazio, e **nenhum** nos outros;
   - `wheat_ready` → um retângulo em **cada** campo pronto;
   - `shop` → **1** retângulo na banca.
5. Clique em **Testar todas** para ver tudo de uma vez, com cores diferentes.
6. **Teste com outra tela:** mexa um pouco a câmera ou espere o trigo balançar, clique em
   **Capturar nova** e teste de novo. Tem que continuar funcionando.

### Como ler a mensagem

| Mensagem | O que significa | O que fazer |
|---|---|---|
| `melhor 0.9x` e retângulos certos | ✅ Tudo certo | Nada |
| `com zoom 0.85: 0.97` | O jogo está com outro zoom | Clique **Calibrar zoom** (o bot faz isso sozinho) |
| `rejeitado pela cor/brilho (janela por cima?)` | Tem uma janela escurecendo a tela | Feche a janela no jogo e capture de novo |
| `melhor 0.5x` e nada sugerido | O recorte não serve | Recorte de novo seguindo as regras de ouro |
| Retângulos em lugares errados | Recorte pouco característico | Recorte uma área mais distinta |
| Trigo pronto às vezes sim, às vezes não | Faltam quadros da animação | Recorte de novo com **5 quadros extras** |

> ⚠️ **Não baixe o “Limiar” abaixo de 0.80 para “fazer funcionar”.** Isso causa cliques errados.
> Se precisar, refaça o recorte.

✅ **Confira:** `farm`, `wheat_empty` e `wheat_ready` são encontrados corretamente em pelo menos 2 capturas diferentes.

---

## Etapa 10 — Configurar plantio e venda

**Onde:** 🤖 aba **Configurações**.

Ajuste só o que precisar. Os mais importantes:

| Seção | Campo | Recomendação |
|---|---|---|
| Cultivo | **Estoque inicial de trigo no silo (estimativa)** | Quantos trigos você tem **agora** no silo (veja no jogo). |
| Cultivo | **Reserva de trigo que nunca é vendida** | No mínimo o **número de campos** (ex.: 9 campos → 20). |
| Venda | **Vender trigo na banca** | Marcado para vender; desmarcado para só plantar/colher. |
| Venda | **Quantidade mínima para vender** / **máxima por caixote** | Ex.: `10` e `10`. |
| Venda | **Preço** | `max` (usa o botão de preço máximo) ou `default` (preço sugerido). |
| Anúncio | **Criar anúncios no jornal** | Marcado se criou o template `advertise`. |
| Coleta de dinheiro | **Coletar vendas concluídas** | Marcado se criou o template `collect`. |
| Tempo e segurança | **Intervalo de verificação (s)** | `5`. |
| Tempo e segurança | **Tecla de emergência** | `F8`. |

Clique em **Salvar configurações** no final da aba.

✅ **Confira:** no log (aba **Painel**) aparece `Configurações salvas em config.json`.

---

## Etapa 11 — Iniciar o bot

**Onde:** 📱 Hay Day → 🤖 botão **INICIAR BOT**.

1. 📱 Deixe o Hay Day **na fazenda**, sem janelas, com a câmera da Etapa 5.
2. 🤖 Vá na aba **Painel** (para ver o log).
3. Clique em **INICIAR BOT**.
   - Se aparecer “Templates faltando”, clique **Não** e volte à Etapa 8.
4. **Não mexa no MEmu** enquanto o bot roda (pode usar outras janelas do Windows).

O log deve mostrar algo assim:
```
[12:31:04] ADB conectado (127.0.0.1:21503, 1280x720)
[12:31:07] Hay Day encontrado (zoom da câmera 1.00x)
[12:31:10] Campos encontrados: 9 (vazios 9, prontos 0, crescendo 0)
[12:31:11] Plantando trigo
[12:31:16] 9 campos plantados
[12:31:16] Aguardando o trigo crescer (~120s, verificando a cada 5s)
[12:33:20] Trigo pronto (9 campos)
[12:33:21] Colhendo
[12:33:25] 9 campos colhidos
[12:33:30] Abrindo loja
[12:33:34] Produto colocado à venda (10x trigo)
[12:33:38] Anúncio realizado
```

✅ **Confira:** a bolinha fica **amarela (Executando)** e os números do painel sobem.

### Como ler o log de diagnóstico

A cada decisão o bot mostra **o que viu** e **por quê** agiu assim:

```
[colheita] Plantações detectadas: 9 -> vazias 0, prontas 8, crescendo 1 | candidatos descartados: 2
   descartado wheat_ready em (231, 402) (0.76): pontuação 0.76 abaixo do limiar 0.80
   descartado wheat_empty em (300, 270) (0.83): mesma plantação já classificada como pronta (0.95 > 0.83)
Colhendo 8 trigo(s)
Clique enviado: (158, 330) — colher: abrir menu na plantação (158, 330); aguardando confirmação...
Ação confirmada: colher: abrir menu na plantação (158, 330) (0.4s)
Arrastando 'sickle' de (213, 285) sobre 8 plantações (modo motionevent): (158, 330) -> ...
[colher] Passagem 1/3: 8 alvos -> 7 confirmados na tela; sem mudança em (344, 468)
Clique enviado: (344, 468) — colher: abrir menu ...; aguardando confirmação...
Ação NÃO confirmada: ... — o jogo não respondeu em 2.5s; recalculando a posição e tentando de novo
Posição recalculada: (344, 468) -> (343, 466)
Clique enviado: (343, 466) — ... [tentativa 2/2, toque de 90 ms]; aguardando confirmação...
Ação confirmada: ...
[colher] Passagem 2/3: 1 alvos -> 1 confirmados na tela
8 campos colhidos
```

| Linha | O que significa |
|---|---|
| `Plantações detectadas: N -> vazias/prontas/crescendo` | A lista única de plantações que o bot vai usar (cada posição com um só estado). |
| `descartado ... abaixo do limiar` | Parecia o elemento (forma e cor), mas a pontuação ficou abaixo do limiar. Se for um trigo real, **recorte de novo** (não baixe o limiar). |
| `descartado ... cor/brilho diferente` | A forma bate, mas a cor não (ex.: janela escurecendo a tela, ou outro tipo de plantação). |
| `descartado ... eco/duplicado da plantação` | Um segundo acerto dentro da MESMA plantação. Foi descartado de propósito. |
| `descartado ... já classificada como ...` | Dois templates viram a mesma posição; ficou o estado de maior pontuação. |
| `Clique enviado` / `Ação confirmada` | O toque foi enviado **e** o jogo respondeu (o menu abriu). |
| `Ação NÃO confirmada` | O jogo não respondeu. O bot recalcula a posição num screenshot novo e tenta **uma** vez mais com um toque um pouco mais longo. |
| `Passagem N: X alvos -> Y confirmados; sem mudança em (...)` | Depois de cada arrasto, o bot confere plantação por plantação. As que não mudaram entram na próxima passagem. |
| `trigo(s) não responderam à colheita ... nova tentativa em até 180s` | Um trigo que não respondeu fica em espera por 3 minutos, **não** para sempre. Enquanto isso, o bot continua plantando os espaços vazios. |

---

## Etapa 12 — Acompanhar e parar

**Onde:** 🤖 aba **Painel**.

- **Parar:** botão **PARAR BOT** ou tecla **F8** (funciona mesmo com o MEmu em foco).
- **Painel:** campos encontrados, plantados e colhidos, quantidade vendida, anúncios, dinheiro
  coletado, tempo de execução, estado atual, última ação e **último erro**.
- **Bolinha vermelha (Erro):** o bot parou sozinho por segurança. Leia o **Último erro** e veja:
  - o log completo: botão **Abrir pasta de logs** → `logs\haydaybot_AAAAMMDD.log`;
  - a foto da tela no momento do erro: botão **Abrir screenshots** → pasta `errors`.

---

## Atualizar o bot sem perder seus templates

**Onde:** 🪟 Explorer.

Quando houver uma versão nova:

1. **Guarde** (copie para outro lugar) a pasta **`templates`** e o arquivo **`config.json`** de `C:\HayDayBot`.
2. Baixe o ZIP novo (Etapa 1) e extraia **por cima** de `C:\HayDayBot`, confirmando a substituição.
3. **Copie de volta** a pasta `templates` e o `config.json` que você guardou, substituindo.
4. Dê dois cliques em `install.bat` de novo (atualiza as dependências) e depois em `run.bat`.

> Configurações novas que ainda não existiam no seu `config.json` são preenchidas sozinhas com os valores padrão.

---

## Gerar o HayDayBot.exe (opcional)

**Onde:** 🪟 Explorer, em `C:\HayDayBot`.

1. Dê dois cliques em **`build.bat`** e espere (de 2 a 5 minutos).
2. O resultado fica em **`C:\HayDayBot\dist\`**:
   ```
   dist\HayDayBot.exe
   dist\config.json
   dist\templates\
   dist\screenshots\
   dist\logs\
   ```
3. Para usar em outro PC, copie a **pasta `dist` inteira** (o `.exe` sozinho não funciona sem `templates` e `config.json`).

---

## Problemas comuns e o que fazer

| Problema | Onde resolver | O que fazer |
|---|---|---|
| `install.bat` diz “Python não encontrado” | 🪟 | Reinstale o Python marcando **Add python.exe to PATH** (Etapa 2). |
| “adb não encontrado” | 🤖 Conexão | Corrija o **Caminho do adb.exe** com **Procurar...**. |
| Nenhum dispositivo / conexão FALHOU | 🤖 Conexão | Com o MEmu aberto, clique em **Procurar emuladores** e depois em **CONECTAR**. |
| “adb server version doesn't match” | 🪟 | Feche Android Studio e outros emuladores. Use o `adb.exe` **do MEmu**. |
| Dispositivo `offline` ou `unauthorized` | 📱 | Reinicie o MEmu. |
| `OPEN_GAME` falha: “não chegou à fazenda” | 🤖 Painel / Templates | Leia a linha `Fazenda ainda não reconhecida — ...` no log e faça a Etapa 9 com o template `farm`. |
| “Nenhum campo reconhecido” | 📱 + 🤖 Templates | Confira se os campos estão na tela (Etapa 5) e teste `wheat_empty`/`wheat_ready` (Etapa 9). |
| Planta ou colhe só alguns campos | 🤖 Configurações → Arrasto | Aumente **Segurar antes de arrastar** para `0.4`, ou mude o **Modo** para `swipe`. |
| Clica no lugar errado | 🤖 Templates | Refaça o recorte da categoria culpada, com uma área mais característica. |
| Trigo pronto às vezes não é achado | 🤖 Templates | Recorte `wheat_ready` de novo com **5 quadros extras**. |
| Log mostra `descartado ... abaixo do limiar` num trigo real | 🤖 Templates | Recorte de novo aquele tipo (mais quadros da animação, ou o miolo do campo). |
| Muitos `Ação NÃO confirmada` seguidos | 🤖 Configurações → Tempo e segurança | Aumente **Duração do toque** para `60` e **Tempo máx. esperando o jogo responder** para `3.5`. |
| Muitos `sem mudança` nas passagens de plantio | 🤖 Configurações → Arrasto | Aumente **Segurar antes de arrastar** para `0.4`, ou mude o **Modo** para `swipe`. |
| F8 não funciona | 🪟 | Feche o bot e abra o `run.bat` com botão direito → **Executar como administrador**. |
| Bot parou com 🔴 Erro | 🤖 Painel | Veja o **Último erro**, o log e o screenshot em `screenshots\errors`. |

---

## Como me pedir ajuda com informações úteis

Se algo não funcionar, junte estes arquivos (todos ficam em `C:\HayDayBot`):

1. `config.json`
2. a pasta `templates` inteira
3. o trecho do log com as linhas `Plantações detectadas`, `descartado`, `Clique enviado` e `Passagem` do momento do problema
4. 1 ou 2 screenshots da **fazenda**, tirados pelo botão **CAPTURAR TELA** (ficam em `screenshots`)
5. o screenshot do erro em `screenshots\errors` (se houver)
6. o log do dia em `logs`
7. o texto que o **Testar detecção** mostra para a categoria com problema

O jeito mais fácil de me mandar, sem usar git:

1. 🪟 Abra `github.com/pedrohaddad/bothayday` e selecione a branch **`claude/hay-day-automation-bot-74ov9f`**.
2. Clique em **Add file → Upload files**.
3. Arraste os arquivos acima para a página. Para ficar organizado, antes de arrastar digite
   `amostras/` no nome da pasta, ou arraste uma pasta chamada `amostras` com tudo dentro.
4. Embaixo, em **Commit changes**, deixe marcado *Commit directly to the ...* e clique em **Commit changes**.

Depois me avise. Assim eu testo o detector com as **suas imagens reais**.

> Não coloque os screenshots dentro da pasta `screenshots/` do repositório: o `.gitignore` ignora
> os PNGs dessa pasta e eles não seriam enviados. Use `amostras/`.
