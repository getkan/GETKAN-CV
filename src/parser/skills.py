"""Deterministic skill extraction and normalization for job packets.

The LLM parser frequently emits education requirements, soft skills, and
experience-summary fragments in the skill lists. This module filters and
normalizes those lists so only concise, technology-focused terms survive.
"""

from __future__ import annotations

import re


def clean_unknown(value: object) -> str:
    if not isinstance(value, str):
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    if cleaned.lower() in {"unknown", "unavailable", "n/a", "na", "none", "null"}:
        return ""
    return cleaned


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


def normalize_skill_item(item: str) -> str:
    cleaned = clean_unknown(item)
    if not cleaned:
        return ""

    cleaned = re.sub(r"[()\[\]{}<>.,;:!?]+", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()

    lowered = cleaned.lower()
    # Strip leading qualifier words (e.g. "strong proficiency in X").
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
        cleaned = clean_unknown(str(raw))
        if not cleaned:
            continue

        # Protect CI/CD from being split on the slash.
        cleaned = re.sub(r"\bci\s*/\s*cd\b", "ci cd", cleaned, flags=re.I)

        for candidate in re.split(r"\s*(?:,|/|\band\b|\bor\b)\s*", cleaned):
            normalized_item = normalize_skill_item(candidate)
            if normalized_item and normalized_item.lower() not in seen:
                seen.add(normalized_item.lower())
                normalized.append(normalized_item)

    return [item for item in normalized if item and re.search(r"[A-Za-z0-9]", item)]
