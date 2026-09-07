"""Job parsing workflow, skill extraction, normalization, and compatibility scoring for job packets."""

import json
import os
import re
from datetime import datetime, timezone
from html import unescape
from pathlib import Path
from typing import Any, TypedDict
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from src.infrastructure.environment import load_dotenv
from src.infrastructure.openrouter import post_json_schema
from src.infrastructure.prompt_config import load_prompt_config

# Configuration & Constants
COMPATIBILITY_BORDERLINE_LOW = 3
COMPATIBILITY_BORDERLINE_HIGH = 10
RESUME_MODULE_NAMES = ("summary.tex", "experience.tex", "personalprojects.tex", "aboutme.tex")

PROMPT_CONFIG_PATH = Path(__file__).resolve().parents[1] / "infrastructure" / "prompts.json"

DEFAULT_PARSER_PROMPTS: dict[str, str] = {
    "job_parser_system_prompt": (
        "You extract structured job posting data. Return valid JSON with keys: "
        "title, company, location, employment_type, description, must_have, "
        "nice_to_have, responsibilities, domain."
    ),
    "job_parser_user_prompt_template": (
        "Parse the following job listing into JSON. "
        "Use empty arrays for missing skill lists and unknown for missing values.\n\n"
        "{listing_text}"
    ),
}

SKILL_CANONICAL_MAP: dict[str, str] = {
    # JavaScript ecosystem
    "node js": "Node.js",
    "nodejs": "Node.js",
    "node": "Node.js",
    "express js": "Express.js",
    "expressjs": "Express.js",
    "express": "Express.js",
    "typescript": "TypeScript",
    "ts": "TypeScript",
    "javascript": "JavaScript",
    "js": "JavaScript",
    "react": "React",
    "react js": "React",
    "reactjs": "React",
    "next js": "Next.js",
    "nextjs": "Next.js",
    "vue": "Vue",
    "vue js": "Vue",
    "vuejs": "Vue",
    "nuxt": "Nuxt",
    "nuxt js": "Nuxt",
    "angular": "Angular",
    "angularjs": "Angular",
    "angular js": "Angular",
    "solid": "Solid",
    "solid js": "Solid",
    "svelte": "Svelte",
    "sveltekit": "SvelteKit",
    "jquery": "jQuery",
    "redux": "Redux",
    "webpack": "Webpack",
    "vite": "Vite",
    "turborepo": "Turborepo",
    "graphql": "GraphQL",
    "graph ql": "GraphQL",
    "rest": "REST APIs",
    "rest api": "REST APIs",
    "rest apis": "REST APIs",
    "restful": "REST APIs",
    "restful apis": "REST APIs",
    "html": "HTML",
    "html5": "HTML",
    "css": "CSS",
    "css3": "CSS",
    "sass": "Sass",
    "scss": "Sass",
    "less": "Less",
    "tailwind": "Tailwind CSS",
    "tailwind css": "Tailwind CSS",
    "tailwindcss": "Tailwind CSS",
    # Backend languages
    "python": "Python",
    "django": "Django",
    "flask": "Flask",
    "fastapi": "FastAPI",
    "rust": "Rust",
    "go": "Go",
    "golang": "Go",
    "java": "Java",
    "spring": "Spring",
    "spring boot": "Spring Boot",
    "kotlin": "Kotlin",
    "scala": "Scala",
    "c#": "C#",
    "c sharp": "C#",
    "csharp": "C#",
    "net": ".NET",
    "net core": ".NET",
    "dotnet": ".NET",
    "c++": "C++",
    "cpp": "C++",
    "c": "C",
    "php": "PHP",
    "laravel": "Laravel",
    "ruby": "Ruby",
    "rails": "Rails",
    "ruby on rails": "Rails",
    "elixir": "Elixir",
    "haskell": "Haskell",
    "swift": "Swift",
    "objective-c": "Objective-C",
    # Databases
    "sql": "SQL",
    "nosql": "NoSQL",
    "no sql": "NoSQL",
    "postgresql": "PostgreSQL",
    "postgres": "PostgreSQL",
    "mysql": "MySQL",
    "mariadb": "MariaDB",
    "sqlite": "SQLite",
    "mongodb": "MongoDB",
    "mongo": "MongoDB",
    "redis": "Redis",
    "elasticsearch": "Elasticsearch",
    "dynamodb": "DynamoDB",
    "cassandra": "Cassandra",
    "oracle": "Oracle",
    "sql server": "SQL Server",
    "mssql": "SQL Server",
    "relational databases": "Relational Databases",
    "relational database": "Relational Databases",
    "databases sql": "SQL",
    "databases nosql": "NoSQL",
    # Cloud & DevOps
    "aws": "AWS",
    "aws technologies": "AWS",
    "amazon web services": "AWS",
    "gcp": "GCP",
    "google cloud": "GCP",
    "google cloud platform": "GCP",
    "azure": "Azure",
    "microsoft azure": "Azure",
    "docker": "Docker",
    "kubernetes": "Kubernetes",
    "k8s": "Kubernetes",
    "terraform": "Terraform",
    "ansible": "Ansible",
    "jenkins": "Jenkins",
    "ci": "CI",
    "cd": "CD",
    "ci cd": "CI/CD",
    "cicd": "CI/CD",
    "ci/cd": "CI/CD",
    "devops": "DevOps",
    "devops experience": "DevOps",
    "linux": "Linux",
    "nginx": "Nginx",
    "apache": "Apache",
    "serverless": "Serverless",
    "lambda": "AWS Lambda",
    "aws lambda": "AWS Lambda",
    # Version control & tooling
    "git": "Git",
    "gitlab": "GitLab",
    "git lab": "GitLab",
    "github": "GitHub",
    "git hub": "GitHub",
    "bitbucket": "Bitbucket",
    "svn": "SVN",
    "jira": "Jira",
    "confluence": "Confluence",
    "linear": "Linear",
    "cursor": "Cursor",
    "vim": "Vim",
    "vscode": "VS Code",
    "vs code": "VS Code",
    "visual studio code": "VS Code",
    "intellij": "IntelliJ",
    # Testing
    "jest": "Jest",
    "mocha": "Mocha",
    "pytest": "pytest",
    "cypress": "Cypress",
    "playwright": "Playwright",
    "selenium": "Selenium",
    "unit testing": "Unit Testing",
    "integration testing": "Integration Testing",
    "tdd": "TDD",
    "test driven development": "TDD",
    # Data & ML
    "machine learning": "Machine Learning",
    "ml": "Machine Learning",
    "deep learning": "Deep Learning",
    "tensorflow": "TensorFlow",
    "pytorch": "PyTorch",
    "pandas": "Pandas",
    "numpy": "NumPy",
    "scikit-learn": "scikit-learn",
    "sklearn": "scikit-learn",
    "spark": "Spark",
    "apache spark": "Spark",
    "kafka": "Kafka",
    "apache kafka": "Kafka",
    "airflow": "Airflow",
    "apache airflow": "Airflow",
    "ai-powered developer tools": "AI-powered development",
    "ai powered developer tools": "AI-powered development",
    "ai-powered development": "AI-powered development",
    "ai": "AI",
    "artificial intelligence": "AI",
    # Mobile
    "ios": "iOS",
    "android": "Android",
    "react native": "React Native",
    "flutter": "Flutter",
    "dart": "Dart",
    # Misc compound phrases seen in listings
    "frontend typescript": "TypeScript",
    "front-end typescript": "TypeScript",
    "backend node js": "Node.js",
    "back-end node js": "Node.js",
    "infrastructure relational databases": "Relational Databases",
    "cd pipelines in gitlab": "GitLab",
    "pipelines in gitlab": "GitLab",
    "ci cd pipelines in gitlab": "GitLab",
    "git version control": "Git",
    "git version control software": "Git",
    "microservices": "Microservices",
    "micro services": "Microservices",
    "agile": "Agile",
    "scrum": "Scrum",
    "oauth": "OAuth",
    "jwt": "JWT",
    "websockets": "WebSockets",
    "web sockets": "WebSockets",
    "grpc": "gRPC",
    "rabbitmq": "RabbitMQ",
    "redis cache": "Redis",
    "bash": "Bash",
    "shell scripting": "Shell Scripting",
    "powershell": "PowerShell",
    "containerization": "Docker",
    "containers": "Docker",
    "virtualization": "Docker",
    "storybook": "Storybook",
    "storybook-driven testing": "Storybook",
    "storybook driven testing": "Storybook",
    "tanstack": "TanStack",
    "tanstack query": "TanStack",
    "react query": "TanStack",
    "react aria": "React Aria",
    "cloud": "Cloud",
}

