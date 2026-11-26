import asyncio

from emelab import wsqueue


def test_lift_queue_makes_bounded_queue_unbounded():
    q = asyncio.Queue(maxsize=3)
    assert wsqueue.lift_queue(q) is True
    for i in range(10):
        q.put_nowait(i)
    assert q.qsize() == 10
    assert wsqueue.lift_queue(q) is False


def test_lift_sets_module_constant():
    from streamlit.web.server.starlette import starlette_websocket as ws
    wsqueue.lift()
    assert ws.WEBSOCKET_MAX_SEND_QUEUE_SIZE == 0
