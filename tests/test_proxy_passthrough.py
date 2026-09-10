"""Every parameter the page sends is one the proxy forwards.

The check that replaced two `paired_paths` groups on 10 Sep 2026. What is held
here is mostly the two things the pairing got WRONG, because those are the
reasons it was replaced and a replacement that shares them is not one:

  a page-only change that introduces no parameter must PASS  (task 55)
  both files moving with a parameter dropped must FAIL       (the blind spot)

and, with equal weight, that it cannot go quietly green: a page or a proxy this
cannot read is could-not-run, never a pass. That is the failure this codebase
keeps making, and a static check reading TypeScript with regexes is exactly
where it would make it again.
"""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
CHECK = ROOT / "contracts" / "checks" / "proxy_passthrough.py"

ORDERS_PAGE = "platform/app/(dashboard)/analytics/orders/page.tsx"
ORDERS_PROXY = "platform/app/api/analytics/orders/route.ts"
OVERVIEW_PAGE = "platform/app/(dashboard)/analytics/page.tsx"
DASHBOARD_PROXY = "platform/app/api/analytics/dashboard/route.ts"

# The shape both real pages use, reduced to what the check reads. Not a copy of
# the real file: this must fail when the CHECK breaks, not when the platform
# repo is edited.
PAGE_TSX = """
  useEffect(() => {
    async function fetchOrders() {
      const params = new URLSearchParams({
        start: dateRange.start,
        end: dateRange.end,
        page: String(page),
      })
      if (status) params.set('status', status)
      if (debouncedPayment) params.set('payment_method', debouncedPayment)
      const [ordersRes, statusRes] = await Promise.all([
        fetch(`/api/analytics/orders?${params}`),
        fetch(`/api/analytics/orders/statuses?start=${dateRange.start}&end=${dateRange.end}`),
      ])
    }
    fetchOrders()
  }, [])
"""

PROXY_TS = """
const PASSTHROUGH = [
  'start', 'end', 'page', 'status', 'payment_method',
]

export async function GET(req: NextRequest) {
  const { searchParams } = new URL(req.url)
  const params = new URLSearchParams()
  for (const key of PASSTHROUGH) {
    const value = searchParams.get(key)
    if (value) params.set(key, value)
  }
}
"""

OVERVIEW_TSX = """
  const params = new URLSearchParams({
    start: dateRange.start,
    end: dateRange.end,
    comparison_mode: comparisonMode,
  })
  const res = await fetch(`/api/analytics/dashboard?${params}`)
"""

DASHBOARD_TS = """
  const params = new URLSearchParams()
  for (const key of ['start', 'end', 'comparison_mode']) {
    const value = searchParams.get(key)
    if (value) params.set(key, value)
  }
"""


@pytest.fixture
def tree(tmp_path) -> Path:
    for rel, body in ((ORDERS_PAGE, PAGE_TSX), (ORDERS_PROXY, PROXY_TS),
                      (OVERVIEW_PAGE, OVERVIEW_TSX),
                      (DASHBOARD_PROXY, DASHBOARD_TS)):
        f = tmp_path / rel
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(body)
    return tmp_path


def run(tree: Path) -> subprocess.CompletedProcess:
    return subprocess.run(["python3", str(CHECK)], cwd=tree,
                          capture_output=True, text=True)


def edit(tree: Path, rel: str, old: str, new: str) -> None:
    f = tree / rel
    text = f.read_text()
    assert old in text, f"fixture no longer contains {old!r}"
    f.write_text(text.replace(old, new))


def test_agreement_passes_and_says_what_it_compared(tree):
    r = run(tree)
    assert r.returncode == 0, r.stdout
    assert "2 page/proxy pair(s) agree" in r.stdout
    # A green that does not say what it read is a green nobody can check.
    assert "payment_method" in r.stdout
    assert "comparison_mode" in r.stdout


def test_a_dropped_parameter_is_refused_and_named(tree):
    """FEAT-035 itself: the control renders, the proxy drops it, the table
    comes back unfiltered with a summary that agrees."""
    edit(tree, ORDERS_PROXY, "'payment_method',", "")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "DROPPED  payment_method" in r.stdout
    # The reason travels with the refusal, or the agent cannot act on it.
    assert "since task 2" in r.stdout


def test_a_page_only_change_that_sends_nothing_new_passes(tree):
    """TASK 55, which the pairing refused at £2.25 and one attempt.

    Clicking a table cell sets a filter the page already sent. No parameter is
    introduced, the proxy is untouched, and there is nothing for a check to
    refuse -- which a pairing could not tell from any other page change.
    """
    edit(tree, ORDERS_PAGE, "if (status) params.set('status', status)",
         "if (status) params.set('status', status)\n"
         "      // a cell that sets an existing filter")
    r = run(tree)
    assert r.returncode == 0, r.stdout


def test_a_proxy_only_widening_passes(tree):
    """Dead code the next task notices, not a page lying to a merchant. The
    pairing refused this too, and it is the direction that never mattered."""
    edit(tree, ORDERS_PROXY, "'payment_method',", "'payment_method', 'country',")
    r = run(tree)
    assert r.returncode == 0, r.stdout


