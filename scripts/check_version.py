"""
check_version.py — Verifica se o PDF de um formulário USCIS está atualizado.

Uso:
    python scripts/check_version.py I-130
    python scripts/check_version.py I-130 --download
    python scripts/check_version.py I-130 --update-hash

Modos:
    (padrão)        Compara o PDF local com o hash registrado em data/registry.json.
                    Extrai a edição de dentro do PDF e compara com a edição registrada.
    --download      Baixa o PDF da URL oficial e compara o hash com o local.
                    Se forem diferentes, avisa que há nova versão disponível.
    --update-hash   Recalcula o hash do PDF local e atualiza data/registry.json.
                    Use após baixar manualmente uma nova versão do formulário.
"""

import sys
import json
import hashlib
import argparse
import re
from pathlib import Path
from urllib.request import urlopen, Request
from urllib.error import URLError

try:
    from pypdf import PdfReader
except ImportError:
    print("ERROR: pypdf não instalado. Execute: pip install pypdf", file=sys.stderr)
    sys.exit(1)


REGISTRY_PATH = Path("data/registry.json")
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/125.0 Safari/537.36"


# ── Utilitários ───────────────────────────────────────────────────────────────

def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _status(label: str, value: str, ok: bool | None = None) -> None:
    if ok is True:
        mark = "\033[32m✓\033[0m"
    elif ok is False:
        mark = "\033[31m✗\033[0m"
    else:
        mark = "\033[33m·\033[0m"
    print(f"  {mark}  {label:<28} {value}")


# ── Leitura do registry ───────────────────────────────────────────────────────

def load_registry() -> dict:
    if not REGISTRY_PATH.exists():
        print(f"ERRO: registry não encontrado: {REGISTRY_PATH}", file=sys.stderr)
        sys.exit(1)
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def get_form_entry(registry: dict, form_id: str) -> dict:
    entry = registry.get("forms", {}).get(form_id.upper())
    if not entry:
        available = list(registry.get("forms", {}).keys())
        print(f"ERRO: formulário '{form_id}' não encontrado no registry.", file=sys.stderr)
        print(f"  Disponíveis: {', '.join(available)}", file=sys.stderr)
        sys.exit(1)
    return entry


# ── Extração de edição do PDF ─────────────────────────────────────────────────

def extract_edition_from_pdf(pdf_path: Path) -> str | None:
    """
    Tenta extrair a data de edição de dentro do PDF.

    Estratégia 1: campo de barcode (PDF417BarCode1) com padrão "FORM|MM/DD/YY|pagina".
    Estratégia 2: metadata /CreationDate ou /ModDate.
    Estratégia 3: busca textual por "Edition MM/YYYY" no conteúdo.
    """
    try:
        reader = PdfReader(str(pdf_path))

        # Estratégia 1 — campo de barcode
        fields = reader.get_fields() or {}
        for name, field in fields.items():
            v = str(field.get("/V", ""))
            m = re.match(r"[A-Z0-9-]+\|(\d{2}/\d{2}/\d{2,4})\|", v)
            if m:
                return m.group(1)

        # Estratégia 2 — metadata
        info = reader.metadata
        if info:
            for key in ("/ModDate", "/CreationDate"):
                val = info.get(key, "")
                if val:
                    # Formato típico: D:20240401...
                    m2 = re.search(r"D:(\d{4})(\d{2})(\d{2})", val)
                    if m2:
                        y, mo, d = m2.groups()
                        return f"{mo}/{d}/{y[2:]}"

    except Exception as exc:
        print(f"  Aviso: não foi possível ler o PDF: {exc}", file=sys.stderr)

    return None


# ── Comparação de edições ─────────────────────────────────────────────────────

def editions_match(edition_pdf: str, edition_registry: str) -> bool:
    """Compara datas no formato MM/DD/YY ou MM/DD/YYYY."""
    def normalize(e: str) -> str:
        parts = e.split("/")
        if len(parts) == 3:
            mm, dd, yy = parts
            if len(yy) == 2:
                yy = "20" + yy
            return f"{mm.zfill(2)}/{dd.zfill(2)}/{yy}"
        return e
    return normalize(edition_pdf) == normalize(edition_registry)