SKILL_BLOCKLIST_PATTERNS: list[re.Pattern[str]] = [
    re.compile(pattern, flags=re.I)
    for pattern in [
        # Education & credentials
        r"\bbachelor'?s?\b",
        r"\bmaster'?s?\b",
        r"\bph\.?d\b",
        r"\bdegree\b",
        r"\bcomputer science\b",
        r"\bcomputer engineering\b",
        r"\brelated (?:technical )?(?:field|discipline)\b",
        r"\bbootcamp\b",
        r"^cs$",
        r"^ee$",
        r"\buniversity\b",
        r"\bcollege\b",
        r"\bcertification\b",
        r"\bcertified\b",
        # Experience-level statements
        r"\bequivalent (?:hands-on |practical )?experience\b",
        r"\byears? of\b",
        r"\b\d+\s*[-\u2013+]\s*\d*\s*years?\b",
        r"\bhands-on experience\b",
        r"\bprofessional experience\b",
        r"\brelevant experience\b",
        r"\bpractical experience\b",
        r"\bdirectly relevant\b",
        # Clearances & eligibility
        r"\bsecurity clearance\b",
        r"\bsecret\b",
        r"\bclearance\b",
        r"\bgovernment\b",
        r"\bu s\b",
        r"\bwork authorization\b",
        r"\bvisa\b",
        r"\bsponsorship\b",
        r"\bcitizen\b",
        # Soft skills & collaboration phrases
        r"\bcommunication skills?\b",
        r"\bsoft ?skills?\b",
        r"\bteamwork\b",
        r"\bcollaborat\w*\b",
        r"\bself-?learner\b",
        r"\blearning new technologies\b",
        r"\bdesign skills?\b",
        r"\bsense of ownership\b",
        r"\buser experience\b",
        r"\brapid solution assessment\b",
        r"\bproblem[- ]solving\b",
        r"\battention to detail\b",
        r"\btime management\b",
        r"\bfast-paced\b",
        r"\bself-?motivated\b",
        r"\bteam player\b",
        r"\bpassionate\b",
        r"\bpassion for\b",
        r"\bcurious\b",
        r"\bresourceful\b",
        r"\bmentor\w*\b",
        r"\bleadership\b",
        r"\bstakeholder\w*\b",
        r"\bcross-?functional\b",
        r"\binterpersonal\b",
        r"\bgrowth mindset\b",
        r"\bopen to feedback\b",
        r"\bcode reviews?\b",
        r"\bteam discussions?\b",
        r"\bshared understanding\b",
        r"\balignment\b",
        r"\bmove faster\b",
        r"\bbuild smarter\b",
        r"\bwork better\b",
        r"\bask questions\b",
        r"\bgive input\b",
        r"\bsupport your teammates\b",
        r"\ba coding\b",
        r"\bwilling to\b",
        r"\badopt\b",
        r"\blearn\b",
        r"\bownership\b",
        r"\bfeedback\b",
        r"\bgrow as an engineer\b",
        r"\binterest in innovation\b",
        r"\bemerging trends\b",
        r"\bbest-?in-?class\b",
        # Domain & company context
        r"\bhighly regulated\b",
        r"\btelehealth\b",
        r"\bmission-?critical\b",
        r"\bcustomer-facing\b",
        r"\buser-facing\b",
        r"\buser-first\b",
        r"\bintuitive\b",
        r"\bacross our platform\b",
        r"\btechnical challenges\b",
        r"\breal-world (?:problems|applications)\b",
        r"\bthrough code\b",
        r"\benjoys\b",
        r"\btackle\b",
        r"\bdebug issues\b",
        r"\bcode quality\b",
        r"\bsystem reliability\b",
        r"\btechnical limitations\b",
        r"\bux/ui team\b",
        r"\bprogress reports?\b",
        r"\bdocumentation for customers\b",
        r"\btechnical (?:and non-technical )?deliverables\b",
        r"\bagile (?:meetings|tools|methodolog\w+)\b",
        r"\bchanging priorities\b",
        r"\bin person\b",
        r"\bcolorado springs\b",
        # Generic experience-summary fragments
        r"\bsoftware architecture best practices\b",
        r"\benterprise level\b",
        r"\bfull-?stack software engineer\b",
        r"\bsoftware engineer\b",
        r"\bsoftware development\b",
        r"\bproduction systems\b",
        r"\bfront-end software engineering\b",
        r"\bapplication development issues\b",
        r"\bexisting applications\b",
        r"\bmobile app development\b",
        r"\bweb applications\b",
        r"\bvisually engaging\b",
        r"\bui architecture\b",
        r"\bclient-side performance\b",
        r"\bshared design system\b",
        r"\bmetrics instrumentation\b",
        r"\bdata-driven\b",
        r"\bperformance tuning\b",
        r"\bmonitoring\b",
        r"\bproduct managers\b",
        r"\bdesigners\b",
        r"\bengineers\b",
        r"\bmodularization\b",
        r"\bgeneralization\b",
        r"\bseparation of concerns\b",
        r"\basynchronous programming\b",
        r"\bcallbacks?\b",
        r"\bpromises\b",
        r"\brefactoring\b",
        r"\bversion control software\b",
        r"\bserver-side technologies\b",
        r"\bframeworks?\b",
        r"\bdatabases?\b",
        r"\bunderstanding of\b",
        r"\bgrasp of\b",
        r"\bcomfort working\b",
        r"\bbuild(?:ing)?\b",
        r"\bshipping\b",
        r"\bdevelop\b",
        r"\bsustain\b",
        # Filler words & fragments
        r"\betc\b",
        r"\be g\b",
        r"\bsuch as\b",
        r"\bor similar\b",
        r"\bsimilar\b",
        r"\bcurrent\b",
        r"\brecent\b",
        r"\bhigher\b",
        r"\blevel\b$",
        r"\bor higher\b",
        r"\bweb\b$",
        r"\bdesktop\b$",
        r"\bnew\b$",
        r"\bmust have\b",
        r"\bnice to have\b",
        r"\brequired\b",
        r"\bpreferred\b",
        r"\bplus\b$",
        r"\bbonus\b",
        r"\bqualifications?\b",
        r"\brequirements?\b",
        r"\bresponsibilities\b",
        r"\bwhat you'?ll do\b",
        r"\bwho you are\b",
        r"\babout (?:you|the role)\b",
        r"\blooking for\b",
        r"\bseeking\b",
        r"\bjoin\b",
        r"\bincluding\b",
        r"\bdemonstrated\b",
        r"\bexpertise\b",
        r"\bdesigning\b",
        r"\bmaintaining\b",
        r"\bproduction\b",
        r"\bfront-end application\w*\b",
        r"\bapplication\w*\b$",
    ]
]

