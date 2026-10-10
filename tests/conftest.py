import copy
import json
import pytest
from opportunityscout.app import create_app
from opportunityscout.config import DEFAULTS
from opportunityscout.database.repository import create_database


@pytest.fixture
def settings():
    return copy.deepcopy(DEFAULTS)


@pytest.fixture
def sessions(tmp_path):
    engine, factory = create_database(str(tmp_path / 'test.db'))
    yield factory
    engine.dispose()


@pytest.fixture
def app(tmp_path, settings):
    path = tmp_path / 'settings.json'
    path.write_text(json.dumps(settings))
    application = create_app({'TESTING': True, 'SECRET_KEY': 'test-secret', 'DATABASE': str(tmp_path / 'app.db'), 'SETTINGS_PATH': str(path)})
    yield application
    application.extensions['engine'].dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def paid_record():
    return dict(kind='income', title='Website maintenance', organization='Test fixture client',
                location='United States', remote=True, url='https://example.org/fixture-job',
                category='website', amount=50, compensation_type='hourly', pay_basis='contractor_gross',
                work_hours=10, travel_hours=0, preparation_hours=0, expenses=0, weekly_hours=10,
                flexible=True, evidence={'fit': {'value': 95, 'reason': 'Relevant website experience reviewed'},
                                        'career': {'value': 80, 'reason': 'Documented recurring contract'}})


def token(client):
    client.get('/')
    with client.session_transaction() as session:
        return session['csrf_token']
