# Medical Claims Studio design context

## Product and audience

Medical Claims Studio is a decision-support workspace for Department of Posts processing officers who check CGHS medical reimbursement claims and issue draft sanction documents. The single job of the interface is to make a high-consequence review sequence easy to scan: ingest, verify identity, review each rate decision, then create a draft.

## Visual direction

The interface is a calm casework desk for processing officers. Soft sage (`#DFEAE3`), mist blue (`#E2EDF0`), warm sand (`#F2E9DE`) and lavender (`#EBE8F1`) support long review sessions. Deep slate (`#29363B`) carries text; muted sage (`#55766B`) marks primary actions and focus. Colour reinforces status, while every result retains its written label and explanation.

DM Sans provides a compact, clear interface. Amounts use DM Mono so digits align. Motion confirms interaction with short hover, press and entrance transitions. The Three.js scene moves gently and pauses under `prefers-reduced-motion`.

## Layout and tokens

- Maximum content width: 1460px, compact padding on narrow screens.
- Grid: Streamlit responsive columns; controls collapse naturally on smaller viewports.
- Radius: 11px for controls, 13–17px for data surfaces and feedback.
- Primary action: muted sage (`#55766B`), with a darker sage on hover.
- Attention states: Streamlit warning/error semantics plus a readable calculation-sheet row tint and written result.
- Scrollbars: platform-owned Streamlit surfaces remain visible and operable.

## Runtime mapping

`app.py` owns the runtime theme and component styling through its top-level CSS block. Its `render_claim_orbit` function owns an isolated Three.js document-review scene, with a CSS illustration when WebGL or the CDN is unavailable. This file owns design intent; CSS custom properties in that block implement its named tokens.

## Accessibility and motion

The workflow preserves Streamlit's semantic controls and visible focus behavior. Labels remain visible for data entry and uploaded files. The design supports a keyboard-driven workflow through native Streamlit widgets. Do not make document status depend on colour alone. Any future custom control must retain a native semantic equivalent or explicit keyboard behavior.

## Hero scene

The hero shows an abstract stack of claim papers under a loupe. It represents close scrutiny, never automatic approval. Three.js draws the three-dimensional scene in a separate Streamlit component, with small pointer-responsive rotation and gentle floating motion. A flat CSS document remains visible if WebGL or the pinned CDN module is unavailable. The India Post logo stays in a small mark for departmental context.

## Review controls

Rate review uses one compact disclosure per claim item. The first entry opens automatically; the rest show their description and claimed amount until needed. The Billed code and Matched CGHS code controls are native searchable selects backed by the same CGHS master catalogue. A selection reveals the official description and tier-specific rate; it never silently replaces the amount actually billed. The applicant-form diagnosis is shown as a separate, source-labelled review field so a diagnosis from a summary cannot masquerade as the applicant's declaration.
