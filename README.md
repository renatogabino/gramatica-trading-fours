# Trading fours com gramática probabilística

Gera solos de bateria de 4 compassos para *trading fours* de jazz a partir de uma
gramática probabilística, e os converte em MIDI/WAV.

**Restrição estilística:** *trading fours* de jazz em swing. A bateria alterna solos de
4 compassos com os solos de trompete e trombone; as frases são escritas em colcheias de
tercina (12 por compasso em 4/4) e usam a caixa, o tom, o surdo e o chimbal aberto.

## Arquivos

- `gramatica.py`: a gramática e o motor de derivação (`gerar(rng, **params)`).
- `frase_para_audio.py`: converte uma frase (48 tercinas = 4 compassos 4/4) em MIDI e WAV.
- `montagem.py`: monta a peça completa (banda + condução + solos da gramática nas pausas).
- `pipeline.py`: ponto de entrada; gera frases avulsas ou peças completas.
- `experimento_acentos.py`: mede a distribuição dos acentos por instrumento (Tabela 2 do resumo).
- `assets/banda.mid`: arranjo da banda (contrabaixo, piano, trompete, trombone), escrito a
  180 bpm e reescalado para o `--bpm` escolhido. **Necessário para o modo `--completo`.**
  A trilha de bateria dele é descartada.
