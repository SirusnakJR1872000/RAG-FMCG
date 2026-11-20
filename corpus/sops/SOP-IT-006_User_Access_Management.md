FICTIONAL DOCUMENT — created for demonstration

# SOP-IT-006 User Access Management for GxP Systems

| Field | Value |
|---|---|
| Company | Acme Pharma Ltd. (fictional) |
| Document number | SOP-IT-006 |
| Version | 2.0 |
| Effective date | 2026-05-11 |
| Supersedes | Version 1.2 |
| Owner | Head of IT Quality and Compliance |
| Approved by | Head of Quality Assurance |
| Review period | 2 years |

## 1. Purpose

This procedure describes how user access to GxP computerised systems at Acme Pharma Ltd. is requested, approved, granted, reviewed and removed. It ensures that only authorised people can access GMP systems, that each person has only the access needed for their job, and that every action can be attributed to one individual.

## 2. Scope

This SOP applies to all GxP computerised systems in the system inventory, for all users: employees, contractors, supplier service engineers and system administrators.

## 3. Responsibilities

| Role | Responsibility |
|---|---|
| Line manager | Requests access for their staff and confirms that training is complete. Notifies IT of role changes and leavers. |
| System owner | Defines the user roles and their permissions, approves access requests and performs the periodic access review. |
| IT system administrator | Creates, changes and deactivates accounts as approved. Must not approve their own access. |
| QA | Approves the role definitions and reviews the results of periodic access reviews. |

## 4. Principles

4.1 **Unique accounts.** Each user has a personal account. Shared or generic accounts for GMP work are prohibited.

4.2 **Least privilege.** Users receive only the permissions needed for their tasks.

4.3 **Segregation of duties.** Users who generate or approve GMP data must not have administrator rights in the same system. System administrators perform administration only, using a separate administrator account.

4.4 **Accounts are never deleted.** Accounts of leavers are deactivated, not deleted, so that the audit trail remains attributable. User identifiers are never reused.

## 5. Procedure

### 5.1 Requesting and granting access

5.1.1 The line manager submits an access request in the IT service portal, stating the system, the role and the business reason.

5.1.2 The system owner approves the request. Access is granted only after the user's training on the system and its role is recorded.

5.1.3 The administrator creates the account with a temporary password that the user must change at first login.

### 5.2 Password and session rules

5.2.1 Passwords must have at least **12 characters** and must not match any of the user's last **5** passwords.

5.2.2 Passwords expire every **90 days** unless the system uses single sign-on with multi-factor authentication.

5.2.3 An account is locked after **5 consecutive failed login attempts**. Unlocking requires a request through the IT service desk and verification of the user's identity.

5.2.4 Sessions lock automatically after **15 minutes** of inactivity on shop-floor and laboratory workstations.

5.2.5 Users must never share passwords or let another person work under their login. Doing so is a data integrity breach handled under SOP-QA-005.

### 5.3 Role changes

When a user changes job, the line manager requests the new role within **5 working days**, and access not needed for the new job is removed at the same time.

### 5.4 Leavers

5.4.1 HR notifies IT of each leaver. The accounts of a leaver are deactivated **on their last working day**.

5.4.2 For involuntary terminations, accounts are deactivated before the person is informed, or immediately afterwards.

### 5.5 Emergency and supplier access

5.5.1 Emergency access with elevated privileges may be granted for a maximum of **24 hours**, with approval from the system owner and QA. All actions during emergency access are reviewed afterwards using the audit trail.

5.5.2 Supplier service engineers receive time-limited named accounts, enabled only for the duration of the service visit.

### 5.6 Periodic access review

5.6.1 The system owner reviews all accounts and their roles at a frequency based on system risk: **every 6 months** for High risk systems (CDS, LIMS, EBR) and **annually** for other GxP systems.

5.6.2 The review confirms that each active account belongs to a current employee or contractor, that the role matches the job, and that no dormant accounts remain. Accounts not used for **90 days** are deactivated unless justified.

5.6.3 Discrepancies, such as a leaver with an active account, are corrected immediately and recorded. If the account was used after the person left, a deviation is raised under SOP-QA-005.

## 6. Records

Access requests, approvals, access review records and account histories are kept for the lifetime of the system plus **6 years**.

## 7. References

- EU GMP Annex 11, section 12 Security, including 12.1 on physical and logical access controls and 12.3 on recording access authorisations; section 2 Personnel.
- FDA Guidance, Part 11 Scope and Application, section III.C Approach to Specific Part 11 Requirements.
- ICH Q7, section 5.4 Computerized Systems.
- SOP-IT-003 Audit Trail Review for Computerised Systems; SOP-QA-005 Deviation Management; SOP-QA-001 Document Control.

## 8. Revision history

| Version | Date | Change |
|---|---|---|
| 1.2 | 2024-12-02 | Added supplier service engineer accounts. |
| 2.0 | 2026-05-11 | Aligned password rules with the site security policy; added 6-monthly review for High risk systems and the 90-day dormant account rule. |