# ── Download do PDF oficial ───────────────────────────────────────────────────

def download_pdf(url: str, timeout: int = 60) -> bytes | None:
    print(f"  Baixando {url} ...")
    try:
        req = Request(url, headers={"User-Agent": UA})
        with urlopen(req, timeout=timeout) as resp:
            data = resp.read()
        print(f"  Recebido: {len(data):,} bytes")
        return data
    except URLError as e:
        print(f"  Erro ao baixar: {e}", file=sys.stderr)
        return None


# ── Exibe informações de taxa ─────────────────────────────────────────────────

def print_fee_info(entry: dict) -> None:
    fees = entry.get("fees", {})
    filing = fees.get("filing", {})
    bio    = fees.get("biometric", {})
    total  = fees.get("total_typical", "?")
    print()
    print("  Taxa de protocolo:")
    print(f"    Online : USD {filing.get('online', '?')}")
    print(f"    Papel  : USD {filing.get('paper', '?')}")
    if filing.get("notes"):
        print(f"    Nota   : {filing['notes']}")
    if bio.get("amount", 0) > 0:
        print(f"    Biometria: USD {bio['amount']}")
    print(f"    Total típico: USD {total}")
    for key, case in fees.get("special_cases", {}).items():
        if isinstance(case, dict) and "amount" in case:
            print(f"    Caso especial ({key}): USD {case['amount']} — {case.get('description','')}")
    print(f"    Pagar a : {fees.get('payable_to','')}")
    print(f"    Verificar taxas atuais: uscis.gov/forms/our-fees")


# ── Main ──────────────────────────────────────────────────────────────────────

