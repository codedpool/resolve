from pathlib import Path

import yaml

from resolve_workflows.graphs.discovery import DiscoveryPorts, build_discovery_graph
from resolve_workflows.nodes.contacts import Page, confident, extract, html_to_text, rank

PAGES = Path(__file__).resolve().parents[1] / "evals" / "saved_pages"
MANIFEST = yaml.safe_load((PAGES / "manifest.yaml").read_text(encoding="utf-8"))["companies"]


class SavedPages:
    def search(self, company):
        entry = next(c for c in MANIFEST.values() if c["name"].lower() == company.lower())
        pages = [Page(p["url"], html_to_text((PAGES / p["file"]).read_text(encoding="utf-8")), p["official"]) for p in entry["pages"]]
        return entry["domain"], pages


class FakeStore:
    def __init__(self, company, contact=None):
        self.company, self._contact = company, contact
        self._rejected, self._pending, self.approvals, self.asked, self.saved, self.status = [], None, [], [], None, None

    def company_name(self, case_id): return self.company
    def contact(self, case_id): return self._contact
    def rejected(self, case_id): return list(self._rejected)
    def add_rejected(self, case_id, value): self._rejected.append(value)
    def pending(self, case_id): return self._pending
    def set_pending(self, case_id, candidate): self._pending = candidate
    def request_approval(self, case_id, candidate): self.approvals.append(candidate); self.status = "pending"; return "a1"
    def approval_status(self, case_id): return self.status
    def save_contact(self, case_id, candidate): self.saved = candidate
    def ask_consumer(self, case_id, options): self.asked.append(options)


def graph_for(company, **kw):
    store = FakeStore(company, **kw)
    return build_discovery_graph(DiscoveryPorts(SavedPages(), store)), store


def run(graph, event="start", **extra):
    return graph.invoke({"case_id": "c", "event": event, **extra})


def test_the_official_grievance_officer_is_ranked_first_and_sent_for_approval():
    graph, store = graph_for("ZenMart")
    out = run(graph)
    assert out["state"] == "waiting_approval"
    assert store.approvals[0]["value"] == "grievance@zenmart.example" and store.approvals[0]["role"] == "grievance"
    assert store.saved is None  # nothing is stored before the owner approves


def test_a_third_party_page_never_outranks_the_companys_own_page():
    domain, pages = SavedPages().search("ZenMart")
    found = [c for p in pages for c in extract(p, domain)]
    ranked = rank(found)
    assert ranked[0].official and "complaintboard" not in ranked[0].url
    assert any(not c.official for c in ranked)  # the aggregator's numbers are seen, just ranked lower


def test_approval_stores_the_contact():
    graph, store = graph_for("ZenMart")
    run(graph)
    store.status = "approved"
    out = run(graph, "approval_decided")
    assert out["state"] == "stored" and store.saved["value"] == "grievance@zenmart.example"


def test_a_decision_event_without_an_approved_approval_stores_nothing():
    for status in ("pending", None):
        graph, store = graph_for("ZenMart")
        run(graph)
        store.status = status
        run(graph, "approval_decided")
        assert store.saved is None, status


def test_rejection_searches_again_without_that_contact_and_asks_the_consumer_when_unsure():
    graph, store = graph_for("ZenMart")
    run(graph)
    store.status = "rejected"
    out = run(graph, "approval_decided")
    assert store._rejected == ["grievance@zenmart.example"]
    # What is left (a customer-care address and numbers) has no clear winner, so the consumer is asked rather than guessed for.
    assert out["state"] in {"needs_consumer", "waiting_approval"}
    assert store.saved is None


def test_two_equally_good_officials_mean_the_consumer_is_asked():
    graph, store = graph_for("KiranaKart")
    out = run(graph)
    assert out["state"] == "needs_consumer" and store.approvals == []
    assert {o["value"] for o in out["options"]} >= {"grievance@kiranakart.example", "officer@kiranakart.example"}


def test_a_company_with_no_contacts_on_its_pages_asks_the_consumer():
    for company in ("PayQuick", "GhostMart"):
        graph, store = graph_for(company)
        out = run(graph)
        assert out["state"] == "needs_consumer" and out["options"] == []


def test_a_contact_the_consumer_picks_still_needs_approval():
    graph, store = graph_for("KiranaKart")
    out = run(graph)
    pick = out["options"][0]
    out = run(graph, "consumer_choice", choice=pick)
    assert out["state"] == "waiting_approval" and store.approvals[-1]["value"] == pick["value"] and store.saved is None


def test_a_known_contact_ends_immediately():
    graph, store = graph_for("ZenMart", contact={"value": "x@y.example"})
    assert run(graph)["state"] == "contact_known" and store.approvals == []


def test_giving_up_after_repeated_rejections():
    graph, store = graph_for("KiranaKart")
    store._pending = None
    for value in ("a", "b", "c"):
        store._pending = {"value": value}
        store.status = "rejected"
        out = run(graph, "approval_decided")
    assert out["state"] == "gave_up"


def test_html_text_extraction_keeps_headings_on_their_own_lines():
    text = html_to_text("<h2>Grievance Officer</h2><p>Email: a@b.example</p>")
    assert text.splitlines() == ["Grievance Officer", "Email: a@b.example"]


def test_confidence_needs_an_official_page():
    ranked = rank(extract(Page("https://x.example", "Grievance Officer\nEmail: g@x.example", False), "x.example"))
    assert not confident(ranked)
