"""
Gramática probabilística das frases de bateria (4 compassos de tercinas).

gerar(rng, **params) deriva uma frase a partir do axioma. Todos os sorteios usam
o `rng` recebido, então a mesma semente gera sempre a mesma frase; `params` traz
os hiperparâmetros passados com --param nome=valor.

Terminais gerados: S, T, U, C (caixa, tom, surdo e chimbal aberto acentuados) e
s (nota fantasma de caixa, usada em todo preenchimento).
"""
from __future__ import annotations

import random
import re
from dataclasses import dataclass, field

# =============================================================================
# DEFINIÇÃO DA GRAMÁTICA
# Para alterar a gramática, basta mexer nesta seção; o motor abaixo é genérico.
#
# - Cabeça da regra: "Nome" ou "Nome(arg1, arg2, ...)". Cada argumento é uma
#   variável declarada em VARIAVEIS (casa com qualquer valor do domínio) ou um
#   valor literal (casa só com ele). Se várias cabeças casarem, vence a mais
#   específica (com mais literais), então dá para sobrescrever casos, ex.:
#   "Tempo(x)" genérico e "Tempo(c)" especial.
# - Corpo: símbolos separados por espaço. Um símbolo cujo nome é o de algum
#   não-terminal é expandido; qualquer outro é terminal. Argumentos que são
#   variáveis ligadas (da cabeça ou de um sorteio) são substituídos pelo valor.
# - Peso: relativo (não precisa somar 1). Pode ser Param("nome", padrão) para
#   ser controlado pela linha de comando com --param nome=valor.
# - Sorteios: P(..., var=distribuição) sorteia `var` uma vez por aplicação da
#   regra; cada variável é sorteada independentemente das outras.
# - Rótulos com memória: um não-terminal no corpo pode levar um rótulo, ex.:
#   "Bloco#A" ou "Comp(p)#A". A primeira ocorrência de um rótulo é derivada
#   normalmente; as seguintes, no mesmo corpo, repetem a mesma derivação
#   (cópia idêntica, sem novos sorteios). O escopo é uma aplicação da regra:
#   o #A de "Frase" não interfere num #A usado em outra regra.
# =============================================================================

@dataclass(frozen=True)
class Param:
    """Peso/probabilidade ajustável via --param nome=valor."""
    nome: str
    padrao: float

    def resolver(self, params: dict) -> float:
        return float(params.get(self.nome, self.padrao))


@dataclass
class Producao:
    corpo: str
    peso: float | Param = 1
    sorteios: dict[str, dict[str, float | Param]] = field(default_factory=dict)


def P(corpo: str, peso: float | Param = 1, **sorteios) -> Producao:
    """Atalho: P("A(x) s s", 1/8) ou P("Comp(p) ...", p={"s": 0.5, "t": 0.5})."""
    return Producao(corpo, peso, sorteios)


def uniforme(*valores: str) -> dict[str, float]:
    return {v: 1 for v in valores}


AXIOMA = "Frase"

VARIAVEIS = {
    "p": ["s", "t", "u"],
    "x": ["s", "t", "u", "c"],
}

DIST_P = {"s": Param("prob_s", 1/3), "t": Param("prob_t", 1/3), "u": Param("prob_u", 1/3)}
DIST_TAMBORES = uniforme("s", "t", "u")
DIST_LIVRE = uniforme("s", "t", "u", "c")

