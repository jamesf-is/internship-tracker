"""Everything you might want to tweak lives here."""

# ---------------------------------------------------------------- filtering
# A posting must look like an internship / co-op ...
INTERN_RE = r"\b(intern|interns|internship|co-?op|coop|student trainee|pathways|summer (20\d\d )?(engineer|associate|trainee))\b"

# ... AND match a relevant engineering discipline in the title.
# STRONG terms are accepted at any company; WEAK terms (generic "systems", "test", ...) are only
# accepted at aerospace/defense companies so chip, audio and consulting roles stay out.
STRONG_RE = (
    r"mechanic|aerospace|aeronaut|astronaut|\bstructur|\bstress|thermal|propulsion|launch|spacecraft|"
    r"satellite|\bspace\b|rocket|composite|flight|mechanism|orbit|reentry|"
    r"hypersonic|propellant|\bcfd\b|\bfea\b|\bgnc\b|payload|turbopump"
)
WEAK_RE = (
    r"\bengines?\b|systems? engineer|\btest\b|testing|material|manufacturing|design eng|integration|reliability|"
    r"quality eng|vehicle|\bcad\b|fluid|dynamics|guidance|mission|ground support|\bgse\b|"
    r"environmental|vibration|metrology|machin|fabrication|welding|additive|production eng|process eng"
)
INCLUDE_RE = STRONG_RE + "|" + WEAK_RE
# ... or be a generic "Engineering Intern" title (accepted only at aerospace companies).
GENERIC_ENG_RE = r"\bengineer|engineering"

# A company counts as aerospace if it is on your spreadsheet / the extra list in this file,
# OR its name looks aerospace, OR the posting text clearly describes space work.
AERO_NAME_RE = r"aerospace|\baero|space|rocket|orbital|orbit|satellite|launch|astro|lunar|stellar|cosmic"
SPACE_DESC_RE = r"spacecraft|satellite|launch vehicle|rocket|space systems|space station|orbital|lunar|space exploration|in-space|aerospace"

# Air / ocean work is dropped (title always; description only if it never mentions space).
AIR_OCEAN_RE = (
    r"\baircraft|aviation|airframe|helicopter|rotorcraft|fixed[- ]wing|\bmarine|naval|\bocean|undersea|"
    r"maritime|submarine|\bships?\b|shipbuilding|commercial airplane|fighter|jet engine|\buas\b|\buav\b|drone"
)
# Companies that mostly do aircraft: their postings must explicitly mention space to be kept.
# (matched as prefixes of the normalized company name)
AIR_FOCUSED_COMPANIES = [
    "gulfstream", "textron", "bell", "archer", "joby", "boom", "spirit", "generalatomics", "magellan",
    "triumph", "kaman", "geaerospace", "prattwhitney", "safran", "raytheon", "hermeus", "skyryse",
    "venus", "sceye", "zipline", "aerovironment", "parker",
]

# Undergraduate summer only.
GRAD_TITLE_RE = r"\b(graduate|grad|master'?s?|phd|ph\.d|doctoral|returning|post-?bac|postgraduate)\b"
GRAD_DESC_RE = (r"graduate student|master'?s? (degree )?(student|program|candidate)|enrolled in a graduate|"
                r"ph\.?d\.? (student|candidate)|returning (intern|student|co-?op)s?|must be a returning|"
                r"rising (second|2nd)[- ]year (master|graduate)")
UNDERGRAD_RE = r"undergrad|bachelor|rising (sophomore|junior|senior)|sophomore|junior|freshman|b\.?s\.? (degree|student)"
NON_SUMMER_TITLE_RE = r"\b(fall|spring|winter|autumn|year[- ]round|semester)\b"

# Anything matching these in the TITLE is dropped (finance, AI, software, ...).
EXCLUDE_RE = (
    r"software|\bdata\b|machine learning|\bml\b|\bai\b|artificial|finance|financial|accounting|"
    r"marketing|sales|human resources|\bhr\b|legal|business|procurement|supply chain|cyber|"
    r"information tech|\bit\b|firmware|fpga|embedded|electrical|electronic|\brf\b|chemical|civil|"
    r"biomed|clinical|quant|trading|product manage|program manage|communications|graphic|"
    r"\bphd\b|ph\.d|master|postdoc|high school|economics|analyst|recruit|legal|paralegal|"
    r"nurs|pharma|biolog|developer|devops|cloud|network|facilities|silicon|asic|\bdft\b|semiconductor|"
    r"wafer|audio|analog|digital|\bsoc\b|verification|\brtl\b|circuit|\bpcb\b|\bgpu\b|\bcpu\b|physics engine|"
    r"platform hardware|chip|photonic|optical|liquidity|stress test|bank|programmer|game"
)

# Terms that mean "not summer 2027" when they appear in title/description.
OTHER_TERM_RE = (
    r"(spring|fall|autumn|winter)\s*'?(20)?2[5-9]\b|"      # spring/fall/winter of any nearby year
    r"summer\s*'?(20)?(24|25|26)\b|"                          # earlier summers
    r"summer\s*'?(20)?(28|29)\b"
)
TARGET_YEAR = "2027"

# Only US locations (blank locations are kept). Non-US hints that drop a posting:
NON_US_RE = r"\b(canada|united kingdom|uk|india|germany|france|australia|china|singapore|japan|mexico|brazil|israel|ireland|netherlands|poland)\b|, ON\b|, BC\b|, QC\b"

