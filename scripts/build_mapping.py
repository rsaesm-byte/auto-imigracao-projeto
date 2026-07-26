"""
build_mapping.py — Aplica os question_id ao esqueleto de mapeamento do I-130.

Uso:
    python scripts/build_mapping.py
    # Sobrescreve data/mappings/i-130.json com question_id preenchidos.
"""

import json
import re
from pathlib import Path

# ── Regras de base: nome-do-campo → { question_id, check_if_answer?, notes? }
# Para checkboxes de grupo (radio/checkbox no PDF): check_if_answer = valor que ativa.
# Campos gerados ou internos: question_id = "_ignore"
MAPPING_RULES: dict[str, dict] = {

    "PDF417BarCode1":         {"question_id": "_ignore", "notes": "Código de barras automático"},
    "CheckBox1":              {"question_id": "_ignore", "notes": "Checkbox representação advogado"},
    "VolagNumber":            {"question_id": "_ignore", "notes": "Número VOLAG interno"},
    "AttorneyStateBarNumber": {"question_id": "_ignore", "notes": "OAB/Bar do advogado"},
    "USCISOnlineAcctNumber":  {"question_id": "_ignore", "notes": "Conta USCIS Online do advogado"},

    # Parte 1 — Relação
    "Pt1Line1_Spouse":   {"question_id": "rel_tipo", "check_if_answer": "conjuge"},
    "Pt1Line1_Child":    {"question_id": "rel_tipo", "check_if_answer": "filho"},
    "Pt1Line1_Parent":   {"question_id": "rel_tipo", "check_if_answer": "pai_mae"},
    "Pt1Line1_Siblings": {"question_id": "rel_tipo", "check_if_answer": "irmao"},
    "Pt1Line2_InWedlock":    {"question_id": "rel_tipo_filho", "check_if_answer": "legitimo"},
    "Pt1Line2_AdoptedChild": {"question_id": "rel_tipo_filho", "check_if_answer": "adotado"},
    "Pt1Line2_Stepchild":    {"question_id": "rel_tipo_filho", "check_if_answer": "enteado"},
    "Pt1Line2_OutOfWedlock": {"question_id": "rel_tipo_filho", "check_if_answer": "ilegitimo"},
    "Pt1Line3_Yes": {"question_id": "rel_cidad_nato",        "check_if_answer": "sim"},
    "Pt1Line3_No":  {"question_id": "rel_cidad_nato",        "check_if_answer": "nao"},
    "Pt1Line4_Yes": {"question_id": "rel_pai_fora_casamento","check_if_answer": "sim"},
    "Pt1Line4_No":  {"question_id": "rel_pai_fora_casamento","check_if_answer": "nao"},

    # Parte 2 — Peticionário: nome
    "Pt2Line4a_FamilyName":           {"question_id": "pet_sobrenome"},
    "Pt2Line4b_GivenName":            {"question_id": "pet_nome"},
    "Pt2Line4c_MiddleName":           {"question_id": "pet_nome_meio"},
    "Pt2Line5a_FamilyName":           {"question_id": "pet_outros_sobrenome"},
    "Pt2Line5b_GivenName":            {"question_id": "pet_outros_nome"},
    "Pt2Line5c_MiddleName":           {"question_id": "pet_outros_meio"},
    "Pt2Line1_AlienNumber":           {"question_id": "pet_alien_number"},
    "Pt2Line2_USCISOnlineActNumber":  {"question_id": "pet_uscis_online"},
    "Pt2Line11_SSN":                  {"question_id": "pet_ssn"},
    "Pt2Line6_CityTownOfBirth":       {"question_id": "pet_cidade_nascimento"},
    "Pt2Line7_CountryofBirth":        {"question_id": "pet_pais_nascimento"},
    "Pt2Line8_DateofBirth":           {"question_id": "pet_data_nascimento"},
    "Pt2Line9_Male":   {"question_id": "pet_sexo", "check_if_answer": "masculino"},
    "Pt2Line9_Female": {"question_id": "pet_sexo", "check_if_answer": "feminino"},
    "Pt2Line11_Yes":   {"question_id": "pet_nos_eua", "check_if_answer": "sim"},
    "Pt2Line11_No":    {"question_id": "pet_nos_eua", "check_if_answer": "nao"},

    # Parte 2 — Endereço atual
    "Pt2Line10_StreetNumberName": {"question_id": "pet_end_rua"},
    "Pt2Line10_AptSteFlrNumber":  {"question_id": "pet_end_num_unidade"},
    "Pt2Line10_InCareofName":     {"question_id": "pet_end_cuidados_de"},
    "Pt2Line10_CityOrTown":       {"question_id": "pet_end_cidade"},
    "Pt2Line10_State":            {"question_id": "pet_end_estado"},
    "Pt2Line10_ZipCode":          {"question_id": "pet_end_cep"},
    "Pt2Line10_Province":         {"question_id": "pet_end_provincia"},
    "Pt2Line10_PostalCode":       {"question_id": "pet_end_codigo_postal"},
    "Pt2Line10_Country":          {"question_id": "pet_end_pais"},
    "Pt2Line13a_DateFrom":        {"question_id": "pet_end_desde"},

    # Parte 2 — Endereço anterior 1
    "Pt2Line12_StreetNumberName": {"question_id": "pet_end_ant1_rua"},
    "Pt2Line12_AptSteFlrNumber":  {"question_id": "pet_end_ant1_num_unidade"},
    "Pt2Line12_CityOrTown":       {"question_id": "pet_end_ant1_cidade"},
    "Pt2Line12_State":            {"question_id": "pet_end_ant1_estado"},
    "Pt2Line12_ZipCode":          {"question_id": "pet_end_ant1_cep"},
    "Pt2Line12_Province":         {"question_id": "pet_end_ant1_provincia"},
    "Pt2Line12_PostalCode":       {"question_id": "pet_end_ant1_codigo_postal"},
    "Pt2Line12_Country":          {"question_id": "pet_end_ant1_pais"},
    "Pt2Line15a_DateFrom":        {"question_id": "pet_end_ant1_de"},
    "Pt2Line15b_DateTo":          {"question_id": "pet_end_ant1_ate"},

    # Parte 2 — Endereço anterior 2
    "Pt2Line14_StreetNumberName": {"question_id": "pet_end_ant2_rua"},
    "Pt2Line14_AptSteFlrNumber":  {"question_id": "pet_end_ant2_num_unidade"},
    "Pt2Line14_CityOrTown":       {"question_id": "pet_end_ant2_cidade"},
    "Pt2Line14_State":            {"question_id": "pet_end_ant2_estado"},
    "Pt2Line14_ZipCode":          {"question_id": "pet_end_ant2_cep"},
    "Pt2Line14_Province":         {"question_id": "pet_end_ant2_provincia"},
    "Pt2Line14_PostalCode":       {"question_id": "pet_end_ant2_codigo_postal"},
    "Pt2Line14_Country":          {"question_id": "pet_end_ant2_pais"},
    "Pt2Line13b_DateTo":          {"question_id": "pet_end_ant2_ate"},

    # Parte 2 — Estado civil
    "Pt2Line16_NumberofMarriages":{"question_id": "pet_num_casamentos"},
    "Pt2Line17_Single":    {"question_id": "pet_estado_civil", "check_if_answer": "solteiro"},
    "Pt2Line17_Married":   {"question_id": "pet_estado_civil", "check_if_answer": "casado"},
    "Pt2Line17_Divorced":  {"question_id": "pet_estado_civil", "check_if_answer": "divorciado"},
    "Pt2Line17_Widowed":   {"question_id": "pet_estado_civil", "check_if_answer": "viuvo"},
    "Pt2Line17_Separated": {"question_id": "pet_estado_civil", "check_if_answer": "separado"},
    "Pt2Line17_Annulled":  {"question_id": "pet_estado_civil", "check_if_answer": "anulado"},
    "Pt2Line18_DateOfMarriage": {"question_id": "pet_data_casamento"},
    "Pt2Line19a_CityTown":      {"question_id": "pet_local_casamento_cidade"},
    "Pt2Line19b_State":         {"question_id": "pet_local_casamento_estado"},
    "Pt2Line19c_Province":      {"question_id": "pet_local_casamento_provincia"},
    "Pt2Line19d_Country":       {"question_id": "pet_local_casamento_pais"},
    "PtLine20a_FamilyName":     {"question_id": "pet_conj_ant1_sobrenome"},
    "Pt2Line20b_GivenName":     {"question_id": "pet_conj_ant1_nome"},
    "Pt2Line20c_MiddleName":    {"question_id": "pet_conj_ant1_meio"},
    "Pt2Line21_DateMarriageEnded": {"question_id": "pet_conj_ant1_fim"},
    "Pt2Line22a_FamilyName":    {"question_id": "pet_conj_ant2_sobrenome"},
    "Pt2Line22b_GivenName":     {"question_id": "pet_conj_ant2_nome"},
    "Pt2Line22c_MiddleName":    {"question_id": "pet_conj_ant2_meio"},
    "Pt2Line23_DateMarriageEnded": {"question_id": "pet_conj_ant2_fim"},
    "Pt2Line23a_checkbox": {"question_id": "pet_conj_ant2_fim_como", "check_if_answer": "divorcio"},
    "Pt2Line23b_checkbox": {"question_id": "pet_conj_ant2_fim_como", "check_if_answer": "viuvez"},
    "Pt2Line23c_checkbox": {"question_id": "pet_conj_ant2_fim_como", "check_if_answer": "anulacao"},

    # Parte 2 — Pais do peticionário
    "Pt2Line24_FamilyName": {"question_id": "pet_pai_sobrenome"},
    "Pt2Line24_GivenName":  {"question_id": "pet_pai_nome"},
    "Pt2Line24_MiddleName": {"question_id": "pet_pai_meio"},
    "Pt2Line25_DateofBirth":{"question_id": "pet_pai_data_nasc"},
    "Pt2Line26_Male":       {"question_id": "pet_pai_sexo", "check_if_answer": "masculino"},
    "Pt2Line26_Female":     {"question_id": "pet_pai_sexo", "check_if_answer": "feminino"},
    "Pt2Line27_CountryofBirth":          {"question_id": "pet_pai_pais_nasc"},
    "Pt2Line28_CityTownOrVillageOfResidence": {"question_id": "pet_pai_cidade_resid"},
    "Pt2Line29_CountryOfResidence":      {"question_id": "pet_pai_pais_resid"},
    "Pt2Line30a_FamilyName":{"question_id": "pet_mae_sobrenome"},
    "Pt2Line30b_GivenName": {"question_id": "pet_mae_nome"},
    "Pt2Line30c_MiddleName":{"question_id": "pet_mae_meio"},
    "Pt2Line31_DateofBirth":{"question_id": "pet_mae_data_nasc"},
    "Pt2Line32_Male":       {"question_id": "pet_mae_sexo", "check_if_answer": "masculino"},
    "Pt2Line32_Female":     {"question_id": "pet_mae_sexo", "check_if_answer": "feminino"},
    "Pt2Line33_CountryofBirth":          {"question_id": "pet_mae_pais_nasc"},
    "Pt2Line34_CityTownOrVillageOfResidence": {"question_id": "pet_mae_cidade_resid"},
    "Pt2Line35_CountryOfResidence":      {"question_id": "pet_mae_pais_resid"},
    "Pt2Line36_USCitizen":  {"question_id": "pet_cidadania_tipo", "check_if_answer": "cidadao"},
    "Pt2Line36_LPR":        {"question_id": "pet_cidadania_tipo", "check_if_answer": "lpr"},
    "Pt2Line36_Yes":        {"question_id": "_ignore"},
    "Pt2Line36_No":         {"question_id": "_ignore"},
    "Pt2Line37a_CertificateNumber": {"question_id": "pet_cert_nat_numero"},
    "Pt2Line37b_PlaceOfIssuance":   {"question_id": "pet_cert_nat_local"},
    "Pt2Line37c_DateOfIssuance":    {"question_id": "pet_cert_nat_data"},

    # Parte 2 — Emprego atual
    "Pt2Line40_EmployerOrCompName":  {"question_id": "pet_emp_atual_empresa"},
    "Pt2Line40a_ClassOfAdmission":   {"question_id": "pet_emp_atual_classe_admissao"},
    "Pt2Line40b_DateOfAdmission":    {"question_id": "pet_emp_atual_data_admissao"},
    "Pt2Line40d_CityOrTown":         {"question_id": "pet_emp_atual_cidade"},
    "Pt2Line40e_State":              {"question_id": "pet_emp_atual_estado"},
    "Pt2Line41_Yes":                 {"question_id": "_ignore"},
    "Pt2Line41_No":                  {"question_id": "_ignore"},
    "Pt2Line41_StreetNumberName":    {"question_id": "pet_emp_atual_rua"},
    "Pt2Line41_AptSteFlrNumber":     {"question_id": "pet_emp_atual_num_unidade"},
    "Pt2Line41_CityOrTown":          {"question_id": "pet_emp_atual_cidade"},
    "Pt2Line41_State":               {"question_id": "pet_emp_atual_estado"},
    "Pt2Line41_ZipCode":             {"question_id": "pet_emp_atual_cep"},
    "Pt2Line41_Province":            {"question_id": "pet_emp_atual_provincia"},
    "Pt2Line41_PostalCode":          {"question_id": "pet_emp_atual_codigo_postal"},
    "Pt2Line41_Country":             {"question_id": "pet_emp_atual_pais"},
    "Pt2Line42_Occupation":          {"question_id": "pet_emp_atual_ocupacao"},
    "Pt2Line43a_DateFrom":           {"question_id": "pet_emp_atual_de"},
    "Pt2Line43b_DateTo":             {"question_id": "pet_emp_atual_ate"},
    "Pt2Line44_EmployerOrOrgName":   {"question_id": "pet_emp_ant_empresa"},
    "Pt2Line45_StreetNumberName":    {"question_id": "pet_emp_ant_rua"},
    "Pt2Line45_AptSteFlrNumber":     {"question_id": "pet_emp_ant_num_unidade"},
    "Pt2Line45_CityOrTown":          {"question_id": "pet_emp_ant_cidade"},
    "Pt2Line45_State":               {"question_id": "pet_emp_ant_estado"},
    "Pt2Line45_ZipCode":             {"question_id": "pet_emp_ant_cep"},
    "Pt2Line45_Province":            {"question_id": "pet_emp_ant_provincia"},
    "Pt2Line45_PostalCode":          {"question_id": "pet_emp_ant_codigo_postal"},
    "Pt2Line45_Country":             {"question_id": "pet_emp_ant_pais"},
    "Pt2Line46_Occupation":          {"question_id": "pet_emp_ant_ocupacao"},
    "Pt2Line47a_DateFrom":           {"question_id": "pet_emp_ant_de"},
    "Pt2Line47b_DateTo":             {"question_id": "pet_emp_ant_ate"},

    # Parte 3 — Biográfico (não indexados)
    "Pt3Line2_Race_White":      {"question_id": "pet_raca", "check_if_answer": "branco"},
    "Pt3Line2_Race_Black":      {"question_id": "pet_raca", "check_if_answer": "negro"},
    "Pt3Line2_Race_AmericanIndianAlaskaNative": {"question_id": "pet_raca", "check_if_answer": "indigena_alaska"},
    "Pt3Line2_Race_Asian":      {"question_id": "pet_raca", "check_if_answer": "asiatico"},
    "Pt3Line2_Race_NativeHawaiianOtherPacificIslander": {"question_id": "pet_raca", "check_if_answer": "pacifico"},
    "Pt3Line3_HeightFeet":      {"question_id": "pet_altura_pes"},
    "Pt3Line3_HeightInches":    {"question_id": "pet_altura_polegadas"},
    "Pt3Line4_Pound1":          {"question_id": "pet_peso", "notes": "Centena do peso em libras"},
    "Pt3Line4_Pound2":          {"question_id": "pet_peso", "notes": "Dezena do peso em libras"},
    "Pt3Line4_Pound3":          {"question_id": "pet_peso", "notes": "Unidade do peso em libras"},

    # Parte 4 — Beneficiário: nome
    "Pt4Line1_AlienNumber":          {"question_id": "ben_alien_number"},
    "Pt4Line2_USCISOnlineActNumber": {"question_id": "ben_uscis_online"},
    "Pt4Line3_SSN":                  {"question_id": "ben_ssn"},
    "Pt4Line4a_FamilyName":          {"question_id": "ben_sobrenome"},
    "Pt4Line4b_GivenName":           {"question_id": "ben_nome"},
    "Pt4Line4c_MiddleName":          {"question_id": "ben_nome_meio"},
    "P4Line5a_FamilyName":           {"question_id": "ben_outros_sobrenome"},
    "Pt4Line5b_GivenName":           {"question_id": "ben_outros_nome"},
    "Pt4Line5c_MiddleName":          {"question_id": "ben_outros_meio"},
    "Pt4Line7_CityTownOfBirth":      {"question_id": "ben_cidade_nascimento"},
    "Pt4Line8_CountryOfBirth":       {"question_id": "ben_pais_nascimento"},
    "Pt4Line9_DateOfBirth":          {"question_id": "ben_data_nascimento"},
    "Pt4Line9_Male":   {"question_id": "ben_sexo", "check_if_answer": "masculino"},
    "Pt4Line9_Female": {"question_id": "ben_sexo", "check_if_answer": "feminino"},
    "Pt4Line10_Yes":     {"question_id": "ben_cidadania_us", "check_if_answer": "cidadao"},
    "Pt4Line10_No":      {"question_id": "ben_cidadania_us", "check_if_answer": "nenhum"},
    "Pt4Line10_Unknown": {"question_id": "ben_cidadania_us", "check_if_answer": "desconhece"},
    "Pt4Line14_DaytimePhoneNumber": {"question_id": "ben_telefone"},
    "Pt4Line15_MobilePhoneNumber":  {"question_id": "_ignore"},
    "Pt4Line16_EmailAddress":       {"question_id": "_ignore"},

    # Parte 4 — Endereço atual beneficiário
    "Pt4Line11_StreetNumberName": {"question_id": "ben_end_rua"},
    "Pt4Line11_AptSteFlrNumber":  {"question_id": "ben_end_num_unidade"},
    "Pt4Line11_CityOrTown":       {"question_id": "ben_end_cidade"},
    "Pt4Line11_State":            {"question_id": "ben_end_estado"},
    "Pt4Line11_ZipCode":          {"question_id": "ben_end_cep"},
    "Pt4Line11_Province":         {"question_id": "ben_end_provincia"},
    "Pt4Line11_PostalCode":       {"question_id": "ben_end_codigo_postal"},
    "Pt4Line11_Country":          {"question_id": "ben_end_pais"},
    "Pt4Line12a_StreetNumberName":{"question_id": "ben_end_corr_rua"},
    "Pt4Line12b_AptSteFlrNumber": {"question_id": "ben_end_corr_num_unidade"},
    "Pt4Line12c_CityOrTown":      {"question_id": "ben_end_corr_cidade"},
    "Pt4Line12d_State":           {"question_id": "ben_end_corr_estado"},
    "Pt4Line12e_ZipCode":         {"question_id": "ben_end_corr_cep"},
    "Pt4Line13_StreetNumberName": {"question_id": "ben_end_ant_rua"},
    "Pt4Line13_AptSteFlrNumber":  {"question_id": "ben_end_ant_num_unidade"},
    "Pt4Line13_CityOrTown":       {"question_id": "ben_end_ant_cidade"},
    "Pt4Line13_Province":         {"question_id": "ben_end_ant_provincia"},
    "Pt4Line13_PostalCode":       {"question_id": "ben_end_ant_codigo_postal"},
    "Pt4Line13_Country":          {"question_id": "ben_end_ant_pais"},

    # Parte 4 — Estado civil beneficiário
    "Pt4Line17_NumberofMarriages": {"question_id": "ben_num_casamentos"},
    "Pt4Line18a_FamilyName":       {"question_id": "ben_conj_sobrenome"},
    "Pt4Line18b_GivenName":        {"question_id": "ben_conj_nome"},
    "Pt4Line18c_MiddleName":       {"question_id": "ben_conj_meio"},
    "Pt4Line19_DateOfMarriage":    {"question_id": "ben_data_casamento"},
    "Pt4Line20a_CityTown":         {"question_id": "ben_local_casamento_cidade"},
    "Pt4Line20b_State":            {"question_id": "ben_local_casamento_estado"},
    "Pt4Line20c_Province":         {"question_id": "ben_local_casamento_provincia"},
    "Pt4Line20d_Country":          {"question_id": "ben_local_casamento_pais"},
    "Pt4Line16a_FamilyName":       {"question_id": "ben_conj_ant1_sobrenome"},
    "Pt4Line16b_GivenName":        {"question_id": "ben_conj_ant1_nome"},
    "Pt4Line16c_MiddleName":       {"question_id": "ben_conj_ant1_meio"},

    # Parte 4 — Pais do beneficiário
    "Pt4Line6a_FamilyName":  {"question_id": "ben_pai1_sobrenome"},
    "Pt4Line6b_GivenName":   {"question_id": "ben_pai1_nome"},
    "Pt4Line6c_MiddleName":  {"question_id": "ben_pai1_meio"},
    "Pt4Line7_Relationship": {"question_id": "ben_pai1_relacao"},
    "Pt4Line8a_FamilyName":  {"question_id": "ben_pai2_sobrenome"},
    "Pt4Line8b_GivenName":   {"question_id": "ben_pai2_nome"},
    "Pt4Line8c_MiddleName":  {"question_id": "ben_pai2_meio"},
    "Pt4Line9_Relationship": {"question_id": "ben_pai2_relacao"},

    # Parte 4 — Filhos
    "Pt4Line30a_FamilyName":  {"question_id": "ben_filho1_sobrenome"},
    "Pt4Line30b_GivenName":   {"question_id": "ben_filho1_nome"},
    "Pt4Line30c_MiddleName":  {"question_id": "ben_filho1_meio"},
    "Pt4Line31_Relationship": {"question_id": "ben_filho1_relacao"},
    "Pt4Line32_DateOfBirth":  {"question_id": "ben_filho1_nasc"},
    "Pt4Line34a_FamilyName":  {"question_id": "ben_filho2_sobrenome"},
    "Pt4Line34b_GivenName":   {"question_id": "ben_filho2_nome"},
    "Pt4Line34c_MiddleName":  {"question_id": "ben_filho2_meio"},
    "Pt4Line35_Relationship": {"question_id": "ben_filho2_relacao"},
    "Pt4Line36_DateOfBirth":  {"question_id": "ben_filho2_nasc"},
    "Pt4Line37_CountryOfBirth":{"question_id": "ben_filho2_pais_nasc"},
    "Pt4Line38a_FamilyName":  {"question_id": "ben_filho3_sobrenome"},
    "Pt4Line38b_GivenName":   {"question_id": "ben_filho3_nome"},
    "Pt4Line38c_MiddleName":  {"question_id": "ben_filho3_meio"},
    "Pt4Line39_Relationship": {"question_id": "ben_filho3_relacao"},
    "Pt4Line40_DateOfBirth":  {"question_id": "ben_filho3_nasc"},
    "Pt4Line41_CountryOfBirth":{"question_id": "ben_filho3_pais_nasc"},
    "Pt4Line42a_FamilyName":  {"question_id": "ben_filho4_sobrenome"},
    "Pt4Line42b_GivenName":   {"question_id": "ben_filho4_nome"},
    "Pt4Line42c_MiddleName":  {"question_id": "ben_filho4_meio"},
    "Pt4Line43_Relationship": {"question_id": "ben_filho4_relacao"},
    "Pt4Line44_DateOfBirth":  {"question_id": "ben_filho4_nasc"},
    "Pt4Line45_CountryOfBirth":{"question_id": "ben_filho4_pais_nasc"},
    "Pt4Line46a_FamilyName":  {"question_id": "ben_filho5_sobrenome"},
    "Pt4Line46b_GivenName":   {"question_id": "ben_filho5_nome"},
    "Pt4Line46c_MiddleName":  {"question_id": "ben_filho5_meio"},
    "Pt4Line47_Relationship": {"question_id": "ben_filho5_relacao"},
    "Pt4Line48_DateOfBirth":  {"question_id": "ben_filho5_nasc"},

    # Parte 4 — Imigração
    "Pt4Line20_Yes":               {"question_id": "ben_nos_eua", "check_if_answer": "sim"},
    "Pt4Line20_No":                {"question_id": "ben_nos_eua", "check_if_answer": "nao"},
    "Pt4Line21a_ClassOfAdmission": {"question_id": "ben_classe_admissao"},
    "Pt4Line21b_ArrivalDeparture": {"question_id": "ben_i94"},
    "Pt4Line21c_DateOfArrival":    {"question_id": "ben_data_chegada"},
    "Pt4Line21d_DateExpired":      {"question_id": "ben_data_exp_status"},
    "Pt4Line22_PassportNumber":    {"question_id": "ben_passaporte_numero"},
    "Pt4Line23_TravelDocNumber":   {"question_id": "ben_doc_viagem_numero"},
    "Pt4Line24_CountryOfIssuance": {"question_id": "ben_passaporte_pais_emissao"},
    "Pt4Line25_ExpDate":           {"question_id": "ben_passaporte_exp"},

    # Parte 4 — Emprego beneficiário
    "Pt4Line26_NameOfCompany":    {"question_id": "ben_emp_empresa"},
    "Pt4Line26_StreetNumberName": {"question_id": "ben_emp_rua"},
    "Pt4Line26_AptSteFlrNumber":  {"question_id": "ben_emp_num_unidade"},
    "Pt4Line26_CityOrTown":       {"question_id": "ben_emp_cidade"},
    "Pt4Line26_State":            {"question_id": "ben_emp_estado"},
    "Pt4Line26_ZipCode":          {"question_id": "ben_emp_cep"},
    "Pt4Line26_Province":         {"question_id": "ben_emp_provincia"},
    "Pt4Line26_PostalCode":       {"question_id": "ben_emp_codigo_postal"},
    "Pt4Line26_Country":          {"question_id": "ben_emp_pais"},
    "Pt4Line27_DateEmploymentBegan":{"question_id": "ben_emp_inicio"},
    "Pt4Line28_Yes": {"question_id": "ben_emp_tem_anterior", "check_if_answer": "sim"},
    "Pt4Line28_No":  {"question_id": "ben_emp_tem_anterior", "check_if_answer": "nao"},

    # Parte 4 — Processos de remoção
    "Part4Line1_Yes": {"question_id": "ben_processo_remocao", "check_if_answer": "sim"},
    "Part4Line1_No":  {"question_id": "ben_processo_remocao", "check_if_answer": "nao"},
    "Pt4Line54_Removal":            {"question_id": "ben_tipo_processo", "check_if_answer": "remocao"},
    "Pt4Line54_Exclusion":          {"question_id": "ben_tipo_processo", "check_if_answer": "exclusao"},
    "Pt4Line54_Rescission":         {"question_id": "ben_tipo_processo", "check_if_answer": "rescisao"},
    "Pt4Line54_JudicialProceedings":{"question_id": "ben_tipo_processo", "check_if_answer": "procedimento_jud"},
    "Pt4Line55a_FamilyName":        {"question_id": "ben_processo_nome_sobrenome"},
    "Pt4Line55b_GivenName":         {"question_id": "ben_processo_nome_nome"},
    "Pt4Line55c_MiddleName":        {"question_id": "ben_processo_nome_meio"},
    "Pt4Line55a_CityOrTown":        {"question_id": "ben_processo_cidade",
                                     "notes": "Cidade do processo de remoção"},
    "Pt4Line55b_State":             {"question_id": "ben_processo_estado",
                                     "notes": "Estado do processo de remoção"},
    "Pt4Line56_Date":               {"question_id": "ben_processo_data"},
    "Pt4Line56_StreetNumberName":   {"question_id": "ben_emp_ant_rua"},
    "Pt4Line56_AptSteFlrNumber":    {"question_id": "_ignore"},
    "Pt4Line56_CityOrTown":         {"question_id": "ben_emp_ant_cidade"},
    "Pt4Line56_Province":           {"question_id": "ben_emp_ant_provincia"},
    "Pt4Line56_Country":            {"question_id": "ben_emp_ant_pais"},
    "Pt4Line56_PostalCode":         {"question_id": "ben_emp_ant_codigo_postal"},
    "Pt4Line57_StreetNumberName":   {"question_id": "_ignore"},
    "Pt4Line57_AptSteFlrNumber":    {"question_id": "_ignore"},
    "Pt4Line57_CityOrTown":         {"question_id": "ben_end_ext_cidade"},
    "Pt4Line57_Province":           {"question_id": "ben_end_ext_provincia"},
    "Pt4Line57_Country":            {"question_id": "ben_end_ext_pais"},
    "Pt4Line57_PostalCode":         {"question_id": "_ignore"},
    "Pt4Line57_ZipCode":            {"question_id": "_ignore"},
    "Pt4Line57_State":              {"question_id": "_ignore"},
    "Pt4Line58a_DateFrom":          {"question_id": "ben_emp_ant_de"},
    "Pt4Line58b_DateTo":            {"question_id": "ben_emp_ant_ate"},
    "Pt4Line60a_CityOrTown":        {"question_id": "ben_processo_cidade"},
    "Pt4Line60b_State":             {"question_id": "ben_processo_estado"},
    "Pt4Line61a_CityOrTown":        {"question_id": "_ignore"},
    "Pt4Line61b_Province":          {"question_id": "_ignore"},
    "Pt4Line61c_Country":           {"question_id": "_ignore"},
    "Pt4Line53_DaytimePhoneNumber": {"question_id": "ben_telefone_deport"},
    "Pt4Line36_USCitizen": {"question_id": "_ignore"},
    "Pt4Line36_LPR":       {"question_id": "_ignore"},
    "Pt4Line36_Yes":       {"question_id": "_ignore"},
    "Pt4Line36_No":        {"question_id": "_ignore"},
    "Pt4Line37a_CertificateNumber": {"question_id": "_ignore"},
    "Pt4Line37b_PlaceOfIssuance":   {"question_id": "_ignore"},
    "Pt4Line37c_DateOfIssuance":    {"question_id": "_ignore"},

    # Parte 5 — Petição anterior
    "Pt5Line2a_FamilyName": {"question_id": "pet_ant_sobrenome"},
    "Pt5Line2b_GivenName":  {"question_id": "pet_ant_nome"},
    "Pt5Line2c_MiddleName": {"question_id": "pet_ant_meio"},
    "Pt5Line3a_CityOrTown": {"question_id": "pet_ant_local_cidade"},
    "Pt5Line3b_State":      {"question_id": "pet_ant_local_estado"},
    "Pt5Line4_DateFiled":   {"question_id": "pet_ant_data"},
    "Pt5Line5_Result":      {"question_id": "pet_ant_resultado"},

    # Parte 6 — Declaração
    "Pt6Line1b_Language":           {"question_id": "ass_idioma_interprete"},
    "Pt6Line2_Checkbox":            {"question_id": "ass_tem_representante", "check_if_answer": "sim"},
    "Pt6Line2_RepresentativeName":  {"question_id": "ass_representante_nome"},
    "Pt6Line3_DaytimePhoneNumber":  {"question_id": "ass_telefone"},
    "Pt6Line4_MobileNumber":        {"question_id": "ass_celular"},
    "Pt6Line5_Email":               {"question_id": "ass_email"},
    "Pt6Line6b_DateofSignature":    {"question_id": "ass_data"},
    "P5_Line6a_SignatureofApplicant":{"question_id": "_ignore"},

    # Parte 7 — Intérprete
    "Pt7Line1a_InterpreterFamilyName":   {"question_id": "int_sobrenome"},
    "Pt7Line1b_InterpreterGivenName":    {"question_id": "int_nome"},
    "Pt7Line2_InterpreterBusinessorOrg": {"question_id": "int_empresa"},
    "Pt7Line3_StreetNumberName":         {"question_id": "int_rua"},
    "Pt7Line3_AptSteFlrNumber":          {"question_id": "int_num_unidade"},
    "Pt7Line3_CityOrTown":               {"question_id": "int_cidade"},
    "Pt7Line3_State":                    {"question_id": "int_estado"},
    "Pt7Line3_ZipCode":                  {"question_id": "int_cep"},
    "Pt7Line3_Country":                  {"question_id": "int_pais"},
    "Pt7Line3_Province":                 {"question_id": "int_provincia"},
    "Pt7Line3_PostalCode":               {"question_id": "int_codigo_postal"},
    "Pt7Line4_InterpreterDaytimeTelephone": {"question_id": "int_telefone"},
    "Pt7Line5_Email":                    {"question_id": "int_email"},
    "Pt7_NameofLanguage":                {"question_id": "int_idioma"},
    "Pt7Line7b_DateofSignature":         {"question_id": "int_data_assinatura"},
    "Pt7Line7a_Signature":               {"question_id": "_ignore"},

    # Parte 8 — Preparador
    "Pt8Line1a_PreparerFamilyName": {"question_id": "prep_sobrenome"},
    "Pt8Line1b_PreparerGivenName":  {"question_id": "prep_nome"},
    "Pt8Line2_BusinessName":        {"question_id": "prep_empresa"},
    "Pt8Line3_StreetNumberName":    {"question_id": "prep_rua"},
    "Pt8Line3_AptSteFlrNumber":     {"question_id": "prep_num_unidade"},
    "Pt8Line3_CityOrTown":          {"question_id": "prep_cidade"},
    "Pt8Line3_State":               {"question_id": "prep_estado"},
    "Pt8Line3_ZipCode":             {"question_id": "prep_cep"},
    "Pt8Line3_Country":             {"question_id": "prep_pais"},
    "Pt8Line3_Province":            {"question_id": "prep_provincia"},
    "Pt8Line3_PostalCode":          {"question_id": "prep_codigo_postal"},
    "Pt8Line4_DaytimePhoneNumber":  {"question_id": "prep_telefone"},
    "Pt8Line5_PreparerFaxNumber":   {"question_id": "prep_fax"},
    "Pt8Line6_Email":               {"question_id": "prep_email"},
    "Pt8Line8a_Signature":          {"question_id": "_ignore"},
    "Pt8Line8b_DateofSignature":    {"question_id": "prep_data_assinatura"},

    # Parte 9 — Informações adicionais
    "Pt9Line3a_PageNumber":    {"question_id": "_ignore"},
    "Pt9Line3b_PartNumber":    {"question_id": "_ignore"},
    "Pt9Line3c_ItemNumber":    {"question_id": "_ignore"},
    "Pt9Line3d_AdditionalInfo":{"question_id": "_ignore"},
    "Pt9Line4a_PageNumber":    {"question_id": "_ignore"},
    "Pt9Line4b_PartNumber":    {"question_id": "_ignore"},
    "Pt9Line4c_ItemNumber":    {"question_id": "_ignore"},
    "Pt9Line4d_AdditionalInfo":{"question_id": "_ignore"},
    "Pt9Line5a_PageNumber":    {"question_id": "_ignore"},
    "Pt9Line5b_PartNumber":    {"question_id": "_ignore"},
    "Pt9Line5c_ItemNumber":    {"question_id": "_ignore"},
    "Pt9Line5d_AdditionalInfo":{"question_id": "_ignore"},
    "Pt9Line6a_PageNumber":    {"question_id": "_ignore"},
    "Pt9Line6b_PartNumber":    {"question_id": "_ignore"},
    "Pt9Line6c_ItemNumber":    {"question_id": "_ignore"},
    "Pt9Line6d_AdditionalInfo":{"question_id": "_ignore"},
    "Pt9Line7b_PartNumber":    {"question_id": "_ignore"},
    "Pt9Line7c_ItemNumber":    {"question_id": "_ignore"},
    "Pt9Line7d_AdditionalInfo":{"question_id": "_ignore"},
    "Pt9Line9a_PageNumber":    {"question_id": "_ignore"},
    "Pt8Line7_Checkbox":       {"question_id": "_ignore"},
    "Pt8Line7b_Checkbox":      {"question_id": "_ignore"},
}