REGRAS: dict[str, list[Producao]] = {
    "Frase": [
        P("Bloco#A Bloco#B Bloco#C Bloco#D", 1/5),   # ABCD
        P("Bloco#A Bloco#A Bloco#B Bloco#B", 1/5),   # AABB
        P("Bloco#A Bloco#B Bloco#A Bloco#B", 1/5),   # ABAB
        P("Bloco#A Bloco#A Bloco#B Bloco#C", 1/5),   # AABC
        P("Bloco#A Bloco#B Bloco#B Bloco#C", 1/5),   # ABBC
    ],
    "Bloco": [
        P("Comp(p)",      Param("prob_comp", 1/3), p=DIST_P),
        P("CompTambores", Param("prob_tambores", 1/3)),
        P("CompLivre",    Param("prob_livre", 1/3)),
    ],
    "Comp(p)": [
        P("Tempo(p) Tempo(p) Tempo(p) Tempo(p)"),
    ],
    "CompTambores": [
        P("Tempo(r1) Tempo(r2) Tempo(r3) Tempo(r4)",
          r1=DIST_TAMBORES, r2=DIST_TAMBORES, r3=DIST_TAMBORES, r4=DIST_TAMBORES),
    ],
    "CompLivre": [
        P("Tempo(r1) Tempo(r2) Tempo(r3) Tempo(r4)",
          r1=DIST_LIVRE, r2=DIST_LIVRE, r3=DIST_LIVRE, r4=DIST_LIVRE),
    ],
    "Tempo(x)": [
        P("A(x) s s",       10/32),
        P("s s A(x)",       10/32),
        P("A(x) s A(x)",    10/32),
        P("s s s",          2/32),
    ],
    "A(s)": [P("S")],
    "A(t)": [P("T")],
    "A(u)": [P("U")],
    "A(c)": [P("C")],
}

SEPARADOR_PADRAO = " "
SEPARADORES = {
    "Tempo": "",
}

PROFUNDIDADE_MAXIMA = 200


# MOTOR GENÉRICO DE DERIVAÇÃO

_TOKEN = re.compile(r"[^\s(]+\([^)]*\)(?:#\S+)?|\S+")
_SIMBOLO = re.compile(r"^([^\s(#]+)(?:\(([^)]*)\))?(?:#(\w+))?$")


def _parse_simbolo(texto: str) -> tuple[str, tuple[str, ...], str | None]:
    """Retorna (nome, argumentos, rótulo); rótulo é None se não houver '#'."""
    m = _SIMBOLO.match(texto.strip())
    if not m:
        raise ValueError(f"Símbolo mal formado: '{texto}'")
    nome, args, rotulo = m.groups()
    return nome, tuple(a.strip() for a in args.split(",")) if args else (), rotulo


@dataclass
class _Regra:
    padrao: tuple[str, ...]          # argumentos da cabeça (variáveis ou literais)
    producoes: list[Producao]
    corpos: list[list[tuple[str, tuple[str, ...], str | None]]]

    @property
    def especificidade(self) -> int:
        return sum(a not in VARIAVEIS for a in self.padrao)

    def casar(self, args: tuple[str, ...]) -> dict[str, str] | None:
        """Retorna as ligações de variáveis se a cabeça casa com `args`."""
        if len(args) != len(self.padrao):
            return None
        ligacoes: dict[str, str] = {}
        for formal, real in zip(self.padrao, args):
            if formal in VARIAVEIS:
                if real not in VARIAVEIS[formal] or ligacoes.get(formal, real) != real:
                    return None
                ligacoes[formal] = real
            elif formal != real:
                return None
        return ligacoes


def _compilar() -> dict[str, list[_Regra]]:
    indice: dict[str, list[_Regra]] = {}
    for cabeca, producoes in REGRAS.items():
        nome, padrao, rotulo = _parse_simbolo(cabeca)
        if rotulo:
            raise ValueError(f"Cabeça de regra não pode ter rótulo: '{cabeca}'.")
        corpos = [[_parse_simbolo(t) for t in _TOKEN.findall(p.corpo)] for p in producoes]
        indice.setdefault(nome, []).append(_Regra(padrao, producoes, corpos))

    if AXIOMA not in indice:
        raise ValueError(f"Axioma '{AXIOMA}' não tem regras.")
    for nome, regras in indice.items():
        for regra in regras:
            if not regra.producoes:
                raise ValueError(f"Regra {nome}{regra.padrao} sem produções.")
            for corpo in regra.corpos:
                rotulados: dict[str, tuple[str, tuple[str, ...]]] = {}
                for simbolo, args, rotulo in corpo:
                    if (args or rotulo) and simbolo not in indice:
                        raise ValueError(f"Não-terminal '{simbolo}' usado em '{nome}' não tem regras.")
                    if rotulo and rotulados.setdefault(rotulo, (simbolo, args)) != (simbolo, args):
                        raise ValueError(f"Rótulo '#{rotulo}' usado com símbolos diferentes em '{nome}'.")
    return indice