def test_both_files_moving_does_not_excuse_a_dropped_parameter(tree):
    """THE PAIRING'S BLIND SPOT, and the reason this is not merely a narrower
    pairing. Co-movement is not agreement: a change can touch both files and
    still leave the new filter out of the proxy's list, which satisfies every
    pairing rule there is.
    """
    edit(tree, ORDERS_PAGE, "if (status) params.set('status', status)",
         "if (status) params.set('status', status)\n"
         "      if (country) params.set('country', country)")
    edit(tree, ORDERS_PROXY, "const PASSTHROUGH = [",
         "// touched, and not with the name the page now sends\nconst PASSTHROUGH = [")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "DROPPED  country" in r.stdout


def test_parameters_are_attributed_to_the_proxy_that_receives_them(tree):
    """The orders page calls two proxies. `start` and `end` on the statuses URL
    are not the orders route's business, and a check that pooled every
    `params.set` in the file into one set would report them against it.
    """
    edit(tree, ORDERS_PAGE,
         "fetch(`/api/analytics/orders/statuses?start=${dateRange.start}&end=${dateRange.end}`)",
         "fetch(`/api/analytics/orders/statuses?start=${dateRange.start}&only_open=${x}`)")
    r = run(tree)
    assert r.returncode == 0, r.stdout


def test_a_page_it_cannot_read_is_could_not_run_not_a_pass(tree):
    edit(tree, ORDERS_PAGE, "fetch(`/api/analytics/orders?${params}`)",
         "fetch(buildOrdersUrl(filters))")
    r = run(tree)
    assert r.returncode == 2, r.stdout
    assert "could not read" in r.stdout
    assert "never as a pass" in r.stdout


def test_a_proxy_it_cannot_read_is_could_not_run_not_a_pass(tree):
    edit(tree, ORDERS_PROXY, "for (const key of PASSTHROUGH) {",
         "for (const key of forwardedNames()) {")
    edit(tree, ORDERS_PROXY, "'start', 'end', 'page', 'status', 'payment_method',", "")
    r = run(tree)
    assert r.returncode == 2, r.stdout
    assert "stopped using the shape this check can read" in r.stdout


def test_a_missing_file_is_could_not_run_not_a_pass(tree):
    (tree / DASHBOARD_PROXY).unlink()
    r = run(tree)
    assert r.returncode == 2, r.stdout
    assert "does not exist" in r.stdout


def test_an_array_that_is_not_iterated_is_not_a_forwarding_rule(tree):
    """A `const` list of names sitting beside the passthrough list is not a
    rule, and counting it would make this pass for a name nothing forwards."""
    edit(tree, ORDERS_PROXY, "const PASSTHROUGH = [",
         "const KNOWN_STATUSES = ['country']\nconst PASSTHROUGH = [")
    edit(tree, ORDERS_PAGE, "if (status) params.set('status', status)",
         "if (status) params.set('status', status)\n"
         "      if (country) params.set('country', country)")
    r = run(tree)
    assert r.returncode == 1, r.stdout
    assert "DROPPED  country" in r.stdout


def test_the_contract_that_replaced_the_pairings_runs_this(tree):
    """The check exists to be RUN. It replaced two groups in one contract, and
    the removal is only sound while that contract's verification list carries
    it -- see tests/test_paired_paths.py for the other half of that argument.
    """
    import yaml
    c = yaml.safe_load(
        (ROOT / "contracts" / "dd-analytics-frontend.yaml").read_text())
    assert any("proxy_passthrough.py" in v for v in c["verification"]), (
        "dd-analytics-frontend.yaml dropped its paired_paths groups and does "
        "not run the check that replaced them")


def test_every_declared_pair_names_files_the_contract_can_reach(tree):
    """024's grounding rule, in the form it takes here.

    A pairing naming an unwritable path was a check that could not fail. The
    analogue for this check is a pair naming a file no task under the contract
    may write: the check would report a disagreement no task could then fix,
    and every frontend task would fail on it. `platform/app/(dashboard)/analytics/interventions/**`
    is floored, which is exactly such a path, and is why it is not in PAIRS.
    """
    import yaml
    import importlib.util
    spec = importlib.util.spec_from_file_location("proxy_passthrough", CHECK)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)

    c = yaml.safe_load(
        (ROOT / "contracts" / "dd-analytics-frontend.yaml").read_text())
    prefixes = [w.split("*", 1)[0].rstrip("/") for w in c["writable_paths"]]
    for pair in mod.PAIRS:
        for path in (pair["page"], pair["proxy"]):
            assert any(path == pre or path.startswith(pre + "/")
                       for pre in prefixes), (
                f"{path} is not writable under the contract that runs this "
                f"check, so a disagreement it reports could not be fixed by "
                f"the task it fails")
        assert pair["why"].strip(), f"{pair['url']} has no why to print"
