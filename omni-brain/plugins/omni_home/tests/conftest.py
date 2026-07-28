"""omni_home 测试共享 fixtures：演示家庭 states 数据。

数据结构与 Home Assistant ``GET /api/states`` 的返回格式一致，
权威定义在 ``omni_home.client.DEMO_HOME_STATES``（fake 客户端与 CLI 演示同源），
供 entities/nlu/knowledge/tools 等测试复用（全 fake，无需真实 HA）。
"""

from __future__ import annotations

import copy

import pytest

from omni_home.client import DEMO_HOME_STATES

#: 测试内引用的演示家庭别名（与 client.DEMO_HOME_STATES 同源）
DEMO_STATES = DEMO_HOME_STATES


@pytest.fixture
def demo_states() -> list[dict]:
    """返回演示家庭 states 的深拷贝（测试间互不影响）。"""
    return copy.deepcopy(DEMO_STATES)
