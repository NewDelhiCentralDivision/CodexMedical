# Medical Claims Studio UX contract

## Sources and safety boundary

The original `README.md`, `bundles.py`, `matcher.py`, and `letter_templates.py` define the business behaviour carried into this project. This UI contract does not authorise or replace sanction policy. The app is decision support only: an officer reviews all matches, rates, held-back rows and final amount before issuing a draft.

## Canonical behaviour

| Capability | Owner | Contract |
| --- | --- | --- |
| Form fields and selects | Streamlit native widgets | Visible labels; selected city tier can always be overridden. The CGHS-code pickers use Streamlit's searchable select popup so officers can search code or description. |
| File upload | Streamlit `file_uploader` | PDF/JPEG/PNG only; user starts extraction explicitly. Files are processed in the active app session. |
| Diagnosis source | AI extraction + officer field | Diagnosis is extracted only from the applicant's reimbursement form; summaries, prescriptions, referrals and discharge records are not eligible sources. The officer can correct the displayed value. |
| Rate review | Streamlit expanders + native searchable selects + `dataframe` | Officer can add, edit or delete a session-local entry. Billed-code and matched-code pickers search the official catalogue; selection displays the official description and applicable rate without overwriting the actual billed amount. |
| Feedback | Streamlit alerts/status | Success, warning and error copy explains whether action is required. No browser-native dialogs. |
| Document generation | `letter_templates.py` | Generate is disabled until claimant name and employee ID exist. Downloads stay available after generation. |

## Flow ledger

1. Select read mode and rate tier. Pending is the normal idle state; API secrets are never entered in the UI.
2. Upload one or more documents and select **Extract claim details** (or enter information manually). Failure retains manual-entry access.
3. Review claimant information and the diagnosis taken from the applicant form; correct it directly if needed.
4. Add, edit or delete item entries. Correct codes through the searchable official catalogue or set a documented treatment override. Unmatched rows and review rows are prominent warnings; no automatic approval occurs.
5. Generate documents. The result remains a pair of downloadable draft `.docx` files. Changes require generation again.

## Accessibility and responsive rules

Native labelled inputs and buttons are retained. Feedback uses textual labels in addition to colour. At narrow widths, Streamlit column groups stack; no task is hover-only. Motion is decorative only and obeys reduced-motion preferences.
