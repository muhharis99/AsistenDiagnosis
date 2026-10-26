from receivables.models import ReceivableLedgerEntry


def test_receivable_ledger_supports_payer_patient_and_cob_entries():
    assert ReceivableLedgerEntry.AccountType.PAYER == "PAYER"
    assert ReceivableLedgerEntry.AccountType.PATIENT == "PATIENT"
    assert ReceivableLedgerEntry.EntryType.COB_TRANSFER_TO_SECONDARY == "COB_TRANSFER_TO_SECONDARY"
    assert ReceivableLedgerEntry.Direction.DEBIT == "DEBIT"
    assert ReceivableLedgerEntry.Direction.CREDIT == "CREDIT"