_SKILL_PREFIXES: tuple[str, ...] = (
    "experience with ",
    "experience in ",
    "experience working with ",
    "experience maintaining ",
    "experienced in ",
    "production experience with ",
    "comfortable with ",
    "comfortable in ",
    "proficiency in ",
    "proficiency with ",
    "proficient in ",
    "proficient with ",
    "knowledge of ",
    "familiarity with ",
    "working knowledge of ",
    "background in ",
    "focus on ",
    "interested in ",
    "ability to ",
    "willingness to ",
    "adopt best-in-class tools like ",
    "learn best-in-class tools like ",
    "best-in-class tools like ",
    "solid ",
    "strong ",
    "good ",
)


# Data Types
class JobParserState(TypedDict):
    source: dict[str, Any]
    raw_listing_text: str
    extracted_facts: dict[str, Any]
    normalized_packet: dict[str, Any]
    confidence: float


# Public API Entry Points
def parse_job(*, job_url: str | None = None, listing_text: str = "") -> dict[str, Any]:
    """Return a normalized and validated job packet for one job source."""
    state: JobParserState = {
        "source": {"job_url": job_url, "listing_text": listing_text},
        "raw_listing_text": listing_text,
        "extracted_facts": {},
        "normalized_packet": {},
        "confidence": 0.0,
    }
    fetch_or_load_listing(state)
    extract_facts(state)
    normalize_packet(state)
    validate_packet(state)
    calculate_packet_compatibility_score(state)
    return state["normalized_packet"]


def handoff_to_tailor(state: JobParserState, output_dir: str | Path | None = None) -> dict[str, Any]:
    if not state.get("normalized_packet"):
        normalize_packet(state)
        validate_packet(state)
        calculate_compatibility_score(state)

    destination = Path(output_dir or "output/tailored/default")
    destination.mkdir(parents=True, exist_ok=True)
    output_path = destination / "job_packet.json"
    output_path.write_text(json.dumps(state["normalized_packet"], indent=2), encoding="utf-8")

    return {
        "output_path": str(output_path),
        "job_packet": state["normalized_packet"],
    }


