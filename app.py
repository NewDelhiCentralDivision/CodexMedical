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

import streamlit as st
import pandas as pd
import streamlit.components.v1 as components

from matcher import match_line_item, get_rate, extract_cghs_code, TIER_KEYS
from letter_templates import build_sanction_memo, build_ns_checklist, DEFAULT_OFFICE
from bundles import (
    apply_billing_rules, summarise, validate_rules, OVERRIDE_CHOICES, OVERRIDE_AUTO,
    COUNTED, INCLUDED, REPEAT, FORCED_EXCLUDE, UNMATCHED,
)
from num2words_inr import rupees_in_words

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

# India Post red and white, with soft neutral surfaces for long review sessions.
st.markdown("""
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:opsz,wght@9..40,400;9..40,500;9..40,600;9..40,700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');
:root { --post-red:#c9252c; --post-red-dark:#a71920; --post-red-soft:#fff0f0; --ink:#242326; --ink-soft:#68666a; --paper:#fbf8f8; --panel:#ffffff; --rule:#eadfe0; --shadow:0 14px 38px rgba(72,22,25,.07); }
.stApp { background:radial-gradient(ellipse at 90% 0%,#fff0f0 0,transparent 32rem),var(--paper); color:var(--ink); font-family:'DM Sans',sans-serif; }
[data-testid="stSidebar"] { background:linear-gradient(165deg,#b91f26 0%,#8e141b 100%); }
[data-testid="stSidebar"] * { color:#f4f8fa; }
[data-testid="stSidebar"] .stCaption, [data-testid="stSidebar"] p { color:rgba(255,255,255,.82)!important; }
[data-testid="stSidebar"] h1 { font-family:'Fraunces',Georgia,serif!important; color:#fff!important; font-size:2.6rem!important; line-height:1.06!important; letter-spacing:-.05em!important; }
[data-testid="stSidebar"] [data-baseweb="select"] * { color:var(--ink); }
[data-testid="stSidebar"] input { background:rgba(255,255,255,.12)!important; color:#fff!important; border-color:rgba(255,255,255,.42)!important; }
[data-testid="stSidebar"] [data-testid="stRadio"] label { padding:.35rem .2rem; }
.block-container { max-width:1440px; padding-top:1.55rem; padding-bottom:4rem; }
h1 { font-family:'Fraunces',Georgia,serif!important; color:var(--ink)!important; font-size:clamp(2.2rem,4vw,4rem)!important; letter-spacing:-.05em!important; margin:0!important; animation:rise .62s cubic-bezier(.2,.7,.2,1) both; }
h2,h3 { color:var(--ink)!important; font-family:'DM Sans',sans-serif!important; letter-spacing:-.025em!important; }
h2 { border-top:1px solid var(--rule); padding-top:1.8rem!important; margin-top:2.3rem!important; font-size:1.45rem!important; scroll-margin-top:1rem; }
p,.stCaption { color:var(--ink-soft)!important; }
[data-testid="stMetric"] { background:var(--panel); border:1px solid var(--rule); border-radius:15px; padding:1rem 1.15rem; box-shadow:var(--shadow); transition:transform .2s ease,border-color .2s ease,box-shadow .2s ease; }
[data-testid="stMetric"]:hover { transform:translateY(-2px); border-color:#e8b9bc; box-shadow:0 18px 42px rgba(72,22,25,.11); }
[data-testid="stMetricLabel"] { font-size:.76rem; font-weight:700; letter-spacing:.055em; text-transform:uppercase; color:var(--ink-soft)!important; }
[data-testid="stMetricValue"] { color:var(--post-red-dark)!important; font-family:'DM Mono',monospace; font-size:1.55rem!important; }
.stButton > button,.stDownloadButton > button { border-radius:10px; font-family:'DM Sans',sans-serif; font-weight:700; min-height:2.8rem; transition:transform .18s cubic-bezier(.2,.7,.2,1),box-shadow .18s ease,background .18s ease,border-color .18s ease; }
.stButton > button[kind="primary"],.stDownloadButton > button[kind="primary"] { background:var(--post-red); border-color:var(--post-red); color:#fff; box-shadow:0 7px 16px rgba(201,37,44,.2); }
.stButton > button[kind="primary"]:hover,.stDownloadButton > button[kind="primary"]:hover { background:var(--post-red-dark); border-color:var(--post-red-dark); box-shadow:0 12px 24px rgba(201,37,44,.25); }
.stButton > button:hover,.stDownloadButton > button:hover { transform:translateY(-2px); border-color:#d9868a; box-shadow:0 8px 20px rgba(72,22,25,.13); }
.stButton > button:active,.stDownloadButton > button:active { transform:translateY(0) scale(.985); }
button:focus-visible,[tabindex="0"]:focus-visible { outline:3px solid rgba(201,37,44,.42)!important; outline-offset:3px!important; }
[data-baseweb="input"]:focus-within,[data-baseweb="textarea"]:focus-within,[data-baseweb="select"]:focus-within { border-color:var(--post-red)!important; box-shadow:0 0 0 3px rgba(201,37,44,.13)!important; }
[data-baseweb="input"] input,[data-baseweb="textarea"] textarea { min-height:2.7rem; }
[data-testid="stDialog"] [role="dialog"] { border-radius:18px; border:1px solid var(--rule); box-shadow:0 24px 70px rgba(45,14,17,.22); }
[data-testid="stDialog"] button { min-height:2.75rem; }
[data-testid="stFileUploader"] { background:rgba(255,255,255,.88); border:1px dashed #d9868a; border-radius:15px; padding:.8rem; transition:background .2s ease,border-color .2s ease,transform .2s ease; }
[data-testid="stFileUploader"]:hover { background:#fff; border-color:var(--post-red); transform:translateY(-1px); }
[data-testid="stDataFrame"],[data-testid="stDataEditor"] { border:1px solid var(--rule); border-radius:13px; overflow:hidden; background:#fff; box-shadow:0 8px 24px rgba(72,22,25,.045); }
[data-testid="stAlert"] { border-radius:12px; border-width:1px; animation:rise .28s ease-out both; }
[data-testid="stExpander"] { border:1px solid var(--rule); border-radius:13px; background:rgba(255,255,255,.72); transition:border-color .2s ease,box-shadow .2s ease; }
[data-testid="stExpander"]:hover { border-color:#dfb5b7; box-shadow:0 8px 22px rgba(72,22,25,.055); }
.studio-kicker { color:var(--post-red)!important; font-family:'DM Mono',monospace; font-size:.76rem; font-weight:500; letter-spacing:.14em; text-transform:uppercase; margin-bottom:.45rem; }
.workflow-rail { display:flex; flex-wrap:wrap; gap:.45rem; margin:1.55rem 0 1rem; }
.workflow-rail span { border:1px solid var(--rule); background:rgba(255,255,255,.9); border-radius:999px; padding:.42rem .78rem; color:var(--ink-soft); font-size:.78rem; font-weight:600; transition:transform .2s ease,border-color .2s ease,color .2s ease; }
.workflow-rail span:hover { transform:translateY(-2px); border-color:#d9868a; color:var(--post-red-dark); }
.workflow-rail b { color:var(--post-red); margin-right:.3rem; }
.trust-note { border-left:3px solid var(--post-red); background:rgba(255,255,255,.86); border-radius:0 10px 10px 0; padding:.7rem .9rem; margin:.7rem 0 1.2rem; color:var(--ink-soft); font-size:.88rem; }
.hero-shell { margin-bottom:.65rem; }
@keyframes rise { from { opacity:0; transform:translateY(12px) } to { opacity:1; transform:none } }
@media (prefers-reduced-motion:reduce) { *,*::before,*::after { animation-duration:.01ms!important; animation-iteration-count:1!important; scroll-behavior:auto!important; transition-duration:.01ms!important; } }
@media (max-width:700px) { .block-container { padding-left:1rem; padding-right:1rem; padding-top:1.25rem; } h1 { font-size:2.35rem!important; } }
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
st.sidebar.title("Claim setup")
st.sidebar.caption("Choose how this claim is read and which CGHS rate tier applies.")

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

P_GEMINI = "Google (Gemini)"
P_CLAUDE = "Anthropic (Claude)"
P_OCR = "Local OCR (offline, free - Tesseract)"
P_MANUAL = "Manual entry only - no OCR, no key needed"
PROVIDER_LABELS = {
    P_GEMINI: "🤖 Auto-read with AI (Gemini)",
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
        "Uses Gemini 3.5 Flash-Lite for fast, cost-efficient document extraction. "
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
st.sidebar.success(f"{len(MASTER_DATA)} CGHS codes loaded (all 3 tiers)")
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
    """A clear, humane arrival scene: an injured claimant approaches an assisting officer."""
    logo_path = os.path.join(os.path.dirname(__file__), "assets", "india-post-logo.png")
    with open(logo_path, "rb") as logo_file:
        logo_data = base64.b64encode(logo_file.read()).decode("ascii")
    components.html(f"""
    <div class="hero" aria-label="An injured claimant walks to a desk where a postal officer is ready to assist">
      <img class="india-post-logo" src="data:image/png;base64,{logo_data}" alt="India Post">
      <div class="ambient light-one"></div><div class="ambient light-two"></div>
      <svg class="scene" viewBox="0 0 790 320" aria-hidden="true">
        <defs>
          <linearGradient id="wall" x1="0" x2="1"><stop stop-color="#9f1920"/><stop offset="1" stop-color="#4f1117"/></linearGradient>
          <linearGradient id="deskwood" x1="0" x2="0" y2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#e8d9da"/></linearGradient>
          <linearGradient id="uniform" x1="0" x2="1"><stop stop-color="#fff"/><stop offset="1" stop-color="#eadfe0"/></linearGradient>
          <filter id="soft"><feGaussianBlur stdDeviation="8"/></filter><filter id="shadow"><feDropShadow dx="0" dy="8" stdDeviation="6" flood-opacity=".34"/></filter>
        </defs>
        <rect width="790" height="320" fill="url(#wall)"/><path d="M0 247H790" class="floor-line"/><path d="M0 248H790V320H0z" class="floor"/>
        <g class="window"><rect x="568" y="38" width="158" height="111" rx="5"/><path d="M647 38v111M568 94h158"/></g>
        <ellipse class="desk-shadow" cx="622" cy="265" rx="157" ry="18"/>
        <g class="desk" filter="url(#shadow)"><path d="M500 183h219l18 23H482z"/><path d="M500 205h219v64H500z"/><path d="M518 269v34m177-34v34"/><path class="document" d="M548 174l54 5-5 19-54-5z"/><path class="document" d="M606 176l45 0 0 18-45 0z"/><path class="lamp" d="M682 178l12-38m-25 0h48m-24 0v37"/></g>
        <g class="officer" filter="url(#shadow)"><ellipse class="chair" cx="630" cy="220" rx="40" ry="36"/><path class="officer-leg" d="M611 233l-5 50m38-50 12 50"/><path class="officer-shoe" d="M591 284h26m27 0h27"/><path class="officer-body" d="M602 141q28-17 55 0l8 76h-69z"/><circle class="skin" cx="630" cy="119" r="22"/><path class="hair" d="M608 116q8-27 43-14l3 18q-23-11-46 5z"/><path class="collar" d="M616 143l14 16 15-16"/><path class="badge" d="M646 160h12v18h-12z"/><path class="officer-arm" d="M654 153q35 19 55 31"/><path class="officer-hand" d="M709 184q10 4 15-3"/></g>
        <g class="traveller" filter="url(#shadow)"><ellipse class="traveller-shadow" cx="252" cy="281" rx="60" ry="10"/><circle class="skin" cx="252" cy="111" r="23"/><path class="hair" d="M230 108q7-28 43-18l4 21q-25-13-47 4z"/><path class="traveller-shirt" d="M228 136q23 12 48 0l11 83h-73z"/><path class="traveller-arm" d="M230 151l-27 44"/><path class="traveller-hand" d="M201 194q-3 9 6 12"/><path class="traveller-arm helping" d="M274 150l33 24"/><path class="traveller-hand" d="M306 173q9 3 12-5"/><path class="trouser leg-back" d="M229 216l-15 60"/><path class="trouser leg-front" d="M265 216l21 60"/><path class="shoe" d="M198 278h33m42 0h34"/><path class="brace" d="M260 220l20 54m-31-32 28 0"/><path class="crutch" d="M205 174l-16 105m0-54h29m-29 54h-13"/></g>
        <g class="papers"><path d="M355 232l36-8 8 28-37 8z"/><path d="M385 226l36-7 8 28-36 8z"/></g>
      </svg>
      <div class="copy"><div class="eyebrow">Department of Posts · medical reimbursement</div><h1>Care, from<br>claim to <i>clarity.</i></h1><p>A clear route from medical papers to a reviewed draft—with assistance at every step.</p><div class="chips"><span>CGHS rate intelligence</span><span>Officer review required</span></div></div>
      <div class="scene-label"><b>ASSISTED REVIEW</b><small>claim desk · 01—04</small></div>
    </div>
    <style>
      @import url('https://fonts.googleapis.com/css2?family=DM+Mono:wght@400;500&family=DM+Sans:wght@400;500;600;700&family=Fraunces:opsz,wght@9..144,600;9..144,700&display=swap');
      *{{box-sizing:border-box}}.hero{{height:320px;position:relative;overflow:hidden;border-radius:22px;background:linear-gradient(118deg,#c9252c 0%,#a51a21 46%,#56151a 100%);color:#fff;font-family:'DM Sans',sans-serif;isolation:isolate;box-shadow:0 18px 50px rgba(96,20,25,.17)}}.ambient{{position:absolute;z-index:1;border-radius:50%;filter:blur(32px);opacity:.42}}.light-one{{width:260px;height:260px;right:-40px;top:-92px;background:#fff}}.light-two{{width:260px;height:180px;right:200px;bottom:-130px;background:#f5a4a7;opacity:.19}}.india-post-logo{{position:absolute;z-index:5;right:25px;top:20px;width:96px;height:auto;padding:7px;background:rgba(255,255,255,.98);border-radius:8px;box-shadow:0 8px 25px rgba(0,0,0,.2)}}.copy{{position:relative;z-index:4;padding:39px 40px;max-width:470px}}.eyebrow{{font:500 11px 'DM Mono',monospace;letter-spacing:.12em;text-transform:uppercase;color:#ffe0e1}}.copy h1{{font-family:Fraunces,Georgia,serif;font-size:49px;line-height:.94;letter-spacing:-.06em;margin:10px 0 15px}}.copy h1 i{{color:#fff;font-weight:600}}.copy p{{margin:0;max-width:385px;color:#fff;font-size:14px;line-height:1.48;opacity:.88}}.chips{{display:flex;gap:8px;margin-top:21px;flex-wrap:wrap}}.chips span{{padding:6px 10px;border:1px solid rgba(255,255,255,.38);border-radius:99px;background:rgba(255,255,255,.1);font-size:11px;font-weight:600;backdrop-filter:blur(8px)}}.scene-label{{position:absolute;z-index:4;right:143px;top:28px;text-align:right}}.scene-label b{{display:block;font:500 10px 'DM Mono',monospace;letter-spacing:.11em;color:#fff}}.scene-label small{{font-size:10px;color:#ffe0e1;letter-spacing:.06em}}.scene{{position:absolute;z-index:2;right:0;bottom:0;height:100%;width:67%;overflow:visible}}.floor{{fill:#57141a}}.floor-line,.window rect,.window path{{stroke:#fff;stroke-width:2;fill:none;opacity:.44}}.desk path{{fill:url(#deskwood);stroke:#fff;stroke-width:1.2}}.desk .document{{fill:#fff;stroke:#eadfe0}}.desk .lamp{{fill:none;stroke:#fff;stroke-width:3;stroke-linecap:round}}.desk-shadow,.traveller-shadow{{fill:#24080a;opacity:.4;filter:url(#soft)}}.chair{{fill:#71191f;stroke:#e78b8f;stroke-width:2}}.skin{{fill:#c88361}}.hair{{fill:#1e2024}}.officer-body{{fill:url(#uniform);stroke:#eadfe0;stroke-width:1.4}}.collar{{fill:#fff;stroke:#eadfe0;stroke-width:1.3}}.badge{{fill:#c9252c}}.officer-arm,.traveller-arm{{fill:none;stroke:#fff;stroke-width:13;stroke-linecap:round}}.officer-hand,.traveller-hand{{fill:none;stroke:#c88361;stroke-width:10;stroke-linecap:round}}.officer-leg,.trouser{{fill:none;stroke:#343034;stroke-width:16;stroke-linecap:round}}.officer-shoe,.shoe{{fill:none;stroke:#201c1f;stroke-width:10;stroke-linecap:round}}.traveller-shirt{{fill:#fff;stroke:#eadfe0;stroke-width:1.3}}.brace{{stroke:#c9252c;stroke-width:5;stroke-linecap:round}}.crutch{{fill:none;stroke:#fff;stroke-width:7;stroke-linecap:round}}.papers path{{fill:#fff;stroke:#eadfe0;stroke-width:1}}.traveller{{animation:arrival 8s cubic-bezier(.35,.02,.28,1) infinite;transform-origin:center}}.leg-back{{animation:leg-back .72s ease-in-out infinite alternate;transform-origin:229px 216px}}.leg-front{{animation:leg-front .72s .36s ease-in-out infinite alternate;transform-origin:265px 216px}}.crutch{{animation:crutch-step .72s .18s ease-in-out infinite alternate;transform-origin:205px 174px}}.helping{{animation:reassure 8s ease-in-out infinite}}.officer-arm{{animation:welcome 8s ease-in-out infinite}}.papers{{animation:paper-offer 8s ease-in-out infinite}}@keyframes arrival{{0%,15%{{transform:translateX(-155px)}}55%,100%{{transform:translateX(115px)}}}}@keyframes leg-back{{to{{transform:rotate(10deg)}}}}@keyframes leg-front{{to{{transform:rotate(-12deg)}}}}@keyframes crutch-step{{to{{transform:rotate(5deg) translateY(3px)}}}}@keyframes welcome{{0%,44%{{transform:rotate(0)}}55%,78%{{transform:rotate(-7deg)}}100%{{transform:rotate(0)}}}}@keyframes reassure{{0%,47%{{transform:translate(0,0)}}58%,76%{{transform:translate(9px,1px)}}100%{{transform:translate(0,0)}}}}@keyframes paper-offer{{0%,45%{{opacity:0;transform:translateX(-28px)}}58%,82%{{opacity:1;transform:translateX(0)}}100%{{opacity:0;transform:translateX(12px)}}}}@media(max-width:700px){{.hero{{height:300px}}.copy{{padding:34px 25px;max-width:410px}}.copy h1{{font-size:42px}}.scene{{width:100%;opacity:.42}}.india-post-logo{{right:16px;top:14px;width:76px}}.scene-label{{display:none}}}}@media(prefers-reduced-motion:reduce){{.traveller,.leg-back,.leg-front,.crutch,.helping,.officer-arm,.papers{{animation:none}}}}
    </style>
    """, height=320)


render_claim_orbit()
_division_name = (st.session_state.get("office_division") or "").strip()
st.caption(f"{_division_name + ' — ' if _division_name else ''}decision-support tool. "
           "Every match and amount must be reviewed by the processing officer before a case is sanctioned.")

st.markdown(
    '<div class="workflow-rail"><span><b>01</b>Choose reading mode</span><span><b>02</b>Read the claim</span>'
    '<span><b>03</b>Review rates</span><span><b>04</b>Issue documents</span></div>',
    unsafe_allow_html=True,
)
st.markdown('<div class="trust-note">Drafts only — review each match, rate and final amount before sanction. '
            'Your API key remains in Streamlit secrets and is never shown in the workspace.</div>', unsafe_allow_html=True)
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
st.header("01 — Add claim documents")

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
    raw = f.read()
    images = []
    if f.type == "application/pdf" or f.name.lower().endswith(".pdf"):
        from pdf2image import convert_from_bytes
        images.extend(convert_from_bytes(raw, dpi=200))
    else:
        images.append(Image.open(io.BytesIO(raw)))
    return images

EXTRACTION_PROMPT = """You are reading scanned/photographed CGHS medical reimbursement claim documents
(claim form, bill/receipt, doctor's referral, CGHS card). Extract the following as strict JSON, with
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
  "line_items": [
    {
      "description": string,          // the test/treatment name exactly as printed; expand common abbreviations in parentheses if unambiguous, e.g. "CBC (Complete Haemogram)"
      "code": string or null,         // only a CGHS code actually visible in the document; never guess or invent a code
      "claimed_amount": number
    }
  ]
}

Read every page provided. First identify the applicant's completed reimbursement/claim form. Extract
`diagnosis` only from the diagnosis field or handwritten/typed diagnosis on that applicant form. Do NOT
copy a diagnosis from a discharge summary, prescription, referral, bill, laboratory report or any other
attachment, even if those documents are more detailed. If the applicant form has no diagnosis, return
null for both diagnosis fields. For line_items, include every
distinct billed test/treatment/procedure row you can find, with its exact price as printed - including
rows priced at 0. If no CGHS code is printed, leave code null: the application will match the description against
the official rate master and will mark uncertain results for officer review. Do not invent values. Output ONLY the JSON object."""

def _clean_json_text(raw_text):
    raw_text = raw_text.strip().strip("`")
    if raw_text.lower().startswith("json"):
        raw_text = raw_text[4:].strip()
    return raw_text

def extract_with_anthropic(images, api_key, model_name):
    import anthropic
    client = anthropic.Anthropic(api_key=api_key)
    content_blocks = []
    for im in images:
        buf = io.BytesIO()
        im.convert("RGB").save(buf, format="PNG")
        b64 = base64.b64encode(buf.getvalue()).decode()
        content_blocks.append({"type": "image", "source": {"type": "base64", "media_type": "image/png", "data": b64}})
    content_blocks.append({"type": "text", "text": EXTRACTION_PROMPT})

    resp = client.messages.create(
        model=model_name,
        max_tokens=4000,
        messages=[{"role": "user", "content": content_blocks}]
    )
    raw_text = "".join(b.text for b in resp.content if b.type == "text")
    return json.loads(_clean_json_text(raw_text))

def extract_with_gemini(images, api_key, model_name):
    from google import genai
    client = genai.Client(api_key=api_key)
    contents = list(images) + [EXTRACTION_PROMPT]
    resp = client.models.generate_content(model=model_name, contents=contents)
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
                images = []
                for f in uploaded_files:
                    images.extend(file_to_pil_images(f))

                if provider == P_CLAUDE:
                    extracted = extract_with_anthropic(images, api_key, model_name)
                else:
                    extracted = extract_with_gemini(images, api_key, model_name)

                st.session_state.extracted = extracted
                st.session_state.line_items = extracted.get("line_items", [])
                # A fresh extraction starts a fresh officer review. Do not carry
                # code choices from a previous claim into the new one.
                st.session_state.pop("review_rows", None)
                st.success("Extraction complete. Review and correct the details below.")
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
                        + ("Please tell the administrator. They need to update the fixed `GEMINI_MODEL` setting "
                           "in `app.py` to a currently available Google model."
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
                st.session_state.pop("review_rows", None)

# ---------------------------------------------------------------------------
# Step 2: Review / correct claimant details (manual override always available)
# ---------------------------------------------------------------------------
st.header("02 — Confirm claimant details")
st.caption("If OCR could not read the name or employee ID, fill them in here manually - everything on this page is editable.")

ex = st.session_state.extracted or {}
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
st.header("03 — Review CGHS rate check")


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
         "claimed_amount": it.get("claimed_amount", 0) or 0, "override": OVERRIDE_AUTO}
        for i, it in enumerate(items_raw)
    ] or [{"id": "new-0", "description": "", "billed_code": "", "matched_code": "",
            "claimed_amount": 0, "override": OVERRIDE_AUTO}]

st.caption(f"Rate lookup: **{tier_label}**, **{nabh_status}** (change in the sidebar if needed)")
st.write(
    "Search either code picker by code or description. Selecting a CGHS code fetches its official "
    "description and the rate for the chosen tier. You can add, edit or delete any review entry before preparing the draft."
)

NO_CODE = "— Search CGHS codes —"
code_labels = {code: f"{code} — {record['description']}" for code, record in BY_CODE.items()}
code_options = [NO_CODE] + [code_labels[code] for code in sorted(code_labels)]
label_to_code = {label: code for code, label in code_labels.items()}

def _picker_value(code):
    return code_labels.get(code, NO_CODE)

def _code_from_picker(value):
    return label_to_code.get(value, "")

def _use_selected_code(row, field, selected_code):
    """Apply a searchable CGHS-code selection without overwriting billed amount."""
    row[field] = selected_code
    if selected_code:
        row["description"] = BY_CODE[selected_code]["description"]
        # The description input is created later in this run, so keep its
        # widget value in step with a code selection as well.
        st.session_state[f"description_{row['id']}"] = row["description"]

for index, review_row in enumerate(st.session_state.review_rows):
    row_id = review_row["id"]
    label = _txt(review_row.get("description")) or "New item"
    with st.expander(f"{index + 1:02d} · {label}", expanded=True):
        c1, c2 = st.columns(2)
        with c1:
            selected_billed = st.selectbox(
                "Billed code", code_options,
                index=code_options.index(_picker_value(review_row.get("billed_code", ""))),
                key=f"billed_code_{row_id}",
                help="Search the dropdown by CGHS code or description. This is a searchable official-code catalogue.",
            )
            selected_billed_code = _code_from_picker(selected_billed)
            if selected_billed_code != review_row.get("billed_code", ""):
                _use_selected_code(review_row, "billed_code", selected_billed_code)
                if not review_row.get("matched_code"):
                    _use_selected_code(review_row, "matched_code", selected_billed_code)
                    # The matched picker is created after the billed picker.
                    st.session_state[f"matched_code_{row_id}"] = _picker_value(selected_billed_code)
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
        active_code = review_row.get("matched_code") or review_row.get("billed_code")
        rate = get_rate(BY_CODE[active_code], tier_label, nabh_status) if active_code else None
        with c5:
            st.metric("Official CGHS rate", f"₹{rate:,.2f}" if rate is not None else "—")
            if st.button("Delete entry", key=f"delete_{row_id}", help="Remove this entry from the current review."):
                st.session_state.review_rows.pop(index)
                st.rerun()
        if active_code:
            st.caption(f"Official description: **{BY_CODE[active_code]['description']}**")

if st.button("+ Add new entry", key="add_review_entry"):
    st.session_state.review_rows.append({
        "id": f"new-{len(st.session_state.review_rows)}-{datetime.datetime.now().timestamp():.0f}",
        "description": "", "billed_code": "", "matched_code": "", "claimed_amount": 0,
        "override": OVERRIDE_AUTO,
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
    if not code and (desc_billed or billed_code):
        auto = match_line_item({"description": desc_billed, "code": billed_code, "claimed_amount": claimed},
                               BY_CODE, DESCRIPTIONS, tier_label=tier_label, accreditation=nabh_status)
        code = auto.get("matched_code")
    if not (desc_billed or billed_code or code or claimed):
        continue
    rate = get_rate(BY_CODE[code], tier_label, nabh_status) if code else None
    rows_final.append({
        "description": desc_billed, "billed_code": billed_code, "code": code,
        "claimed_amount": claimed, "cghs_rate": rate,
        "admissible_amount": min(claimed, rate) if rate is not None else None,
        "matched_description": BY_CODE[code]["description"] if code else desc_billed,
        "override": _txt(row.get("override")) or OVERRIDE_AUTO,
    })

final_items = apply_billing_rules(rows_final, BY_CODE)


def _result_note(r):
    note = r['rule_note']
    if r['cghs_rate'] is not None and r['claimed_amount'] > r['cghs_rate']:
        capped = f"Billed ₹{r['claimed_amount']:,.2f} is above the CGHS rate ₹{r['cghs_rate']:,.2f} - restricted to the rate."
        note = f"{note} {capped}".strip()
    return note


sheet = pd.DataFrame([{
    'Sl.': i + 1,
    'Particulars': r['matched_description'],
    'CGHS code': r['code'] or '-',
    'Claimed (₹)': r['claimed_amount'],
    'CGHS rate (₹)': r['cghs_rate'],
    'Counted (₹)': r['counted_amount'],
    'Result': r['rule_status'],
    'Note': _result_note(r),
} for i, r in enumerate(final_items)])


def _row_colour(row):
    status = row['Result']
    if status in (INCLUDED, REPEAT, FORCED_EXCLUDE):
        bg = 'rgba(220, 53, 69, 0.18)'       # held back
    elif status == UNMATCHED or str(status).startswith('REVIEW'):
        bg = 'rgba(255, 193, 7, 0.22)'       # needs the officer's attention
    else:
        bg = ''
    return [f'background-color: {bg}' if bg else '' for _ in row]


st.subheader("Calculation sheet")
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

total_claimed = sum(r['claimed_amount'] for r in final_items)
total_admissible = sum(r['counted_amount'] for r in final_items if r['counted_amount'] is not None)
unresolved = [r for r in final_items if r['counted_amount'] is None]
summary = summarise(final_items)

m1, m2, m3 = st.columns(3)
m1.metric("Total claimed", f"₹{total_claimed:,.2f}")
m2.metric("Total admissible (as per CGHS rates)", f"₹{total_admissible:,.2f}")
diff = total_claimed - total_admissible
m3.metric("Difference", f"₹{diff:,.2f}", delta=f"-₹{diff:,.2f}" if diff > 0 else None, delta_color="inverse")

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

st.markdown("---")

# ---------------------------------------------------------------------------
# Step 4: Generate documents
# ---------------------------------------------------------------------------
st.header("04 — Prepare sanction documents")


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

use_admissible = st.checkbox("Sanction the CGHS-checked admissible amount (recommended)", value=True,
                              help="Uncheck only if you intend to sanction the full claimed amount regardless of the rate check above.")
final_amount = total_admissible if use_admissible else total_claimed

st.write(f"**Amount to be sanctioned: ₹{final_amount:,.0f}** ({rupees_in_words(final_amount)})")

if unresolved or summary['review']:
    st.caption("⚠️ Some rows above still need a decision (REVIEW / NO MATCH). You can generate the documents now, "
               "but the amounts will change if you resolve them afterwards - generate again if so.")


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


if st.button("📄 Generate documents", type="primary", disabled=(not name or not emp_id)):
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
    }
    ns_items = [{
        'sl_no': i + 1,
        'particulars': r['matched_description'] or r['description'],
        'code': r['code'],
        'claimed': f"{float(r['claimed_amount']):.2f}",
        'admissible': f"{float(r['counted_amount']):.2f}" if r['counted_amount'] is not None else 'MANUAL REVIEW',
        'remark': _remark(r),
    } for i, r in enumerate(final_items)]

    out_dir = os.path.join(tempfile.gettempdir(), 'cghs_out')
    os.makedirs(out_dir, exist_ok=True)
    sanction_path = os.path.join(out_dir, 'Sanction_Memo.docx')
    ns_path = os.path.join(out_dir, 'NS_Checklist.docx')
    build_sanction_memo(case, sanction_path)
    build_ns_checklist(case, ns_items, ns_path)

    # Keep the finished files in the session so both download buttons stay on screen
    # (clicking one download button reruns the page, which would otherwise make the other vanish).
    with open(sanction_path, 'rb') as f1, open(ns_path, 'rb') as f2:
        st.session_state.generated_docs = {'memo': f1.read(), 'ns': f2.read(), 'emp_id': emp_id, 'name': name}

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
