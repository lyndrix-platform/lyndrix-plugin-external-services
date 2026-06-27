import importlib
import sys
import types
import unittest
from unittest.mock import MagicMock


def _install_core_api_stub():
    core_mod = types.ModuleType("core")
    api_mod = types.ModuleType("core.api")

    class _DummyMetadata:
        @staticmethod
        def create_all(bind=None):
            return None

    class _DummyBase:
        metadata = _DummyMetadata()

    session_mock = MagicMock()
    session_mock.__enter__.return_value = session_mock
    session_mock.__exit__.return_value = False
    session_mock.query.return_value.order_by.return_value.all.return_value = []

    db_instance = types.SimpleNamespace(
        engine=MagicMock(),
        SessionLocal=lambda: session_mock,
    )

    api_mod.Base = _DummyBase
    api_mod.db_instance = db_instance

    sys.modules.setdefault("core", core_mod)
    sys.modules["core.api"] = api_mod
    if "sqlalchemy" not in sys.modules:
        sqlalchemy_mod = types.ModuleType("sqlalchemy")
        sqlalchemy_mod.Column = lambda *args, **kwargs: None
        sqlalchemy_mod.Integer = int
        sqlalchemy_mod.String = str
        sqlalchemy_mod.Boolean = bool
        sys.modules["sqlalchemy"] = sqlalchemy_mod


class ServiceSmokeTest(unittest.TestCase):
    def test_manager_exists_and_empty_payload_does_not_raise(self):
        _install_core_api_stub()

        service_module = importlib.import_module("app.logic.service")

        self.assertTrue(hasattr(service_module, "ext_service_manager"))
        service_module.ext_service_manager.register_from_payload({})


if __name__ == "__main__":
    unittest.main()
