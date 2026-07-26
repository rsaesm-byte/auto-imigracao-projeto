"""
run_questionnaire.py — Wizard interativo genérico para coletar respostas de
qualquer questionário USCIS (data/questionnaires/<FORM>.json).

Uso:
    python scripts/run_questionnaire.py data/questionnaires/i-130.json
    python scripts/run_questionnaire.py data/questionnaires/n-400.json --answers output/respostas.json
    python scripts/run_questionnaire.py data/questionnaires/n-400.json --answers output/respostas.json --resume

Comandos durante o wizard:
    Enter vazio     → pular campo opcional / confirmar campo obrigatório em branco (avisa)
    voltar / v      → retorna à pergunta anterior
    pular  / p      → pula campo opcional (limpa resposta anterior se houver)
    sair   / s      → salva e encerra
    resumo / r      → exibe todas as respostas dadas até agora
    ajuda  / ?      → exibe os comandos disponíveis
"""

import sys
import io
import json
import re
import argparse
import os
from pathlib import Path

# Força UTF-8 no stdout/stderr do Windows para suportar caracteres especiais.
if sys.stdout.encoding and sys.stdout.encoding.lower() not in ("utf-8", "utf8"):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

# ── Estados dos EUA (para campos select) ──────────────────────────────────────
US_STATES = [
    "AL","AK","AZ","AR","CA","CO","CT","DE","FL","GA",
    "HI","ID","IL","IN","IA","KS","KY","LA","ME","MD",
    "MA","MI","MN","MS","MO","MT","NE","NV","NH","NJ",
    "NM","NY","NC","ND","OH","OK","OR","PA","RI","SC",
    "SD","TN","TX","UT","VT","VA","WA","WV","WI","WY",
    "DC","PR","GU","VI","AS","MP",
]

# ── Cores ANSI (Windows 10+ e terminais modernos) ────────────────────────────
def _supports_color() -> bool:
    if os.name == "nt":
        try:
            import ctypes
            kernel = ctypes.windll.kernel32
            kernel.SetConsoleMode(kernel.GetStdHandle(-11), 7)
        except Exception:
            return False
    return hasattr(sys.stdout, "isatty") and sys.stdout.isatty()

USE_COLOR = _supports_color()

def c(text: str, code: str) -> str:
    if not USE_COLOR:
        return text
    return f"\033[{code}m{text}\033[0m"

def bold(t):    return c(t, "1")
def cyan(t):    return c(t, "36")
def yellow(t):  return c(t, "33")
def green(t):   return c(t, "32")
def red(t):     return c(t, "31")
def dim(t):     return c(t, "2")
def magenta(t): return c(t, "35")


# ── Lógica condicional ────────────────────────────────────────────────────────

def is_visible(question: dict, answers: dict) -> bool:
    """Retorna True se a pergunta deve ser exibida dado o estado atual das respostas.

    "equals" aceita um valor único (igualdade simples) OU uma lista de valores
    (visível se a resposta bater com QUALQUER um deles) -- extensão mínima
    usada quando uma pergunta só deve aparecer para um subconjunto de valores
    de uma pergunta anterior de múltipla escolha (ex.: "nome da escola" só
    para quem respondeu COS F1 ou COS F2, não para EOS/COS B2). Continua sem
    suporte a múltiplas perguntas-gatilho (AND/OR entre perguntas diferentes)."""
    show_if = question.get("show_if")
    if not show_if:
        return True
    dep_qid = show_if.get("question")
    expected = show_if.get("equals")
    actual = answers.get(dep_qid)
    if actual is None:
        return False
    if isinstance(expected, list):
        return str(actual) in [str(e) for e in expected]
    return str(actual) == str(expected)


def active_questions(all_questions: list[dict], answers: dict) -> list[dict]:
    """Retorna somente as perguntas visíveis no estado atual."""
    return [q for q in all_questions if is_visible(q, answers)]


# ── Exibição ──────────────────────────────────────────────────────────────────

LINE = "─" * 60

def print_section_header(title: str) -> None:
    print()
    print(cyan(LINE))
    print(cyan(f"  {title}"))
    print(cyan(LINE))
    print()