def main() -> None:
    parser = argparse.ArgumentParser(
        description="Verifica se o PDF de um formulário USCIS está atualizado."
    )
    parser.add_argument("form", help="ID do formulário (ex: I-130)")
    parser.add_argument("--pdf", help="Caminho do PDF local (usa registry se omitido)")
    parser.add_argument("--download", "-d", action="store_true",
                        help="Baixa o PDF da URL oficial e compara o hash")
    parser.add_argument("--update-hash", action="store_true",
                        help="Atualiza o hash no registry com o PDF local atual")
    parser.add_argument("--fees", action="store_true",
                        help="Exibe informações de taxa e sai")
    args = parser.parse_args()

    registry  = load_registry()
    entry     = get_form_entry(registry, args.form)
    form_id   = args.form.upper()

    print()
    print(f"  Formulário : {form_id} — {entry.get('name_pt', entry.get('name',''))}")
    print(f"  Edição (registry): {entry.get('edition','?')} ({entry.get('edition_iso','?')})")
    print()

    if args.fees:
        print_fee_info(entry)
        print()
        return

    # ── Localiza o PDF local ───────────────────────────────────────────────
    pdf_path = Path(args.pdf) if args.pdf else Path(entry.get("local_pdf", ""))
    if not pdf_path or not pdf_path.exists():
        print(f"  PDF local não encontrado: {pdf_path}")
        print(f"  Baixe em: {entry.get('pdf_url','')}")
        sys.exit(2)

    local_hash = sha256_file(pdf_path)
    local_size = pdf_path.stat().st_size

    # ── Modo --update-hash ─────────────────────────────────────────────────
    if args.update_hash:
        old_hash = entry.get("pdf_sha256", "")
        entry["pdf_sha256"]    = local_hash
        entry["pdf_size_bytes"] = local_size
        registry["forms"][form_id] = entry
        REGISTRY_PATH.write_text(
            json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        if old_hash == local_hash:
            print(f"  Hash já estava correto. Nenhuma alteração.")
        else:
            print(f"  Hash atualizado no registry.")
            print(f"    Anterior : {old_hash or '(vazio)'}")
            print(f"    Novo     : {local_hash}")
        print()
        return

    # ── Verifica edição dentro do PDF ─────────────────────────────────────
    print("  Verificando PDF local...")
    _status("Arquivo", str(pdf_path))
    _status("Tamanho", f"{local_size:,} bytes")
    _status("SHA-256 local", local_hash[:16] + "…")

    # Hash vs registry
    reg_hash = entry.get("pdf_sha256", "")
    if reg_hash:
        hash_match = (local_hash == reg_hash)
        _status("Hash vs registry", "OK" if hash_match else "DIVERGE", hash_match)
        if not hash_match:
            print(f"       registry: {reg_hash}")
            print(f"       local   : {local_hash}")
    else:
        _status("Hash vs registry", "(sem hash no registry)", None)

    # Edição dentro do PDF
    edition_pdf = extract_edition_from_pdf(pdf_path)
    if edition_pdf:
        edition_reg = entry.get("edition", "")
        match = editions_match(edition_pdf, edition_reg)
        _status("Edição no PDF", edition_pdf, match)
        if not match:
            print(f"       registry: {edition_reg}")
            print()
            print("  \033[31m⚠  ATENÇÃO: A edição no PDF diverge do registry!\033[0m")
            print("     Verifique se o formulário foi atualizado pelo USCIS.")
            print(f"     Use --download para comparar com a versão oficial.")
    else:
        _status("Edição no PDF", "(não encontrada)", None)

    # ── Modo --download ────────────────────────────────────────────────────
    if args.download:
        print()
        print("  Comparando com versão oficial (download)...")
        pdf_url = entry.get("pdf_url", "")
        if not pdf_url:
            print("  ERRO: pdf_url não configurada no registry.", file=sys.stderr)
            sys.exit(1)

        live_data = download_pdf(pdf_url)
        if live_data is None:
            print("  Não foi possível baixar. Verifique sua conexão.", file=sys.stderr)
            sys.exit(1)

        live_hash = sha256_bytes(live_data)
        live_size = len(live_data)
        hashes_equal = (local_hash == live_hash)

        print()
        _status("SHA-256 oficial", live_hash[:16] + "…")
        _status("Tamanho oficial", f"{live_size:,} bytes")
        _status("Local == Oficial", "SIM — formulário atual" if hashes_equal else "NÃO — há nova versão!", hashes_equal)

        if not hashes_equal:
            print()
            print("  \033[33m⚠  Nova versão disponível!\033[0m")
            print("  Passos para atualizar:")
            print(f"    1. Salve o PDF em: {pdf_path}")
            print(f"       (substitua o arquivo atual)")
            print(f"    2. Execute:")
            print(f"       python scripts/inspect_form.py {pdf_path} --out data/mappings/{form_id.lower()}_novo.json")
            print(f"       python scripts/build_mapping.py")
            print(f"       python scripts/check_version.py {form_id} --update-hash")
            print()
            print("  \033[33m  Verifique se os campos mudaram antes de usar o novo mapeamento!\033[0m")

            # Salva o PDF novo automaticamente? Pergunta.
            try:
                resp = input("\n  Substituir o PDF local pelo novo? [s/N] ").strip().lower()
            except (EOFError, KeyboardInterrupt):
                resp = "n"
            if resp == "s":
                with open(pdf_path, "wb") as f:
                    f.write(live_data)
                entry["pdf_sha256"]    = live_hash
                entry["pdf_size_bytes"] = live_size
                registry["forms"][form_id] = entry
                REGISTRY_PATH.write_text(
                    json.dumps(registry, indent=2, ensure_ascii=False), encoding="utf-8"
                )
                print(f"  PDF atualizado: {pdf_path}")
                print(f"  Hash atualizado no registry.")
                print("  Execute inspect_form.py e build_mapping.py para verificar mudanças nos campos.")
        else:
            print()
            print("  \033[32m✓  O PDF local está atualizado.\033[0m")

    else:
        # Resultado do check local
        print()
        all_ok = (reg_hash == local_hash) if reg_hash else True
        if all_ok and edition_pdf and editions_match(edition_pdf, entry.get("edition","")):
            print("  \033[32m✓  Formulário local está na versão registrada.\033[0m")
            print("  Use --download para confirmar contra a versão oficial do USCIS.")
        elif not reg_hash:
            print("  \033[33m·  Sem hash no registry para comparar. Use --update-hash.\033[0m")
        else:
            print("  \033[31m✗  Divergência detectada. Use --download para investigar.\033[0m")

    print_fee_info(entry)
    print()


if __name__ == "__main__":
    main()
