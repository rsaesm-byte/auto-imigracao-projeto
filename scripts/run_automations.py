"""Roda todas as Automations ativas (Prompt Mestre, Seção 7 -- "Ciclo de
vida dos serviços"), 2026-08-06.

Por que um script em vez de um scheduler embutido no site: o app roda
hoje via `waitress`/servidor dev Flask (ver wsgi.py), sem nenhuma
infraestrutura de tarefa em segundo plano -- adicionar uma (ex.:
APScheduler) mudaria o comportamento em produção do processo web inteiro
(thread nova rodando dentro do mesmo processo) só pra isso, uma decisão
grande demais pra tomar sem confirmar com o usuário. Este script faz a
MESMA coisa que o botão "Run all active automations now" da tela admin
(/staff/crm/automacoes) -- só chamado de fora, agendado pelo sistema
operacional (Agendador de Tarefas do Windows, ex.: todo dia às 7h),
não de dentro do processo do site.

Rodar manualmente: python scripts/run_automations.py
(da raiz do projeto, mesmo venv do site)

Agendar no Windows: Agendador de Tarefas -> Criar Tarefa Básica ->
Diariamente -> Ação: iniciar um programa ->
Programa: caminho do python.exe do venv
Argumentos: scripts\\run_automations.py
Iniciar em: C:\\Users\\rsaes\\auto-imigracao-projeto
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app import create_app
from app.services import automation_service as autosvc
from app.services import crm_service as svc


def main() -> None:
    app = create_app()
    with app.app_context():
        results_by_rule = autosvc.run_all_active_rules(svc.today(), dry_run=False)
        total = 0
        for rule_id, results in results_by_rule.items():
            for r in results:
                total += 1
                status = r["run"].status.value
                text = r["run"].result_text or r["run"].error_text
                print(f"[rule {rule_id}] case #{r['case'].id} ({r['case'].title}): {status} -- {text}")
        print(f"Done. {total} action(s) executed across {len(results_by_rule)} active rule(s).")


if __name__ == "__main__":
    main()
