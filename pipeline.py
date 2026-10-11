#!/usr/bin/env python3
"""
Pipeline: gramática -> sequência de terminais -> MIDI -> WAV.

Modo padrão: a frase i usa a semente semente + i.
Com --completo, cada peça junta a banda de assets/banda.mid com uma frase da
gramática em cada pausa (ver montagem.py); a peça k usa as sementes
semente + 4k, ..., semente + 4k + 3.

Cada execução grava um registro próprio, registro_<modo>_semente<base>_<data-hora>.json.

Uso:
    python pipeline.py -n 5 --semente 42 --sf2 GeneralUser-GS/GeneralUser-GS.sf2
    python pipeline.py -n 3 --semente 7 --param prob_u=0.6 --metronomo -o saida/exp1
    python pipeline.py -n 10 --sem-audio
    python pipeline.py -n 5 --sem-audio --param prob_comp=1 --param prob_tambores=0 \\
        --param prob_livre=0 --param prob_t=0 --param prob_u=0      # acentos só de caixa
    python pipeline.py --completo -n 2 --semente 1 --sf2 GeneralUser-GS/GeneralUser-GS.sf2
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from datetime import datetime
from fractions import Fraction
from pathlib import Path

from frase_para_audio import (COMPASSOS_POR_FRASE, TERCINAS_POR_COMPASSO, frase_para_midi,
                              ler_sequencia, renderizar_audio, verificar_audio)
from gramatica import PARAMETROS, gerar
from montagem import N_PAUSAS, montar


class ErroAudio(Exception):
    """Falha do FluidSynth; interrompe a geração."""


def ler_params(pares: list[str]) -> dict[str, float]:
    """Converte ["a=0.5", "b=3", "c=1/3"] em {"a": 0.5, "b": 3.0, "c": 0.333...}."""
    params = {}
    for par in pares:
        nome, sep, bruto = par.partition("=")
        try:
            if not sep:
                raise ValueError
            params[nome.strip()] = float(Fraction(bruto.strip()))
        except (ValueError, ZeroDivisionError):
            raise ValueError(f"Parâmetro mal formado: '{par}'. Use nome=valor, com valor "
                             f"numérico (ex.: prob_s=0.5 ou prob_s=1/3).") from None
    return params


def caminho_registro(pasta: Path, modo: str, semente_base: int, data: datetime) -> Path:
    """Nome único por execução; nunca sobrescreve um registro anterior."""
    base = f"registro_{modo}_semente{semente_base}_{data:%Y%m%d-%H%M%S}"
    caminho, n = pasta / f"{base}.json", 2
    while caminho.exists():
        caminho, n = pasta / f"{base}_{n}.json", n + 1
    return caminho


def main() -> int:
    ap = argparse.ArgumentParser(description="Gera frases com a gramática e converte em MIDI/WAV")
    ap.add_argument("-n", "--quantidade", type=int, default=3,
                    help="Quantas frases gerar (ou peças, com --completo) (padrão: 3)")
    ap.add_argument("--semente", type=int, default=None,
                    help=f"Semente base: a frase i usa semente + i; com --completo, a peça k usa "
                         f"semente + {N_PAUSAS}k a semente + {N_PAUSAS}k + {N_PAUSAS - 1}. "
                         f"Sem ela, uma semente é sorteada e registrada.")
    ap.add_argument("--param", action="append", default=[], metavar="NOME=VALOR",
                    help=f"Hiperparâmetro da gramática ({', '.join(PARAMETROS)}); pode repetir a opção")
    ap.add_argument("-o", "--saida", type=Path, default=Path("saida"), help="Pasta de saída (padrão: saida)")
    ap.add_argument("--bpm", type=float, default=160.0, help="Andamento (padrão: 160)")
    ap.add_argument("--sf2", type=Path, help="Soundfont para o áudio; sem ele, só gera MIDI")
    ap.add_argument("--sem-audio", action="store_true", help="Gera apenas MIDI")
    ap.add_argument("-m", "--metronomo", action="store_true",
                    help="Inclui trilha de metrônomo (ignorado com --completo)")
    ap.add_argument("--ganho", type=float, default=0.6, help="Ganho do FluidSynth (padrão: 0.6)")
    ap.add_argument("--completo", action="store_true",
                    help=f"Gera peças completas: banda + bateria + {N_PAUSAS} solos da gramática nas pausas")
    args = ap.parse_args()

    try:
        params = ler_params(args.param)
    except ValueError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    for nome in sorted(params.keys() - PARAMETROS.keys()):
        print(f"Aviso: parâmetro '{nome}' não existe na gramática "
              f"(conhecidos: {', '.join(PARAMETROS)}).", file=sys.stderr)

    semente_base = args.semente if args.semente is not None else random.SystemRandom().randrange(2**31)
    com_audio = not args.sem_audio and args.sf2 is not None
    if not args.sem_audio and args.sf2 is None:
        print("Aviso: nenhum --sf2 informado; gerando só os MIDIs.", file=sys.stderr)
    if com_audio:
        try:
            verificar_audio(args.sf2)  # falha antes de gerar qualquer arquivo
        except (RuntimeError, FileNotFoundError) as e:
            print(f"Erro no áudio: {e}", file=sys.stderr)
            return 1

    if args.completo and args.metronomo:
        print("Aviso: --metronomo é ignorado no modo --completo.", file=sys.stderr)
        args.metronomo = False

    args.saida.mkdir(parents=True, exist_ok=True)
    data = datetime.now()
    modo = "completo" if args.completo else "frases"
    registro = {
        "modo": modo, "data": data.isoformat(timespec="seconds"),
        "params": params, "semente_base": semente_base,
        "bpm": args.bpm, "metronomo": args.metronomo,
    }
    itens = registro.setdefault("pecas" if args.completo else "frases", [])
    unidade = "peças" if args.completo else "frases"

    erro_audio = None
    try:
        if args.completo:
            gerar_pecas(args, gerar, params, semente_base, com_audio, itens)
        else:
            gerar_frases(args, gerar, params, semente_base, com_audio, itens)
    except ErroAudio as e:
        erro_audio = e
        print(f"Erro no áudio: {e}\nGeração interrompida.", file=sys.stderr)

    caminho_reg = caminho_registro(args.saida, modo, semente_base, data)
    caminho_reg.write_text(json.dumps(registro, ensure_ascii=False, indent=2), encoding="utf-8")
    geradas = sum("erro" not in item for item in itens)
    print(f"\n{geradas} de {args.quantidade} {unidade} geradas em {args.saida}/ "
          f"(semente base {semente_base}). Registro em {caminho_reg}.")
    return 1 if erro_audio or geradas < args.quantidade else 0


def renderizar(args, caminho_midi: Path, entrada: dict) -> None:
    """Gera o WAV ao lado do MIDI e anota em `entrada`; levanta ErroAudio se o FluidSynth falhar."""
    caminho_wav = caminho_midi.with_suffix(".wav")
    try:
        renderizar_audio(caminho_midi, caminho_wav, args.sf2, ganho=args.ganho)
    except (RuntimeError, FileNotFoundError) as e:
        raise ErroAudio(e) from e
    entrada["audio"] = caminho_wav.name


def gerar_pecas(args, gerar, params: dict, semente_base: int, com_audio: bool, pecas: list) -> None:
    """Modo --completo: a peça k usa as sementes semente_base + N_PAUSAS*k + j, j = 0..N_PAUSAS-1."""
    for k in range(args.quantidade):
        sementes = [semente_base + N_PAUSAS * k + j for j in range(N_PAUSAS)]
        nome = f"trading4s_{k + 1:02d}_semente{sementes[0]}"
        try:
            frases = [gerar(random.Random(s), **params).strip() for s in sementes]
            pm = montar(frases, args.bpm)
        except Exception as e:  # erro dentro do gerador ou frase inválida para a montagem
            print(f"[{k + 1}] sementes {sementes}: falhou ({type(e).__name__}: {e})", file=sys.stderr)
            pecas.append({"sementes": sementes, "erro": f"{type(e).__name__}: {e}"})
            continue

        caminho_midi = args.saida / f"{nome}.mid"
        pm.write(str(caminho_midi))
        entrada = {"sementes": sementes, "frases": frases, "midi": caminho_midi.name}
        pecas.append(entrada)
        if com_audio:
            renderizar(args, caminho_midi, entrada)

        print(f"[{k + 1}] {caminho_midi.name}")
        for s, f in zip(sementes, frases):
            print(f"    semente {s}: {f}")


def gerar_frases(args, gerar, params: dict, semente_base: int, com_audio: bool, frases: list) -> None:
    """Modo padrão: uma frase isolada por semente."""
    esperado = TERCINAS_POR_COMPASSO * COMPASSOS_POR_FRASE
    for i in range(args.quantidade):
        semente = semente_base + i
        nome = f"frase_{i + 1:02d}_semente{semente}"
        try:
            sequencia = gerar(random.Random(semente), **params).strip()
            simbolos = ler_sequencia(sequencia)
        except Exception as e:  # erro dentro do gerador ou símbolo inválido na saída
            print(f"[{i + 1}] semente {semente}: falhou ({type(e).__name__}: {e})", file=sys.stderr)
            frases.append({"semente": semente, "erro": f"{type(e).__name__}: {e}"})
            continue

        # Aqui o tamanho errado só gera aviso; no --completo a montagem recusa a frase.
        if len(simbolos) != esperado:
            print(f"[{i + 1}] aviso: {len(simbolos)} posições (esperado {esperado})", file=sys.stderr)

        caminho_midi = args.saida / f"{nome}.mid"
        frase_para_midi(simbolos, args.bpm, metronomo=args.metronomo).write(str(caminho_midi))
        entrada = {"semente": semente, "sequencia": sequencia, "midi": caminho_midi.name}
        frases.append(entrada)
        if com_audio:
            renderizar(args, caminho_midi, entrada)

        print(f"[{i + 1}] semente {semente}: {sequencia}")


if __name__ == "__main__":
    sys.exit(main())
