"""Testes da detecção de edição simultânea (Seção 16/17).

Cobre o mecanismo em dois níveis:
- unitário: app/services/concurrency_service.py isolado (sem Flask, sem
  banco de dado real -- um objeto qualquer com atributo `version` serve).
- integração: as duas rotas que já usam o mecanismo,
  `crm_pipeline.client_update` e `crm_ops.case_details_update` (ver
  app/crm_staff_pipeline.py e app/crm_staff_ops.py), through o
  test client Flask de verdade contra o banco de teste (tests/conftest.py).
"""
from __future__ import annotations

import pytest

from app.services import concurrency_service


class _Registro:
    """Dublê mínimo de um modelo com VersionedMixin (app/db.py) -- só
    precisa do atributo `version` pros testes unitários abaixo."""

    def __init__(self, version: int = 1):
        self.id = 1
        self.version = version


# --------------------------------------------------------------------------
# Unitário: app/services/concurrency_service.py isolado
# --------------------------------------------------------------------------

def test_checar_versao_passa_quando_bate():
    registro = _Registro(version=3)
    concurrency_service.checar_versao(registro, "3")  # não deve levantar


def test_checar_versao_levanta_conflito_quando_diverge():
    registro = _Registro(version=3)
    with pytest.raises(concurrency_service.ConflitoEdicaoError) as exc_info:
        concurrency_service.checar_versao(registro, "2")
    erro = exc_info.value
    assert erro.versao_atual == 3
    assert erro.versao_enviada == 2


@pytest.mark.parametrize("versao_form", [None, "", "não-é-um-número"])
def test_checar_versao_fail_open_para_valor_ausente_ou_invalido(versao_form):
    """Formulário sem o campo oculto (tela ainda não migrada) ou um valor
    quebrado não deve travar a rota -- fail-open é intencional."""
    registro = _Registro(version=5)
    concurrency_service.checar_versao(registro, versao_form)  # não deve levantar


def test_bump_versao_incrementa():
    registro = _Registro(version=1)
    concurrency_service.bump_versao(registro)
    assert registro.version == 2
    concurrency_service.bump_versao(registro)
    assert registro.version == 3


# --------------------------------------------------------------------------
# Integração: rotas reais via Flask test client
# --------------------------------------------------------------------------

# Cada requisição via `logged_in_client` empurra e derruba um app
# context de verdade, o que dispara `SessionLocal.remove()` no teardown
# (app/__init__.py) e desanexa qualquer objeto ORM carregado antes da
# request. Por isso os testes abaixo capturam ids/valores primitivos
# ANTES de cada `.post()` e recarregam um objeto fresco via `db.get(...)`
# depois -- nunca reusam o objeto de fixture original pós-request.

def test_client_update_feliz_incrementa_versao(logged_in_client, client_record, db):
    from app.crm_models import Client

    client_id = client_record.id
    assert client_record.version == 1

    resp = logged_in_client.post(
        f"/staff/crm/clientes/{client_id}/salvar",
        data={"full_name": "Novo Nome", "version": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    reloaded = db.get(Client, client_id)
    assert reloaded.full_name == "Novo Nome"
    assert reloaded.version == 2


def test_client_update_detecta_edicao_simultanea(logged_in_client, client_record, db):
    """Simula duas abas: as duas carregam o cliente na versão 1; a
    primeira salva (vai pra versão 2); a segunda tenta salvar levando a
    versão 1 (desatualizada) -- tem que ser rejeitada, e o nome gravado
    pela primeira não pode ser sobrescrito."""
    from app.crm_models import Client

    client_id = client_record.id

    resp1 = logged_in_client.post(
        f"/staff/crm/clientes/{client_id}/salvar",
        data={"full_name": "Salvo Primeiro", "version": "1"},
        follow_redirects=True,
    )
    assert resp1.status_code == 200
    reloaded = db.get(Client, client_id)
    assert reloaded.full_name == "Salvo Primeiro"
    assert reloaded.version == 2

    # segunda "aba" ainda manda a versão antiga (1)
    resp2 = logged_in_client.post(
        f"/staff/crm/clientes/{client_id}/salvar",
        data={"full_name": "Tentativa Atrasada", "version": "1"},
        follow_redirects=True,
    )
    assert resp2.status_code == 200
    assert b"edited by someone else" in resp2.data

    reloaded = db.get(Client, client_id)
    assert reloaded.full_name == "Salvo Primeiro", "conflito devia ter impedido a sobrescrita"
    assert reloaded.version == 2, "tentativa rejeitada não pode incrementar a versão"


def test_case_details_update_feliz_incrementa_versao(logged_in_client, case_record, db):
    from app.crm_models import Case

    case_id = case_record.id
    priority_value = case_record.priority.value
    assert case_record.version == 1

    resp = logged_in_client.post(
        f"/staff/crm/casos/{case_id}/detalhes",
        data={"priority": priority_value, "notes": "primeira nota", "version": "1"},
        follow_redirects=True,
    )
    assert resp.status_code == 200

    reloaded = db.get(Case, case_id)
    assert reloaded.notes == "primeira nota"
    assert reloaded.version == 2


def test_case_details_update_detecta_edicao_simultanea(logged_in_client, case_record, db):
    from app.crm_models import Case

    case_id = case_record.id
    priority_value = case_record.priority.value

    resp1 = logged_in_client.post(
        f"/staff/crm/casos/{case_id}/detalhes",
        data={"priority": priority_value, "notes": "nota da primeira aba", "version": "1"},
        follow_redirects=True,
    )
    assert resp1.status_code == 200
    reloaded = db.get(Case, case_id)
    assert reloaded.notes == "nota da primeira aba"
    assert reloaded.version == 2

    resp2 = logged_in_client.post(
        f"/staff/crm/casos/{case_id}/detalhes",
        data={"priority": priority_value, "notes": "nota atrasada da segunda aba", "version": "1"},
        follow_redirects=True,
    )
    assert resp2.status_code == 200
    assert b"edited by someone else" in resp2.data

    reloaded = db.get(Case, case_id)
    assert reloaded.notes == "nota da primeira aba", "conflito devia ter impedido a sobrescrita"
    assert reloaded.version == 2


def test_case_details_update_sem_campo_version_ainda_funciona(logged_in_client, case_record, db):
    """Fail-open: uma chamada sem o campo `version` (ex.: script antigo,
    request manual) não deve ser bloqueada -- é o comportamento
    documentado de checar_versao."""
    from app.crm_models import Case

    case_id = case_record.id
    priority_value = case_record.priority.value

    resp = logged_in_client.post(
        f"/staff/crm/casos/{case_id}/detalhes",
        data={"priority": priority_value, "notes": "sem campo version"},
        follow_redirects=True,
    )
    assert resp.status_code == 200
    reloaded = db.get(Case, case_id)
    assert reloaded.notes == "sem campo version"
