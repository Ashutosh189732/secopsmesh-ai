"""Demo scenario runner - POSTs a scenario file's signals to /api/signals in
order, printing the FP-gate score/status after each one so the effect of
correlation is visible signal-by-signal rather than just at the end.

Usage:
    python run_scenario.py <scenario.json|all> [--api-base http://127.0.0.1:8000]
"""

import argparse
import json
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

SCENARIOS_DIR = Path(__file__).resolve().parent / "scenarios"
DEFAULT_API_BASE = "http://127.0.0.1:8000"


def post_signal(api_base: str, payload: dict) -> dict:
    body = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(
        f"{api_base}/api/signals",
        data=body,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} from {api_base}/api/signals: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(
            f"Could not reach {api_base} ({exc.reason}). Is the backend running?"
        ) from exc


def _pause_for_enter(next_signal: dict) -> None:
    """Presenter-paced scenarios: block until Enter before firing the next
    signal, so the audience can sit on the current dashboard state as long as
    needed. Falls back to a short fixed delay when stdin isn't interactive
    (e.g. running under 'all' in CI or a pipe)."""
    prompt = (
        f"\n  [paused] Next up: {next_signal['signal_type']} "
        f"(severity={next_signal['severity']}, source={next_signal['source']}). "
        f"Press Enter to fire it..."
    )
    try:
        input(prompt)
    except EOFError:
        print("\n  (stdin not interactive - continuing after 3s)")
        time.sleep(3)


def run_scenario(path: Path, api_base: str) -> None:
    scenario = json.loads(path.read_text(encoding="utf-8"))
    name = scenario.get("name", path.stem)
    signals = scenario["signals"]
    delay = scenario.get("delay_seconds_between_signals", 0)
    wait_for_enter = scenario.get("wait_for_enter_between_signals", False)

    print(f"\n=== {name} ===")
    if scenario.get("description"):
        print(scenario["description"])
    if scenario.get("expected_outcome"):
        print(f"Expected: {scenario['expected_outcome']}")
    print()

    for i, signal in enumerate(signals, start=1):
        print(f"  [{i}/{len(signals)}] POST {signal['signal_type']} on "
              f"'{signal['resource_name']}' (severity={signal['severity']}, "
              f"source={signal['source']})")
        incident = post_signal(api_base, signal)
        print(f"      -> incident #{incident['id']}: status={incident['status']}, "
              f"fp_score={incident['fp_score']}, correlated_count={incident['correlated_count']}")
        print(f"      -> {incident['fp_decision_reason']}")
        if i < len(signals):
            if wait_for_enter:
                _pause_for_enter(signals[i])
            elif delay:
                time.sleep(delay)

    print(f"\n{name} done. Watch http://localhost:3000 for the incident to populate.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "scenario",
        help="Scenario file name (e.g. 03_investigating_gdpr or "
        "03_investigating_gdpr.json), or 'all' to run every scenario in order.",
    )
    parser.add_argument("--api-base", default=DEFAULT_API_BASE, help="Backend base URL")
    parser.add_argument(
        "--between-scenarios",
        type=float,
        default=3.0,
        help="Seconds to wait between scenarios when running 'all' (default: 3)",
    )
    args = parser.parse_args()

    if args.scenario == "all":
        paths = sorted(SCENARIOS_DIR.glob("*.json"))
        if not paths:
            sys.exit(f"No scenario files found in {SCENARIOS_DIR}")
        for i, path in enumerate(paths):
            if i > 0:
                time.sleep(args.between_scenarios)
            run_scenario(path, args.api_base)
        return

    candidate = Path(args.scenario)
    if not candidate.suffix:
        candidate = candidate.with_suffix(".json")
    if not candidate.is_absolute():
        candidate = SCENARIOS_DIR / candidate.name

    if not candidate.exists():
        # Allow a bare prefix ("08", "03_invest") to resolve to its full name,
        # matching the run_scenario.sh wrapper's behavior.
        matches = sorted(SCENARIOS_DIR.glob(f"{args.scenario}*.json"))
        if len(matches) == 1:
            candidate = matches[0]
        else:
            available = ", ".join(p.stem for p in sorted(SCENARIOS_DIR.glob("*.json")))
            sys.exit(f"Scenario not found: {candidate}\nAvailable: {available}")

    run_scenario(candidate, args.api_base)


if __name__ == "__main__":
    main()