def calculate_hybrid_compatibility_score(
    job_packet: dict[str, Any],
    model_name: str | None = None,
) -> int | None:
    """Keyword baseline + optional LLM adjustment for borderline scores."""
    if not job_packet or job_packet.get("metadata", {}).get("validation_errors", []):
        return None

    baseline = calculate_resume_compatibility_score(job_packet)
    if COMPATIBILITY_BORDERLINE_LOW <= baseline <= COMPATIBILITY_BORDERLINE_HIGH:
        return _llm_adjust_score(baseline, job_packet, model_name=model_name)
    return baseline


def calculate_resume_compatibility_score(job_packet: dict[str, Any]) -> int:
    job = job_packet.get("job", {}) if isinstance(job_packet, dict) else {}
    must_have = [str(item).strip() for item in (job.get("must_have") or []) if str(item).strip()]
    nice_to_have = [str(item).strip() for item in (job.get("nice_to_have") or []) if str(item).strip()]
    title = str(job.get("title") or "")
    domain = str(job.get("domain") or "")

    corpus = _resume_match_corpus()
    known_terms = _known_skill_terms()

    must_ratio = 0.0
    if must_have:
        must_scores = [_requirement_match_score(corpus, item, known_terms) for item in must_have]
        must_ratio = sum(must_scores) / len(must_scores)

    nice_ratio = 0.0
    if nice_to_have:
        nice_scores = [_requirement_match_score(corpus, item, known_terms) for item in nice_to_have]
        nice_ratio = sum(nice_scores) / len(nice_scores)

    title_tokens = [
        token
        for token in re.findall(r"[A-Za-z][A-Za-z+#]{2,}", f"{title} {domain}")
        if token.lower() not in {"senior", "software", "engineer"}
    ]
    title_ratio = 0.0
    if title_tokens:
        title_matches = sum(1 for token in title_tokens if _contains_keyword(corpus, token.lower()))
        title_ratio = title_matches / len(title_tokens)

    weighted_ratio = (must_ratio * 0.7) + (nice_ratio * 0.2) + (title_ratio * 0.1)
    if not must_have and not nice_to_have and not title_tokens:
        weighted_ratio = 0.45

    score = int(round(1 + (weighted_ratio * 9)))
    return max(1, min(10, score))


calculate_compatibility_score = calculate_resume_compatibility_score


# Pipeline Step Functions
def fetch_or_load_listing(state: JobParserState) -> JobParserState:
    source = state.get("source", {})
    listing_text = (source.get("listing_text") or "").strip()

    if listing_text:
        state["raw_listing_text"] = listing_text
        return state

    job_url = source.get("job_url")
    if not job_url:
        state["raw_listing_text"] = ""
        return state

    try:
        request = Request(job_url, headers={"User-Agent": "Mozilla/5.0"})
        with urlopen(request, timeout=10) as response:
            payload = response.read().decode("utf-8", errors="ignore")

        source["listing_html"] = payload
        state["source"] = source

        cleaned = re.sub(r"<script.*?</script>", " ", payload, flags=re.S | re.I)
        cleaned = re.sub(r"<style.*?</style>", " ", cleaned, flags=re.S | re.I)
        cleaned = re.sub(r"<[^>]+>", "\n", cleaned)
        cleaned = unescape(cleaned)
        cleaned = re.sub(r"\s+", "\n", cleaned).strip()
        state["raw_listing_text"] = cleaned
    except (HTTPError, URLError, ValueError):
        state["raw_listing_text"] = ""

    return state


def extract_facts(state: JobParserState) -> JobParserState:
    text = (state.get("raw_listing_text") or "").strip()
    if not text:
        state["extracted_facts"] = {}
        return state

    source = state.get("source") or {}
    html_text = (source.get("listing_html") or "").strip()

    try:
        payload = _parse_job_with_openrouter(text, state.get("source"))
    except RuntimeError:
        payload = {}

    fallback_payload = _heuristic_fallback(html_text or text)

    def _pick_value(primary: Any, fallback: Any) -> Any:
        def _is_placeholder(value: Any) -> bool:
            if value is None:
                return True
            if isinstance(value, str):
                stripped = value.strip()
                return not stripped or stripped.lower() == "unknown"
            if isinstance(value, (list, dict, tuple, set)):
                return not value
            return False

        if not _is_placeholder(primary):
            return primary
        if not _is_placeholder(fallback):
            return fallback
        return primary or fallback or ""

    merged_payload = {
        "title": _pick_value(payload.get("title"), fallback_payload.get("title")),
        "company": _pick_value(payload.get("company"), fallback_payload.get("company")),
        "location": _pick_value(payload.get("location"), fallback_payload.get("location")),
        "employment_type": _pick_value(payload.get("employment_type"), fallback_payload.get("employment_type")),
        "description": _pick_value(payload.get("description"), fallback_payload.get("description")),
        "must_have": (payload.get("must_have") or fallback_payload.get("must_have") or []),
        "nice_to_have": (payload.get("nice_to_have") or fallback_payload.get("nice_to_have") or []),
        "responsibilities": (payload.get("responsibilities") or fallback_payload.get("responsibilities") or []),
        "domain": _pick_value(payload.get("domain"), fallback_payload.get("domain")),
    }

    state["extracted_facts"] = {
        "title": _clean_unknown(str(merged_payload.get("title") or "")),
        "company": _clean_unknown(str(merged_payload.get("company") or "")),
        "location": _clean_unknown(str(merged_payload.get("location") or "")),
        "employment_type": _normalize_employment_type(str(merged_payload.get("employment_type") or "")),
        "description": _clean_unknown(str(merged_payload.get("description") or "")),
        "must_have": normalize_skill_items(merged_payload.get("must_have") or []),
        "nice_to_have": normalize_skill_items(merged_payload.get("nice_to_have") or []),
        "responsibilities": _clean_list(merged_payload.get("responsibilities") or []),
        "domain": _clean_unknown(str(merged_payload.get("domain") or "")),
    }
    return state


