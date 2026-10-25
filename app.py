"""
CGHS Claim Checker & Sanction Letter Generator
------------------------------------------------
Upload a scanned/photographed CGHS medical reimbursement claim (form, bill,
referral). This tool reads it with an AI vision model, matches every claimed
test/treatment against the official CGHS rate list, flags any amount billed
above the CGHS rate, and generates the Sanction Memo + NS/Checklist note
used by this division -- with only the claimant details changing each time.

Run:  streamlit run app.py
"""
import os
import io
import json
import base64
import datetime
import tempfile
import hashlib

import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from matcher import get_rate, extract_cghs_code, description_candidates, TIER_KEYS
from letter_templates import (build_sanction_memo, build_ns_checklist,
                              build_circle_sanction_order, build_unit_sanction_memo,
                              build_calculation_checklist, DEFAULT_OFFICE)
from bundles import (
    apply_billing_rules, summarise, validate_rules, OVERRIDE_CHOICES, OVERRIDE_AUTO,
    COUNTED, INCLUDED, REPEAT, FORCED_EXCLUDE, UNMATCHED,
)
from num2words_inr import rupees_in_words
from review_logic import resolve_item, CODE_BASED, MANUAL, NO_CODE
from claim_audit import fingerprint, merge_extractions, reconcile

DATA_DIR = os.path.join(os.path.dirname(__file__), 'data')
MASTER_JSON = os.path.join(DATA_DIR, 'cghs_all_tiers.json')

# A starter list of well-known CGHS Tier I (X) and Tier II (Y) cities so the
# dropdown can suggest the right tier - anything not in these lists defaults
# to Tier III (Z), which covers "all other" CGHS-covered cities.
TIER1_CITIES = ["Delhi", "Mumbai", "Kolkata", "Chennai", "Hyderabad", "Bengaluru", "Ahmedabad", "Pune"]
TIER2_CITIES = [
    "Chandigarh", "Jaipur", "Lucknow", "Kanpur", "Nagpur", "Kochi", "Guwahati", "Patna",
    "Surat", "Faridabad", "Gurgaon", "Srinagar", "Jammu", "Indore", "Bhopal", "Coimbatore",
    "Ludhiana", "Amritsar", "Meerut", "Agra", "Varanasi", "Noida", "Vadodara", "Rajkot",
]

st.set_page_config(page_title="Medical Claims Studio", page_icon="✦", layout="wide", initial_sidebar_state="expanded")

