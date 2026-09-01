from pipeline.ledger import Ledger, hash_payload
from pipeline.schemas import LedgerEvent


def _event(request_id: str = "RWK-000001", layer: str = "classifier") -> LedgerEvent:
    return LedgerEvent(
        request_id=request_id,
        layer=layer,
        decision="no_change",
        payload_hash=hash_payload({"p_nan": 0.97}),
    )


def test_append_and_read_back(tmp_path):
    ledger = Ledger(f"sqlite:///{tmp_path}/ledger.db")
    ledger.append(_event(layer="classifier"))
    ledger.append(_event(layer="orchestrator"))
    ledger.append(_event(request_id="RWK-000002"))
    rows = ledger.for_request("RWK-000001")
    assert [r["layer"] for r in rows] == ["classifier", "orchestrator"]
    assert all(r["created_at"] is not None for r in rows)


def test_ledger_api_is_append_only():
    # the hard rule: no update/delete surface exists on the ledger
    public = {name for name in dir(Ledger) if not name.startswith("_")}
    assert public == {"append", "for_request"}


def test_hash_payload_is_canonical():
    assert hash_payload({"a": 1, "b": 2}) == hash_payload({"b": 2, "a": 1})
    assert hash_payload({"a": 1}) != hash_payload({"a": 2})