def normalize_packet(state: JobParserState) -> JobParserState:
    if not state.get("extracted_facts"):
        extract_facts(state)

    extracted = state.get("extracted_facts", {})
    job = {
        "title": extracted.get("title") or "",
        "company": extracted.get("company") or "",
        "location": extracted.get("location") or "",
        "employment_type": extracted.get("employment_type") or "",
        "description": extracted.get("description") or "",
        "must_have": extracted.get("must_have") or [],
        "nice_to_have": extracted.get("nice_to_have") or [],
        "responsibilities": extracted.get("responsibilities") or [],
        "domain": extracted.get("domain") or "",
    }

    confidence = 0.0
    if job["title"]:
        confidence += 0.3
    if job["company"]:
        confidence += 0.2
    if job["location"]:
        confidence += 0.1
    if job["description"]:
        confidence += 0.2
    if job["must_have"] or job["nice_to_have"]:
        confidence += 0.1
    if job["responsibilities"]:
        confidence += 0.1

    state["normalized_packet"] = {
        "job": job,
        "metadata": {
            "source_url": (state.get("source") or {}).get("job_url", ""),
            "parsed_at": datetime.now(timezone.utc).isoformat(),
            "confidence": round(min(confidence, 1.0), 2),
            "field_attribution": {},
        },
    }
    state["confidence"] = state["normalized_packet"]["metadata"]["confidence"]
    return state


def validate_packet(state: JobParserState) -> JobParserState:
    if not state.get("normalized_packet"):
        normalize_packet(state)

    job = state["normalized_packet"].get("job", {})
    metadata = state["normalized_packet"].setdefault("metadata", {})
    validation_errors: list[str] = []

    if not job.get("title"):
        validation_errors.append("Missing job title")
    if not job.get("company"):
        validation_errors.append("Missing company")
    if not job.get("description"):
        validation_errors.append("Missing description")

    if validation_errors:
        metadata["validation_errors"] = validation_errors
        state["confidence"] = max(0.0, state["confidence"] - 0.1)
    else:
        metadata["validation_errors"] = []

    return state


def calculate_packet_compatibility_score(state: JobParserState) -> JobParserState:
    if not state.get("normalized_packet"):
        normalize_packet(state)

    state["normalized_packet"]["compatibility_score"] = calculate_hybrid_compatibility_score(state["normalized_packet"])
    return state


# Skill Normalization & Cleaning Helpers
def _clean_unknown(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if cleaned.lower() in {"unknown", "unavailable", "n/a", "na", "none", "null"}:
        return ""
    return cleaned


def normalize_skill_item(item: str) -> str:
    cleaned = _clean_unknown(item)
    if not cleaned:
        return ""

    cleaned = re.sub(r"[()\[\]{}<>.,;:!?]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    lowered = cleaned.lower()
    lowered = re.sub(r"^(?:strong|solid|good|deep|expert|advanced|proven|demonstrated)\s+", "", lowered)
    cleaned = cleaned[len(cleaned) - len(lowered):] if cleaned.lower().endswith(lowered) else cleaned
    for prefix in _SKILL_PREFIXES:
        if lowered.startswith(prefix):
            cleaned = cleaned[len(prefix):].strip()
            lowered = cleaned.lower()
            break

    if not cleaned:
        return ""

    canonical = SKILL_CANONICAL_MAP.get(lowered)
    if canonical:
        return canonical

    for pattern in SKILL_BLOCKLIST_PATTERNS:
        if pattern.search(cleaned):
            return ""

    if len(cleaned.split()) > 4:
        return ""

    return cleaned


def normalize_skill_items(items: list[str] | None) -> list[str]:
    normalized: list[str] = []
    seen: set[str] = set()

    for raw in items or []:
        cleaned = _clean_unknown(str(raw))
        if not cleaned:
            continue

        cleaned = re.sub(r"\bci\s*/\s*cd\b", "ci cd", cleaned, flags=re.I)

        for candidate in re.split(r"\s*(?:,|/|\band\b|\bor\b)\s*", cleaned):
            normalized_item = normalize_skill_item(candidate)
            if normalized_item and normalized_item.lower() not in seen:
                seen.add(normalized_item.lower())
                normalized.append(normalized_item)

    return [item for item in normalized if item and re.search(r"[A-Za-z0-9]", item)]

def _clean_list(items: list[str] | None) -> list[str]:
    deduped: list[str] = []
    seen: set[str] = set()
    for raw in items or []:
        cleaned = _clean_unknown(str(raw))
        if not cleaned:
            continue
        key = cleaned.lower()
        if key in seen:
            continue
        seen.add(key)
        deduped.append(cleaned)
    return deduped


# Compatibility Scoring Helpers
def _resume_summary() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "resume" / "modules").is_dir():
        raise FileNotFoundError(
            f"Base resume modules not found at {repo_root / 'resume' / 'modules'}. "
            "Copy resume.example/ to resume/ and fill in your details before scoring."
        )
    modules_dir = repo_root / "resume" / "modules"
    parts: list[str] = []
    for name in RESUME_MODULE_NAMES:
        path = modules_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)[:3000]


