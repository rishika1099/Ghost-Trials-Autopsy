"""Run the agent on the README's sample queries and keep the outputs in runs/.

    uv run python scripts/run_samples.py            # every query in samples.json
    uv run python scripts/run_samples.py s1 vague   # some of them, by id or id prefix
"""

import asyncio
import datetime as dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from ghost.config import ROOT  # noqa: E402
from ghost.pipeline import investigate  # noqa: E402


async def main() -> None:
    samples = json.loads((ROOT / "samples.json").read_text())
    wanted = set(sys.argv[1:])
    out = ROOT / "runs"
    out.mkdir(exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d-%H%M")
    for sample in samples:
        if wanted and not any(sample["id"].startswith(w) for w in wanted):
            continue
        started = time.monotonic()
        result = await investigate(sample["query"])
        seconds = time.monotonic() - started
        result["elapsed_s"] = round(seconds, 1)
        (out / f"{stamp}_{sample['id']}.json").write_text(json.dumps(result, indent=2, default=str))
        (out / f"{sample['id']}_latest.md").write_text(f"# {sample['query']}\n\n{result['markdown']}\n\n_{seconds:.0f} s, {len(result['tool_calls'])} tool calls_\n")
        print(f"## {sample['id']} ({seconds:.0f} s, {result['kind']}, rounds {result['trace']['rounds']})\n{result['markdown']}\n", flush=True)


if __name__ == "__main__":
    asyncio.run(main())