def print_question(q: dict, pos: int, total: int) -> None:
    label = q["label"].rstrip(" *").rstrip()
    req = bold(red(" *")) if q.get("required") else dim(" (opcional)")
    progress = dim(f"[{pos}/{total}]")
    print(f"  {progress} {bold(label)}{req}")
    hint = q.get("hint")
    if hint:
        print(f"       {dim(hint)}")


def print_options(options: list[dict], multi: bool = False) -> None:
    for i, opt in enumerate(options, 1):
        print(f"    {yellow(str(i))}) {opt['label']}")
    if multi:
        print(f"    {dim('(separe múltiplos com vírgula, ex: 1,3)')}")


def print_state_grid() -> None:
    cols = 10
    states = US_STATES
    rows = [states[i:i+cols] for i in range(0, len(states), cols)]
    for row in rows:
        print("    " + "  ".join(f"{dim(s)}" for s in row))


def print_help() -> None:
    print()
    print(bold("  Comandos disponíveis:"))
    print(f"    {yellow('voltar')} / {yellow('v')}   → voltar à pergunta anterior")
    print(f"    {yellow('pular')}  / {yellow('p')}   → pular campo opcional")
    print(f"    {yellow('sair')}   / {yellow('s')}   → salvar e sair")
    print(f"    {yellow('resumo')} / {yellow('r')}   → ver respostas até agora")
    print(f"    {yellow('ajuda')}  / {yellow('?')}   → mostrar esta ajuda")
    print(dim("    Em campos de texto/data, use a palavra completa (ex: 'sair'),"))
    print(dim("    não a abreviação de 1 letra — evita conflito com respostas curtas"))
    print(dim("    como uma inicial de nome do meio."))
    print()


def print_summary(all_questions: list[dict], answers: dict) -> None:
    print()
    print(bold("  Resumo das respostas:"))
    print(dim("  " + LINE))
    count = 0
    for q in all_questions:
        val = answers.get(q["id"])
        if val is None:
            continue
        short_label = q["label"].rstrip(" *").rstrip()
        if len(short_label) > 45:
            short_label = short_label[:42] + "..."
        if isinstance(val, list):
            display = ", ".join(val)
        else:
            display = str(val)
        print(f"  {dim(q['id']+':')} {green(display)}")
        count += 1
    print(dim(f"  {LINE}"))
    print(f"  Total: {bold(str(count))} respostas")
    print()


# ── Coleta de resposta por tipo ───────────────────────────────────────────────

CMDS = {"voltar", "v", "pular", "p", "sair", "s", "resumo", "r", "ajuda", "?"}

# Campos de texto/data aceitam qualquer valor curto como resposta legítima
# (ex: inicial do meio-nome "S", "V", "R" são comuns) — por isso não reconhecem
# os atalhos de UMA letra ("s", "v", "p", "r"), só as palavras completas. Um
# atalho de uma letra nesses campos apagaria silenciosamente a resposta do
# usuário (ex: responder "S" como nome do meio era interpretado como "sair").
TEXT_CMDS = {"voltar", "pular", "sair", "resumo", "ajuda", "?"}


def _prompt(question: dict) -> str:
    """Monta a linha de prompt com dica de formato."""
    ftype = question.get("type")
    if ftype == "date":
        return f"  {bold('→')} {dim('(MM/DD/AAAA)')} "
    if ftype in ("radio", "checkbox_group"):
        opts = question.get("options", [])
        if question.get("type") == "checkbox_group":
            return f"  {bold('→')} {dim('números separados por vírgula')} "
        return f"  {bold('→')} {dim(f'número 1–{len(opts)}')} "
    if ftype == "select":
        return f"  {bold('→')} {dim('sigla do estado (ex: NJ)')} "
    return f"  {bold('→')} "


def ask_radio(question: dict, prev=None) -> str | None:
    """Pergunta de radio (escolha única). Retorna value ou comando."""
    options = question.get("options", [])
    print_options(options, multi=False)
    print()
    while True:
        raw = input(_prompt(question)).strip()
        if not raw:
            if question.get("required") and prev is None:
                print(red("  ✗ Campo obrigatório. Digite um número ou 'sair'."))
                continue
            return None
        if raw.lower() in CMDS:
            return raw.lower()
        try:
            idx = int(raw) - 1
            if 0 <= idx < len(options):
                chosen = options[idx]
                print(f"  {green('✓')} {chosen['label']}")
                return chosen["value"]
            print(red(f"  ✗ Digite um número entre 1 e {len(options)}."))
        except ValueError:
            print(red(f"  ✗ Opção inválida. Digite um número entre 1 e {len(options)}."))


