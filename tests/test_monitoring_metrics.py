from app.monitoring.metrics import profile_updates_total, record_profile_update


def _count(field: str, result: str) -> float:
    return profile_updates_total.labels(field=field, result=result)._value.get()


def test_record_profile_update_increments_the_labelled_counter() -> None:
    before = _count("classes", "unknown_subject")

    record_profile_update("classes", "unknown_subject")

    assert _count("classes", "unknown_subject") == before + 1