# ── Regras para campos COM ÍNDICE que mudam de question_id ou check_if_answer ──
# Formato: base_name -> lista indexada de dicts (índice 0, 1, 2 ...)
INDEXED_RULES: dict[str, list[dict]] = {

    # Endereços — tipo de unidade: [0]=Apt, [1]=Ste, [2]=Flr
    # Cada entrada mapeia: (question_id do endereço, check_if_answer)
    "Pt2Line10_Unit":  [("pet_end_tipo_unidade",      "apt"), ("pet_end_tipo_unidade",      "ste"), ("pet_end_tipo_unidade",      "flr")],
    "Pt2Line12_Unit":  [("pet_end_ant1_tipo_unidade",  "apt"), ("pet_end_ant1_tipo_unidade",  "ste"), ("pet_end_ant1_tipo_unidade",  "flr")],
    "Pt2Line14_Unit":  [("pet_end_ant2_tipo_unidade",  "apt"), ("pet_end_ant2_tipo_unidade",  "ste"), ("pet_end_ant2_tipo_unidade",  "flr")],
    "Pt2Line41_Unit":  [("pet_emp_atual_tipo_unidade", "apt"), ("pet_emp_atual_tipo_unidade", "ste"), ("pet_emp_atual_tipo_unidade", "flr")],
    "Pt2Line45_Unit":  [("pet_emp_ant_tipo_unidade",   "apt"), ("pet_emp_ant_tipo_unidade",   "ste"), ("pet_emp_ant_tipo_unidade",   "flr")],
    "Pt4Line11_Unit":  [("ben_end_tipo_unidade",       "apt"), ("ben_end_tipo_unidade",       "ste"), ("ben_end_tipo_unidade",       "flr")],
    "Pt4Line12b_Unit": [("ben_end_corr_tipo_unidade",  "apt"), ("ben_end_corr_tipo_unidade",  "ste"), ("ben_end_corr_tipo_unidade",  "flr")],
    "Pt4Line13_Unit":  [("ben_end_ant_tipo_unidade",   "apt"), ("ben_end_ant_tipo_unidade",   "ste"), ("ben_end_ant_tipo_unidade",   "flr")],
    "Pt4Line26_Unit":  [("ben_emp_tipo_unidade",       "apt"), ("ben_emp_tipo_unidade",       "ste"), ("ben_emp_tipo_unidade",       "flr")],
    "Pt4Line56_Unit":  [("_ignore", None), ("_ignore", None), ("_ignore", None)],
    "Pt4Line57_Unit":  [("_ignore", None), ("_ignore", None), ("_ignore", None)],
    "Pt7Line3_Unit":   [("int_tipo_unidade",           "apt"), ("int_tipo_unidade",           "ste"), ("int_tipo_unidade",           "flr")],
    "Pt8Line3_Unit":   [("prep_tipo_unidade",          "apt"), ("prep_tipo_unidade",          "ste"), ("prep_tipo_unidade",          "flr")],

    # Etnia: [0]=hispânico, [1]=não hispânico
    "Pt3Line1_Ethnicity": [
        ("pet_etnia", "hispanico"),
        ("pet_etnia", "nao_hispanico"),
    ],

    # Cor dos olhos: [0-8]
    "Pt3Line5_EyeColor": [
        ("pet_cor_olhos", "preto"),
        ("pet_cor_olhos", "castanho"),
        ("pet_cor_olhos", "azul"),
        ("pet_cor_olhos", "cinza"),
        ("pet_cor_olhos", "verde"),
        ("pet_cor_olhos", "avel"),
        ("pet_cor_olhos", "rosa"),
        ("pet_cor_olhos", "bicolor"),
        ("pet_cor_olhos", "outro"),
    ],

    # Cor do cabelo: [0-8]
    "Pt3Line6_HairColor": [
        ("pet_cor_cabelo", "preto"),
        ("pet_cor_cabelo", "castanho"),
        ("pet_cor_cabelo", "loiro"),
        ("pet_cor_cabelo", "ruivo"),
        ("pet_cor_cabelo", "grisalho"),
        ("pet_cor_cabelo", "branco"),
        ("pet_cor_cabelo", "careca"),
        ("pet_cor_cabelo", "arenoso"),
        ("pet_cor_cabelo", "outro"),
    ],

    # Estado civil do beneficiário: [0-5]
    "Pt4Line18_MaritalStatus": [
        ("ben_estado_civil", "solteiro"),
        ("ben_estado_civil", "casado"),
        ("ben_estado_civil", "divorciado"),
        ("ben_estado_civil", "viuvo"),
        ("ben_estado_civil", "separado"),
        ("ben_estado_civil", "anulado"),
    ],

    # Declaração — leu em inglês ou via intérprete: [0]=ingles, [1]=interprete
    "Pt6Line1Checkbox": [
        ("ass_leu_ingles", "leu_ingles"),
        ("ass_leu_ingles", "leu_interprete"),
    ],

    # Datas de término de casamento do beneficiário (2 campos de texto distintos)
    "Pt4Line17_DateMarriageEnded": [
        ("ben_conj_ant1_fim1", None),  # texto, sem check_if_answer
        ("ben_conj_ant1_fim2", None),
    ],

    # País de nascimento do filho — [0]=filho1, [1]=filho5
    "Pt4Line49_CountryOfBirth": [
        ("ben_filho1_pais_nasc", None),
        ("ben_filho5_pais_nasc", None),
    ],
}