def _coletar_parametros() -> dict[str, float]:
    """Nome -> valor padrão de todo Param usado em pesos ou distribuições de REGRAS."""
    encontrados: dict[str, float] = {}
    for producoes in REGRAS.values():
        for p in producoes:
            for peso in [p.peso, *(v for dist in p.sorteios.values() for v in dist.values())]:
                if isinstance(peso, Param):
                    encontrados.setdefault(peso.nome, peso.padrao)
    return encontrados


_INDICE = _compilar()
PARAMETROS = _coletar_parametros()   # consultado pelo pipeline para avisar sobre nomes desconhecidos


def _valor(peso: float | Param, params: dict) -> float:
    return peso.resolver(params) if isinstance(peso, Param) else float(peso)


def _resolver_pesos(pesos: list[float | Param], params: dict, contexto: str) -> list[float]:
    """Resolve os pesos; exige todos >= 0 e soma > 0, com erro que cita os parâmetros envolvidos."""
    valores = [_valor(p, params) for p in pesos]
    if any(v < 0 for v in valores) or sum(valores) <= 0:
        ajustaveis = [p.nome for p in pesos if isinstance(p, Param)]
        dica = f"; confira {', '.join(ajustaveis)}" if ajustaveis else ""
        raise ValueError(f"Pesos inválidos em {contexto}: {valores} "
                         f"(precisam ser >= 0 e somar mais que 0){dica}.")
    return valores


def _sortear(rng: random.Random, dist: dict[str, float | Param], params: dict, contexto: str) -> str:
    valores = list(dist)
    return rng.choices(valores, weights=_resolver_pesos([dist[v] for v in valores], params, contexto))[0]


def _escolher_regra(nome: str, args: tuple[str, ...]) -> tuple[_Regra, dict[str, str]]:
    candidatas = [(r, lig) for r in _INDICE[nome] if (lig := r.casar(args)) is not None]
    if not candidatas:
        raise ValueError(f"Nenhuma regra para {nome}({', '.join(args)}).")
    melhor = max(r.especificidade for r, _ in candidatas)
    empatadas = [c for c in candidatas if c[0].especificidade == melhor]
    if len(empatadas) > 1:
        raise ValueError(f"Regras ambíguas para {nome}({', '.join(args)}).")
    return empatadas[0]


def expandir(rng: random.Random, nome: str, args: tuple[str, ...] = (),
             params: dict | None = None, profundidade: int = 0) -> str:
    """Deriva o não-terminal `nome(args)` até restarem só terminais."""
    params = params or {}
    if profundidade > PROFUNDIDADE_MAXIMA:
        raise RecursionError(f"Derivação passou de {PROFUNDIDADE_MAXIMA} níveis (recursão infinita?).")

    regra, ambiente = _escolher_regra(nome, args)
    pesos = _resolver_pesos([p.peso for p in regra.producoes], params, nome)
    i = rng.choices(range(len(regra.producoes)), weights=pesos)[0]
    producao, corpo = regra.producoes[i], regra.corpos[i]

    ambiente = dict(ambiente)
    for var, dist in producao.sorteios.items():
        ambiente[var] = _sortear(rng, dist, params, f"sorteio de '{var}' em {nome}")

    partes = []
    memoria: dict[str, str] = {}     # rótulo -> derivação já feita nesta aplicação
    for simbolo, sargs, rotulo in corpo:
        if rotulo in memoria:
            partes.append(memoria[rotulo])
        elif simbolo in _INDICE:
            reais = tuple(ambiente.get(a, a) for a in sargs)
            derivado = expandir(rng, simbolo, reais, params, profundidade + 1)
            if rotulo:
                memoria[rotulo] = derivado
            partes.append(derivado)
        else:
            partes.append(simbolo)
    return SEPARADORES.get(nome, SEPARADOR_PADRAO).join(partes)


def gerar(rng: random.Random, **params) -> str:
    nome, args, _ = _parse_simbolo(AXIOMA)
    return expandir(rng, nome, args, params)


if __name__ == "__main__":
    for semente in range(5):
        print(f"semente {semente}: {gerar(random.Random(semente))}")
