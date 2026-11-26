from resolve_workflows.graphs.evidence import EvidencePorts, build_evidence_graph
from resolve_workflows.nodes.doc_fields import find_fields
from resolve_workflows.schemas import FIELDS as ALL_FIELDS

RECEIPT = "Flipkart\nOrder Confirmation\nOrder ID: OD1234567890\nOrder date: 20 Nov 2026\nOrder total: Rs. 10,900.00\n"


class FakeOCR:
    def __init__(self, *texts):
        self.texts = list(texts)

    def read(self, image):
        return self.texts


class FakeVision:
    def __init__(self, text=RECEIPT):
        self.text, self.calls = text, 0

    def read_text(self, image):
        self.calls += 1
        return self.text


class FakeLLM:
    def __init__(self, **values):
        self.values, self.calls = values, 0

    def structured(self, role, prompt_text, variables, schema, mode="instruct"):
        self.calls += 1
        data = {n: {"value": "", "certainty": "not_stated", "original_phrase": "", "ambiguity_note": ""} for n in ALL_FIELDS}
        for k, v in self.values.items():
            data[k] = {"value": v, "certainty": "stated", "original_phrase": v, "ambiguity_note": ""}
        return data, {}


class FakeRedactor:
    class _R:
        def __init__(self, text, withheld=False):
            self.text, self.tokens, self.withheld = text, {}, withheld

    def redact_or_withhold(self, text, tokens=None):
        return self._R(text, withheld="WITHHOLD" in text)

    def restore(self, text, tokens):
        return text


class FakeStore:
    def __init__(self, approval=None, confirmed=None):
        self.approval, self.confirmed = approval, confirmed or {}
        self.requested, self.saved, self.flags, self.state = 0, None, [], ""

    def image(self, evidence_id): return b"png"
    def request_vision_approval(self, evidence_id): self.requested += 1; self.approval = "pending"; return "a1"
    def approval_status(self, evidence_id): return self.approval
    def confirmed_facts(self, case_id): return dict(self.confirmed)
    def save_result(self, evidence_id, doc_type, fields, source): self.saved = (doc_type, fields, source)
    def flag(self, case_id, evidence_id, field, evidence_value, fact_value): self.flags.append((field, evidence_value, fact_value))
    def set_state(self, evidence_id, state): self.state = state
    def today(self): return "2026-11-26"


def make(ocr, store=None, vision=None, llm=None):
    store = store or FakeStore()
    vision = vision or FakeVision()
    llm = llm or FakeLLM()
    return build_evidence_graph(EvidencePorts(ocr, vision, llm, FakeRedactor(), store)), store, vision, llm


def run(graph, event="process"):
    return graph.invoke({"case_id": "c", "evidence_id": "e", "event": event})


def test_local_ocr_reads_a_receipt_without_any_vision_call():
    graph, store, vision, llm = make(FakeOCR(RECEIPT))
    out = run(graph)
    assert vision.calls == 0 and store.requested == 0
    doc_type, fields, source = store.saved
    assert doc_type == "order_confirmation" and source == "local_ocr"
    assert fields["order_id"]["value"] == "OD1234567890" and fields["amount"]["candidates"][0] == "10900"
    assert fields["order_date"]["value"] == "2026-11-20" and out["state"] == "read" and llm.calls == 0


def test_unreadable_image_asks_for_approval_and_calls_no_model():
    graph, store, vision, _ = make(FakeOCR("", "  "))
    out = run(graph)
    assert out["state"] == "waiting_approval" and store.requested == 1 and vision.calls == 0


def test_a_decision_event_without_an_approved_approval_never_reaches_vision():
    for status in (None, "pending", "rejected"):
        graph, store, vision, _ = make(FakeOCR(""), FakeStore(approval=status))
        run(graph, "approval_decided")
        assert vision.calls == 0, status


def test_approved_image_goes_to_vision_then_through_redaction_and_checks():
    graph, store, vision, _ = make(FakeOCR(""), FakeStore(approval="approved"))
    out = run(graph, "approval_decided")
    assert vision.calls == 1 and out["state"] == "read" and store.saved[2] == "vision"


def test_rejected_approval_leads_to_type_it_yourself():
    graph, store, vision, _ = make(FakeOCR(""), FakeStore(approval="rejected"))
    out = run(graph, "approval_decided")
    assert out["state"] == "type_it_yourself" and store.state == "type_it_yourself" and vision.calls == 0


def test_vision_that_returns_nothing_falls_back_to_typing():
    graph, store, _, _ = make(FakeOCR(""), FakeStore(approval="approved"), FakeVision(""))
    assert run(graph, "approval_decided")["state"] == "type_it_yourself"


def test_contradiction_with_a_confirmed_fact_is_flagged():
    graph, store, _, _ = make(FakeOCR(RECEIPT), FakeStore(confirmed={"amount": "9000", "order_id": "OD1234567890"}))
    out = run(graph)
    assert out["state"] == "needs_attention"
    assert store.flags == [("amount", "10900", "9000")] and store.state == "needs_attention"


def test_matching_values_written_differently_do_not_flag():
    graph, store, _, _ = make(FakeOCR(RECEIPT), FakeStore(confirmed={"amount": "10,900", "order_id": "od 1234567890", "company_name": "flipkart"}))
    assert run(graph)["state"] == "read" and store.flags == []


def test_misread_rupee_sign_still_matches_through_the_second_candidate():
    text = "Flipkart\nOrder ID: OD1234567890\nOrder total: 710,900\nOrder date: 20 Nov 2026\n"
    graph, store, _, _ = make(FakeOCR(text), FakeStore(confirmed={"amount": "10900"}))
    assert find_fields(text)["amount"] == "710900"
    assert run(graph)["state"] == "read" and store.flags == []


def test_a_future_order_date_is_flagged():
    text = "Flipkart\nOrder ID: OD1234567890\nOrder total: Rs. 450\nOrder date: 20 Dec 2026\n"
    graph, store, _, _ = make(FakeOCR(text))
    assert run(graph)["state"] == "needs_attention"


def test_model_only_fills_gaps_from_text_that_is_really_in_the_document():
    text = "Flipkart\nOrder ID: OD1234567890\nOrder total: Rs. 450\n"  # no date: the finder cannot place one
    graph, store, _, llm = make(FakeOCR(text), llm=FakeLLM(order_date="2026-11-20"))
    run(graph)
    assert llm.calls == 1 and store.saved[1]["order_date"]["value"] == ""  # "2026-11-20" is not in the document text


def test_text_that_cannot_be_redacted_is_not_used():
    graph, store, _, _ = make(FakeOCR("WITHHOLD " + RECEIPT))
    assert run(graph)["state"] == "type_it_yourself"
