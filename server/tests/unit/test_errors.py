from app.core.errors import AppError


def test_error_body_omits_details_when_absent():
    error = AppError("not_found", "Case was not found", status_code=404)
    assert error.body() == {"error": {"code": "not_found", "message": "Case was not found"}}


def test_error_body_includes_details_when_present():
    error = AppError("invalid", "Check the field", details={"field": "amount"})
    assert error.body()["error"]["details"] == {"field": "amount"}
