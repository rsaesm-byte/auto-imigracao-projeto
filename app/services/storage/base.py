"""Interface de armazenamento de arquivos (Seção 10, CRM SAES).

A Seção 10 está bloqueada no backend físico -- as credenciais de object
storage (S3) ainda não existem. Em vez de esperar, esta interface isola
TUDO que a aplicação sabe sobre "onde os bytes moram" atrás de quatro
métodos. `DocumentStorageService` (app/services/document_storage_service.py)
e os modelos (app/document_storage_models.py) só conhecem esta interface e
a chave opaca que ela devolve -- nunca um caminho de disco, um bucket ou
qualquer outro detalhe do backend.

Quando as credenciais do S3 chegarem, o trabalho é escrever mais uma
implementação desta mesma interface -- ver o stub em
app/services/storage/s3.py -- e trocar `DOCUMENT_STORAGE_BACKEND=s3`
(app/services/storage/__init__.py::get_storage_backend). Nada em
document_storage_service.py, nos modelos ou nas rotas precisa mudar.
"""
from __future__ import annotations

import abc


class StorageBackend(abc.ABC):
    """Backend de storage de arquivos.

    `chave` é sempre uma string opaca no formato
    "documentos/{caso_id}/{uuid}" -- quem gera a chave é
    `DocumentStorageService`, não o backend. O backend só sabe salvar,
    ler, excluir e checar existência de uma chave; nunca decide o
    formato dela.
    """

    @abc.abstractmethod
    def salvar(self, dados: bytes, chave: str) -> str:
        """Grava `dados` sob `chave`. Retorna a própria `chave` (o
        chamador já a escolheu; o retorno existe só pra manter a
        interface simétrica com backends que no futuro possam
        normalizá-la, ex.: prefixo de bucket)."""
        raise NotImplementedError

    @abc.abstractmethod
    def ler(self, chave: str) -> bytes:
        """Lê e retorna o conteúdo bruto gravado sob `chave`."""
        raise NotImplementedError

    @abc.abstractmethod
    def excluir(self, chave: str) -> None:
        """Apaga o arquivo físico sob `chave`. Usado só pela ferramenta
        de manutenção/migração -- o fluxo normal de exclusão do
        documento é lógico (`DocumentStorageService.excluir`) e nunca
        chama isto."""
        raise NotImplementedError

    @abc.abstractmethod
    def existe(self, chave: str) -> bool:
        """True se houver um arquivo gravado sob `chave`."""
        raise NotImplementedError