def parse_field_index(pdf_field: str) -> tuple[str, int]:
    """Extrai nome-base e índice do último componente da path.

    Exemplos:
        "...Pt2Line10_Unit[1]"  → ("Pt2Line10_Unit", 1)
        "...Pt2Line10_Unit[0]"  → ("Pt2Line10_Unit", 0)
        "...Pt2Line4a_FamilyName[0]" → ("Pt2Line4a_FamilyName", 0)
    """
    last = pdf_field.split(".")[-1]
    m = re.match(r"^([^\[]+)\[(\d+)\]$", last)
    if m:
        return m.group(1), int(m.group(2))
    m2 = re.match(r"^([^\[]+)", last)
    return (m2.group(1) if m2 else last), 0


def apply_mapping(skeleton_path: Path, out_path: Path) -> None:
    data = json.loads(skeleton_path.read_text(encoding="utf-8"))
    matched = 0
    unmatched: list[str] = []

    for field in data["fields"]:
        base_name, idx = parse_field_index(field["pdf_field"])

        # 1. Try indexed rules first (index-aware)
        if base_name in INDEXED_RULES:
            variants = INDEXED_RULES[base_name]
            if idx < len(variants):
                qid, check = variants[idx]
                field["question_id"] = qid
                if check is not None:
                    field["check_if_answer"] = check
                elif "check_if_answer" in field:
                    del field["check_if_answer"]
                matched += 1
                continue
            # idx out of range: fall through to base rules

        # 2. Base name lookup
        rule = MAPPING_RULES.get(base_name)
        if rule:
            field["question_id"] = rule["question_id"]
            if "check_if_answer" in rule:
                field["check_if_answer"] = rule["check_if_answer"]
            elif "check_if_answer" in field:
                del field["check_if_answer"]
            if "notes" in rule:
                field["notes"] = rule["notes"]
            matched += 1
        else:
            if field["type"] != "unknown":
                unmatched.append(base_name)

    out_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"Mapeados: {matched} campos")
    if unmatched:
        print(f"Sem mapeamento ({len(set(unmatched))} nomes únicos, {len(unmatched)} campos):")
        for name in sorted(set(unmatched)):
            print(f"  - {name}")
    else:
        print("Todos os campos cobertos.")


if __name__ == "__main__":
    base = Path("C:/Users/rsaes/auto-imigracao-projeto")
    apply_mapping(
        base / "data/mappings/i-130.json",
        base / "data/mappings/i-130.json",
    )
