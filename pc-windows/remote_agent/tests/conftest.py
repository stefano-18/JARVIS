"""Aislamiento de la suite: el log local del agente va a tmp_path.

Sin esto, test_killswitch.py y test_killswitch_wire.py (que llaman a
agent._handle_killswitch/_handle_unlock) anadirian lineas al
logs/remote_agent.log REAL via agent._log. audit.jsonl y killswitch.json
ya usan tmp_path en cada test; agent.lock no se usa en tests.
No toca codigo de produccion: solo redirige agent.LOG_FILE en memoria.
"""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import agent as _agent_mod


@pytest.fixture(autouse=True)
def _aislar_log_local(tmp_path, monkeypatch):
    monkeypatch.setattr(_agent_mod, "LOG_FILE", tmp_path / "remote_agent_test.log")