def ask_checkbox_group(question: dict, prev=None) -> list[str] | str | None:
    """Pergunta de múltipla escolha. Retorna lista de values ou comando."""
    options = question.get("options", [])
    print_options(options, multi=True)
    print()
    while True:
        raw = input(_prompt(question)).strip()
        if not raw:
            if question.get("required") and prev is None:
                print(red("  ✗ Campo obrigatório. Selecione ao menos uma opção."))
                continue
            return None
        if raw.lower() in CMDS:
            return raw.lower()
        parts = [p.strip() for p in raw.split(",") if p.strip()]
        selected = []
        error = False
        for p in parts:
            try:
                idx = int(p) - 1
                if 0 <= idx < len(options):
                    selected.append(options[idx]["value"])
                else:
                    print(red(f"  ✗ Número inválido: {p}. Use 1–{len(options)}."))
                    error = True
                    break
            except ValueError:
                print(red(f"  ✗ '{p}' não é um número válido."))
                error = True
                break
        if not error and selected:
            labels = [options[i]["label"] for i in
                      [int(p)-1 for p in parts]]
            print(f"  {green('✓')} {', '.join(labels)}")
            return selected


def ask_select(question: dict, prev=None) -> str | None:
    """Pergunta de estado dos EUA. Retorna sigla ou comando."""
    print()
    print_state_grid()
    print()
    while True:
        raw = input(_prompt(question)).strip().upper()
        if not raw:
            if question.get("required") and prev is None:
                print(red("  ✗ Campo obrigatório."))
                continue
            return None
        if raw.lower() in CMDS:
            return raw.lower()
        if raw in US_STATES:
            print(f"  {green('✓')} {raw}")
            return raw
        print(red(f"  ✗ Sigla inválida. Use uma das siglas listadas acima."))


DATE_RE = re.compile(r"^(0[1-9]|1[0-2])/(0[1-9]|[12]\d|3[01])/\d{4}$")

def ask_date(question: dict, prev=None) -> str | None:
    """Campo de data com validação de formato MM/DD/AAAA."""
    print()
    while True:
        raw = input(_prompt(question)).strip()
        if not raw:
            if question.get("required") and prev is None:
                print(red("  ✗ Campo obrigatório. Formato: MM/DD/AAAA"))
                continue
            return None
        if raw.lower() in TEXT_CMDS:
            return raw.lower()
        if DATE_RE.match(raw):
            print(f"  {green('✓')} {raw}")
            return raw
        print(red("  ✗ Formato inválido. Use MM/DD/AAAA (ex: 03/15/1985)."))


def ask_text(question: dict, prev=None) -> str | None:
    """Campo de texto livre."""
    print()
    while True:
        raw = input(_prompt(question)).strip()
        if not raw:
            if question.get("required") and prev is None:
                print(red("  ✗ Campo obrigatório. Digite um valor."))
                continue
            return None
        if raw.lower() in TEXT_CMDS:
            return raw.lower()
        print(f"  {green('✓')} {raw}")
        return raw


def ask_question(question: dict, answers: dict) -> tuple[str | list | None, str | None]:
    """
    Pede resposta de uma pergunta.

    Retorna (value, cmd) onde:
      - value = resposta digitada (str, list ou None se pulado)
      - cmd   = comando especial ("voltar", "pular", "sair", "resumo", "ajuda") ou None
    """
    ftype = question.get("type")
    prev = answers.get(question["id"])
    if ftype in ("radio",):
        result = ask_radio(question, prev)
        valid_cmds = CMDS
    elif ftype == "checkbox_group":
        result = ask_checkbox_group(question, prev)
        valid_cmds = CMDS
    elif ftype == "select":
        result = ask_select(question, prev)
        valid_cmds = CMDS
    elif ftype == "date":
        result = ask_date(question, prev)
        valid_cmds = TEXT_CMDS
    else:
        result = ask_text(question, prev)
        valid_cmds = TEXT_CMDS

    if isinstance(result, str) and result in valid_cmds:
        return None, result
    return result, None