# ---------------------------------------------------------------- LinkedIn
LINKEDIN_QUERIES = [
    "aerospace engineering intern summer 2027",
    "mechanical engineering intern summer 2027 aerospace",
    "structures engineering intern space",
    "structural analysis intern aerospace",
    "systems engineering intern spacecraft",
    "test engineering intern aerospace",
    "propulsion engineering intern",
    "thermal engineering intern spacecraft",
    "satellite engineering intern",
    "launch vehicle engineering intern",
    "composites engineering intern",
    "mechanical design intern space",
    "aerospace co-op summer 2027",
    "manufacturing engineering intern aerospace",
]
LINKEDIN_HOURS = 72  # look-back window per run (duplicates are removed anyway)

# ---------------------------------------------------------------- Muse / Adzuna / USAJOBS
ADZUNA_QUERIES = ["aerospace engineering intern", "mechanical engineering intern aerospace",
                  "structures engineer intern", "systems engineering intern space"]
USAJOBS_QUERIES = ["engineering intern aerospace", "mechanical engineer student trainee",
                   "aerospace engineer pathways", "NASA intern engineering"]

# ---------------------------------------------------------------- company boards
# Extra aerospace companies (beyond the spreadsheet) whose public job boards we try to
# auto-discover on Greenhouse / Lever / Ashby / SmartRecruiters / Workable.
EXTRA_COMPANIES = [
    "SpaceX", "Astranis", "Stoke Space", "Impulse Space", "True Anomaly", "Hadrian", "Vast",
    "Axiom Space", "Voyager Space", "Muon Space", "K2 Space", "Albedo", "Ursa Major",
    "Skyryse", "Hermeus", "Boom Supersonic", "Venus Aerospace", "Radiant", "Astroscale",
    "Orbit Fab", "Momentus", "Redwire", "Maxar", "ABL Space", "Phantom Space", "Lunar Outpost",
    "Karman Space", "Blue Canyon Technologies", "Spire", "Planet Labs", "Capella Space",
    "Umbra", "Shield AI", "Epirus", "Castelion", "Northwood Space", "Quindar", "Sidus Space",
    "Loft Orbital", "X-Bow Systems", "Vaya Space", "Frontier Aerospace", "Rocket Lab",
    "Firefly Aerospace", "Relativity Space", "Anduril", "Archer Aviation", "Joby Aviation",
    "Sierra Space", "Apex Space", "Varda Space", "Astrobotic", "Intuitive Machines",
    "Terran Orbital", "York Space Systems", "CesiumAstro", "Aalyria", "Ball Aerospace",
    "Sceye", "Zero Gravity Solutions", "Vulcan Elements", "Saronic", "Leonardo DRS",
    "Mercury Systems", "Teledyne", "Kratos", "AeroVironment", "Aerojet Rocketdyne", "Xeus",
    "Starfish Space", "Inversion Space", "Atomos Space", "Starlab Space", "Gravitics",
    "Outpost Space", "Interlune", "Sierra Nevada Corporation", "Virgin Orbit", "Orbital Sciences",
]

# Workday tenants: (label, tenant, wdN, site). Best-effort; any that 404 are reported
# in the run health and simply skipped. Fix/add via each company's careers URL:
#   https://<tenant>.<wdN>.myworkdayjobs.com/<site>
WORKDAY = [
    ("Northrop Grumman", "ngc", "wd1", "Northrop_Grumman_External_Site"),
    ("L3Harris / Aerojet", "l3harris", "wd1", "L3Harris"),
    ("Boeing", "boeing", "wd1", "EXTERNAL_CAREERS"),
    ("RTX (Raytheon, Collins, Pratt)", "globalhr", "wd5", "REC_RTX_Ext_Gateway"),
    ("GE Aerospace", "ge", "wd5", "GE_ExternalSite"),
    ("Honeywell", "honeywell", "wd5", "Honeywell"),
    ("Lockheed Martin", "lmco", "wd1", "LockheedMartinJobs"),
    ("General Dynamics Mission Systems", "gdmissionsystems", "wd1", "External_Career_Site"),
    ("Leidos", "leidos", "wd5", "External"),
    ("Textron", "textron", "wd1", "textron"),
    ("BAE Systems", "baesystems", "wd3", "BAE_Systems"),
    ("MITRE", "mitre", "wd5", "MITRE"),
    ("Parsons", "parsons", "wd5", "Search"),
    ("Peraton", "peraton", "wd1", "Careers"),
    ("Blue Origin", "blueorigin", "wd5", "BlueOrigin"),
    ("Spirit AeroSystems", "spiritaero", "wd1", "Spirit_Careers"),
    ("Sierra Space", "sierraspace", "wd5", "sierra_space_careers"),
    ("Johns Hopkins APL", "jhuapl", "wd5", "APLCareers"),
    ("Moog", "moog", "wd5", "moog_careers"),
    ("Parker Hannifin", "parker", "wd5", "Parker_Careers"),
    ("Woodward", "woodward", "wd5", "Woodward"),
    ("Howmet Aerospace", "howmet", "wd5", "Howmet"),
    ("Triumph Group", "triumphgroup", "wd5", "Triumph_Careers"),
    ("Curtiss-Wright", "curtisswright", "wd5", "CW_Careers"),
    ("Gulfstream", "gulfstream", "wd1", "Gulfstream"),
    ("Ducommun", "ducommun", "wd5", "Ducommun"),
    ("ULA", "ula", "wd1", "ULA_External"),
]

# Community-maintained Summer 2027 internship list (JSON, updated daily).
SIMPLIFY_URL = "https://raw.githubusercontent.com/SimplifyJobs/Summer2027-Internships/dev/.github/scripts/listings.json"
SIMPLIFY_CATEGORIES = {"Hardware", "Hardware Engineering"}

# ---------------------------------------------------------------- housekeeping
EMAIL_MAX_ROWS = 80          # rows listed in the email (rest are on the page)
STALE_DAYS_NONSNAPSHOT = 60  # LinkedIn/Muse/Adzuna postings disappear from the page after this
