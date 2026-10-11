#!/usr/bin/env python3
"""
Converte uma sequência de terminais (S, s, T, t, U, u, C, c) gerada pela gramática
em um arquivo MIDI de bateria e, opcionalmente, renderiza esse MIDI em WAV
com o FluidSynth.

Cada terminal ocupa uma colcheia de tercina em 4/4 (12 posições por compasso).
Espaços na entrada são ignorados, então "Tss TsT" e "TssTsT" são equivalentes.

Uso:
    python frase_para_audio.py "Tss TsT ssU CsC ..." --sf2 GeneralUser-GS/GeneralUser-GS.sf2
    python frase_para_audio.py -a frase.txt --bpm 180 -o saida/frase1 --sf2 GeneralUser-GS/GeneralUser-GS.sf2
    python frase_para_audio.py "Tss TsT ..." --sem-audio
    python frase_para_audio.py "Tss TsT ..." --sf2 GeneralUser-GS/GeneralUser-GS.sf2 --metronomo
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import wave
from pathlib import Path

import numpy as np
import pretty_midi

TERCINAS_POR_COMPASSO = 12   # tercinas de colcheia em 4/4
COMPASSOS_POR_FRASE = 4

# Mapeamento terminal -> lista de (nota General MIDI de percussão, velocity).
# 38 = caixa, 47 = tom médio-grave, 43 = surdo (floor tom), 46 = chimbal aberto.
# A gramática só gera notas fantasmas na caixa (s); t, u e c ficam disponíveis
# para sequências escritas à mão.
KIT = {
    "S": [(38, 110)],             # caixa acentuada
    "s": [(38, 35)],              # caixa fantasma
    "T": [(47, 110)],             # tom acentuado
    "t": [(47, 35)],              # tom fantasma
    "U": [(43, 110)],             # surdo acentuado
    "u": [(43, 35)],              # surdo fantasma
    "C": [(46, 115)],             # chimbal aberto acentuado
    "c": [(46, 40)],              # chimbal aberto fraco
}

# Metrônomo: um clique por semínima (a cada 3 tercinas), com o tempo 1 destacado.
# Cada clique é uma camada de sons agudos tocados juntos, no volume máximo (127).
# 34 = metronome bell, 76 = wood block agudo, 75 = claves.
METRONOMO_TEMPO_1 = [(34, 127), (76, 127)]
METRONOMO_DEMAIS = [(75, 127), (76, 127)]


def ler_sequencia(sequencia: str) -> list[str]:
    """Separa a sequência em terminais (ignorando espaços) e valida contra o KIT."""
    simbolos = [ch for ch in sequencia if not ch.isspace()]
    invalidos = sorted({ch for ch in simbolos if ch not in KIT})
    if invalidos:
        raise ValueError(f"Símbolos desconhecidos na sequência: {', '.join(invalidos)}. "
                         f"Esperado apenas: {', '.join(KIT)}.")
    if not simbolos:
        raise ValueError("A sequência está vazia.")
    return simbolos


def trilha_metronomo(n_tercinas: int, bpm: float) -> pretty_midi.Instrument:
    """Trilha separada com um clique por semínima; o tempo 1 de cada compasso soa diferente."""
    metronomo = pretty_midi.Instrument(program=0, is_drum=True, name="Metrônomo")
    tempo = 60.0 / bpm
    n_tempos = -(-n_tercinas // 3)  # arredonda para cima
    for b in range(n_tempos):
        inicio = b * tempo
        for nota, velocity in (METRONOMO_TEMPO_1 if b % 4 == 0 else METRONOMO_DEMAIS):
            metronomo.notes.append(pretty_midi.Note(velocity=velocity, pitch=nota,
                                                    start=inicio, end=inicio + tempo * 0.25))
    return metronomo


def frase_para_midi(simbolos: list[str], bpm: float, metronomo: bool = False,
                    cauda_segundos: float = 2.0) -> pretty_midi.PrettyMIDI:
    pm = pretty_midi.PrettyMIDI(initial_tempo=bpm)
    pm.time_signature_changes.append(pretty_midi.TimeSignature(4, 4, 0.0))
    bateria = pretty_midi.Instrument(program=0, is_drum=True, name="Bateria")

    tercina = 60.0 / bpm / 3.0  # duração de uma colcheia de tercina, em segundos
    for i, simbolo in enumerate(simbolos):
        inicio = i * tercina
        for nota, velocity in KIT[simbolo]:
            bateria.notes.append(pretty_midi.Note(velocity=velocity, pitch=nota,
                                                  start=inicio, end=inicio + tercina * 0.5))

    # Evento inofensivo no fim para o arquivo não cortar a ressonância do último golpe.
    fim = len(simbolos) * tercina + cauda_segundos
    bateria.control_changes.append(pretty_midi.ControlChange(number=64, value=0, time=fim))

    pm.instruments.append(bateria)
    if metronomo:
        pm.instruments.append(trilha_metronomo(len(simbolos), bpm))
    return pm


def verificar_audio(sf2: Path) -> str:
    """Confere se o FluidSynth está no PATH e o soundfont existe; retorna o executável."""
    exe = shutil.which("fluidsynth")
    if exe is None:
        raise RuntimeError("FluidSynth não encontrado no PATH (ver Instalação no README).")
    if not sf2.is_file():
        raise FileNotFoundError(f"Soundfont não encontrado: {sf2}")
    return exe


def renderizar_audio(caminho_midi: Path, caminho_wav: Path, sf2: Path, ganho: float = 0.6,
                     taxa_amostragem: int = 44100) -> None:
    exe = verificar_audio(sf2)
    cmd = [exe, "-ni", "-g", str(ganho), "-r", str(taxa_amostragem), "-F", str(caminho_wav),
           str(sf2), str(caminho_midi)]
    resultado = subprocess.run(cmd, capture_output=True, text=True)
    if resultado.returncode != 0 or not caminho_wav.is_file():
        raise RuntimeError(f"FluidSynth falhou:\n{resultado.stderr or resultado.stdout}")
    cortar_silencio(caminho_wav)


def cortar_silencio(caminho_wav: Path, limiar_db: float = -60.0, manter_segundos: float = 0.5,
                    fade_segundos: float = 0.2) -> None:
    """Corta o silêncio do fim do WAV.

    O FluidSynth só para de gravar quando todas as vozes terminam de decair (cauda do
    crash, reverb), o que deixa dezenas de segundos de quase-silêncio no arquivo.
    Mantém `manter_segundos` após o último som acima de `limiar_db` e aplica um fade-out.
    """
    with wave.open(str(caminho_wav), "rb") as w:
        if w.getsampwidth() != 2:
            return  # o FluidSynth gera 16 bits por padrão; outro formato fica como está
        parametros = w.getparams()
        audio = np.frombuffer(w.readframes(w.getnframes()), dtype=np.int16).reshape(-1, w.getnchannels())

    taxa = parametros.framerate
    limiar = 32767 * 10 ** (limiar_db / 20)
    sons = np.nonzero(np.abs(audio).max(axis=1) > limiar)[0]
    fim = min(len(audio), (sons[-1] + 1 if len(sons) else 0) + int(manter_segundos * taxa))
    if fim >= len(audio):
        return

    audio = audio[:fim].astype(np.float32)
    n_fade = min(fim, int(fade_segundos * taxa))
    audio[fim - n_fade:] *= np.linspace(1.0, 0.0, n_fade, dtype=np.float32)[:, None]

    with wave.open(str(caminho_wav), "wb") as w:
        w.setparams(parametros)
        w.writeframes(audio.astype(np.int16).tobytes())


def main() -> int:
    ap = argparse.ArgumentParser(description="Sequência de terminais -> MIDI -> WAV")
    origem = ap.add_mutually_exclusive_group(required=True)
    origem.add_argument("sequencia", nargs="?", help="Sequência de terminais, ex.: \"Tss TsT ssU ...\"")
    origem.add_argument("-a", "--arquivo", type=Path, help="Arquivo de texto contendo a sequência")
    ap.add_argument("--bpm", type=float, default=160.0, help="Andamento em semínimas por minuto (padrão: 160)")
    ap.add_argument("-o", "--saida", type=Path, default=Path("frase"),
                    help="Caminho de saída sem extensão (padrão: frase -> frase.mid / frase.wav)")
    ap.add_argument("--sf2", type=Path, help="Soundfont (.sf2) para renderizar o áudio")
    ap.add_argument("--sem-audio", action="store_true", help="Gera apenas o MIDI")
    ap.add_argument("-m", "--metronomo", action="store_true",
                    help="Inclui uma trilha de metrônomo (um clique por semínima, tempo 1 destacado)")
    ap.add_argument("--ganho", type=float, default=0.6,
                    help="Ganho geral do FluidSynth (padrão: 0.6). Diminua se o áudio distorcer.")
    args = ap.parse_args()

    sequencia = args.arquivo.read_text(encoding="utf-8") if args.arquivo else args.sequencia
    try:
        simbolos = ler_sequencia(sequencia)
    except ValueError as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1

    esperado = TERCINAS_POR_COMPASSO * COMPASSOS_POR_FRASE
    if len(simbolos) != esperado:
        print(f"Aviso: {len(simbolos)} posições; o esperado para {COMPASSOS_POR_FRASE} compassos é {esperado}.",
              file=sys.stderr)

    args.saida.parent.mkdir(parents=True, exist_ok=True)
    caminho_midi = args.saida.with_suffix(".mid")
    frase_para_midi(simbolos, args.bpm, metronomo=args.metronomo).write(str(caminho_midi))
    extra = ", com metrônomo" if args.metronomo else ""
    print(f"MIDI salvo em {caminho_midi} ({len(simbolos)} posições, "
          f"{len(simbolos) / TERCINAS_POR_COMPASSO:g} compassos, {args.bpm:g} bpm{extra})")

    if args.sem_audio:
        return 0
    if args.sf2 is None:
        print("Aviso: nenhum --sf2 informado; pulei a renderização de áudio.", file=sys.stderr)
        return 0

    caminho_wav = args.saida.with_suffix(".wav")
    try:
        renderizar_audio(caminho_midi, caminho_wav, args.sf2, ganho=args.ganho)
    except (RuntimeError, FileNotFoundError) as e:
        print(f"Erro: {e}", file=sys.stderr)
        return 1
    print(f"Áudio salvo em {caminho_wav}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