# ── Loop principal ────────────────────────────────────────────────────────────

def run_wizard(
    all_questions: list[dict],
    sections: dict[str, str],
    answers: dict,
    output_path: Path,
    title: str = "Wizard",
) -> dict:
    """
    Executa o wizard perguntando cada questão ativa.

    Gerencia:
    - Cálculo dinâmico de perguntas ativas (show_if)
    - Navegação: próxima, anterior, pular, sair
    - Cabeçalhos de seção
    - Salvamento incremental após cada resposta
    """
    pos        = 0     # posição na lista de perguntas ativas atual
    last_section = None
    skip_to_id   = None   # usado para retomar do ponto salvo

    # Se há respostas carregadas, avança até a primeira pergunta sem resposta
    if answers:
        active = active_questions(all_questions, answers)
        for i, q in enumerate(active):
            if q["id"] not in answers:
                pos = i
                break
        else:
            pos = len(active)  # todas respondidas

    header = f"Wizard — {title}"
    bar = "═" * max(len(header) + 4, 40)
    print()
    print(bold(cyan(f"  {bar}")))
    print(bold(cyan(f"    {header}")))
    print(bold(cyan(f"  {bar}")))
    print(f"  Arquivo de respostas: {dim(str(output_path))}")
    print(f"  {dim('Digite')} {yellow('ajuda')} {dim('para ver os comandos disponíveis.')}")
    print()

    while True:
        active = active_questions(all_questions, answers)
        total  = len(active)

        if pos >= total:
            # Wizard concluído
            print()
            print(bold(green("  ✓ Todas as perguntas respondidas!")))
            _save(answers, output_path)
            print(f"  Respostas salvas em: {bold(str(output_path))}")
            print()
            break

        if pos < 0:
            pos = 0

        q = active[pos]

        # Cabeçalho de seção
        section_id    = q.get("section", "")
        section_title = sections.get(section_id, section_id)
        if section_title != last_section:
            print_section_header(section_title)
            last_section = section_title

        # Mostra pergunta
        print_question(q, pos + 1, total)

        # Mostra resposta anterior se houver
        prev = answers.get(q["id"])
        if prev is not None:
            if isinstance(prev, list):
                prev_display = ", ".join(str(v) for v in prev)
            else:
                prev_display = str(prev)
            print(f"       {dim('Resposta anterior:')} {yellow(prev_display)}")
            print(f"       {dim('(Enter = manter, ou digite nova resposta)')}")

        # Coleta resposta
        value, cmd = ask_question(q, answers)
        print()

        # Processa comandos
        if cmd == "voltar" or cmd == "v":
            if pos > 0:
                # Remove resposta atual ao voltar (para que show_if seja reavaliado)
                # mas mantém para não perder progresso — apenas recua o ponteiro
                pos -= 1
                last_section = None  # força reexibir header
                print(dim("  ← Voltando para a pergunta anterior...\n"))
            else:
                print(dim("  ← Já estamos na primeira pergunta.\n"))
            continue

        if cmd == "pular" or cmd == "p":
            if q.get("required"):
                print(red("  ✗ Este campo é obrigatório e não pode ser pulado.\n"))
                continue
            # Remove a resposta se havia uma e avança
            answers.pop(q["id"], None)
            _save(answers, output_path)
            pos += 1
            continue

        if cmd == "sair" or cmd == "s":
            _save(answers, output_path)
            print(f"\n  Respostas salvas em: {bold(str(output_path))}")
            print(f"  {dim('Retome com')} --resume {dim('para continuar depois.')}\n")
            return answers

        if cmd == "resumo" or cmd == "r":
            print_summary(all_questions, answers)
            continue

        if cmd == "ajuda" or cmd == "?":
            print_help()
            continue

        # Se value é None e havia resposta anterior, mantém a anterior
        if value is None and prev is not None:
            pos += 1
            continue

        # Armazena resposta e avança
        if value is not None:
            answers[q["id"]] = value
        elif q["id"] in answers:
            # Campo opcional deixado em branco: remove
            del answers[q["id"]]

        _save(answers, output_path)
        pos += 1

    return answers


