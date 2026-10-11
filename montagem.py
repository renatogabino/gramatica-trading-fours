#!/usr/bin/env python3
"""
Monta a peça completa de trading fours: banda (de assets/banda.mid) + bateria de
condução + solos de bateria gerados pela gramática nas pausas da banda.

Uso (normalmente via pipeline.py --completo):
    from montagem import montar
    pm = montar([frase1, frase2, frase3, frase4], bpm=160)
    pm.write("peca.mid")
"""
from __future__ import annotations

import copy
import math
import random
from pathlib import Path

import pretty_midi

from frase_para_audio import KIT, TERCINAS_POR_COMPASSO, ler_sequencia

# =============================================================================
# CONSTANTES
# =============================================================================

CAMINHO_BANDA = Path(__file__).parent / "assets" / "banda.mid"

TEMPOS_POR_COMPASSO = 4
TERCINAS_POR_TEMPO = TERCINAS_POR_COMPASSO // TEMPOS_POR_COMPASSO   # 3

# Forma da peça: (nome, compasso inicial, compasso final), ambos inclusivos, contados a partir de 1.
# O Final não tem condução: a bateria só marca a chegada (crash + bumbo) no tempo 1 do compasso 41.
FORMA = [
    ("Tema",           1,  8),
    ("Solo trompete",  9, 12),
    ("Bateria",       13, 16),
    ("Solo trombone", 17, 20),
    ("Bateria",       21, 24),
    ("Solo trompete", 25, 28),
    ("Bateria",       29, 32),
    ("Solo trombone", 33, 36),
    ("Bateria",       37, 40),
    ("Final",         41, 42),
]
SECAO_PAUSA = "Bateria"                                  # seções em que a gramática sola
SECOES_CONDUCAO = {"Tema", "Solo trompete", "Solo trombone"}  # seções com condução de ride

PAUSAS = [(ini, fim) for nome, ini, fim in FORMA if nome == SECAO_PAUSA]
N_PAUSAS = len(PAUSAS)

# Notas General MIDI de percussão.
BUMBO = 36
CHIMBAL_PE = 44
CRASH = 49
RIDE = 51

# Padrões por compasso: (nota, posição em tempos a partir do tempo 1, velocity).
# A 3ª tercina do tempo n fica em (n - 1) + 2/3.
CONDUCAO = [
    (RIDE, 0, 78), (RIDE, 1, 90), (RIDE, 1 + 2/3, 62),
    (RIDE, 2, 78), (RIDE, 3, 90), (RIDE, 3 + 2/3, 62),
    (CHIMBAL_PE, 1, 70), (CHIMBAL_PE, 3, 70),
    (BUMBO, 0, 32), (BUMBO, 1, 32), (BUMBO, 2, 32), (BUMBO, 3, 32),
]
CHIMBAL_PAUSA = [(CHIMBAL_PE, 1, 70), (CHIMBAL_PE, 3, 70)]  # omitido onde o solo abre o chimbal
CHEGADA = [(CRASH, 0, 115), (BUMBO, 0, 110)]             # tempo 1 do compasso após cada pausa

VARIACAO_VELOCITY = 6         # condução: velocity sorteada em ±VARIACAO_VELOCITY
SEMENTE_HUMANIZACAO = 2024    # fixa, para a condução ser sempre igual
DURACAO_GOLPE = 1 / (2 * TERCINAS_POR_TEMPO)  # meia tercina, em tempos (como em frase_para_midi)


# =============================================================================
# MONTAGEM
# =============================================================================

def _inicio_compasso(compasso: int) -> float:
    """Posição, em tempos, do tempo 1 do compasso (numerado a partir de 1)."""
    return (compasso - 1) * TEMPOS_POR_COMPASSO


def _validar_frase(frase: str, n_compassos: int) -> list[str]:
    simbolos = ler_sequencia(frase)
    esperado = n_compassos * TERCINAS_POR_COMPASSO
    if len(simbolos) != esperado:
        raise ValueError(f"Frase com {len(simbolos)} símbolos; cada pausa de {n_compassos} compassos "
                         f"exige exatamente {esperado}: '{frase}'")
    return simbolos