def _resume_match_corpus() -> str:
    repo_root = Path(__file__).resolve().parents[2]
    if not (repo_root / "resume" / "modules").is_dir():
        raise FileNotFoundError(
            f"Base resume modules not found at {repo_root / 'resume' / 'modules'}. "
            "Copy resume.example/ to resume/ and fill in your details before scoring."
        )
    modules_dir = repo_root / "resume" / "modules"
    parts: list[str] = []
    for name in RESUME_MODULE_NAMES:
        path = modules_dir / name
        if path.exists():
            parts.append(path.read_text(encoding="utf-8"))

    skills_path = modules_dir / "skills.json"
    if skills_path.exists():
        try:
            payload = json.loads(skills_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for values in payload.values():
                    if isinstance(values, list):
                        parts.append(" ".join(str(item) for item in values))
        except (json.JSONDecodeError, OSError):
            pass
    return "\n".join(parts).lower()


def _known_skill_terms() -> list[str]:
    repo_root = Path(__file__).resolve().parents[2]
    skills_path = repo_root / "resume" / "modules" / "skills.json"
    terms: list[str] = []
    if skills_path.exists():
        try:
            payload = json.loads(skills_path.read_text(encoding="utf-8"))
            if isinstance(payload, dict):
                for values in payload.values():
                    if isinstance(values, list):
                        for item in values:
                            cleaned = str(item).strip().lower()
                            if cleaned:
                                terms.append(cleaned)
        except (json.JSONDecodeError, OSError):
            pass

    terms.extend(
        [
            "api",
            "json:api",
            "backend",
            "frontend",
            "distributed systems",
            "microservices",
            "mysql",
            "postgresql",
            "redis",
            "observability",
            "opentelemetry",
            "ci/cd",
            "websockets",
            "kubernetes",
            "docker",
            "go",
            "python",
            "php",
            "laravel",
            "react",
            "vue",
            "typescript",
            "javascript",
        ]
    )
    deduped: list[str] = []
    seen: set[str] = set()
    for term in terms:
        if term in seen:
            continue
        seen.add(term)
        deduped.append(term)
    return deduped


def _extract_requirement_terms(requirement: str, known_terms: list[str]) -> list[str]:
    text = (requirement or "").strip().lower()
    if not text:
        return []

    candidates: list[str] = []
    for term in known_terms:
        if _contains_keyword(text, term):
            candidates.append(term)

    chunked = re.split(r"[,;/]|\band\b|\bor\b|\bwith\b|\bsuch as\b|\bincluding\b|\blike\b", text)
    for chunk in chunked:
        cleaned = re.sub(r"\s+", " ", chunk).strip(" .:-")
        if len(cleaned) < 3:
            continue
        if len(cleaned.split()) > 8:
            continue
        candidates.append(cleaned)

    for token in re.findall(r"[a-z0-9+#\.:-]{2,}", text):
        if token in {"years", "experience", "strong", "skills", "ability", "understanding"}:
            continue
        if token.isdigit():
            continue
        candidates.append(token)

    deduped: list[str] = []
    seen: set[str] = set()
    for item in candidates:
        key = item.strip()
        if not key or key in seen:
            continue
        seen.add(key)
        deduped.append(key)
    return deduped


def _requirement_match_score(corpus: str, requirement: str, known_terms: list[str]) -> float:
    req = (requirement or "").strip().lower()
    if not req:
        return 0.0

    if _contains_keyword(corpus, req):
        return 1.0

    terms = _extract_requirement_terms(req, known_terms)
    if not terms:
        return 0.0

    matches = sum(1 for term in terms if _contains_keyword(corpus, term))
    ratio = matches / len(terms)
    return min(0.95, ratio)


def _llm_adjust_score(
    baseline_score: int,
    job_packet: dict[str, Any],
    model_name: str | None = None,
) -> int:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        return baseline_score

    job = job_packet.get("job", {}) if isinstance(job_packet, dict) else {}
    model = model_name or os.getenv("OPENROUTER_MODEL_ADVISOR") or os.getenv("OPENROUTER_MODEL") or "openai/gpt-4o-mini"
    prompts = _load_scorer_prompts()

    try:
        message = post_json_schema(
            api_key=api_key,
            model=model,
            system_prompt=prompts["compatibility_scorer_system_prompt"],
            user_prompt=prompts["compatibility_scorer_user_prompt_template"].format(
                resume_summary=_resume_summary(),
                title=str(job.get("title") or "unknown"),
                domain=str(job.get("domain") or "unknown"),
                must_have=", ".join(str(item) for item in (job.get("must_have") or [])),
                nice_to_have=", ".join(str(item) for item in (job.get("nice_to_have") or [])),
            ),
            schema_name="compatibility_score",
            schema={
                "type": "object",
                "properties": {
                    "compatibility_score": {"type": "integer", "minimum": 1, "maximum": 10},
                },
                "required": ["compatibility_score"],
                "additionalProperties": False,
            },
            title="GETKAN-CV Compatibility Scorer",
            timeout=30,
            strict=True,
        )
        payload = json.loads(message)
        llm_score = int(payload.get("compatibility_score", baseline_score))
        avg_score = (baseline_score + llm_score) / 2
        return max(1, min(10, int(round(avg_score))))
    except Exception:
        return baseline_score


def _contains_keyword(text: str, keyword: str) -> bool:
    escaped = re.escape(keyword)
    if re.search(r"[^A-Za-z0-9]", keyword):
        return escaped.lower() in text.lower()
    return re.search(rf"\b{escaped}\b", text, flags=re.I) is not None


# LLM & Prompt Loading Helpers
def _load_parser_prompts() -> dict[str, str]:
    return load_prompt_config(PROMPT_CONFIG_PATH, DEFAULT_PARSER_PROMPTS, section="parser")


def _load_scorer_prompts() -> dict[str, str]:
    defaults = {
        "compatibility_scorer_system_prompt": (
            "You are a career compatibility assessor. Given a resume summary and a job's required/preferred skills, "
            "rate the candidate's compatibility on a scale of 1-10. Consider transferable skills, seniority, and "
            "related technologies — not just exact keyword matches. Return only valid JSON with a single key "
            "'compatibility_score' (integer 1-10)."
        ),
        "compatibility_scorer_user_prompt_template": (
            "Resume summary:\n{resume_summary}\n\n"
            "Job title: {title}\n"
            "Job domain: {domain}\n"
            "Must-have skills: {must_have}\n"
            "Nice-to-have skills: {nice_to_have}\n\n"
            "Rate compatibility 1-10. Consider that experience with one framework/language often transfers to another "
            "(e.g. Vue.js experience is relevant to React roles). Seniority and leadership experience also matter."
        ),
    }
    if not PROMPT_CONFIG_PATH.exists():
        return defaults
    try:
        payload = json.loads(PROMPT_CONFIG_PATH.read_text(encoding="utf-8")).get("parser", {})
    except (json.JSONDecodeError, OSError):
        return defaults
    if not isinstance(payload, dict):
        return defaults
    for key, default_value in defaults.items():
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            defaults[key] = value
    return defaults


def _extract_json_payload(content: Any) -> dict[str, Any] | None:
    if isinstance(content, dict):
        return content

    if not isinstance(content, str):
        return None

    text = content.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        return None


def _parse_job_with_openrouter(listing_text: str, source: dict[str, Any] | None = None) -> dict[str, Any]:
    load_dotenv(Path(__file__).resolve().parents[2] / ".env")
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError("OPENROUTER_API_KEY is not configured")

    model = os.getenv("OPENROUTER_MODEL_PARSER") or os.getenv("OPENROUTER_MODEL", "openai/gpt-4o-mini")
    prompts = _load_parser_prompts()
    system_prompt = prompts["job_parser_system_prompt"]
    user_prompt = prompts["job_parser_user_prompt_template"].format(listing_text=listing_text)

    schema = {
        "type": "object",
        "properties": {
            "title": {"type": "string"},
            "company": {"type": "string"},
            "location": {"type": "string"},
            "employment_type": {"type": "string"},
            "description": {"type": "string"},
            "must_have": {"type": "array", "items": {"type": "string"}},
            "nice_to_have": {"type": "array", "items": {"type": "string"}},
            "responsibilities": {"type": "array", "items": {"type": "string"}},
            "domain": {"type": "string"},
        },
        "required": ["title", "company", "description"],
    }

    try:
        message = post_json_schema(
            api_key=api_key,
            model=model,
            system_prompt=system_prompt,
            user_prompt=user_prompt,
            schema_name="job_packet",
            schema=schema,
            title="GETKAN-CV Job Parser",
            timeout=20,
        )
        parsed = _extract_json_payload(message)
        if not parsed:
            raise RuntimeError("OpenRouter did not return valid JSON")
        return parsed
    except (RuntimeError, ValueError, KeyError, TypeError) as exc:
        raise RuntimeError("OpenRouter request failed") from exc


# HTML & Heuristic Fallback Helpers
def _strip_html(html: str) -> str:
    text = re.sub(r"<br\s*/?>", "\n", html, flags=re.I)
    text = re.sub(r"</(p|div|ul|li|span|strong|b|em|h[1-6])>", "\n", text, flags=re.I)
    text = re.sub(r"<(p|div|ul|li|span|strong|b|em|h[1-6])[^>]*>", " ", text, flags=re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"&nbsp;", " ", text)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.split("\n")]
    return "\n".join([line for line in lines if line])


