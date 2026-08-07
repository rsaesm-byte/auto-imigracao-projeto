"""TODO(Seção 10): reenvia pro S3 os arquivos hoje em
instance/document_storage/ quando as credenciais de object storage
chegarem.

Ainda não roda de verdade -- S3Storage (app/services/storage/s3.py)
levanta NotImplementedError até existir bucket/credenciais. Este script
já está pronto pra funcionar no dia em que isso acontecer, bastando:

1. Implementar app/services/storage/s3.py::S3Storage de verdade.
2. Definir DOCUMENT_STORAGE_BACKEND=s3 e as credenciais (env vars do
   boto3: AWS_ACCESS_KEY_ID, AWS_SECRET_ACCESS_KEY, bucket etc.).
3. Rodar: python scripts/migrate_local_to_s3.py [--dry-run]

O que ele faz: para cada DocumentoArquivoVersao no banco, lê o conteúdo
via LocalDiskStorage usando a `storage_key` já gravada, grava o MESMO
conteúdo no S3 sob a MESMA `storage_key` (via S3Storage), e confere o
sha-256 batendo com `DocumentoArquivoVersao.hash` antes de considerar a
versão migrada. Como a chave não muda, nenhuma linha do banco precisa
ser tocada -- só o backend por trás dela. Os arquivos locais NUNCA são
apagados por este script (nem em modo real): a limpeza de
instance/document_storage/ é uma decisão manual e separada, depois de
confirmar visualmente que a migração foi completa.
"""
from __future__ import annotations

import argparse
import hashlib
import sys

from app.db import SessionLocal
from app.document_storage_models import DocumentoArquivoVersao
from app.services.storage.local_disk import LocalDiskStorage
from app.services.storage.s3 import S3Storage


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true",
                         help="só lista o que seria migrado, não escreve no S3")
    args = parser.parse_args()

    try:
        destino = S3Storage()
    except NotImplementedError as exc:
        print(f"S3Storage ainda não está implementado: {exc}", file=sys.stderr)
        print("Este script é um TODO -- ver o docstring do topo do arquivo.", file=sys.stderr)
        sys.exit(1)

    origem = LocalDiskStorage()
    session = SessionLocal()
    versoes = session.query(DocumentoArquivoVersao).order_by(DocumentoArquivoVersao.id).all()

    migradas = falhas = 0
    for versao in versoes:
        chave = versao.storage_key
        if not origem.existe(chave):
            print(f"[FALHA] versao {versao.id}: chave {chave!r} não existe em disco local")
            falhas += 1
            continue

        conteudo = origem.ler(chave)
        if hashlib.sha256(conteudo).hexdigest() != versao.hash:
            print(f"[FALHA] versao {versao.id}: hash em disco não bate com o gravado no banco")
            falhas += 1
            continue

        if args.dry_run:
            print(f"[OK] (dry-run) versao {versao.id}: {chave!r}, {len(conteudo)} bytes")
        else:
            destino.salvar(conteudo, chave)
            print(f"[OK] versao {versao.id}: {chave!r} migrada")
        migradas += 1

    print(f"\n{migradas} versão(ões) migrada(s), {falhas} falha(s), de {len(versoes)} no total.")
    print("Arquivos locais preservados -- limpeza de instance/document_storage/ é manual.")


if __name__ == "__main__":
    main()
