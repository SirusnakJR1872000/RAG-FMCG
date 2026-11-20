FICTIONAL DOCUMENT — created for demonstration

# SOP-IT-003 Audit Trail Review for Computerised Systems

| Field | Value |
|---|---|
| Company | Acme Pharma Ltd. (fictional) |
| Document number | SOP-IT-003 |
| Version | 1.4 |
| Effective date | 2026-04-20 |
| Supersedes | Version 1.3 |
| Owner | Head of IT Quality and Compliance |
| Approved by | Head of Quality Assurance |
| Review period | 2 years |

## 1. Purpose

This procedure defines how audit trails of GMP computerised systems at Acme Pharma Ltd. are configured, reviewed and acted upon. Audit trail review provides assurance that GMP data are attributable, complete and have not been altered or deleted without authorisation.

## 2. Scope

This SOP applies to every computerised system classified as GMP-relevant in the system inventory, including the chromatography data system (CDS), LIMS, the electronic batch record (EBR) system, the eQMS and the electronic document management system (EDMS).

## 3. Responsibilities

| Role | Responsibility |
|---|---|
| System owner | Ensures the audit trail is enabled, configured and cannot be switched off by users. Defines which events are reviewed. |
| Data reviewer | Reviews audit trail entries relevant to each data set as part of routine data review (SOP-QC-011, SOP-PR-004). |
| Periodic reviewer (QA) | Performs the periodic system-level audit trail review defined in section 5.3. |
| IT | Maintains the technical configuration, the time synchronisation and the protection of audit trail data. |

## 4. Definitions

- **Audit trail:** a secure, computer-generated, time-stamped record of the actions that create, modify or delete GMP data, showing who did what, when, and why.
- **GMP-relevant change:** a change or deletion of GMP data, or a change to a configuration that affects how GMP data are generated, processed or stored.
- **Data-level review:** review of the audit trail entries linked to a specific data set, such as one analytical run or one batch.
- **System-level review:** review of system-wide events, such as user management, configuration changes, failed logins and audit trail settings.

## 5. Procedure

### 5.1 Audit trail requirements

5.1.1 Every GMP computerised system must record, for each GMP-relevant change or deletion: the user identity, the date and time, the old value, the new value, and the reason for the change.

5.1.2 Audit trails must be enabled at all times. Users, including administrators performing routine work, must not be able to switch off, edit or delete the audit trail.

5.1.3 System clocks are synchronised to the site time server. The system records time in UTC or with a stated time zone.

5.1.4 Audit trail data are retained for at least as long as the GMP records they relate to, and remain readable for the whole retention period.

5.1.5 These requirements are verified during validation of the system and after any change that could affect the audit trail configuration (SOP-QA-012).

### 5.2 Data-level review

5.2.1 Audit trail entries relevant to a data set are reviewed **before** the data are used for a GMP decision, such as batch release.

5.2.2 For analytical data, this review is part of the second-person data review under SOP-QC-011. For batch records, it is part of the batch record review under SOP-PR-004.

5.2.3 The reviewer looks for: deleted or modified results, repeated processing or integration, aborted runs, changes to methods or limits, and entries made outside normal working times without an explanation.

### 5.3 Periodic system-level review

5.3.1 QA performs a system-level audit trail review at a frequency based on system risk:

| System risk | Examples | Review frequency |
|---|---|---|
| High | CDS, LIMS, EBR | **Monthly** |
| Medium | eQMS, EDMS | **Quarterly** |
| Low | Building management system with GMP alarms only | **Annually** |

5.3.2 The system-level review covers:

- creation, modification and deactivation of user accounts and changes to user roles (see SOP-IT-006);
- **failed login attempts** and account lockouts;
- changes to system configuration, audit trail settings and time settings;
- use of administrator or privileged accounts; and
- data deletion events.

5.3.3 The review is recorded on form IT-003-F1 with the period covered, the reviewer, the events reviewed, and the outcome.

### 5.4 Findings

5.4.1 Any unexplained change or deletion of GMP data, any attempt to disable the audit trail, or any unauthorised use of a privileged account is treated as a **potential data integrity breach**.

5.4.2 The reviewer raises a deviation under SOP-QA-005 within **1 working day**. A potential data integrity breach is classified as critical until the investigation shows otherwise.

5.4.3 Where the finding shows a systemic weakness, for example a configuration that allows data deletion, a CAPA is raised under SOP-QA-008.

### 5.5 Systems without a compliant audit trail

5.5.1 Legacy systems that cannot record a compliant audit trail must be listed in the system inventory with a documented risk assessment.

5.5.2 Compensating controls are applied until the system is replaced. Examples include restricting access, printing and signing data at the time of generation, and logbooks recording each use.

5.5.3 Each legacy system has a replacement plan with a target date approved by the Head of QA.

## 6. Records

Audit trail review records are kept for the same period as the GMP data reviewed, and no less than **6 years**.

## 7. References

- EU GMP Annex 11, section 9 Audit Trails; section 12 Security; section 1 Risk Management.
- FDA Guidance, Part 11 Scope and Application, section III.C.2 Audit Trail and section III.C.3 Legacy Systems.
- ICH Q7, section 5.4 Computerized Systems.
- SOP-QC-011 Analytical Data Review; SOP-PR-004 Batch Record Review and Release Support; SOP-IT-006 User Access Management for GxP Systems; SOP-QA-005 Deviation Management; SOP-QA-008 CAPA Management; SOP-QA-012 Change Control.

## 8. Revision history

| Version | Date | Change |
|---|---|---|
| 1.3 | 2025-04-07 | Added the eQMS and EDMS to the scope. |
| 1.4 | 2026-04-20 | Set risk-based review frequencies (monthly, quarterly, annually); added failed logins to the system-level review. |
