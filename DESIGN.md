# Medical Claims Studio design context

## Product and audience

Medical Claims Studio is a decision-support workspace for Department of Posts processing officers who check CGHS medical reimbursement claims and issue draft sanction documents. The single job of the interface is to make a high-consequence review sequence easy to scan: ingest, verify identity, review each rate decision, then create a draft.

## Visual direction

The interface uses India Post red (`#C9252C`) and white as its identity, balanced with soft neutral paper surfaces and dark ink for comfortable document review. Red marks primary actions, active states and the assisted-review hero; white and pale rose surfaces keep claim details legible. Motion is small and purposeful: the hero illustrates assistance at the claim desk, while buttons, metrics and disclosures respond to pointer and keyboard interaction.

Display type: Fraunces, used only for the product name. Interface/body: DM Sans. Amounts use DM Mono so digits align visually. Motion is one short entrance and small button lift; `prefers-reduced-motion` disables it.

## Layout and tokens

- Maximum content width: 1440px, compact padding on narrow screens.
- Grid: Streamlit responsive columns; controls collapse naturally on smaller viewports.
- Radius: 9px for controls, 12–14px for data surfaces and feedback.
- Primary action: India Post red (`#C9252C`), with a darker red on hover.
- Attention states: Streamlit warning/error semantics plus a readable calculation-sheet row tint.
- Scrollbars: platform-owned Streamlit surfaces remain visible and operable.

## Runtime mapping

`app.py` owns the runtime theme and component styling through its top-level CSS block. Its `render_claim_orbit` function owns the isolated animated SVG hero scene. This file owns design intent; CSS custom properties in that block implement its named tokens. No other styling system is in use.

## Accessibility and motion

The workflow preserves Streamlit's semantic controls and visible focus behavior. Labels remain visible for data entry and uploaded files. The design supports a keyboard-driven workflow through native Streamlit widgets. Do not make document status depend on colour alone. Any future custom control must retain a native semantic equivalent or explicit keyboard behavior.

## Hero scene

The hero is an assisted-arrival scene: an injured claimant, using a crutch and leg brace, walks clearly from the left toward a staffed claims desk. The seated officer reaches out to help, and the documents move into view at the point of arrival. This is a humane representation of the tool's purpose, not an implication that a claim has been approved. It uses layered lighting, shadows and material gradients for a more dimensional, cinematic result while preserving a crisp animated SVG on any deployment. The supplied India Post logo is the only logo used and appears in a white mark at the hero's upper-right.

## Review controls

Rate review uses one compact disclosure per claim item so an officer can see the billed item, code choices, amount and payment treatment together. The Billed code and Matched CGHS code controls are native searchable selects backed by the same CGHS master catalogue. A selection reveals the official description and tier-specific rate; it never silently replaces the amount actually billed. The applicant-form diagnosis is shown as a separate, source-labelled review field so a diagnosis from a summary cannot masquerade as the applicant's declaration.
