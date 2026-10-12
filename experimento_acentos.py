#!/usr/bin/env python3
"""
Distribuição dos acentos por instrumento em frases isoladas (Tabela 2 do resumo).

Para cada configuração, gera as frases das sementes 0 a N-1 e compara a porcentagem
de acentos de cada instrumento com o valor esperado pela gramática:
    tambor i: prob_comp * prob_i + prob_tambores / 3 + prob_livre / 4
    chimbal:  prob_livre / 4
(com os pesos já normalizados).

Uso:
    python experimento_acentos.py            # 2000 frases por configuração
    python experimento_acentos.py -n 500
"""
from __future__ import annotations

import argparse
import random
from collections import Counter

from gramatica import PARAMETROS, gerar

INSTRUMENTOS = {"S": "Caixa", "T": "Tom", "U": "Surdo", "C": "Chimbal"}

CONFIGURACOES = {
    "Padrão": {},
    "prob_u = 0,8": {"prob_s": 0.1, "prob_t": 0.1, "prob_u": 0.8},
    "prob_s = 0,8": {"prob_s": 0.8, "prob_t": 0.1, "prob_u": 0.1},
    "prob_livre = 1": {"prob_comp": 0, "prob_tambores": 0, "prob_livre": 1},
}


def esperado(params: dict) -> dict[str, float]:
    p = {**PARAMETROS, **params}
    total_bloco = p["prob_comp"] + p["prob_tambores"] + p["prob_livre"]
    comp, tambores, livre = (p[k] / total_bloco for k in ("prob_comp", "prob_tambores", "prob_livre"))
    total_p = p["prob_s"] + p["prob_t"] + p["prob_u"]
    return {
        "S": comp * p["prob_s"] / total_p + tambores / 3 + livre / 4,
        "T": comp * p["prob_t"] / total_p + tambores / 3 + livre / 4,
        "U": comp * p["prob_u"] / total_p + tambores / 3 + livre / 4,
        "C": livre / 4,
    }


def medido(params: dict, n: int) -> dict[str, float]:
    contagem = Counter(ch for semente in range(n)
                       for ch in gerar(random.Random(semente), **params) if ch in INSTRUMENTOS)
    total = sum(contagem.values())
    return {i: contagem[i] / total for i in INSTRUMENTOS}


def main() -> None:
    ap = argparse.ArgumentParser(description="Porcentagem de acentos por instrumento")
    ap.add_argument("-n", type=int, default=2000, help="Frases por configuração (padrão: 2000)")
    args = ap.parse_args()

    print(f"{'Configuração':<16}" + "".join(f"{nome:>16}" for nome in INSTRUMENTOS.values()))
    for rotulo, params in CONFIGURACOES.items():
        m, e = medido(params, args.n), esperado(params)
        print(f"{rotulo:<16}" + "".join(f"{100 * m[i]:>9.1f} ({100 * e[i]:4.1f})" for i in INSTRUMENTOS))
    print(f"\n{args.n} frases por configuração (sementes 0 a {args.n - 1}); esperado entre parênteses.")


if __name__ == "__main__":
    main()