def _extract_section(description_html: str, heading: str) -> str:
    pattern = rf"(?is)<strong>\s*{re.escape(heading)}\s*</strong>\s*<br\s*/?>\s*<br\s*/?>(.*?)(?=<br\s*/?>\s*<strong>|$)"
    match = re.search(pattern, description_html)
    if not match:
        return ""
    return _strip_html(match.group(1)).strip()


def _normalize_employment_type(value: str) -> str:
    cleaned = _clean_unknown(value)
    if not cleaned:
        return ""
    normalized = cleaned.replace("_", " ").replace("-", " ")
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized.title()


def _extract_jsonld_job_postings(text: str) -> list[dict[str, Any]]:
    postings: list[dict[str, Any]] = []
    for match in re.finditer(r"<script[^>]*type=['\"]application/ld\+json['\"][^>]*>(.*?)</script>", text, flags=re.S | re.I):
        snippet = match.group(1)
        try:
            payload = json.loads(snippet)
        except json.JSONDecodeError:
            continue

        if isinstance(payload, dict):
            if payload.get("@type") == "JobPosting":
                postings.append(payload)
            elif isinstance(payload.get("@graph"), list):
                for item in payload["@graph"]:
                    if isinstance(item, dict) and item.get("@type") == "JobPosting":
                        postings.append(item)
    return postings


