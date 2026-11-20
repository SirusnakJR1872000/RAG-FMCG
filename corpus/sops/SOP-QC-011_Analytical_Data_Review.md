FICTIONAL DOCUMENT — created for demonstration

# SOP-QC-011 Analytical Data Review

| Field | Value |
|---|---|
| Company | Acme Pharma Ltd. (fictional) |
| Document number | SOP-QC-011 |
| Version | 2.3 |
| Effective date | 2025-12-01 |
| Supersedes | Version 2.2 |
| Owner | Head of Quality Control |
| Approved by | Head of Quality Assurance |
| Review period | 3 years |

## 1. Purpose

This procedure defines how analytical data generated in the Quality Control laboratories of Acme Pharma Ltd. are reviewed before results are reported. It ensures that reported results are complete, accurate, traceable to the raw data and generated in compliance with the approved method.

## 2. Scope

This SOP applies to all analytical data used for GMP decisions, including release, stability, in-process and qualification testing. It covers data from chromatography data systems (CDS), spectrometers, balances, titrators and other instruments, as well as manual observations recorded in laboratory notebooks. It also defines how out-of-trend (OOT) results are handled.

## 3. Responsibilities

| Role | Responsibility |
|---|---|
| Analyst | Performs the test, records all data contemporaneously and completes a self-review before submitting the data. |
| Second-person reviewer | A trained analyst or supervisor who did not perform the test. Performs the independent data review. |
| QC supervisor | Approves the results for reporting and handles escalations. |
| QA | Performs periodic spot checks of reviewed data packages. |

## 4. Definitions

- **Raw data:** original records and documentation, retained in the format in which they were originally generated, including electronic data and metadata.
- **Out-of-trend (OOT) result:** a result that is within specification but differs from the expected trend, such as a stability result that changes faster than historical data predict.
- **Data package:** all records for one test on one sample: sample preparation records, instrument data, processing methods, calculations, audit trail and the reported result.

## 5. Procedure

### 5.1 Analyst self-review

5.1.1 Before submitting data for review, the analyst checks that all entries are complete, calculations are correct, system suitability criteria are met, and that the correct method version was used.

5.1.2 The analyst records any unexpected event during the analysis, such as an interrupted run or a reinjection, with the reason.

### 5.2 Second-person review

5.2.1 Every data package is reviewed by a second person before the result is reported. The reviewer must not be the person who generated the data.

5.2.2 The reviewer checks:

- that sample identity, weights, dilutions and standards are traceable and within expiry;
- that the instrument was qualified and calibrated on the day of use;
- that system suitability passed for every sequence;
- that integration of chromatograms is consistent and follows the integration SOP; manual integration must be justified and documented;
- that calculations, including any spreadsheet calculations, are correct and use validated templates;
- the electronic **audit trail** for the run, as described in section 5.3; and
- that the reported result matches the raw data.

5.2.3 The review must be completed within **3 working days** of data submission for release testing, and within **10 working days** for stability testing.

### 5.3 Audit trail review as part of data review

5.3.1 For each data package from a computerised instrument, the reviewer reviews the audit trail entries created during the analysis. The review focuses on: deletion or modification of results, reprocessing or reintegration, changes to processing methods, aborted or unexplained injections, and changes to date and time settings.

5.3.2 Any unexplained audit trail entry is treated as a potential data integrity issue. The reviewer stops the review and informs the QC supervisor, who raises a deviation under SOP-QA-005.

5.3.3 The detailed requirements for audit trail review, including periodic system-level review, are defined in SOP-IT-003.

### 5.4 Out-of-trend results

5.4.1 Stability results are compared to the expected trend using the regression model defined for each product. A result outside the **95% prediction interval** of the model is an OOT result.

5.4.2 An OOT result is reported to the QC supervisor within one working day. A laboratory check, using the same checklist as Phase I of SOP-QC-007, is performed within **5 working days**.

5.4.3 If the OOT is confirmed, QA is informed and a deviation is raised under SOP-QA-005 to assess the impact on shelf life.

5.4.4 If a result is both OOT and out of specification, it is handled as an OOS result under SOP-QC-007.

### 5.5 Reporting

5.5.1 Results are reported in the LIMS only after the second-person review is complete and approved.

5.5.2 Corrections to reported results require a documented reason and QC supervisor approval, and are visible in the LIMS audit trail.

## 6. QA oversight

QA reviews at least **5% of completed data packages** each month, chosen at random and weighted toward release testing. Findings are trended and reported at the quarterly quality review.

## 7. Records

Data packages, review checklists and audit trail review records are kept with the batch records, for **batch expiry plus 1 year, minimum 6 years**.

## 8. References

- ICH Q7, section 6.6 Laboratory Control Records and section 11.1 General Controls.
- EU GMP Annex 11, section 9 Audit Trails and section 6 Accuracy Checks.
- FDA Guidance, Part 11 Scope and Application, section III.C.2 Audit Trail.
- SOP-QC-007 OOS Investigation; SOP-QA-005 Deviation Management; SOP-IT-003 Audit Trail Review for Computerised Systems.

## 9. Revision history

| Version | Date | Change |
|---|---|---|
| 2.2 | 2024-08-26 | Added the QA spot check of 5% of data packages. |
| 2.3 | 2025-12-01 | Defined OOT as a result outside the 95% prediction interval; added the 3-day release review limit. |