- `exemplos/`: peças geradas (MIDI, WAV e registro de cada execução); ver
  [Reproduzindo os exemplos](#reproduzindo-os-exemplos).
- `GeneralUser-GS/`: soundfont GeneralUser GS, de S. Christian Collins (licença em
  `GeneralUser-GS/documentation/LICENSE.txt`).

## Instalação

Requer Python 3.10+.

```
pip install -r requirements.txt
```

Para gerar WAV também é preciso o [FluidSynth](https://www.fluidsynth.org/) no PATH:

- Ubuntu/Debian: `sudo apt install fluidsynth`
- macOS: `brew install fluid-synth`
- Windows: `choco install fluidsynth`, ou o binário das
  [releases do projeto](https://github.com/FluidSynth/fluidsynth/releases)

Sem o FluidSynth (ou sem `--sf2`), o pipeline gera só os MIDIs.

## A gramática

Cada terminal é uma colcheia de tercina (12 por compasso):

| Terminal | Som | Nota GM |
|---|---|---|
| `S` | caixa acentuada | 38 |
| `T` | tom acentuado | 47 |
| `U` | surdo acentuado | 43 |
| `C` | chimbal aberto acentuado | 46 |
| `s` | caixa fantasma (preenchimento) | 38 |

(`t`, `u`, `c` também são aceitos pelo `frase_para_audio.py`, mas a gramática não os gera.)

A derivação tem quatro camadas:

1. **Frase** → 4 blocos com uma estrutura sorteada (1/5 cada): `ABCD`, `AABB`, `ABAB`,
   `AABC` ou `ABBC`. Blocos com a mesma letra são cópias idênticas (rótulos `#A`, `#B`... no
   corpo da regra repetem a mesma derivação, sem novos sorteios).
2. **Bloco** → um compasso de um de três tipos (pesos `prob_comp`, `prob_tambores` e
   `prob_livre`, 1/3 cada por padrão):
   - `Comp(p)`: os 4 tempos usam o mesmo tambor `p`, sorteado entre caixa, tom e surdo;
   - `CompTambores`: cada tempo sorteia caixa, tom ou surdo;
   - `CompLivre`: cada tempo sorteia caixa, tom, surdo ou chimbal.
3. **Tempo(x)** → 3 tercinas com o acento `X` do tambor `x`: `Xss`, `ssX`, `XsX` (10/32 cada)
   ou `sss` (2/32).

A saída sai com os tempos separados por espaço, ex.: `Tss TsT ssU CsC ...` (16 grupos).

### Hiperparâmetros

Passados com `--param nome=valor` (pode repetir a opção; aceita decimais ou frações, como `1/3`):

| Nome | No resumo | Padrão | Efeito |
|---|---|---|---|
| `prob_s` | π_s | 1/3 | peso da caixa no sorteio de `p` em `Comp(p)` |
| `prob_t` | π_t | 1/3 | peso do tom no mesmo sorteio |
| `prob_u` | π_u | 1/3 | peso do surdo no mesmo sorteio |
| `prob_comp` | β_P | 1/3 | peso de `Comp(p)` no sorteio do tipo de `Bloco` |
| `prob_tambores` | β_T | 1/3 | peso de `CompTambores` no mesmo sorteio |
| `prob_livre` | β_L | 1/3 | peso de `CompLivre` no mesmo sorteio |

São **pesos relativos**, não precisam somar 1: `--param prob_u=0.6` deixa o surdo com
0,6 / (1/3 + 1/3 + 0,6) ≈ 47% de chance. Peso 0 elimina a opção. Os pesos não podem ser
negativos, e cada sorteio precisa de ao menos um peso positivo; caso contrário a frase falha
com um erro que aponta os parâmetros envolvidos. Um nome que a gramática não usa gera aviso.

Exemplo: acentos só de caixa (todo compasso é `Comp(p)` e `p` é sempre `s`):

```
python pipeline.py -n 5 --sem-audio --param prob_comp=1 --param prob_tambores=0 --param prob_livre=0 --param prob_t=0 --param prob_u=0
```

Para só tom ou só surdo, zere os outros dois entre `prob_s`, `prob_t` e `prob_u`.

## Uso

Frases avulsas (uma por semente; a frase *i* usa a semente `semente + i`):

```
python pipeline.py -n 5 --semente 42 --sf2 GeneralUser-GS/GeneralUser-GS.sf2
```

Peça completa (modo `--completo`):

```
python pipeline.py --completo -n 2 --semente 1 --bpm 160 --sf2 GeneralUser-GS/GeneralUser-GS.sf2 -o saida/completo
```

Cada peça tem 42 compassos: Tema (1–8), solos de trompete e trombone alternados com
4 pausas de bateria (13–16, 21–24, 29–32, 37–40) e Final (41–42). Fora das pausas a bateria
faz condução de ride; nas pausas toca a frase da gramática com chimbal de pé nos tempos 2 e 4
(omitido onde a frase abre o chimbal), e o compasso seguinte a cada pausa começa com crash +
bumbo. A peça *k* chama a gramática 4 vezes, com as sementes `semente + 4k` a
`semente + 4k + 3`, e põe uma frase em cada pausa.

Opções do `pipeline.py`:

| Opção | Descrição |
|---|---|
| `-n`, `--quantidade` | quantas frases (ou peças, com `--completo`) gerar; padrão 3 |
| `--semente` | semente base; sem ela, uma é sorteada e registrada |
| `--param nome=valor` | hiperparâmetro da gramática |
| `--bpm` | andamento; padrão 160 |
| `--sf2` | soundfont para gerar os WAVs |
| `--sem-audio` | gera só MIDI, mesmo com `--sf2` |
| `--ganho` | volume do FluidSynth; padrão 0.6 |
| `-m`, `--metronomo` | adiciona trilha de metrônomo (ignorado com `--completo`) |
| `-o`, `--saida` | pasta de saída; padrão `saida` |
| `--completo` | gera peças completas em vez de frases avulsas |

### Saída

- Modo avulso: `frase_01_semente42.mid` (e `.wav` com `--sf2`), uma por frase.
- Modo completo: `trading4s_01_semente1.mid` (e `.wav`), uma por peça.
- Cada execução grava seu próprio registro, sem sobrescrever os anteriores:
  `registro_<frases|completo>_semente<base>_<AAAAMMDD-HHMMSS>.json`. Ele guarda o modo, a
  data, os parâmetros, a semente base, o bpm e, para cada frase (`semente`, `sequencia`) ou
  peça (`sementes`, `frases`), os arquivos gerados (`midi`, `audio`) ou o `erro`, se a
  geração falhou. O registro é gravado mesmo se o FluidSynth falhar no meio.

## Reproduzindo os exemplos

As peças em `exemplos/` foram geradas com os comandos abaixo (160 bpm). As duas primeiras usam a
configuração padrão com sementes diferentes; as duas últimas usam a mesma semente da primeira
e mudam só os hiperparâmetros.

| Pasta | Variação | Comando |
|---|---|---|
| `1_padrao_semente1` | padrão, semente 1 | `python pipeline.py --completo -n 1 --semente 1 --sf2 GeneralUser-GS/GeneralUser-GS.sf2 -o exemplos/1_padrao_semente1` |
| `2_padrao_semente101` | padrão, semente 101 | `python pipeline.py --completo -n 1 --semente 101 --sf2 GeneralUser-GS/GeneralUser-GS.sf2 -o exemplos/2_padrao_semente101` |
| `3_surdo` | surdo favorecido em `Comp(p)` | `python pipeline.py --completo -n 1 --semente 1 --sf2 GeneralUser-GS/GeneralUser-GS.sf2 -o exemplos/3_surdo --param prob_s=0.1 --param prob_t=0.1 --param prob_u=0.8` |
| `4_livre` | só `CompLivre`: mais chimbal e trocas de tambor | `python pipeline.py --completo -n 1 --semente 1 --sf2 GeneralUser-GS/GeneralUser-GS.sf2 -o exemplos/4_livre --param prob_comp=0 --param prob_tambores=0 --param prob_livre=1` |

Os MIDIs (e as frases no registro) saem idênticos para a mesma semente e os mesmos parâmetros;
o WAV pode variar levemente com a versão do FluidSynth.

## Experimento: distribuição dos acentos

```
python experimento_acentos.py        # -n para mudar o número de frases (padrão: 2000)
```

Gera as frases das sementes 0 a 1999 em quatro configurações (padrão, `prob_u = 0,8`,
`prob_s = 0,8` e `prob_livre = 1`) e imprime a porcentagem de acentos de cada instrumento ao
lado do valor esperado pela gramática (Tabela 2 do resumo).

### Módulos isolados

```
python gramatica.py                          # imprime as frases das sementes 0 a 4
python frase_para_audio.py "Tss TsT ssU CsC Tss TsT ssU CsC Tss TsT ssU CsC Tss TsT ssU CsC" --sf2 GeneralUser-GS/GeneralUser-GS.sf2 -o saida/teste
```

O `frase_para_audio.py` também aceita `-a/--arquivo` (lê a sequência de um arquivo),
`--bpm`, `--sem-audio`, `-m/--metronomo` e `--ganho`.

### Declaração de uso de IA

Durante o desenvolvimento deste trabalho, utilizei o Claude (Anthropic) como assistente de apoio, com os seguintes objetivos: discutir a viabilidade do tema e questões de direitos autorais no uso de gravações existentes; revisar a validade formal de versões preliminares da gramática, com o assistente apontando apenas inconsistências e correções pontuais, sem propor melhorias no método; indicar bibliotecas Python para gerar MIDI e renderizar áudio; gerar o código LaTeX das tabelas que documentam a gramática; e indicar trechos do resumo que poderiam ser condensados para respeitar o limite de páginas. A concepção e a implementação da gramática, o código do gerador e a redação do resumo são de minha autoria. A conversa completa está disponível em: https://claude.ai/share/caf73b64-ddb1-4683-9f3c-e059de3008fb