def _save(answers: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(answers, indent=2, ensure_ascii=False), encoding="utf-8")


# ── Resumo final ──────────────────────────────────────────────────────────────

def print_final_summary(all_questions: list, answers: dict, output_path: Path,
                         form_slug: str = "i-130") -> None:
    """Exibe o que fazer agora após concluir o questionário."""
    print(bold("  Próximos passos:"))
    print()
    print(f"  1. Gere o PDF preenchido:")
    print(f"     {cyan('python scripts/fill_form.py')} \\")
    print(f"         {dim(f'data/forms/{form_slug}.pdf')} \\")
    print(f"         {dim(f'data/mappings/{form_slug}.json')} \\")
    print(f"         {dim(str(output_path))} \\")
    print(f"         {dim(f'output/{form_slug}-preenchido.pdf')} {cyan('--patch-xfa')}")
    print()
    print(f"  2. Abra o PDF em {bold('Adobe Acrobat Reader')} para revisar.")
    print(f"  3. Assine e envie ao USCIS com a taxa correta.")
    print()
    missing = [q["label"] for q in all_questions
               if q.get("required") and is_visible(q, answers) and not answers.get(q["id"])]
    if missing:
        print(red(f"  ⚠  {len(missing)} campo(s) obrigatório(s) ainda sem resposta:"))
        for m in missing[:10]:
            print(red(f"     - {m.rstrip(' *')}"))
        if len(missing) > 10:
            print(red(f"     ... e mais {len(missing)-10}"))
        print()


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Wizard interativo para coletar respostas de um questionário USCIS "
                    "(genérico — funciona com qualquer data/questionnaires/<FORM>.json)."
    )
    parser.add_argument("questionnaire",
                        help="Questionário JSON (ex: data/questionnaires/i-130.json)")
    parser.add_argument("--answers", "-a",
                        default=None,
                        help="Arquivo de respostas JSON (padrão: output/respostas-<formulário>.json)")
    parser.add_argument("--resume", "-r", action="store_true",
                        help="Carrega respostas existentes e continua de onde parou")
    parser.add_argument("--summary", action="store_true",
                        help="Apenas exibe o resumo das respostas salvas e sai")
    args = parser.parse_args()

    q_path  = Path(args.questionnaire)

    if not q_path.exists():
        print(f"ERRO: questionário não encontrado: {q_path}", file=sys.stderr)
        sys.exit(1)

    q_data  = json.loads(q_path.read_text(encoding="utf-8"))
    all_qs  = q_data["questions"]
    sections = {s["id"]: s["title"] for s in q_data.get("sections", [])}
    form_slug = q_data.get("form", q_path.stem).lower()
    title     = q_data.get("title", q_data.get("form", form_slug))

    a_path = Path(args.answers) if args.answers else Path(f"output/respostas-{form_slug}.json")

    # Carrega respostas existentes
    answers: dict = {}
    if a_path.exists() and (args.resume or args.summary):
        answers = json.loads(a_path.read_text(encoding="utf-8"))
        print(f"\n  {green('✓')} {len(answers)} resposta(s) carregada(s) de {a_path}")

    if args.summary:
        print_summary(all_qs, answers)
        print_final_summary(all_qs, answers, a_path, form_slug)
        return

    if a_path.exists() and not args.resume:
        print(f"\n  {yellow('⚠')}  Arquivo {a_path} já existe.")
        print(f"  Use {yellow('--resume')} para continuar de onde parou.")
        print(f"  Ou pressione {yellow('Enter')} para iniciar do começo (sobrescreve).")
        resp = input("  [Enter = recomeçar, 'r' = retomar]: ").strip().lower()
        if resp == "r":
            answers = json.loads(a_path.read_text(encoding="utf-8"))
            print(f"  {green('✓')} Retomando com {len(answers)} resposta(s) salvas.")
        else:
            answers = {}
            print("  Iniciando do começo.\n")

    try:
        final = run_wizard(all_qs, sections, answers, a_path, title)
    except (KeyboardInterrupt, EOFError):
        print(f"\n\n  {yellow('!')} Interrompido. Respostas parciais salvas em {a_path}\n")
        return

    print_final_summary(all_qs, final, a_path, form_slug)


if __name__ == "__main__":
    main()
