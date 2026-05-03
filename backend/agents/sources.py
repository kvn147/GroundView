import os

def get_sources_for_domain(domain: str) -> str:
    """Returns a formatted string of sources for a given domain from sources.md."""
    md_path = os.path.join(os.path.dirname(__file__), 'sources.md')
    try:
        with open(md_path, 'r', encoding='utf-8') as f:
            content = f.read()
    except FileNotFoundError:
        return ""

    # Parse the markdown file
    lines = content.split('\n')
    sources = []
    in_target_domain = False

    for line in lines:
        if line.startswith('## '):
            current_domain = line[3:].strip().lower()
            if current_domain == domain.lower():
                in_target_domain = True
            else:
                in_target_domain = False
        elif in_target_domain and line.strip().startswith('-'):
            sources.append(line.strip())

    return "\n    ".join(sources)