def _heuristic_fallback(text: str) -> dict[str, Any]:
    lowered = text.lower()
    title = ""
    company = ""
    location = ""
    description = ""
    must_have: list[str] = []
    nice_to_have: list[str] = []
    responsibilities: list[str] = []
    employment_type = ""

    job_postings = _extract_jsonld_job_postings(text)
    if job_postings:
        posting = job_postings[0]
        title = (posting.get("title") or "").strip() or title
        organization = posting.get("hiringOrganization") or {}
        company = (organization.get("name") or posting.get("company") or "").strip()
        location_payload = posting.get("jobLocation") or posting.get("jobLocationType") or ""
        if isinstance(location_payload, dict):
            address = location_payload.get("address") or {}
            location_tuple = (
                address.get("addressCountry")
                or address.get("addressLocality")
                or address.get("addressRegion")
                or location_payload.get("name")
                or ""
            )
            location = _clean_unknown(str(location_tuple))
        elif isinstance(location_payload, str):
            location = _clean_unknown(location_payload)

        employment_type = _normalize_employment_type(str(posting.get("employmentType") or ""))

        description_html = posting.get("description") or ""
        overview_section = _extract_section(description_html, "Overview")
        about_section = _extract_section(description_html, "About GitHub")
        if overview_section and about_section:
            description = f"{about_section}\n\n{overview_section}"
        elif overview_section:
            description = overview_section
        elif about_section:
            description = about_section
        else:
            description = _strip_html(description_html)

        if isinstance(posting.get("skills"), list):
            for skill in posting["skills"]:
                if isinstance(skill, str):
                    must_have.append(skill)

        if isinstance(posting.get("qualifications"), list):
            for qualification in posting["qualifications"]:
                if isinstance(qualification, str):
                    must_have.append(qualification)

        if not must_have:
            qualifications = _extract_section(description_html, "Qualifications")
            qualifications_lower = qualifications.lower()
            for keyword in [
                "python",
                "go",
                "rust",
                "java",
                "javascript",
                "react",
                "azure",
                "cloud",
                "c++",
                "c#",
                "ruby",
            ]:
                if keyword in qualifications_lower:
                    must_have.append("Azure" if keyword == "azure" else keyword.upper() if keyword in {"c++", "c#"} else keyword.title())

        if isinstance(posting.get("responsibilities"), list):
            responsibilities = [item for item in posting.get("responsibilities") if isinstance(item, str)]
        elif isinstance(posting.get("responsibilities"), str):
            responsibilities_html = posting.get("responsibilities") or ""
            responsibilities = []
            for bullet in re.findall(r"<li[^>]*>(.*?)</li>", responsibilities_html, flags=re.S | re.I):
                cleaned = re.sub(r"<[^>]+>", " ", bullet)
                cleaned = re.sub(r"&nbsp;", " ", cleaned)
                cleaned = unescape(cleaned)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    responsibilities.append(cleaned)

            if not responsibilities:
                cleaned = re.sub(r"<[^>]+>", " ", responsibilities_html)
                cleaned = re.sub(r"&nbsp;", " ", cleaned)
                cleaned = unescape(cleaned)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                if cleaned:
                    responsibilities = [cleaned]

        if not responsibilities and description_html:
            cleaned_description = re.sub(r"<br\s*/?>", "\n", description_html, flags=re.I)
            cleaned_description = re.sub(r"</(p|div|ul|li|span|strong|b|em)>", "\n", cleaned_description, flags=re.I)
            cleaned_description = re.sub(r"<(p|div|ul|li|span|strong|b|em)[^>]*>", " ", cleaned_description, flags=re.I)
            cleaned_description = re.sub(r"&nbsp;", " ", cleaned_description)
            cleaned_description = unescape(cleaned_description)
            cleaned_description = re.sub(r"\s+", " ", cleaned_description).strip()
            lines = [line.strip() for line in cleaned_description.split("\n") if line.strip()]
            if lines:
                responsibilities = lines[:8]

    title_patterns = [
        r"(?im)^\s*(?:title|role|position)\s*[:\-]\s*([A-Za-z][A-Za-z0-9 .,&/()\-]{2,80})",
        r"(?im)^\s*([A-Za-z][A-Za-z0-9 .,&/()\-]{2,80})\s*(?:at|for|with)\s+[A-Za-z][A-Za-z0-9 .,&/()\-]{2,30}$",
    ]
    for pattern in title_patterns:
        match = re.search(pattern, text)
        if match and not title:
            title = re.sub(r"\s+", " ", match.group(1)).strip()
            break

    if not title:
        for pattern in [r"(?i)title[^\n]{0,40}([A-Za-z][A-Za-z0-9 .,&/()-]{2,80})", r"(?i)job[^\n]{0,40}([A-Za-z][A-Za-z0-9 .,&/()-]{2,80})"]:
            match = re.search(pattern, text)
            if match:
                title = re.sub(r"\s+", " ", match.group(1)).strip()
                break

    if not title:
        title = "Unknown"

    if not company and "github" in lowered:
        company = "GitHub"
    if not location and "united states" in lowered:
        location = "United States"

    if not employment_type:
        employment_match = re.search(r"(?im)employment\s*type\s*[:\-]\s*([^\n]{2,60})", text)
        if employment_match:
            employment_type = _normalize_employment_type(employment_match.group(1))

    if not employment_type and "full time" in lowered:
        employment_type = "Full Time"

    if not description:
        description_match = re.search(r"(?is)(?:about|summary|description)[^\n]{0,200}([A-Za-z][^\n]{20,220})", text)
        if description_match:
            description = re.sub(r"\s+", " ", description_match.group(1)).strip()

    if not description:
        description = ""

    if not must_have:
        for keyword in ["python", "java", "javascript", "typescript", "react", "aws", "kubernetes", "docker", "terraform", "graphql", "postgres", "redis", "distributed systems"]:
            if keyword in lowered:
                must_have.append(keyword.title() if keyword != "aws" else "AWS")

    if not nice_to_have:
        for keyword in ["go", "rust", "machine learning", "ai", "microservices", "linux", "ci/cd", "observability"]:
            if keyword in lowered:
                nice_to_have.append(keyword.title() if keyword != "ci/cd" else "CI/CD")

    if not responsibilities and ("responsibilities" in lowered or "what you will do" in lowered):
        responsibilities.append("Own delivery of core software features")

    return {
        "title": _clean_unknown(title),
        "company": _clean_unknown(company),
        "location": _clean_unknown(location),
        "employment_type": employment_type,
        "description": _clean_unknown(description),
        "must_have": normalize_skill_items(must_have),
        "nice_to_have": normalize_skill_items(nice_to_have),
        "responsibilities": _clean_list(responsibilities),
        "domain": "",
    }
