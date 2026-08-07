# Prompt para o Claude Code — Importar CRM do Notion no schema real do Auto-Imigração

Cole o bloco abaixo no Claude Code, na raiz de `auto-imigracao-projeto`, com o arquivo
`saes_notion_export_CLEAN.json` presente (e `MIGRACAO_README.md` ao lado, opcional).
Este prompt já está adaptado ao schema REAL (`app/crm_models.py`, SQLAlchemy + SQLite `instance/app.db`).

---

```
# TAREFA: Importar o CRM legado do Notion para o banco real do Auto-Imigração

## Papel
Engenheiro de dados do projeto Auto-Imigração. Importe os dados exportados do CRM do
Notion para as tabelas SQLAlchemy REAIS deste repositório, de forma idempotente,
respeitando enums, lookups, criptografia de credenciais e valores em centavos.

## Leia antes de codar (nesta ordem)
- `app/crm_models.py` — modelos e enums reais (fonte da verdade do schema).
- `C:\Users\rsaes\.claude\plans\staged-frolicking-naur.md` — raciocínio de normalização Notion→relacional.
- `scripts/seed_demo_crm_data.py` — padrão de app factory, sessão de DB e criação de registros CRM. SIGA este padrão (não invente bootstrap novo).
- `app/services/crypto.py` — como criptografar credenciais.
- `app/crm_lookups.py` — helpers de leitura/seed das tabelas de lookup.
- `MIGRACAO_README.md` — convenções do export (idempotência, datas, relações, campos "sujos", anexos).

## Fonte: saes_notion_export_CLEAN.json (raiz do JSON)
- `clients_all_deduped` (2184) — JÁ deduplicados; NÃO refazer dedup.
- `cases_dashboard` (33) + `cases_submitted_finalized` (104) — unir e dedup por `notion_page_id`.
- `payments_all` (257).
- `client_deduplication_log`, `metadata`, `counts` — referência; não importar.

## Idempotência (DECISÃO NECESSÁRIA — me pergunte antes de aplicar)
Os modelos NÃO têm coluna de origem do Notion. Para permitir rodar 2x sem duplicar e
religar relações, proponho adicionar coluna nullable+única `notion_page_id` em
`crm_clients`, `crm_cases` e `crm_payments_ledger` (migração aditiva). 
Se você preferir não alterar schema, o fallback é casar por chave natural
(cliente: full_name normalizado; pagamento: description+amount+payment_date). 
Escreva a migração proposta e ESPERE minha aprovação antes de aplicar.

## Regras de conversão (Notion → schema real)
- **Dinheiro em CENTAVOS.** `crm_payments_ledger.amount_cents` = round(Notion "Amount Paid" * 100).
  Idem `discount_cents`. Notion guarda dólar float.
- **Datas:** objeto {start,end,time_zone} ou null → usar `start` como `date`.
- **Nomes de equipe → FK `users.id`.** "Approved  by"/"Reviewed by"/Responsible (Alessandra/
  Bárbara/Ricardo) NÃO são texto: resolva contra `users` (is_staff=True). Se não achar o
  usuário, deixe NULL e registre em import_warnings (não crie usuário fake).
- **Lookups (resolve-or-create)** contra as tabelas reais, via helpers de `app/crm_lookups.py`:
  `crm_lead_sources`, `crm_ad_sources`, `crm_contact_channels`, `crm_field_offices`,
  `crm_fee_types`, `crm_payment_methods`, `crm_close_loss_reasons`, `crm_income_source_types`.
- **Credenciais:** grave SEMPRE criptografadas via `app/services/crypto.py` em
  `crm_client_credentials` (uma linha por service uscis/embassy). NUNCA em texto puro nem em log.
- **Campos formula/rollup do Notion NÃO existem como coluna** (são calculados em
  `app/services/crm_service.py`). Ignore-os (no CLEAN já vêm null).

### Mapa de enums (use os valores EXATOS de app/crm_models.py)
CaseStatus: "Lead Capture & Qualification"→lead_capture; "Conversion & Onboarding"→onboarding;
  "Document Collection & Review"→document_collection; "Process Development & Preparation"→preparation;
  "Submission"→submission; "Follow-up"→follow_up; "Approved"→approved; "Denied"→denied;
  "Gave Up"→gave_up; "Lost Leads"→lost.
ProcessStatus: Intake→intake; Documents→documents; Preparation/Form Preparation→preparation;
  Review/"Final Review & Package Assembly"→review; "Ready to Submit"/"Ready for Submission"→ready_to_submit;
  Submitted→submitted; "Post Submission Monitoring"→post_submission; "RFE Handling"→rfe_handling;
  "Decision & Closing"→decision; Done→done. (valores ambíguos p.ex. "In progress"/"Internal Print
  Request" → escolha o mais próximo e registre em import_warnings).
Priority: Low→low; Medium→medium; High→high; Urgent→urgent.
PaymentStatus: Pending→pending; "Invoice Sent"→invoice_sent; "Partially Paid"→partially_paid;
  "In Dispute"→in_dispute; Paid→paid; Refunded→refunded; "Written Off"→written_off.
PaymentDirection: Receivables→receivable; Payables→payable.
Currency: USD→usd; BRL→brl; Other→other.
PreferredLanguage: Portuguese/PT→pt; English/ENG→en; Spanish/SPA→es.
MaritalStatus: Single→single; Married→married; Divorced→divorced; Widowed→widowed.
ClientTier: "Tier A".."Tier E" → a..e.

## Mapeamento por entidade (colunas reais)

CLIENTE → `crm_clients` (Client), a partir de clients_all_deduped:
  full_name=Client Name; email=Email; us_phone=US Phone; us_phone_has=US Phone?;
  home_phone=Home Country Phone; home_phone_has=Home Country Phone?; us_address=US Address;
  home_address=Home Country Address; city_country=City/Country; country_of_origin=Country of Origin;
  preferred_language=Preferred Language(enum); best_contact_time=Best Contact Time; dob=Date of Birth;
  marital_status=Marital Status(enum); marriage_date=Marriage Date; has_dependents=Has Dependents?;
  n_dependents=Number of Dependents; passport_expiration=Passport Expiration;
  current_status_visa=Current Status/Visa; status_expiration=Current Status Expiration;
  resident_since=Resident Since (LPR); gc_expiration=GC Expiration Date; tier=Status(enum A-E);
  five_letters=5 Letters; key_word=Key Word.
  → `crm_client_intake` (1:1): best_contact_period(enum) de "Qual o melhor horário para contato?"
     (normalize o texto livre p/ manha/tarde/noite); money_problem="Me conte seu maior problema...";
     monthly_income_range(enum) de "Faixa de Renda Mensal Familiar"; desired_solutions="Quais soluções...";
     how_found_us_id=lookup(How Did You Hear About Us?); referral_name=Referral Name;
     previous_service="Por favor selecione o serviço que você já fez conosco:".
     income sources ("De quais fontes...") → `crm_client_intake_income_sources` (M2M, resolve-or-create).
  → `crm_client_credentials` (CRIPTOGRAFADO): service=uscis (USCIS Account Email/Password/Back Up Code);
     service=embassy (Email (Embassy)/Password(Embassy)).
  → `crm_client_dependents`: se houver Dependent's Email / Dependent's Phone Number (USA).

CASO → `crm_cases` (Case), de cases_dashboard ∪ cases_submitted_finalized (dedup por notion_page_id):
  client_id=resolver rel('🧑‍💼 Client'); title=Case Title; case_status(enum)=Case Status;
  process_status(enum)=Process Status; priority(enum)=Priority; ready_for_next_step=(Go to Next Step=="Yes");
  responsible_id=FK users(Responsible); field_office_id=lookup(Field Office); receipt_number=Receipt Number;
  receipt_date=Receipt Date; submission_date=Submission Date; approval_date=Approval Date;
  denial_reason=(Reason for Denial se houver); service_deadline=Service Deadline;
  status_expire_on=Status Expire On; monitoring_started_at="Case Monitoring  Started on";
  next_check_at="Next Case Status check"; last_checked_at="Last Checked on"; rfe_received=Received an RFE/NOID;
  contract_signed=Contract Signed; terms_accepted=Terms Accepted; google_drive_url=Google Drive; notes=Notes.
  service_mode(enum, NOT NULL): derivar — se houver pacote Saes Standard/Plus associado use-o; senão
    default `saes_standard` e liste em import_warnings para revisão (é o modelo full-service do CRM legado).
  → `crm_case_step_log`: uma linha append-only por valor de "Current Step" (step_name=texto, done_at=melhor data disponível).
  → `crm_case_services`: resolver "✅ Services"/"Previous Service" contra `crm_services_catalog`
     (resolve-or-create por nome), role=current/previous.
  → `crm_case_tracked_forms` (PONTE USCIS): derive form_number a partir do serviço/tipo:
        GC (AOS)→"I-485" (+ "I-130" se familiar); GC Consular→"I-130"; GC ROC/Removal of Conditions→"I-751";
        Citizenship→"N-400"; I-765/Work Authorization→"I-765"; Travel Document→"I-131"; K1→"I-129F";
        COS B2/F1/F2, EOS/Extension→"I-539"; AR-11→"AR-11"; RFE→(rfe), NOID→(noid), Reinstatement, I-290B, I-824.
     application_type=valor do enum ApplicationType quando aplicável; filing_method=online por padrão;
     finalized_at=Completed on (só p/ casos vindos de cases_submitted_finalized); copie receipt/approval/monitoring.
     Formulários fora do catálogo de forms do produto → apenas registrar em import_report.forms_a_cadastrar.

PAGAMENTO → `crm_payments_ledger` (PaymentLedgerEntry), de payments_all:
  case_id=resolver rel(Cases); client_id=resolver rel(Client); description=Description;
  amount_cents=round(Amount Paid*100); currency(enum)=Currency; direction(enum)=Type of Payment;
  status(enum)=Status; payment_method_id=lookup(Payment Method); package_id=lookup catálogo(Package, se != Not Applicable);
  invoice_date=Invoice Date; due_date=Due Date; payment_date="Payment Date "; approved_by_id=FK users("Approved  by");
  reviewed_by_id=FK users(Reviewed by); discount_cents=(Discount/Special Price se numérico); notes=juntar Confirmation Note + Paymente Notes.
  → `crm_payment_ledger_fee_types` (M2M): resolver "Type of Fee/Payment" contra `crm_fee_types`.
  Anexos (Attach Receipt): se `_url_expired`=false, baixar e salvar em `instance/payment_proofs/`
    (mesmo diretório já usado pelo app); se true, registrar pendente. NUNCA logar as URLs assinadas.

## Execução
1. Escrever `MAPA_DE_CAMPOS.md` confirmando origem→coluna real + a migração `notion_page_id` proposta. PARAR e pedir aprovação.
2. Implementar como `scripts/import_notion_crm.py` no padrão de `seed_demo_crm_data.py`, com `--dry-run` (default TRUE).
3. Rodar `--dry-run` e apresentar: contagens por tabela, relações resolvidas x órfãs, FKs de staff não resolvidos,
   forms derivados, forms_a_cadastrar, e 3 amostras mapeadas por entidade. PARAR p/ aprovação.
4. Após aprovação e BACKUP de `instance/app.db` (copiar p/ instance/app.db.bak-pre-notion-import-<ts>, padrão do projeto), rodar `--commit`.
5. Gerar `import_report.json`.

## Critérios de aceitação
- 2.184 clientes, casos (33+104 dedup), 257 pagamentos upsertados no app.db.
- Σ amount_cents / 100 = 74300.30 (reportar divergência).
- Rodar 2x seguidas NÃO duplica.
- Nenhuma credencial em texto puro (verificar que colunas *_encrypted não são reversíveis sem crypto).
- Todo pagamento com rel válido aponta para client/case reais; órfãos em import_warnings.
- Backup do app.db criado antes do commit.

Comece lendo crm_models.py, o plano e seed_demo_crm_data.py; depois me mostre o MAPA_DE_CAMPOS.md e a migração antes de codar.
```

---

## Resumo do que confirmei no seu projeto (para você, Rick)

- O CRM **existe e está maduro**: tabelas reais `crm_clients`, `crm_cases`, `crm_payments_ledger`,
  além de intake, credenciais (criptografadas), dependentes, serviços, step-log, documentos,
  comunicações, tarefas e **`crm_case_tracked_forms`** (a ponte caso→formulário USCIS, com I-539 já suportado via checklist).
- O schema **já foi desenhado a partir do Notion** (o código cita os 13 bancos/57 views e há um plano em `.claude/plans/`).
- Por isso o prompt foi ajustado aos nomes e enums reais, com 3 armadilhas tratadas:
  **(1)** dinheiro em **centavos**; **(2)** nomes de equipe viram **FK de `users`**; **(3)** não há
  coluna de origem Notion — proponho adicionar `notion_page_id` para importação idempotente (com sua aprovação).
- Salvei o prompt **dentro do projeto** como `IMPORT_NOTION_PROMPT.md`, então já está no diretório onde você roda o Claude Code.
