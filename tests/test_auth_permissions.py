from app.models import PurchaseRequest, User
from app.extensions import db


def test_login_and_protected_pages(client, login):
    assert client.get("/dashboard").status_code == 302
    assert login("requester").status_code == 200
    assert client.get("/dashboard").status_code == 200
    client.post("/logout")
    response = client.post("/login", data={"email": "requester@test.local", "password": "wrong"})
    assert b"tidak cocok" in response.data


def test_role_enforcement_and_request_ownership(app, client, login):
    with app.app_context():
        owner = User.query.filter_by(role="requester").first()
        other = User(name="Other", email="other@test.local", role="requester", password_hash=owner.password_hash)
        db.session.add(other)
        pr = PurchaseRequest(request_number="PR-OTHER", requester=other, title="Private", description="For another requester", status="pending_approval")
        db.session.add(pr)
        db.session.commit()
        pr_id = pr.id
    login("requester")
    assert client.get(f"/requests/{pr_id}").status_code == 404
    assert client.get("/vendors").status_code == 403
    client.post("/logout")
    login("approver")
    assert client.get("/vendors").status_code == 403