def montar(frases: list[str], bpm: float) -> pretty_midi.PrettyMIDI:
    """Junta a banda (sem a bateria original) com a bateria nova, no andamento `bpm`."""
    if len(frases) != N_PAUSAS:
        raise ValueError(f"São necessárias {N_PAUSAS} frases (uma por pausa); recebidas {len(frases)}.")
    solos = [_validar_frase(f, fim - ini + 1) for f, (ini, fim) in zip(frases, PAUSAS)]

    banda = pretty_midi.PrettyMIDI(str(CAMINHO_BANDA))
    _, andamentos = banda.get_tempo_changes()
    if len(andamentos) != 1:
        raise ValueError(f"{CAMINHO_BANDA} deve ter andamento constante; tem {len(andamentos)} mudanças.")
    bpm_origem = float(andamentos[0])

    def segundos(tempos: float) -> float:
        """Único ponto de conversão de tempos musicais para segundos."""
        return tempos * 60.0 / bpm

    def reescalar(t: float) -> float:
        return segundos(t * bpm_origem / 60.0)   # segundos no andamento original -> tempos -> segundos

    # Resolução múltipla da original e de 3, para notas da banda e tercinas caírem exatas na grade.
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm, resolution=math.lcm(banda.resolution, TERCINAS_POR_TEMPO))
    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))

    # Banda: todas as trilhas melódicas, com notas e velocities originais e tempos reescalados.
    for inst in banda.instruments:
        if inst.is_drum:
            continue
        novo = copy.deepcopy(inst)
        for nota in novo.notes:
            nota.start, nota.end = reescalar(nota.start), reescalar(nota.end)
        for evento in novo.control_changes + novo.pitch_bends:
            evento.time = reescalar(evento.time)
        pm.instruments.append(novo)

    bateria = pretty_midi.Instrument(program=0, is_drum=True, name="Bateria")
    rng = random.Random(SEMENTE_HUMANIZACAO)

    def golpe(nota: int, tempos: float, velocity: int) -> None:
        """Adiciona um golpe; se já houver a mesma nota no mesmo instante, o novo a substitui."""
        inicio = segundos(tempos)
        bateria.notes[:] = [n for n in bateria.notes if not (n.pitch == nota and math.isclose(n.start, inicio))]
        bateria.notes.append(pretty_midi.Note(velocity=max(1, min(127, velocity)), pitch=nota,
                                              start=inicio, end=segundos(tempos + DURACAO_GOLPE)))

    def padrao(compasso: int, notas: list[tuple[int, float, int]], variacao: int = 0) -> None:
        for nota, pos, vel in notas:
            golpe(nota, _inicio_compasso(compasso) + pos, vel + rng.randint(-variacao, variacao))

    for nome, ini, fim in FORMA:
        if nome in SECOES_CONDUCAO:
            for c in range(ini, fim + 1):
                padrao(c, CONDUCAO, VARIACAO_VELOCITY)

    total_compassos = FORMA[-1][2]
    for simbolos, (ini, fim) in zip(solos, PAUSAS):
        inicio = _inicio_compasso(ini)
        for j, simbolo in enumerate(simbolos):
            for nota, vel in KIT[simbolo]:
                golpe(nota, inicio + j / TERCINAS_POR_TEMPO, vel)
        for c in range(ini, fim + 1):
            # Em GM o chimbal de pé abafa o aberto: não pisa onde o solo tem C/c no mesmo instante.
            base = (c - ini) * TERCINAS_POR_COMPASSO
            padrao(c, [(nota, pos, vel) for nota, pos, vel in CHIMBAL_PAUSA
                       if simbolos[base + round(pos * TERCINAS_POR_TEMPO)].upper() != "C"])
        if fim + 1 <= total_compassos:
            padrao(fim + 1, CHEGADA)

    bateria.notes.sort(key=lambda n: (n.start, n.pitch))
    pm.instruments.append(bateria)

    pm.text_events = [pretty_midi.Text(nome, segundos(_inicio_compasso(ini))) for nome, ini, _ in FORMA]
    return pm
