# Migração Notion → Auto-Imigração — README

Guia dos arquivos de export e de como usá-los para importar os dados do Notion (workspace `marketing.saesprofessional@gmail.com`) no sistema Auto-Imigração.

## Arquivos

| Arquivo | Uso |
|---|---|
| `saes_notion_export_CLEAN.json` | **Fonte principal da migração.** Versão tratada do export original. |
| `saes_notion_export_claude_code.json` | Export original (bruto), mantido para referência/auditoria. |
| `saes_notion_export_claude_code.jsonl` | Mesmos registros, um por linha (útil para processamento em streaming). |
| `dedup_audit.json` | Auditoria da deduplicação de clientes. |
| `PROMPT_CLAUDE_CODE.md` | Prompt pronto para colar no Claude Code executar a importação. |

## O que a versão CLEAN mudou em relação ao original

1. **Rollups não resolvidos → `null`.** No export do Notion, 1.233 valores de campos de rollup vieram como o texto literal `"<rollup>"`. Eles foram convertidos para `null` para não poluir a importação. Campos afetados (só em cases): `First Contact`, `Ad Source`, `Closing Deal`, `Deadline`, `Documents`, `Translator`, `Review Status`, `Interest Options`, `Source`. **Esses valores não existem no export** — se forem necessários no sistema novo, é preciso reexportar resolvendo os rollups.
2. **Anexos com validade marcada.** Cada anexo de pagamento recebeu `_url_expires_at` e `_url_expired`. As URLs são links temporários da Amazon S3 (validade ~1 hora a partir da geração do export). **Baixe os 90 recibos imediatamente** — depois da expiração só reexportando.

## Estrutura do CLEAN.json

Objeto raiz com as chaves:

- `metadata` — workspace, origem, timestamps e bloco `cleaning` (o que foi tratado).
- `counts` — totais: `clients_raw` 8831, `clients_deduped` 2184, `client_duplicates_removed` 6647, `payments_all` 257, `cases_dashboard` 33, `cases_submitted_finalized` 104.
- `clients_all_deduped` — **2.184** clientes, já deduplicados (mantido o mais recente por nome).
- `client_deduplication_log` — **6.647** registros removidos, cada um com `duplicate_key`, `kept`, `kept_url`, `removed_url_from_export`.
- `payments_all` — **257** pagamentos.
- `cases_dashboard` — **33** casos ativos (view Dashboard).
- `cases_submitted_finalized` — **104** casos finalizados (view Submitted).

## Convenções de campo (importante para o mapeamento)

- **IDs do Notion:** cada registro tem `notion_page_id` (UUID) e `notion_url`. Use o `notion_page_id` como chave de idempotência e para religar relações.
- **IDs de negócio:** o campo `ID` é um objeto `{"number": N, "prefix": "CUS"|"PAY"}`. Ex.: cliente `CUS-9004`, pagamento `PAY-279`.
- **Relações:** vêm como **arrays de `notion_page_id`** apontando para outros registros. Ex.: em `payments_all`, `Client` e `Cases` são listas de UUIDs; em cases, `🧑‍💼 Client`, `Payments`, `📄 Documents`, `Tasks` idem. Resolva contra os `notion_page_id` dos clientes/cases.
- **Datas:** campos de data vêm como objeto `{"start","end","time_zone"}` ou `null`. Use `start`.
- **Nomes de campo com espaços/typos preservados do Notion:** `"Payment Date "` (espaço final), `"Approved  by"` (2 espaços), `"Case Monitoring  Started on"`, `"Ad  Source"`. Normalize no destino.
- **Booleans "sujos":** existem pares como `US Phone` (valor) e `US Phone?` (bool "possui?").
- **Credenciais em texto puro:** `USCIS Account Email/Password/Back Up Code`, `Email (Embassy)`, `Password(Embassy)`. **Criptografar na importação.**
- **Moeda:** pagamentos têm `Currency` (`USD`/`BRL`/`Other`) e `Amount Paid` numérico. Soma dos `Amount Paid` no export = **74.300,30**.

## Auditoria da deduplicação (resumo)

- Critério: nome **normalizado** (minúsculas + espaços colapsados); mantido o registro mais recente por data/ID.
- 2.160 nomes tinham duplicatas; 516 nomes com 5+ remoções; 57 com 10+.
- Os nomes mais fundidos são **nomes completos distintos** (ex.: "samira silva" 35×, "morgana luiz gomes" 17×) — padrão consistente com **cliente recorrente**, não homônimo. Risco de fusão indevida é baixo.
- **Risco residual:** dois clientes diferentes com exatamente o mesmo nome seriam unidos. Revise por amostragem os itens de `dedup_audit.json` → `top_50_para_revisao`, priorizando nomes genéricos.
- **Não pega variações de grafia/acentuação** (ex.: "João" vs "Joao") — pode haver duplicata residual entre esses.

## Limitações conhecidas

- Cases só contêm as views **Dashboard (33)** e **Submitted (104)** — não é o total de casos do sistema, apenas essas duas visões.
- Documentos e Tasks aparecem apenas como **referências (UUIDs)** dentro de clientes/cases; o conteúdo completo desses bancos não está neste export.
- E-mail presente em apenas 102/2.184 clientes (negócio majoritariamente via telefone/WhatsApp — 1.776 com telefone).
