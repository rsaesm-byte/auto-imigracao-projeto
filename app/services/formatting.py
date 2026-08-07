"""Formatadores de apresentação centralizados (Padronização Global do
Sistema, 2026-08-07, pedido do usuário) -- moeda/número/percentual
sempre em locale en-US na tela. Regra central do documento que motivou
isto: "O banco armazena o dado. A interface decide como apresentá-lo."

Registrados como filtros Jinja em app/__init__.py (`usd`/`num`/`pct`).
Só usar em texto de EXIBIÇÃO -- nunca no `value=` de um campo `<input>`
editável. Um valor como "$1,800.50" não é reaberto corretamente por
`app/services/crm_service.py::parse_dollars_to_cents` (que assume texto
puro tipo "1800.50", sem `$` nem separador de milhar) -- campos
editáveis continuam de propósito com número simples sem formatação,
documentado também na memória do projeto.
"""
from __future__ import annotations


def format_usd(cents: int | float | None) -> str:
    """Espera CENTAVOS (unidade mínima inteira, convenção da casa).
    0 -> "$0"; 180000 -> "$1,800"; 180050 -> "$1,800.50";
    -1195500 -> "-$11,955" (sinal antes do $, nunca "$-11955");
    None -> "—". Nunca mostra ".00" desnecessário; preserva até 2 casas
    quando existem centavos de verdade."""
    if cents is None:
        return "—"
    cents = round(cents)
    negative = cents < 0
    cents = abs(cents)
    dollars, remainder = divmod(cents, 100)
    amount = f"{dollars:,}" if remainder == 0 else f"{dollars:,}.{remainder:02d}"
    sign = "-" if negative else ""
    return f"{sign}${amount}"


def format_usd_input(cents: int | float | None) -> str:
    """`value=` de campo `<input>` editável -- separador de milhar,
    sempre 2 casas decimais (edição se beneficia de precisão visível,
    diferente do "$1,800" compacto de `format_usd`), SEM `$` (o rótulo
    do campo já diz "(USD)" -- ter o cifrão dentro de um campo de texto
    sendo editado é redundante/estranho). `None`/0 -> "" (campo vazio,
    não força "0.00" -- mesmo comportamento de antes desta mudança).
    Round-trip seguro com `crm_service.parse_dollars_to_cents`, que
    agora tolera `$`/separador de milhar."""
    if not cents:
        return ""
    cents = round(cents)
    negative = cents < 0
    cents = abs(cents)
    dollars, remainder = divmod(cents, 100)
    sign = "-" if negative else ""
    return f"{sign}{dollars:,}.{remainder:02d}"


def format_number(value: int | float | None) -> str:
    """1000 -> "1,000"; 25.50 -> "25.5"; 25.75 -> "25.75"; -1000 ->
    "-1,000"; None -> "—"."""
    if value is None:
        return "—"
    value = float(value)
    if value.is_integer():
        return f"{int(value):,}"
    text = f"{value:,.2f}".rstrip("0").rstrip(".")
    return text


def format_percent(value: int | float | None) -> str:
    """Espera o valor JÁ em percentual (25 significa 25%, não 0.25) --
    quem chama converte fração->percentual antes de passar aqui (mesma
    convenção que o código já usava: `savings_rate * 100`). 0 -> "0%";
    25 -> "25%"; 25.5 -> "25.5%"; -5 -> "-5%"; None -> "—"."""
    if value is None:
        return "—"
    value = float(value)
    if value.is_integer():
        return f"{int(value)}%"
    text = f"{value:.2f}".rstrip("0").rstrip(".")
    return f"{text}%"
