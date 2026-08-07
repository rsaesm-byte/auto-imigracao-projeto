"""Detecção de edição simultânea (Seção 16/17, CRM SAES).

Optimistic concurrency control manual (não o `version_id_col` nativo do
SQLAlchemy, que só protege dentro de uma mesma transação/commit): o
cenário real aqui é entre duas requisições HTTP separadas -- staff A
abre a tela de edição, staff B edita e salva primeiro, staff A salva por
cima sem saber. A coluna `version` (app/db.py::VersionedMixin) e as duas
funções abaixo cobrem exatamente essa janela: o formulário leva a versão
que tinha quando foi carregado; a rota compara contra a versão atual no
banco ANTES de aplicar qualquer mudança.

Uso numa rota de edição:

    try:
        concurrency_service.checar_versao(registro, request.form.get("version"))
    except concurrency_service.ConflitoEdicaoError:
        flash("Este registro foi editado por outra pessoa enquanto você "
              "tinha esta página aberta. Recarregue antes de salvar.", "error")
        return redirect(...)

    registro.campo = ...  # aplica as mudanças normalmente

    concurrency_service.bump_versao(registro)
    SessionLocal.commit()
"""
from __future__ import annotations


class ConflitoEdicaoError(Exception):
    """Levantado por `checar_versao` quando a versão enviada pelo
    formulário não bate com a versão atual do registro no banco."""

    def __init__(self, entidade: str, entidade_id, versao_atual: int, versao_enviada: int):
        self.entidade = entidade
        self.entidade_id = entidade_id
        self.versao_atual = versao_atual
        self.versao_enviada = versao_enviada
        super().__init__(
            f"{entidade} {entidade_id}: versão enviada ({versao_enviada}) não "
            f"bate com a versão atual no banco ({versao_atual}) -- o registro "
            f"foi editado por outra pessoa nesse meio-tempo.")


def checar_versao(registro, versao_enviada_form: str | None) -> None:
    """Levanta `ConflitoEdicaoError` se `versao_enviada_form` (o valor do
    campo oculto `<input name="version">` do formulário de edição) não
    bater com `registro.version` (a versão atual, já carregada do banco
    nesta mesma requisição). Chamar isto ANTES de atribuir qualquer
    campo novo em `registro` -- o objetivo é abortar antes de sobrescrever,
    não depois.

    `versao_enviada_form` vazio/None passa sem checar (fail-open) -- é o
    caso de um formulário que ainda não foi migrado pra incluir o campo
    oculto, ou uma chamada feita fora de um form HTML (script, migração
    de dado). Preferir fail-open a quebrar toda rota que ainda não tem o
    campo, já que a checagem é aditiva sobre rotas já existentes."""
    if not versao_enviada_form:
        return
    try:
        versao_enviada = int(versao_enviada_form)
    except (TypeError, ValueError):
        return
    if versao_enviada != registro.version:
        raise ConflitoEdicaoError(
            type(registro).__name__, getattr(registro, "id", None),
            registro.version, versao_enviada)


def bump_versao(registro) -> None:
    """Incrementa `registro.version` -- chamar depois de aplicar as
    mudanças de campo, antes do commit, em toda rota que participa da
    detecção de edição simultânea daquela entidade."""
    registro.version += 1
