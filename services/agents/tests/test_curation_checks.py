from modeler_agents.citations import quote_appears_in, value_stated_in_quote
from modeler_agents.parameter_curation import CurationContext, DocumentHit, record_proposal

PAGE = (
    "Plasma protein binding was determined by equilibrium dialysis. The fraction un-\n"
    "bound in human plasma was 3.1% (n = 6) and was independent of concentration."
)


class OnePageStore:
    def search(self, query: str, max_results: int) -> list[DocumentHit]:
        return [DocumentHit(doc_sha256="d" * 64, title="Example study", page=4, snippet=PAGE[:80])]

    def page_text(self, doc_sha256: str, page: int) -> str | None:
        return PAGE if (doc_sha256, page) == ("d" * 64, 4) else None


def context() -> CurationContext:
    return CurationContext(tenant_id="t1", compound_name="Example-A", requested_parameters=["fraction_unbound"], documents=OnePageStore())


def test_quote_matching_tolerates_layout_but_not_edits():
    assert quote_appears_in(PAGE, "The fraction unbound in human plasma was 3.1%")
    assert not quote_appears_in(PAGE, "The fraction unbound in human plasma was 2.1%")
    assert not quote_appears_in(PAGE, "3.1%")


def test_value_statement_detection():
    assert value_stated_in_quote(0.031, "was 3.1% (n = 6)")
    assert value_stated_in_quote(3.1, "was 3.1% (n = 6)")
    assert not value_stated_in_quote(0.05, "was 3.1% (n = 6)")


def test_valid_proposal_is_recorded_for_review():
    ctx = context()
    reply = record_proposal(
        ctx,
        parameter="fraction_unbound",
        value=0.031,
        unit=None,
        source_type="InVitro",
        doc_sha256="d" * 64,
        page=4,
        quote="The fraction unbound in human plasma was 3.1% (n = 6)",
        conditions="equilibrium dialysis, human plasma",
    )
    assert reply.startswith("RECORDED")
    assert ctx.proposals[0].value_stated_in_quote


def test_fabricated_quote_is_rejected():
    ctx = context()
    reply = record_proposal(
        ctx,
        parameter="fraction_unbound",
        value=0.05,
        unit=None,
        source_type="InVitro",
        doc_sha256="d" * 64,
        page=4,
        quote="The fraction unbound in human plasma was 5%",
    )
    assert reply.startswith("REJECTED INVALID_CITATION")
    assert ctx.proposals == [] and ctx.rejections[0]["code"] == "INVALID_CITATION"


def test_wrong_page_and_unrequested_parameter_are_rejected():
    ctx = context()
    assert "UNKNOWN_DOCUMENT_PAGE" in record_proposal(
        ctx, parameter="fraction_unbound", value=0.031, unit=None, source_type="InVitro", doc_sha256="d" * 64, page=5, quote="x" * 20
    )
    assert "PARAMETER_NOT_REQUESTED" in record_proposal(
        ctx, parameter="logP", value=3.0, unit=None, source_type="InVitro", doc_sha256="d" * 64, page=4, quote="x" * 20
    )
