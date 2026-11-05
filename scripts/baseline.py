"""The no-tools baseline for the README: the same model the agent's Lead and Writer use, with no tools
and no system prompt, given only the user's query.

    uv run python scripts/baseline.py            # every query in samples.json
    uv run python scripts/baseline.py "query"    # one query
"""

import json
import sys
from pathlib import Path

import litellm

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost.config import ROOT, VERTEX_ARGS, WRITER_MODEL  # noqa: E402

OUT = ROOT / "baseline"


def ask(query: str) -> str:
    response = litellm.completion(model=WRITER_MODEL, **VERTEX_ARGS, timeout=120, num_retries=2,
                                  messages=[{"role": "user", "content": query}])
    return response.choices[0].message.content


def main() -> None:
    queries = [{"id": "adhoc", "query": " ".join(sys.argv[1:])}] if len(sys.argv) > 1 else json.loads((ROOT / "samples.json").read_text())
    OUT.mkdir(exist_ok=True)
    for sample in queries:
        answer = ask(sample["query"])
        (OUT / f"{sample['id']}.md").write_text(f"# {sample['query']}\n\nModel: {WRITER_MODEL}, no tools, no system prompt.\n\n{answer}\n")
        print(f"## {sample['id']}\n{answer}\n")


if __name__ == "__main__":
    main()