# A calm, practical casework desk with pastel surfaces and clear status colors.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');
:root { --ink:#29363b; --muted:#667579; --paper:#f2f5f2; --panel:#fbfcfa; --line:#dce5df; --sage:#dfeae3; --sage-deep:#55766b; --sage-dark:#405d54; --blue:#e2edf0; --sand:#f2e9de; --rose:#f4e4e1; --lavender:#ebe8f1; --shadow:0 16px 40px rgba(42,65,55,.07); }
.stApp { background:radial-gradient(ellipse at 80% -8%,#e6eeea 0,transparent 34rem),var(--paper); color:var(--ink); font-family:'DM Sans',sans-serif; }
[data-testid="stSidebar"] { background:#e8eee9; border-right:1px solid var(--line); }
[data-testid="stSidebar"] * { color:var(--ink); }
[data-testid="stSidebar"] .stCaption,[data-testid="stSidebar"] p { color:var(--muted)!important; }
[data-testid="stSidebar"] h1 { font-family:'DM Sans',sans-serif!important; color:var(--ink)!important; font-size:1.55rem!important; line-height:1.15!important; letter-spacing:-.04em!important; font-weight:700!important; }
[data-testid="stSidebar"] [data-baseweb="select"] * { color:var(--ink); }
[data-testid="stSidebar"] input { background:#f7faf7!important; color:var(--ink)!important; border-color:#cddad1!important; }
[data-testid="stRadio"] label { min-height:3rem; padding:.65rem .8rem!important; margin:.2rem 0; border:1px solid #cbdad0; border-radius:12px; background:#f9fbf9; color:var(--ink)!important; cursor:pointer; transition:background .18s ease,border-color .18s ease,box-shadow .18s ease; }
[data-testid="stRadio"] label:hover { background:#edf4ef; border-color:var(--sage-deep); box-shadow:0 3px 10px rgba(42,65,55,.08); }
[data-testid="stRadio"] label:has(input:checked) { background:var(--sage-deep); border-color:var(--sage-deep); }
[data-testid="stRadio"] label:has(input:checked) p,[data-testid="stRadio"] label:has(input:checked) span { color:#fff!important; }
[data-testid="stRadio"] label p,[data-testid="stRadio"] label span { color:var(--ink)!important; font-size:1rem!important; font-weight:600!important; line-height:1.4!important; }
[data-testid="stRadio"] input[type="radio"] { width:1.25rem; height:1.25rem; accent-color:var(--sage-dark); }
.block-container { max-width:1460px; padding-top:1.2rem; padding-bottom:4rem; }
h1 { font-family:'DM Sans',sans-serif!important; color:var(--ink)!important; font-size:clamp(2.1rem,3.2vw,3.2rem)!important; font-weight:700!important; letter-spacing:-.055em!important; margin:0!important; animation:rise .5s cubic-bezier(.2,.7,.2,1) both; }
h2,h3 { color:var(--ink)!important; font-family:'DM Sans',sans-serif!important; letter-spacing:-.035em!important; }
h2 { border-top:1px solid var(--line); padding-top:1.55rem!important; margin-top:2rem!important; font-size:1.35rem!important; scroll-margin-top:1rem; }
p,.stCaption { color:var(--muted)!important; }
[data-testid="stMetric"] { background:var(--panel); border:1px solid var(--line); border-radius:17px; padding:1rem 1.15rem; box-shadow:var(--shadow); transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease; }
[data-testid="stMetric"]:hover { transform:translateY(-2px); border-color:#b9cec1; box-shadow:0 18px 42px rgba(42,65,55,.11); }
[data-testid="stMetricLabel"] { font-size:.74rem; font-weight:700; letter-spacing:.07em; text-transform:uppercase; color:var(--muted)!important; }
[data-testid="stMetricValue"] { color:var(--sage-dark)!important; font-family:'DM Mono',monospace; font-size:1.55rem!important; }
.stButton > button,.stDownloadButton > button { border-radius:13px; font-family:'DM Sans',sans-serif; font-size:1rem; font-weight:700; min-height:3.5rem; padding:.7rem 1.15rem; line-height:1.35; white-space:normal; transition:transform .18s cubic-bezier(.2,.7,.2,1),box-shadow .18s ease,background .18s ease,border-color .18s ease; }
.stButton > button[kind="primary"],.stDownloadButton > button[kind="primary"] { background:var(--sage-deep); border-color:var(--sage-deep); color:#f8fbf8; box-shadow:0 7px 16px rgba(65,94,83,.18); }
.stButton > button[kind="primary"]:hover,.stDownloadButton > button[kind="primary"]:hover { background:var(--sage-dark); border-color:var(--sage-dark); box-shadow:0 12px 24px rgba(65,94,83,.23); }
.stButton > button:hover,.stDownloadButton > button:hover { transform:translateY(-2px); border-color:#abc2b4; box-shadow:0 8px 20px rgba(42,65,55,.12); }
.stButton > button:active,.stDownloadButton > button:active { transform:translateY(0) scale(.985); }
button:focus-visible,[tabindex="0"]:focus-visible { outline:3px solid rgba(85,118,107,.45)!important; outline-offset:3px!important; }
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"]:focus-within { border-color:var(--sage-deep)!important; box-shadow:0 0 0 3px rgba(85,118,107,.15)!important; }
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea { min-height:2.7rem; }
[data-testid="stDialog"] [role="dialog"] { border-radius:20px; border:1px solid var(--line); box-shadow:0 24px 70px rgba(36,53,45,.2); }
[data-testid="stDialog"] button { min-height:3.5rem; font-size:1rem; }
[data-testid="stFileUploader"] { background:#f9fbf9; border:1px dashed #aec5b7; border-radius:17px; padding:.8rem; transition:background .2s ease,border-color .2s ease,transform .2s ease; }
[data-testid="stFileUploader"]:hover { background:#fbfcfa; border-color:var(--sage-deep); transform:translateY(-1px); }
[data-testid="stDataFrame"],[data-testid="stDataEditor"] { border:1px solid var(--line); border-radius:15px; overflow:hidden; background:#fbfcfa; box-shadow:0 8px 24px rgba(42,65,55,.045); }
[data-testid="stAlert"] { border-radius:13px; border-width:1px; animation:rise .28s ease-out both; }
[data-testid="stExpander"] { border:1px solid var(--line); border-radius:15px; background:rgba(251,252,250,.82); transition:border-color .2s ease,box-shadow .2s ease; }
[data-testid="stExpander"]:hover { border-color:#b9cec1; box-shadow:0 8px 22px rgba(42,65,55,.055); }
.studio-kicker { color:var(--sage-dark)!important; font-family:'DM Mono',monospace; font-size:.72rem; font-weight:500; letter-spacing:.14em; text-transform:uppercase; margin-bottom:.45rem; }
.workflow-rail { display:flex; flex-wrap:wrap; gap:.6rem; margin:1.25rem 0 .85rem; }
.workflow-rail span { border:1px solid var(--line); background:#f9fbf9; border-radius:999px; padding:.45rem .8rem; color:var(--muted); font-size:.78rem; font-weight:600; transition:transform .2s ease,border-color .2s ease,color .2s ease; }
.workflow-rail span:hover { transform:translateY(-2px); border-color:#abc2b4; color:var(--sage-dark); }
.workflow-rail b { color:var(--sage-deep); margin-right:.35rem; }
.trust-note { border-left:3px solid #9baa8f; background:#f4f1e9; border-radius:0 11px 11px 0; padding:.7rem .9rem; margin:.7rem 0 1.2rem; color:#59665d; font-size:.88rem; }
.hero-shell { margin-bottom:.65rem; }
@keyframes rise { from { opacity:0; transform:translateY(10px) } to { opacity:1; transform:none } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms!important; animation-iteration-count:1!important; scroll-behavior:auto!important; transition-duration:.01ms!important; } }
@media (max-width:700px) { .block-container { padding-left:1rem; padding-right:1rem; padding-top:1rem; } h1 { font-size:2.15rem!important; } }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Office / division details (edited in step 4, saved in session state so the page
# header and the generated documents always agree). Every field has a key
# "office_<field>"; copy_to is kept as one-line-per-entry text.
# ---------------------------------------------------------------------------
def _office_default_text(field):
    v = DEFAULT_OFFICE[field]
    return "\n".join(v) if isinstance(v, list) else v

for _f in DEFAULT_OFFICE:
    st.session_state.setdefault(f"office_{_f}", _office_default_text(_f))


def current_office_profile():
    """The office settings as currently typed into step 4."""
    prof = {f: st.session_state.get(f"office_{f}", _office_default_text(f)) for f in DEFAULT_OFFICE}
    prof["copy_to"] = [ln.strip() for ln in str(prof["copy_to"]).splitlines() if ln.strip()]
    return prof


def fiscal_year_label(today=None):
    """Indian financial year, April-March: 15 Oct 2026 -> '2026-27', 10 Feb 2027 -> '2026-27'."""
    today = today or datetime.date.today()
    start = today.year if today.month >= 4 else today.year - 1
    return f"{start}-{str(start + 1)[-2:]}"

# ---------------------------------------------------------------------------
# Sidebar: API key + rate list + city/tier
# ---------------------------------------------------------------------------
st.sidebar.title("Case setup")
st.sidebar.caption("Choose how to read this case and which CGHS rate tier applies.")

def _get_secret(name):
    """Check st.secrets first (works for local secrets.toml and Streamlit Cloud secrets), then env vars."""
    try:
        if name in st.secrets:
            return str(st.secrets[name])
    except Exception:
        pass
    return os.environ.get(name, "")


def _clean_key(k):
    """Strip whitespace/quotes - a stray space or quote copied with a key is a common cause of 'key not valid'."""
    return (k or "").strip().strip('"').strip("'").strip()


# The API keys are set ONCE by whoever deploys the tool (Streamlit secrets, a local
# .streamlit/secrets.toml, or an environment variable). Officers never see or type a key.
# They are deliberately NOT written into the source code: this repository is public, and
# Google/Anthropic automatically disable any key they find in a public repo.
GEMINI_KEY = _clean_key(_get_secret("GEMINI_API_KEY") or _get_secret("GOOGLE_API_KEY"))
CLAUDE_KEY = _clean_key(_get_secret("ANTHROPIC_API_KEY"))

P_GEMINI = "Google AI"
P_CLAUDE = "Anthropic (Claude)"
P_OCR = "Local OCR (offline, free - Tesseract)"
P_MANUAL = "Manual entry only - no OCR, no key needed"
PROVIDER_LABELS = {
    P_GEMINI: "🤖 Auto-read with AI (Google)",
    P_CLAUDE: "🤖 Auto-read with AI (Claude)",
    P_OCR: "📝 Offline OCR - raw text only",
    P_MANUAL: "⌨️ Type everything manually",
}
provider_options = ([P_GEMINI] if GEMINI_KEY else []) + ([P_CLAUDE] if CLAUDE_KEY else []) + [P_OCR, P_MANUAL]

st.sidebar.subheader("1 · How to read the documents")
provider = st.sidebar.radio(
    "Reading mode", provider_options, index=0, format_func=lambda p: PROVIDER_LABELS[p],
    label_visibility="collapsed",
    help="AI reading needs the tool's built-in key. Offline OCR and manual typing need no key and send nothing anywhere.",
)

api_key = ""
model_name = ""

# Model lists for the dropdowns. IDs are the exact API model names. The "Other" entry
# at the end of every list lets you type a name that isn't listed yet, so a new
# release never needs a code change.
CLAUDE_MODELS = {
    "claude-sonnet-5-5": "claude-sonnet-5-5 - balanced (recommended)",
    "claude-haiku-5-5": "claude-haiku-5-5 - fastest / cheapest",
    "claude-opus-5-5": "claude-opus-5-5 - stronger",
    "claude-fable-5-1": "claude-fable-5-1 - top tier",
}
# Fixed for predictable cost and latency: this workflow only needs structured
# document extraction, not a per-officer model choice.
GEMINI_MODEL = "gemini-3.5-flash-lite"
OTHER_MODEL = "Other (type a model name)..."


def model_picker(label, models, default, key, help_text):
    """Sidebar dropdown of known model IDs, with an 'Other' escape hatch for anything newer."""
    options = list(models) + [OTHER_MODEL]
    choice = st.sidebar.selectbox(
        label, options, index=options.index(default), key=key, help=help_text,
        format_func=lambda m: models.get(m, m),
    )
    if choice == OTHER_MODEL:
        return st.sidebar.text_input("Model name", value="", key=f"{key}_custom").strip()
    return choice


if provider == P_MANUAL:
    st.sidebar.caption("Nothing is read automatically - type the details in sections 2 and 3. All checks work the same.")
elif provider == P_OCR:
    st.sidebar.caption(
        "Runs on this machine and sends nothing anywhere. Plain OCR can misread digits in amounts, so it "
        "only shows the raw text beside the scan - you type the confirmed values yourself. "
        "Needs the `tesseract` program installed (see README)."
    )
elif provider == P_CLAUDE:
    api_key = CLAUDE_KEY
    model_name = model_picker(
        "Model", CLAUDE_MODELS, "claude-sonnet-5-5", key="claude_model",
        help_text="claude-sonnet-5-5 is a good balance of accuracy and cost for reading scanned bills. "
                  "Pick 'Other' to type any model name; docs.claude.com has the up to date list."
    )
else:
    api_key = GEMINI_KEY
    model_name = GEMINI_MODEL
    st.sidebar.caption(
        "Uses a fast AI model for document extraction. "
        "Review all names, codes and amounts before sanction."
    )

if not GEMINI_KEY and not CLAUDE_KEY:
    st.sidebar.caption(
        "ℹ️ AI reading is switched off because no API key has been set up for this tool yet. "
        "The administrator can enable it once - see the README (\"One-time key setup\")."
    )

if api_key:
    if st.sidebar.button("Check AI connection"):
        try:
            if not model_name:
                raise ValueError("choose a model first (or type a model name under 'Other')")
            if provider == P_CLAUDE:
                import anthropic
                # Keep the client in a variable: if it is only a temporary, Python can discard it
                # mid-call and the request fails with "client has been closed".
                client = anthropic.Anthropic(api_key=api_key)
                client.messages.create(
                    model=model_name, max_tokens=10, messages=[{"role": "user", "content": "Say OK"}])
            else:
                from google import genai
                client = genai.Client(api_key=api_key)
                client.models.generate_content(model=model_name, contents=["Say OK"])
            st.sidebar.success("AI connection works.")
        except Exception as e:
            st.sidebar.error(f"Connection check failed: {e}")

st.sidebar.markdown("---")
with st.sidebar.expander("⚙️ Advanced: replace CGHS rate list"):
    st.caption(
        "Bundled: all three city tiers (X/Y/Z), effective 13.10.2025, 1,998 codes each. "
        "Upload a replacement JSON/Excel only if CGHS issues a revision."
    )
    custom_master = st.file_uploader("Replace rate list (optional)", type=["xlsx", "json"])

@st.cache_data
def get_master(_uploaded_bytes, _uploaded_name):
    if _uploaded_bytes is not None:
        if _uploaded_name.endswith('.json'):
            data = json.loads(_uploaded_bytes)
        else:
            df = pd.read_excel(io.BytesIO(_uploaded_bytes))
            # Expect the multi-tier column layout from CGHS_Rates_All_Tiers.xlsx
            data = []
            for _, row in df.iterrows():
                data.append({
                    'code': row['CGHS Code'],
                    'description': row['Description'],
                    'classification': row.get('Classification', ''),
                    'tiers': {
                        'tier1_x_city': {
                            'rate_non_nabh': row.get('Tier I (X City) Non-NABH'),
                            'rate_nabh': row.get('Tier I (X City) NABH'),
                            'rate_super_speciality': row.get('Tier I (X City) Super Speciality'),
                        },
                        'tier2_y_city': {
                            'rate_non_nabh': row.get('Tier II (Y City) Non-NABH'),
                            'rate_nabh': row.get('Tier II (Y City) NABH'),
                            'rate_super_speciality': row.get('Tier II (Y City) Super Speciality'),
                        },
                        'tier3_z_city': {
                            'rate_non_nabh': row.get('Tier III (Z City) Non-NABH'),
                            'rate_nabh': row.get('Tier III (Z City) NABH'),
                            'rate_super_speciality': row.get('Tier III (Z City) Super Speciality'),
                        },
                    }
                })
        by_code = {r['code']: r for r in data}
        descriptions = {r['code']: r['description'] for r in data}
        return data, by_code, descriptions

    if not os.path.exists(MASTER_JSON):
        # Show exactly what IS present so the missing-file cause is obvious, instead of a bare crash.
        app_dir = os.path.dirname(__file__)
        try:
            app_dir_listing = os.listdir(app_dir)
        except Exception as e:
            app_dir_listing = [f"(could not list {app_dir}: {e})"]
        try:
            data_dir_listing = os.listdir(DATA_DIR) if os.path.isdir(DATA_DIR) else None
        except Exception as e:
            data_dir_listing = [f"(could not list {DATA_DIR}: {e})"]

        st.error(
            "**Can't find the bundled CGHS rate file** at:\n\n"
            f"`{MASTER_JSON}`\n\n"
            "This means the `data/` folder wasn't pushed to your GitHub repo (or ended up in the "
            "wrong place), so Streamlit Cloud has nothing to load.\n\n"
            f"**Contents of the app folder** (`{app_dir}`):\n"
            f"{app_dir_listing}\n\n"
            f"**Contents of the expected data folder** (`{DATA_DIR}`):\n"
            f"{data_dir_listing if data_dir_listing is not None else 'this folder does not exist at all'}\n\n"
            "**To fix:** in your GitHub repo, confirm there is a `data/` folder sitting right next to "
            "`app.py`, containing `cghs_all_tiers.json` (and `CGHS_Rates_All_Tiers.xlsx`). If it's "
            "missing, re-upload that folder to GitHub (drag the whole `data` folder into the repo in "
            "the GitHub web UI, or use `git add data/ && git commit && git push` from the command line), "
            "then reboot the app from 'Manage app'.\n\n"
            "As a temporary workaround, you can also use the **'Replace rate list'** uploader in the "
            "sidebar to upload `CGHS_Rates_All_Tiers.xlsx` directly for this session."
        )
        st.stop()

    with open(MASTER_JSON) as f:
        data = json.load(f)
    by_code = {r['code']: r for r in data}
    descriptions = {r['code']: r['description'] for r in data}
    return data, by_code, descriptions

uploaded_bytes = custom_master.read() if custom_master else None
uploaded_name = custom_master.name if custom_master else None
MASTER_DATA, BY_CODE, DESCRIPTIONS = get_master(uploaded_bytes, uploaded_name)
rate_sheet_id = hashlib.sha256(json.dumps(MASTER_DATA, sort_keys=True, default=str).encode()).hexdigest()[:12]
st.sidebar.success(f"{len(MASTER_DATA)} CGHS codes loaded (all 3 tiers)")
st.sidebar.caption(f"Rate sheet ID: {rate_sheet_id}")
_rule_problems = validate_rules(BY_CODE)
if _rule_problems:
    # Only happens with a replacement rate list that renumbers or drops codes the
    # package rules rely on - the rules for those codes then can't be trusted.
    st.sidebar.warning(
        f"{len(_rule_problems)} package rule(s) refer to codes missing from this rate list, so the "
        "'already included in package' check may miss overlaps. First one: " + _rule_problems[0]
    )

st.sidebar.markdown("---")
st.sidebar.subheader("2 · City / tier")
city_input = st.sidebar.text_input("Beneficiary's / treatment city", value="Delhi")

def suggest_tier(city):
    c = city.strip().lower()
    if any(c == t.lower() for t in TIER1_CITIES):
        return "Tier I (X City)"
    if any(c == t.lower() for t in TIER2_CITIES):
        return "Tier II (Y City)"
    return "Tier III (Z City)"

suggested = suggest_tier(city_input)
tier_label = st.sidebar.selectbox(
    "CGHS city tier for rate lookup",
    list(TIER_KEYS.keys()),
    index=list(TIER_KEYS.keys()).index(suggested),
    help="Auto-suggested from the city typed above - override if needed. "
         "Tier I = X-city (e.g. Delhi, Mumbai), Tier II = Y-city, Tier III = Z-city (all other CGHS-covered cities)."
)
if tier_label != suggested:
    st.sidebar.caption(f"Note: '{city_input}' would normally suggest {suggested}.")

def render_claim_orbit():
    """Render the calm casework welcome panel and its lightweight Three.js desk scene."""
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "india-post-logo.png")
    with open(logo_path, "rb") as logo_file:
        logo_data = base64.b64encode(logo_file.read()).decode("ascii")
    html = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');
* { box-sizing:border-box; }
html,body { margin:0; min-height:100%; background:transparent; font-family:'DM Sans',sans-serif; }
.hero { height:356px; position:relative; overflow:hidden; border:1px solid #dce5df; border-radius:26px; background:linear-gradient(112deg,#f7f8f3 0%,#edf3ee 55%,#e7eff0 100%); color:#29363b; isolation:isolate; box-shadow:0 18px 46px rgba(42,65,55,.075); }
.hero:before { content:''; position:absolute; width:440px; height:440px; right:6%; top:-220px; border-radius:50%; background:radial-gradient(circle,#e1ece6 0%,rgba(225,236,230,0) 70%); }
.hero-copy { position:relative; z-index:2; padding:42px 48px; width:57%; }
.eyebrow { color:#5f7d70; font-size:11px; line-height:1.4; letter-spacing:.13em; text-transform:uppercase; font-weight:700; }
.hero h1 { margin:14px 0 12px; max-width:560px; color:#29363b; font:700 clamp(34px,4vw,48px)/1.04 'DM Sans',sans-serif; letter-spacing:-.055em; }
.hero h1 em { color:#607f72; font-style:normal; }
.hero-copy p { margin:0; max-width:440px; color:#607075; font-size:14px; line-height:1.62; }
.stage-list { display:flex; flex-wrap:wrap; gap:8px; margin-top:23px; }
.stage-list span { border:1px solid rgba(118,145,128,.22); background:rgba(251,252,250,.76); border-radius:999px; padding:7px 11px; color:#52655e; font-size:11px; font-weight:600; }
.stage-list b { margin-right:5px; color:#708e7f; font-variant-numeric:tabular-nums; }
.review-note { margin-top:21px; display:flex; align-items:center; gap:8px; color:#718079; font-size:11px; font-weight:600; }
.review-note i { width:7px; height:7px; border-radius:50%; background:#9baa8f; box-shadow:0 0 0 4px rgba(155,170,143,.17); }
.brand-mark { position:absolute; z-index:3; right:26px; top:22px; width:78px; height:auto; padding:7px 9px; border:1px solid rgba(160,177,165,.25); border-radius:12px; background:rgba(251,252,250,.92); box-shadow:0 8px 20px rgba(42,65,55,.07); }
.scene-wrap { position:absolute; z-index:1; right:0; bottom:0; width:51%; height:100%; }
#desk-scene { width:100%; height:100%; display:block; }
.scene-fallback { position:absolute; inset:0; display:grid; place-items:center; }
.fallback-file { position:relative; width:220px; height:150px; border:1px solid #d9e4dc; border-radius:18px; background:#f9fbf8; box-shadow:12px 18px 26px rgba(71,97,83,.13); transform:rotate(-7deg); }
.fallback-file:before,.fallback-file:after { content:''; position:absolute; left:24px; right:24px; height:8px; border-radius:8px; background:#dce7df; }
.fallback-file:before { top:45px; box-shadow:0 22px #e7eee8,0 44px #e7eee8; }
.fallback-file:after { left:auto; right:25px; top:20px; width:44px; height:44px; border-radius:50%; border:5px solid #9bb5a6; background:transparent; }
.hero.has-three .scene-fallback { display:none; }
@media (max-width:760px) {
  .hero { height:372px; }
  .hero-copy { width:100%; padding:32px 26px; }
  .hero h1 { font-size:37px; max-width:370px; }
  .hero-copy p { max-width:440px; padding-right:22px; }
  .stage-list { max-width:430px; }
  .scene-wrap { width:58%; height:49%; opacity:.65; }
  .brand-mark { right:17px; top:17px; width:65px; }
  .review-note { margin-top:15px; }
}
@media (max-width:430px) {
  .hero { height:372px; border-radius:21px; }
  .hero-copy { padding:29px 21px; }
  .hero h1 { font-size:33px; }
  .stage-list { gap:6px; }
  .stage-list span { padding:6px 9px; font-size:10px; }
  .scene-wrap { width:63%; height:43%; }
}
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { scroll-behavior:auto!important; } }
</style>
</head>
<body>
<section class="hero" aria-label="Medical claims case scrutiny workspace">
  <div class="hero-copy">
    <div class="eyebrow">Department of Posts · Medical claims desk</div>
    <h1>Review each case.<br><em>See every detail.</em></h1>
    <p>A practical workspace for checking claim documents, reviewing CGHS rates and preparing sanction drafts. You stay in control of every decision.</p>
    <div class="stage-list" aria-label="Four review stages">
      <span><b>01</b>Intake</span><span><b>02</b>Claimant</span><span><b>03</b>Rate scrutiny</span><span><b>04</b>Draft</span>
    </div>
    <div class="review-note"><i aria-hidden="true"></i> Officer-reviewed decision support · Drafts only</div>
  </div>
  <img class="brand-mark" src="data:image/png;base64,__LOGO_BASE64__" alt="India Post">
  <div class="scene-wrap" aria-hidden="true">
    <div class="scene-fallback"><div class="fallback-file"></div></div>
    <canvas id="desk-scene"></canvas>
  </div>
</section>
<script type="module">
import * as THREE from 'https://cdn.jsdelivr.net/npm/three@0.180.0/build/three.module.js';

const host = document.querySelector('.scene-wrap');
const canvas = document.querySelector('#desk-scene');
const reduceMotion = window.matchMedia('(prefers-reduced-motion: reduce)').matches;

try {
  const renderer = new THREE.WebGLRenderer({ canvas, alpha: true, antialias: true });
  renderer.setPixelRatio(Math.min(window.devicePixelRatio || 1, 1.6));
  renderer.setClearColor(0x000000, 0);
  renderer.outputColorSpace = THREE.SRGBColorSpace;
  const scene = new THREE.Scene();
  const camera = new THREE.PerspectiveCamera(34, 1, 0.1, 40);
  camera.position.set(0, 0, 8.3);
  scene.add(new THREE.HemisphereLight(0xf7faf6, 0xc8d7ce, 2.1));
  const key = new THREE.DirectionalLight(0xffffff, 2.1);
  key.position.set(-3, 5, 7);
  scene.add(key);
  const fill = new THREE.DirectionalLight(0xd9e7ed, 1.2);
  fill.position.set(4, 0, 5);
  scene.add(fill);

  const desk = new THREE.Group();
  scene.add(desk);

  function roundedPanel(width, height, depth, color, x, y, z, angle=0) {
    const radius = Math.min(0.16, width * 0.08, height * 0.08);
    const shape = new THREE.Shape();
    shape.moveTo(-width/2+radius,-height/2);
    shape.lineTo(width/2-radius,-height/2);
    shape.quadraticCurveTo(width/2,-height/2,width/2,-height/2+radius);
    shape.lineTo(width/2,height/2-radius);
    shape.quadraticCurveTo(width/2,height/2,width/2-radius,height/2);
    shape.lineTo(-width/2+radius,height/2);
    shape.quadraticCurveTo(-width/2,height/2,-width/2,height/2-radius);
    shape.lineTo(-width/2,-height/2+radius);
    shape.quadraticCurveTo(-width/2,-height/2,-width/2+radius,-height/2);
    const geometry = new THREE.ExtrudeGeometry(shape,{depth,bevelEnabled:true,bevelSegments:2,steps:1,bevelSize:.025,bevelThickness:.025});
    const mesh = new THREE.Mesh(geometry,new THREE.MeshStandardMaterial({color,roughness:.67,metalness:.02}));
    mesh.position.set(x,y,z);
    mesh.rotation.z = angle;
    mesh.castShadow = true;
    mesh.receiveShadow = true;
    desk.add(mesh);
    return mesh;
  }
  function bar(width,height,color,x,y,z,angle=0) {
    const mesh = new THREE.Mesh(
      new THREE.BoxGeometry(width,height,.025),
      new THREE.MeshStandardMaterial({color,roughness:.8})
    );
    mesh.position.set(x,y,z);
    mesh.rotation.z=angle;
    desk.add(mesh);
    return mesh;
  }

  const ground = new THREE.Mesh(
    new THREE.CircleGeometry(2.15,48),
    new THREE.MeshBasicMaterial({color:0xa9bbb0,transparent:true,opacity:.18})
  );
  ground.scale.set(1.3,.55,1);
  ground.position.set(0,-1.35,-.5);
  desk.add(ground);

  roundedPanel(3.55,2.42,.14,0xcbdcd1,0,-.1,-.08,-.025);
  roundedPanel(3.32,2.22,.12,0xf7f8f3,-.08,.03,.12,.035);
  roundedPanel(3.1,2.03,.1,0xfafbf8,-.12,.10,.3,-.035);

  // Document details are abstract lines and fields, not status or approval marks.
  bar(1.38,.055,0xa8beb0,-.62,.63,.46,-.035);
  bar(1.95,.035,0xd8e2da,-.34,.31,.46,-.035);
  bar(1.95,.035,0xd8e2da,-.34,.12,.46,-.035);
  bar(1.63,.035,0xd8e2da,-.50,-.07,.46,-.035);
  bar(1.84,.035,0xe3eae4,-.39,-.26,.46,-.035);
  bar(.88,.20,0xe8eee8,.35,-.66,.46,-.035);
  bar(.58,.045,0x789687,.35,-.66,.49,-.035);

  const tab = new THREE.Mesh(
    new THREE.BoxGeometry(.82,.18,.13),
    new THREE.MeshStandardMaterial({color:0xa9c1b1,roughness:.58})
  );
  tab.position.set(-1.1,1.18,.03);
  tab.rotation.z=-.035;
  desk.add(tab);

  // A glass-like loupe frames the document as it is reviewed.
  const ring = new THREE.Mesh(
    new THREE.TorusGeometry(.56,.075,14,56),
    new THREE.MeshStandardMaterial({color:0x89a89a,roughness:.26,metalness:.2})
  );
  ring.position.set(1.0,.03,.72);
  desk.add(ring);
  const glass = new THREE.Mesh(
    new THREE.CircleGeometry(.48,48),
    new THREE.MeshPhysicalMaterial({color:0xdce9e8,transparent:true,opacity:.20,roughness:.12,metalness:.02})
  );
  glass.position.set(1.0,.03,.70);
  desk.add(glass);
  const handle = new THREE.Mesh(
    new THREE.CylinderGeometry(.065,.085,.9,18),
    new THREE.MeshStandardMaterial({color:0x789687,roughness:.35,metalness:.12})
  );
  handle.position.set(1.40,-.59,.69);
  handle.rotation.z=-.67;
  desk.add(handle);
  const grip = new THREE.Mesh(
    new THREE.CylinderGeometry(.083,.09,.22,18),
    new THREE.MeshStandardMaterial({color:0x607f72,roughness:.4})
  );
  grip.position.set(1.67,-.98,.69);
  grip.rotation.z=-.67;
  desk.add(grip);

  const beadMaterial = new THREE.MeshStandardMaterial({color:0xb4c9bd,roughness:.4});
  [[-1.85,.88,.12],[1.9,.88,-.1],[1.88,-1.12,.22],[-1.72,-1.0,.2]].forEach(([x,y,z],i)=>{
    const bead = new THREE.Mesh(new THREE.SphereGeometry(i===0?.09:.055,16,12),beadMaterial);
    bead.position.set(x,y,z);
    desk.add(bead);
  });

  function resize() {
    const width = Math.max(host.clientWidth, 1);
    const height = Math.max(host.clientHeight, 1);
    renderer.setSize(width,height,false);
    camera.aspect = width/height;
    camera.position.x = width < 430 ? .05 : .32;
    camera.position.y = width < 430 ? -.12 : -.02;
    camera.updateProjectionMatrix();
    renderer.render(scene,camera);
  }
  let targetX=0, targetY=0;
  host.addEventListener('pointermove',(event)=>{
    if (reduceMotion) return;
    const rect=host.getBoundingClientRect();
    targetY=((event.clientX-rect.left)/rect.width-.5)*.12;
    targetX=((event.clientY-rect.top)/rect.height-.5)*-.08;
  },{passive:true});
  host.addEventListener('pointerleave',()=>{targetX=0;targetY=0;},{passive:true});
  new ResizeObserver(resize).observe(host);
  resize();
  document.querySelector('.hero').classList.add('has-three');

  if (!reduceMotion) {
    const clock = new THREE.Clock();
    function animate() {
      requestAnimationFrame(animate);
      const elapsed=clock.getElapsedTime();
      desk.rotation.y += (targetY-desk.rotation.y)*.035;
      desk.rotation.x += (targetX-desk.rotation.x)*.035;
      desk.position.y = Math.sin(elapsed*.72)*.035;
      renderer.render(scene,camera);
    }
    animate();
  }
} catch (error) {
  // The CSS document illustration remains as a graceful fallback when WebGL/CDN is unavailable.
}
</script>
</body>
</html>"""
    components.html(html.replace("__LOGO_BASE64__", logo_data), height=372, scrolling=False)


render_claim_orbit()
_division_name = (st.session_state.get("office_division") or "").strip()
st.caption(f"{_division_name + ' · ' if _division_name else ''}Case scrutiny workspace")

st.markdown(
    '<div class="workflow-rail"><span><b>01</b>Intake documents</span><span><b>02</b>Confirm claimant</span>'
    '<span><b>03</b>Scrutinize rates</span><span><b>04</b>Prepare drafts</span></div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="trust-note"><strong>Officer review required.</strong> Confirm each match, CGHS rate and final amount before sanction. '
            'This workspace prepares drafts for your decision.</div>', unsafe_allow_html=True)
with st.expander("CGHS facilities at a glance", expanded=False):
    st.markdown("""
    - OPD treatment, medicines and specialist consultation through CGHS Wellness Centres, polyclinics and eligible hospitals.
    - OPD and indoor treatment, investigations and eligible cashless treatment at empanelled facilities.
    - Reimbursement for eligible emergency or specialist-advised treatment, and for approved aids, appliances and related services.
    - Family welfare, maternity and child-health services, plus AYUSH consultations and medicines.

    This workspace helps prepare a reimbursement claim for review; it does not make the sanctioning decision.
    """)

if "extracted" not in st.session_state:
    st.session_state.extracted = None
if "line_items" not in st.session_state:
    st.session_state.line_items = None

# ---------------------------------------------------------------------------
# Step 1: Upload claim documents
# ---------------------------------------------------------------------------
st.header("01 — Intake documents")

if provider == P_MANUAL:
    st.info(
        "You've chosen manual entry - no documents need to be uploaded here. "
        "Skip down to **2. Claimant details** and **3. Item-wise CGHS rate check** and type "
        "everything in directly from the papers in front of you."
    )
    uploaded_files = None
    run_ocr = False
else:
    st.write("Upload the claim form, bill(s)/receipt, and referral if available. Photos, scans, or PDFs are all fine.")
    uploaded_files = st.file_uploader(
        "Claim documents",
        type=["png", "jpg", "jpeg", "pdf"],
        accept_multiple_files=True
    )
    button_label = ("📝 Read text (offline, no auto-fill)" if provider == P_OCR
                    else "🔍 Extract claim details")
    run_ocr = st.button(button_label, type="primary", disabled=not uploaded_files)

def file_to_pil_images(f):
    """Convert an uploaded file (image or PDF) into a list of PIL Image objects."""
    from PIL import Image
    raw = f.getvalue()
    images = []
    if f.type == "application/pdf" or f.name.lower().endswith(".pdf"):
        from pdf2image import convert_from_bytes
        images.extend(convert_from_bytes(raw, dpi=200))
    else:
        images.append(Image.open(io.BytesIO(raw)))
    return images

EXTRACTION_PROMPT = """You are reading numbered pages of a CGHS medical reimbursement case file.
This batch may contain a claim form, bills, receipts, a pharmacy invoice, referrals, reports or cards.
Extract the following as strict JSON, with
no commentary before or after:

{
  "claimant_name": string or null,
  "employee_id": string or null,
  "designation": string or null,
  "office": string or null,
  "pin": string or null,
  "cghs_beneficiary_id": string or null,
  "cghs_card_validity": string or null,
  "patient_relation": string or null,        // e.g. "SELF", "SPOUSE", "SON" etc.
  "hospital_or_lab_name": string or null,
  "nabh_status": string or null,             // "NABH", "Non-NABH", or "Super Speciality" if stated/visible, else null
  "hco_type": string or null,                // e.g. "CGHS empanelled" / "Private" / "Govt"
  "submission_date": string or null,         // DD.MM.YYYY as printed
  "treatment_type": string or null,          // e.g. "OPD", "Indoor", "TEST/INVESTIGATION", "Emergency"
  "diagnosis": string or null,               // diagnosis written in the applicant's own claim/reimbursement form only
  "diagnosis_source": string or null,        // "Applicant form" when that form states it; otherwise null
  "total_claimed_amount": number or null,
  "claim_form_page": integer or null,
  "bill_totals": [{"invoice_number": string, "printed_total": number, "source_page": integer}],
  "line_items": [
    {
      "description": string,
      "code": string or null,
      "claimed_amount": number,
      "source_page": integer,
      "source_document_type": "bill" or "receipt" or "pharmacy invoice",
      "invoice_number": string or null,
      "line_number": string or null,
      "service_date": string or null
    }
  ]
}

Page labels supplied with each image are the source_page numbers. Read every page provided.
First identify the applicant's completed reimbursement/claim form. Extract claimant_name,
employee_id and total_claimed_amount only from that form; set claim_form_page to its page number.
Never create payable rows from the claim form's summary, prescriptions, referrals, orders,
discharge summaries, reports, cards, deposits or repeated receipt totals. A multi-page receipt
is one invoice; include its numbered rows once and its printed total once. Distinct dated
receipts for the same test are distinct bill rows. Hospital internal procedure codes are not
CGHS codes unless clearly labelled as CGHS. Extract
`diagnosis` only from the diagnosis field or handwritten/typed diagnosis on that applicant form. Do NOT
copy a diagnosis from a discharge summary, prescription, referral, bill, laboratory report or any other
attachment, even if those documents are more detailed. If the applicant form has no diagnosis, return
null for both diagnosis fields. For line_items, include every billed row with its exact
amount, including rows priced at 0. Do not use quantity, unit rate, deposit, subtotal or
invoice total as a line amount. If a digit, code, invoice ID or amount is unreadable, use null
and let the officer review it. Never infer codes or rates; the application uses its own rate master.
Output ONLY the JSON object."""

def _clean_json_text(raw_text):
    raw_text = raw_text.strip().strip("`")
    if raw_text.lower().startswith("json"):
        raw_text = raw_text[4:].strip()
    return raw_text

def extract_with_anthropic(images, api_key, model_name, start_page=1):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    content_blocks = []
    for page_no, im in enumerate(images, start_page):
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        content_blocks.append({"type": "text", "text": f"Source page {page_no}"})
        content_blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    content_blocks.append({"type": "text", "text": EXTRACTION_PROMPT})

    resp = client.messages.create(
        model=model_name,
        max_tokens=12000,
        temperature=0,
        messages=[{"role": "user", "content": content_blocks}]
    )
    raw_text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(_clean_json_text(raw_text))

def extract_with_gemini(images, api_key, model_name, start_page=1):
    from google import genai
    client = genai.Client(api_key=api_key)
    contents = []
    for page_no, im in enumerate(images, start_page):
        contents.extend([f"Source page {page_no}", im])
    contents.append(EXTRACTION_PROMPT)
    resp = client.models.generate_content(
        model=model_name, contents=contents,
        config={"temperature": 0, "response_mime_type": "application/json"},
    )
    return json.loads(_clean_json_text(resp.text))

def run_local_ocr(images):
    """Offline OCR via Tesseract. Returns raw text per image - intentionally NOT
    parsed into structured fields, since digit misreads in amounts are a real risk
    (tested: a real Rs.1000 was misread as Rs.600). This is a reading aid only."""
    import pytesseract
    return [pytesseract.image_to_string(im) for im in images]

if provider == P_OCR and run_ocr:
    try:
        images = []
        for f in uploaded_files:
            images.extend(file_to_pil_images(f))
        with st.spinner("Running offline OCR..."):
            texts = run_local_ocr(images)
        st.warning(
            "This is raw, unverified text straight off the page - it **will** contain misread "
            "characters, especially in numbers. Read it side by side with the original document "
            "and type the confirmed values into the sections below yourself; nothing here is "
            "auto-filled."
        )
        for i, t in enumerate(texts):
            with st.expander(f"Page {i + 1} - raw OCR text"):
                st.text(t)
    except Exception as e:
        st.error(f"Local OCR failed: {e}")
        st.info(
            "This usually means the `tesseract` program itself isn't installed on this machine "
            "(the Python package alone isn't enough) - see the README for the one-line install "
            "command for your OS."
        )

if provider in (P_CLAUDE, P_GEMINI) and run_ocr:
    if not api_key:
        st.error("AI reading is not set up on this installation (no API key configured). Choose another reading mode in the sidebar.")
    else:
        with st.spinner(f"Reading documents with {provider}..."):
            try:
                extraction_key = hashlib.sha256(
                    (fingerprint(uploaded_files) + provider + model_name + EXTRACTION_PROMPT).encode()
                ).hexdigest()
                if st.session_state.get("extraction_key") == extraction_key:
                    st.info("These are the same documents and reading settings. The saved review is shown below unchanged.")
                else:
                    images = []
                    for f in uploaded_files:
                        images.extend(file_to_pil_images(f))
                    chunks = []
                    for start in range(0, len(images), 5):
                        batch = images[start:start + 5]
                        if provider == P_CLAUDE:
                            chunks.append(extract_with_anthropic(batch, api_key, model_name, start + 1))
                        else:
                            chunks.append(extract_with_gemini(batch, api_key, model_name, start + 1))
                    extracted = merge_extractions(chunks)
                    st.session_state.extracted = extracted
                    st.session_state.line_items = extracted.get("line_items", [])
                    st.session_state.extraction_key = extraction_key
                    # New source documents need a fresh officer review.
                    st.session_state.pop("review_rows", None)
                    for widget_key in list(st.session_state):
                        if widget_key.startswith(("billed_code_source-", "matched_code_source-",
                                                  "description_source-", "invoice_source-",
                                                  "service_date_source-", "claimed_source-",
                                                  "treatment_source-")):
                            st.session_state.pop(widget_key, None)
                    st.success(f"Read {len(images)} pages. Review the bills, codes and reconciliation below.")
            except Exception as e:
                err_text = str(e)
                if "API_KEY_INVALID" in err_text or "API key not valid" in err_text or "invalid x-api-key" in err_text.lower():
                    st.error(
                        "**The tool's built-in API key was rejected.** Nothing is wrong with your claim documents - "
                        "please tell the administrator. They need to replace the key in the app's secrets "
                        "(a Google AI Studio key from aistudio.google.com/apikey, with no spaces or quotes). "
                        "Meanwhile, switch the reading mode in the sidebar to manual typing and carry on.\n\n"
                        f"Raw error: `{err_text}`"
                    )
                elif "NOT_FOUND" in err_text or "404" in err_text or "no longer available" in err_text.lower():
                    st.error(
                        f"**The model name `{model_name}` isn't available anymore** - {provider.split()[0]} "
                        "retires specific model versions on a rolling basis, sometimes with little notice.\n\n"
                        + ("Please tell the administrator. They need to update the fixed Google AI model setting "
                           "in `app.py` to a currently available model."
                           if provider == P_GEMINI else
                           "Pick another model in the sidebar (e.g. `claude-sonnet-5-5`) or check "
                           "[docs.claude.com](https://docs.claude.com) for the current model list.")
                        + f"\n\nRaw error: `{err_text}`"
                    )
                else:
                    st.error(f"Extraction failed: {e}")
                st.info("You can still fill in the details manually below.")
                st.session_state.extracted = {}
                st.session_state.line_items = []
                st.session_state.pop("extraction_key", None)
                st.session_state.pop("review_rows", None)

# ---------------------------------------------------------------------------
# Step 2: Review / correct claimant details (manual override always available)
# ---------------------------------------------------------------------------
st.header("02 — Confirm claimant details")
st.caption("If OCR could not read the name or employee ID, fill them in here manually - everything on this page is editable.")

ex = st.session_state.extracted or {}
source_audit = {"form_total": None, "invoice_total": None, "issues": []}
if ex:
    source_audit = reconcile(ex)
    if source_audit["form_total"] is not None:
        st.caption(f"Applicant form total: ₹{source_audit['form_total']:,.2f}"
                   + (f" · Unique invoice totals: ₹{source_audit['invoice_total']:,.2f}"
                      if source_audit["invoice_total"] is not None else ""))
    for issue in source_audit["issues"]:
        st.warning(issue)
col1, col2, col3 = st.columns(3)
with col1:
    name = st.text_input("Claimant name", value=ex.get("claimant_name") or "")
    designation = st.text_input("Designation", value=ex.get("designation") or "")
    office = st.text_input("Office", value=ex.get("office") or "")
with col2:
    emp_id = st.text_input("Employee ID", value=ex.get("employee_id") or "")
    pin = st.text_input("PIN", value=ex.get("pin") or "")
    patient_relation = st.text_input("Patient relation to official", value=ex.get("patient_relation") or "SELF")
with col3:
    hospital = st.text_input("Hospital / Diagnostic Centre", value=ex.get("hospital_or_lab_name") or "")
    cghs_id = st.text_input("CGHS Beneficiary ID", value=ex.get("cghs_beneficiary_id") or "")
    cghs_validity = st.text_input("CGHS card validity", value=ex.get("cghs_card_validity") or "")

col4, col5, col6 = st.columns(3)
with col4:
    _accred_options = ["NABH", "Non-NABH", "Super Speciality"]
    _ex_accred = ex.get("nabh_status") or "NABH"
    nabh_status = st.selectbox("Facility accreditation", _accred_options,
                                index=_accred_options.index(_ex_accred) if _ex_accred in _accred_options else 0,
                                help="Super Speciality rates apply to CGHS-recognised super-speciality "
                                     "hospitals/centres - check the empanelment status on the hospital's "
                                     "CGHS listing if unsure.")
with col5:
    submission_date = st.text_input("Claim submission date", value=ex.get("submission_date") or "")
with col6:
    treatment_type = st.text_input("Treatment type", value=ex.get("treatment_type") or "TEST/INVESTIGATION")

st.subheader("Diagnosis stated on the applicant form")
if ex.get("diagnosis_source") == "Applicant form":
    st.caption("Extracted only from the uploaded applicant form — not from a summary, referral or discharge record. Confirm before using it.")
else:
    st.caption("Enter only the diagnosis stated in the applicant form. The reader deliberately ignores diagnoses found only in summaries and other attachments.")
diagnosis = st.text_area(
    "Applicant-form diagnosis",
    value=ex.get("diagnosis") or "",
    placeholder="No diagnosis found on the applicant form",
    height=88,
    help="This field is kept separate so an officer can see and correct the diagnosis source before preparing a draft.",
)

# ---------------------------------------------------------------------------
# Step 3: Line-item matching against CGHS rates
# ---------------------------------------------------------------------------
st.header("03 — Scrutinize CGHS rates")
fetch_mode = st.selectbox(
    "Matching mode", [CODE_BASED, MANUAL, NO_CODE],
    help="Code Based prefers a valid printed CGHS code. Manual waits for your selection. "
         "No Code suggests a rate-list entry from a billed description, with the applicant-form diagnosis as review context.",
)
st.caption("Changing this mode immediately re-scrutinizes every billed row against the selected CGHS rate sheet. An uncertain match requires officer selection; a diagnosis alone never creates a billed row.")


def _num(x):
    """Cell value -> a clean number (blank / NaN -> 0; 300.0 -> 300)."""
    try:
        v = float(x)
    except (TypeError, ValueError):
        return 0
    if pd.isna(v):
        return 0
    return int(v) if v == int(v) else round(v, 2)


def _txt(x):
    """Cell value -> stripped text (None / NaN -> '')."""
    if x is None or (isinstance(x, float) and pd.isna(x)):
        return ""
    return str(x).strip()


items_raw = st.session_state.line_items or []
if "review_rows" not in st.session_state:
    # Keep an officer's additions, edits and deletions in session rather than
    # rebuilding the review table on each Streamlit rerun.
    st.session_state.review_rows = [
        {"id": f"source-{i}", "description": it.get("description", ""),
         "billed_code": it.get("code", "") or "", "matched_code": "",
         "claimed_amount": it.get("claimed_amount", 0) or 0, "override": OVERRIDE_AUTO,
         "invoice_number": it.get("invoice_number", "") or "",
         "service_date": it.get("service_date", "") or "",
         "line_number": it.get("line_number", "") or "",
         "source_page": it.get("source_page")}
        for i, it in enumerate(items_raw)
    ] or [{"id": "new-0", "description": "", "billed_code": "", "matched_code": "",
            "claimed_amount": 0, "override": OVERRIDE_AUTO}]

st.caption(f"Rate lookup: **{tier_label}**, **{nabh_status}** (change in the sidebar if needed)")
st.caption(f"Rate sheet ID: `{rate_sheet_id}`. Keep this ID with the case record to identify the exact rate chart used.")
st.write(
    "Search either code picker by code or description. Selecting a CGHS code fetches its official "
    "description and the rate for the chosen tier. You can add, edit or delete any review entry before preparing the draft."
)

NO_SELECTION = "— Search CGHS codes —"
code_labels = {code: f"{code} — {record['description']}" for code, record in BY_CODE.items()}
code_options = [NO_SELECTION] + [code_labels[code] for code in sorted(code_labels)]
label_to_code = {label: code for code, label in code_labels.items()}

def _picker_value(code):
    return code_labels.get(code, NO_SELECTION)

def _code_from_picker(value):
    return label_to_code.get(value, "")

def _use_selected_code(row, field, selected_code):
    """Apply a verified code without changing the description printed on the bill."""
    row[field] = selected_code

def _choose_suggestion(row, code):
    row["matched_code"] = code
    st.session_state[f"matched_code_{row['id']}"] = _picker_value(code)

for index, review_row in enumerate(st.session_state.review_rows):
    row_id = review_row["id"]
    label = _txt(review_row.get("description")) or "New review item"
    amount_label = f"₹{_num(review_row.get('claimed_amount')):,.0f}"
    with st.expander(f"{index + 1:02d} · {label} · {amount_label}", expanded=(index == 0)):
        if review_row.get("source_page"):
            st.caption(f"Source page {review_row['source_page']} · "
                       f"Invoice {review_row.get('invoice_number') or 'not identified'}")
        if review_row.get("billed_code") and not extract_cghs_code(review_row["billed_code"], BY_CODE):
            st.warning(f"Printed code {review_row['billed_code']} is not in the selected CGHS rate sheet. Check the original document or select a verified match.")
        c1, c2 = st.columns(2)
        with c1:
            selected_billed = st.selectbox(
                "Billed code", code_options,
                index=code_options.index(_picker_value(review_row.get("billed_code", ""))),
                key=f"billed_code_{row_id}",
                help="Search the dropdown by CGHS code or description. This is a searchable official-code catalogue.",
            )
            selected_billed_code = _code_from_picker(selected_billed)
            if (selected_billed_code != review_row.get("billed_code", "") and
                    (selected_billed_code or review_row.get("billed_code", "") in BY_CODE)):
                _use_selected_code(review_row, "billed_code", selected_billed_code)
        with c2:
            selected_matched = st.selectbox(
                "Matched CGHS code", code_options,
                index=code_options.index(_picker_value(review_row.get("matched_code", ""))),
                key=f"matched_code_{row_id}",
                help="Search to replace or confirm the CGHS match. The official description and rate are shown below.",
            )
            selected_matched_code = _code_from_picker(selected_matched)
            if selected_matched_code != review_row.get("matched_code", ""):
                _use_selected_code(review_row, "matched_code", selected_matched_code)

        review_row["description"] = st.text_input(
            "Description (as billed)", value=review_row.get("description", ""), key=f"description_{row_id}",
        )
        origin_a, origin_b = st.columns(2)
        with origin_a:
            review_row["invoice_number"] = st.text_input(
                "Bill / receipt number", value=review_row.get("invoice_number", ""), key=f"invoice_{row_id}")
        with origin_b:
            review_row["service_date"] = st.text_input(
                "Service date", value=review_row.get("service_date", ""), key=f"service_date_{row_id}")
        if review_row.get("line_number"):
            st.caption(f"Invoice line {review_row['line_number']}")
        c3, c4, c5 = st.columns([1, 1, .6])
        with c3:
            review_row["claimed_amount"] = st.number_input(
                "Claimed amount (₹)", min_value=0.0, value=float(_num(review_row.get("claimed_amount"))),
                step=1.0, format="%.2f", key=f"claimed_{row_id}",
            )
        with c4:
            review_row["override"] = st.selectbox(
                "Treatment", OVERRIDE_CHOICES,
                index=OVERRIDE_CHOICES.index(review_row.get("override", OVERRIDE_AUTO))
                if review_row.get("override", OVERRIDE_AUTO) in OVERRIDE_CHOICES else 0,
                key=f"treatment_{row_id}",
                help="Auto applies billing rules; Count retains this row; Exclude removes it from payment.",
            )
        preview = resolve_item(review_row, BY_CODE, DESCRIPTIONS, tier_label,
                               nabh_status, fetch_mode, diagnosis=diagnosis,
                               treatment_type=treatment_type)
        active_code = preview["code"] if preview else None
        rate = preview["cghs_rate"] if preview else None
        with c5:
            st.metric("Official CGHS rate", f"₹{rate:,.2f}" if rate is not None else "—")
            if st.button("Delete entry", key=f"delete_{row_id}", help="Remove this entry from the current review."):
                st.session_state.review_rows.pop(index)
                st.rerun()
        if active_code:
            st.caption(f"{preview['match_source']}: **{active_code} — {BY_CODE[active_code]['description']}**")
        else:
            st.caption("No reliable CGHS match selected. Search the matched-code picker to choose one.")
        if fetch_mode == NO_CODE and not active_code:
            query = _txt(review_row.get("description")) or diagnosis
            candidates = description_candidates(query, DESCRIPTIONS,
                                                context=diagnosis,
                                                treatment_type=treatment_type)
            if diagnosis:
                st.caption(f"Applicant-form diagnosis for context: {diagnosis}")
            if query == diagnosis and diagnosis:
                st.caption("Diagnosis-only candidates need explicit officer selection; they are not automatically counted.")
            if candidates and candidates[0][2] >= 60:
                st.warning("Several rate-list entries may fit. Compare the official descriptions with the bill before choosing.")
                for candidate_code, candidate_description, candidate_score in candidates:
                    if candidate_score < 60:
                        continue
                    st.button(f"Use {candidate_code} · {candidate_description} ({candidate_score:.0f}%)",
                              key=f"candidate_{row_id}_{candidate_code}",
                              on_click=_choose_suggestion, args=(review_row, candidate_code),
                              help="This records an officer-selected match for this billed row.")

if st.button("+ Add new entry", key="add_review_entry"):
    st.session_state.review_rows.append({
        "id": f"new-{len(st.session_state.review_rows)}-{datetime.datetime.now().timestamp():.0f}",
        "description": "", "billed_code": "", "matched_code": "", "claimed_amount": 0,
        "override": OVERRIDE_AUTO, "invoice_number": "", "service_date": "", "line_number": "", "source_page": None,
    })
    st.rerun()

# Work out the final rows from the reviewed entries, cap each row at its CGHS
# rate, then let the billing rules decide what really counts.
rows_final = []
for row in st.session_state.review_rows:
    desc_billed = _txt(row.get("description"))
    billed_code = _txt(row.get("billed_code"))
    claimed = _num(row.get("claimed_amount"))
    code = _txt(row.get("matched_code"))
    if not (desc_billed or billed_code or code or claimed):
        continue
    resolved = resolve_item(row, BY_CODE, DESCRIPTIONS, tier_label, nabh_status,
                            fetch_mode, diagnosis=diagnosis,
                            treatment_type=treatment_type)
    if resolved is not None:
        rows_final.append(resolved)

final_items = apply_billing_rules(rows_final, BY_CODE)
if fetch_mode == NO_CODE:
    suggested_count = sum(r.get("match_source") == "Description-based suggested match — review"
                          for r in rows_final)
    unmatched_count = sum(r.get("code") is None for r in rows_final)
    st.info(f"Description-based scrutiny complete: {len(rows_final)} billed row(s) checked; "
            f"{suggested_count} rate-list suggestion(s), {unmatched_count} without a reliable match. "
            "Review suggested codes and choose an official rate-list entry for any remaining row before sanction.")
def _result_note(r):
    note = r['rule_note']
    if r['cghs_rate'] is not None and r['claimed_amount'] > r['cghs_rate']:
        capped = f"Billed ₹{r['claimed_amount']:,.2f} is above the CGHS rate ₹{r['cghs_rate']:,.2f} - restricted to the rate."
        note = f"{note} {capped}".strip()
    elif r['cghs_rate'] is not None and r['claimed_amount'] < r['cghs_rate']:
        note = f"{note} Claimed amount is below the CGHS cap; the claim is considered.".strip()
    if r.get('match_source') == 'Description-based suggested match — review':
        note = f"{note} Code inferred from billed description; confirm against the documents.".strip()
    return note


sheet = pd.DataFrame([{
    'Sl.': i + 1,
    'Particulars': r['matched_description'],
    'CGHS code': r['code'] or '-',
    'Bill / receipt': r.get('invoice_number') or '-',
    'Code source': r['match_source'],
    'Claimed (₹)': r['claimed_amount'],
    'CGHS rate (₹)': r['cghs_rate'],
    'Counted (₹)': r['counted_amount'],
    'Result': r['rule_status'],
    'Note': _result_note(r),
} for i, r in enumerate(final_items)])


def _row_colour(row):
    status = row['Result']
    if status in (INCLUDED, REPEAT, FORCED_EXCLUDE):
        bg = 'rgba(222, 233, 225, 0.72)'     # held back
    elif status == UNMATCHED or str(status).startswith('REVIEW'):
        bg = 'rgba(244, 230, 209, 0.72)'     # needs the officer's attention
    else:
        bg = ''
    return [f'background-color: {bg}' if bg else '' for _ in row]


st.subheader("CGHS rate calculation")
if len(sheet):
    _money = lambda v: "-" if v is None or pd.isna(v) else f"{float(v):,.2f}"
    st.dataframe(
        sheet.style.apply(_row_colour, axis=1).format(
            {"Claimed (₹)": _money, "CGHS rate (₹)": _money, "Counted (₹)": _money}),
        width="stretch", hide_index=True)
else:
    st.caption("Nothing to calculate yet - add at least one billed item above.")

st.caption(
    "COUNTED = payable (capped at the CGHS rate) · INCLUDED IN PACKAGE = already covered by a package that is also "
    "billed (e.g. Hb, TLC and Platelets inside a CBC), counted as ₹0 · REPEAT = the same diagnostic code billed twice, "
    "counted once · REVIEW = counted for now, but please confirm · NO MATCH = not found in the rate list, verify the "
    "code or description manually."
)

all_reviewed_claimed = sum(_num(r.get('claimed_amount')) for r in st.session_state.review_rows)
total_claimed = all_reviewed_claimed
total_admissible = sum(r['counted_amount'] for r in final_items if r['counted_amount'] is not None)
unresolved = [r for r in final_items if r['counted_amount'] is None]
summary = summarise(final_items)

m1, m2, m3 = st.columns(3)
m1.metric("Claimed bill rows", f"₹{total_claimed:,.2f}")
m2.metric("Total admissible (as per CGHS rates)", f"₹{total_admissible:,.2f}")
diff = total_claimed - total_admissible
m3.metric("Difference", f"₹{diff:,.2f}", delta=f"-₹{diff:,.2f}" if diff > 0 else None, delta_color="inverse")
form_total = reconcile(ex)["form_total"] if ex else None
if form_total is not None and abs(float(form_total) - all_reviewed_claimed) > 1:
    st.error(f"Applicant form claims ₹{form_total:,.2f}; reviewed bill rows total ₹{all_reviewed_claimed:,.2f}. Check for missing, duplicate or unreadable bill items.")

if summary['excluded']:
    st.info(
        f"🧮 {summary['excluded']} row(s) are already covered by another billed test or package, or are repeats, "
        f"so they are not paid twice (₹{summary['held_back_amount']:,.0f} held back). The reason is in the **Note** "
        "column. Disagree? Set that row's **Treatment** to *Count*."
    )
if summary['review']:
    st.warning(
        f"🔎 {summary['review']} row(s) are marked REVIEW. They are still counted, but please confirm each one - "
        "set **Treatment** to *Exclude* to drop a row."
    )
if unresolved:
    st.warning(f"{len(unresolved)} row(s) have no matched CGHS rate and are excluded from the admissible total above. "
               "Resolve these before sanctioning.")
inferred = [r for r in final_items if r.get('match_source') == 'Description-based suggested match — review']
if inferred:
    st.warning(f"{len(inferred)} code(s) were inferred from billed descriptions. Confirm each against the source documents and select the code explicitly before approval.")

st.markdown("---")

# ---------------------------------------------------------------------------
# Step 4: Generate documents
# ---------------------------------------------------------------------------
st.header("04 — Prepare sanction drafts")


def _apply_office_profile(data):
    """Copy a dict of office settings into the step-4 widgets' session state."""
    for f in DEFAULT_OFFICE:
        if f in data:
            v = data[f]
            st.session_state[f"office_{f}"] = "\n".join(str(x) for x in v) if isinstance(v, list) else str(v)


def _load_office_profile():
    up = st.session_state.get("office_profile_upload")
    if up is None:
        return
    try:
        data = json.loads(up.getvalue().decode("utf-8"))
        if not isinstance(data, dict) or not any(k in DEFAULT_OFFICE for k in data):
            raise ValueError("this doesn't look like a saved office-details file")
        _apply_office_profile(data)
        st.session_state["office_msg"] = ("ok", f"Loaded office details for {data.get('division') or 'the file'}.")
    except Exception as e:
        st.session_state["office_msg"] = ("err", f"Couldn't read that file: {e}")


def _reset_office_profile():
    _apply_office_profile(DEFAULT_OFFICE)
    st.session_state["office_msg"] = ("ok", f"Reset to {DEFAULT_OFFICE['division']} defaults.")


office_now = current_office_profile()
st.caption(f"Documents will be issued for: **{office_now['division'] or '(division name not set)'}**. "
           "Using this tool for another division? Edit the office details below.")

with st.expander("🏢 Office / division details - edit these to use the tool for another division", expanded=False):
    st.caption(
        "Everything here is printed on the Sanction Memo and the NS/Checklist (letterhead, sanction sentence, "
        "signature block, copy-to list, memo number). The defaults are this division's original wording."
    )
    _msg = st.session_state.pop("office_msg", None)
    if _msg:
        (st.success if _msg[0] == "ok" else st.error)(_msg[1])

    o1, o2, o3 = st.columns(3)
    o1.text_input("Department", key="office_dept_name")
    o2.text_input("Office line (printed above the division name)", key="office_office_line",
                  help='For example: "O/o The Senior Superintendent of Post Offices,"')
    o3.text_input("Division / office name", key="office_division",
                  help="For example: North Division, East Division, West Division ...")
    o4, o5, o6 = st.columns(3)
    o4.text_input("Office address", key="office_address",
                  help="Printed under the division name. Leave blank to leave the line out.")
    o5.text_input("Place (for 'Dated at ... the')", key="office_place")
    o6.text_input("City & PIN (sanction sentence and signature block)", key="office_city_pin")
    o7, o8, o9 = st.columns(3)
    o7.text_input("Sanctioning authority - signature block", key="office_sanctioning_authority")
    o8.text_input("Sanctioning authority - in the sanction sentence", key="office_sanctioning_authority_long")
    o9.text_input("Memo No. prefix", key="office_memo_no_prefix",
                  help="The financial year is added automatically, e.g. <prefix>/2026-27")
    st.text_input("Head of Account (HOA)", key="office_hoa",
                  help="Leave blank to leave the 'expenditure will be met from ...' line out.")
    st.text_area("Copy-to list - one line per entry (the claimant is always No. 1)", key="office_copy_to", height=110)
    o10, o11 = st.columns(2)
    o10.text_input("NS/Checklist - prepared by", key="office_prepared_by")
    o11.text_input("NS/Checklist - checked / approved by", key="office_checked_by")

    s1, s2, s3 = st.columns(3)
    with s1:
        st.download_button("💾 Save these details (.json)",
                           data=json.dumps(current_office_profile(), indent=2, ensure_ascii=False),
                           file_name="office_details.json", mime="application/json",
                           help="Keep this file and use 'Load saved details' next time - the app does not "
                                "remember anything between sessions.")
    with s2:
        st.file_uploader("Load saved details", type=["json"], key="office_profile_upload",
                         on_change=_load_office_profile)
    with s3:
        st.button("↩️ Reset to defaults", on_click=_reset_office_profile)

office_now = current_office_profile()

_fy = fiscal_year_label()
col_a, col_b, col_c = st.columns(3)
with col_a:
    memo_no = st.text_input(
        "Memo No.",
        value=f"{office_now['memo_no_prefix']}/{_fy}" if office_now['memo_no_prefix'].strip() else _fy,
    )
with col_b:
    memo_date = st.text_input("Memo date", value=datetime.date.today().strftime("%d.%m.%Y"))
with col_c:
    calc_sheet_sl_no = st.text_input(
        "Calculation sheet Sl. No.", value="05",
        help="The serial number, within this case file, where the item-wise calculation sheet "
             "(appended as the last page of the NS/Checklist doc) will sit - matches the "
             "'Calculation sheet is placed at Sl. No.' column in the summary table."
    )

final_amount = total_admissible
st.caption("The draft sanction uses the checked admissible total. Each matched line is limited to the lower of its claimed amount and CGHS rate.")

st.write(f"**Amount to be sanctioned: ₹{final_amount:,.0f}** ({rupees_in_words(final_amount)})")

if unresolved or summary['review']:
    st.caption("⚠️ Some rows still need a decision (REVIEW / NO MATCH). Confirm the draft review below; "
               "generate again after any amount or code change.")
needs_review = bool(source_audit["issues"] or unresolved or summary['review'] or inferred or
                    (form_total is not None and abs(float(form_total) - all_reviewed_claimed) > 1))
review_confirmed = True
if needs_review:
    review_confirmed = st.checkbox(
        "I checked the source bills, missing or repeated items, inferred codes and totals before preparing drafts")


def _remark(r):
    """Short reason printed in the Remarks column of the Calculation Sheet page."""
    if r['rule_status'] == INCLUDED:
        return f"Included in {r.get('covered_by') or 'a package billed'} - not payable separately"
    if r['rule_status'] == REPEAT:
        return "Same test billed more than once - counted once"
    if r['rule_status'] == FORCED_EXCLUDE:
        return "Not admitted"
    if r['cghs_rate'] is not None and r['claimed_amount'] > r['cghs_rate']:
        return f"Restricted to CGHS rate Rs {r['cghs_rate']}/-"
    if r.get('match_source') == 'Description-based suggested match — review':
        return 'Code inferred from billed description; officer review required'
    return ""


def _order_remark():
    if abs(total_claimed - total_admissible) < 1:
        return 'in order'
    reasons = []
    if any(r['cghs_rate'] is not None and r['claimed_amount'] > r['cghs_rate'] for r in final_items):
        reasons.append('billed above CGHS rates')
    if any(r['rule_status'] in (INCLUDED, REPEAT) for r in final_items):
        reasons.append('tests already included in a package billed / repeated')
    if any(r['rule_status'] == FORCED_EXCLUDE for r in final_items):
        reasons.append('not admitted on verification')
    why = f" - {', '.join(reasons)}" if reasons else ""
    return f'partially admissible (Rs {total_claimed - total_admissible:,.0f}/- disallowed{why} - see calculation sheet)'


if st.button("📄 Generate documents", type="primary", disabled=(not name or not emp_id or not review_confirmed)):
    case = {
        'memo_no': memo_no,
        'memo_date': memo_date,
        'amount': int(final_amount),
        'name': name,
        'designation': designation,
        'office': office,
        'pin': pin,
        'emp_id': emp_id,
        'hospital': hospital,
        'patient_relation': patient_relation,
        'patient_relation_display': patient_relation.upper(),
        'cghs_card_no': cghs_id,
        'cghs_validity': cghs_validity,
        'submission_date': submission_date,
        'treatment_type': treatment_type,
        'nabh_status': nabh_status,
        'tier_label': tier_label,
        'hco_type': 'Yes',
        'total_admissible': int(total_admissible),
        'total_claimed': int(total_claimed),
        'calc_sheet_sl_no': calc_sheet_sl_no,
        'order_remark': _order_remark(),
        'recommended': 'Yes',
        'office_profile': office_now,
        'fetch_mode': fetch_mode,
        'rate_sheet_id': rate_sheet_id,
    }
    ns_items = [{
        'sl_no': i + 1,
        'particulars': r['matched_description'] or r['description'],
        'code': r['code'],
        'claimed': f"{float(r['claimed_amount']):.2f}",
        'admissible': f"{float(r['counted_amount']):.2f}" if r['counted_amount'] is not None else 'MANUAL REVIEW',
        'remark': _remark(r),
        'source': (f"{r.get('match_source', '')}; "
                   f"{r.get('invoice_number') or 'no invoice ID'}; "
                   f"page {r.get('source_page') or '-'}"),
    } for i, r in enumerate(final_items)]

    out_dir = os.path.join(tempfile.gettempdir(), 'cghs_out')
    os.makedirs(out_dir, exist_ok=True)
    sanction_path = os.path.join(out_dir, 'Sanction_Memo.docx')
    ns_path = os.path.join(out_dir, 'NS_Checklist.docx')
    checklist_path = os.path.join(out_dir, 'Calculation_Checklist.docx')
    circle_path = os.path.join(out_dir, 'Circle_Sanction_Order.docx')
    unit_path = os.path.join(out_dir, 'Unit_Sanction_Memo.docx')
    build_sanction_memo(case, sanction_path)
    build_ns_checklist(case, ns_items, ns_path)
    build_calculation_checklist(case, ns_items, checklist_path)
    build_circle_sanction_order(case, circle_path)
    build_unit_sanction_memo(case, unit_path)

    # Keep the finished files in the session so both download buttons stay on screen
    # (clicking one download button reruns the page, which would otherwise make the other vanish).
    st.session_state.generated_docs = {
        'memo': open(sanction_path, 'rb').read(), 'ns': open(ns_path, 'rb').read(),
        'checklist': open(checklist_path, 'rb').read(),
        'circle': open(circle_path, 'rb').read(), 'unit': open(unit_path, 'rb').read(),
        'emp_id': emp_id, 'name': name,
    }

docs = st.session_state.get('generated_docs')
if docs:
    safe_id = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in str(docs['emp_id']))
    st.success(f"Documents generated for {docs['name']} ({docs['emp_id']}).")
    st.caption("These files don't update by themselves - click **Generate documents** again after changing anything above.")
    dl1, dl2 = st.columns(2)
    with dl1:
        st.download_button("⬇️ Download Sanction Memo (.docx)", docs['memo'], file_name=f"Sanction_Memo_{safe_id}.docx")
    with dl2:
        st.download_button("⬇️ Download NS/Checklist (.docx)", docs['ns'], file_name=f"NS_Checklist_{safe_id}.docx")
    dl3, dl4, dl5 = st.columns(3)
    with dl3:
        st.download_button("⬇️ Calculation checklist", docs['checklist'], file_name=f"Calculation_Checklist_{safe_id}.docx")
    with dl4:
        st.download_button("⬇️ Circle sanction order", docs['circle'], file_name=f"Circle_Sanction_Order_{safe_id}.docx")
    with dl5:
        st.download_button("⬇️ Unit sanction memo", docs['unit'], file_name=f"Unit_Sanction_Memo_{safe_id}.docx")
