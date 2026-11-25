// The controlled corpus as shown on the public landing page. It mirrors corpus/manifest.yaml
// (PROJECT_SPEC §6.1); src/landing/corpus.test.js fails if the two drift apart.
// The page is public, so it cannot call the authenticated GET /api/documents.

export const PUBLIC_GUIDANCE = [
  ['ICH-Q7', 'Good Manufacturing Practice Guide for Active Pharmaceutical Ingredients'],
  ['ICH-Q9R1', 'Quality Risk Management Q9(R1)'],
  ['ICH-Q10', 'Pharmaceutical Quality System'],
  ['FDA-PV-2011', 'Process Validation: General Principles and Practices'],
  ['FDA-P11-2003', 'Part 11, Electronic Records; Electronic Signatures — Scope and Application'],
  ['EU-ANNEX11', 'EU GMP Annex 11: Computerised Systems'],
  ['WHO-GMP-MAIN', 'WHO Good Manufacturing Practices for Pharmaceutical Products: Main Principles'],
]

export const FICTIONAL_SOPS = [
  ['ACME-SOP-IT-003', 'Audit Trail Review for Computerised Systems'],
  ['ACME-SOP-IT-006', 'User Access Management for GxP Systems'],
  ['ACME-SOP-PR-004', 'Batch Record Review and Release Support'],
  ['ACME-SOP-QA-001', 'Document Control'],
  ['ACME-SOP-QA-005', 'Deviation Management'],
  ['ACME-SOP-QA-008', 'CAPA Management'],
  ['ACME-SOP-QA-012', 'Change Control'],
  ['ACME-SOP-QA-015', 'Product Quality Review'],
  ['ACME-SOP-QA-019', 'Supplier Qualification'],
  ['ACME-SOP-QC-007', 'Out-of-Specification (OOS) Investigation'],
  ['ACME-SOP-QC-011', 'Analytical Data Review'],
  ['ACME-SOP-VA-002', 'Process Validation Lifecycle'],
]
