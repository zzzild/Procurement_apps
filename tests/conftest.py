import pytest

from app import create_app
from app.extensions import db as _db
from app.models import User


@pytest.fixture
def app(tmp_path):
    app = create_app({"TESTING": True, "WTF_CSRF_ENABLED": False, "SQLALCHEMY_DATABASE_URI": "sqlite://", "UPLOAD_FOLDER": str(tmp_path / "uploads"), "SECRET_KEY": "test-key"})
    with app.app_context():
        _db.create_all()
        for role in ["requester", "approver", "procurement", "receiver"]:
            u = User(name=role.title(), email=f"{role}@test.local", role=role)
            u.set_password("password")
            _db.session.add(u)
        _db.session.commit()
        yield app
        _db.session.remove()
        _db.drop_all()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def login(client):
    def _login(role):
        return client.post("/login", data={"email": f"{role}@test.local", "password": "password"}, follow_redirects=True)
    return _login
