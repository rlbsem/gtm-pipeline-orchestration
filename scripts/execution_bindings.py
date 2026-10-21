"""Lane-specific executable dependency bindings; UI/docs changes cannot relabel native results."""
from publication import source_hashes

CORE = {"engine.py", "store.py", "contracts.py", "fixtures.py", "worker.py", "destination.py",
        "policy.json", "schema.sql", "advice.py", "upgrade_cases.json", "upgrade_scenarios.py", "__init__.py"}


def lane_hashes(lane):
    assert lane in {"ai", "salesforce"}
    names = CORE | ({"salesforce.py"} if lane == "salesforce" else set())
    paths = {"src/gtm/" + name for name in names} | {
        "scripts/execution_bindings.py", "scripts/publication.py", "requirements.lock", "pyproject.toml",
        "scripts/evaluate_ai.py" if lane == "ai" else "scripts/native_salesforce.py"}
    hashes = source_hashes()
    assert paths <= hashes.keys(), "missing_executable_lane_dependency"
    return {p: hashes[p] for p in sorted(paths)}
