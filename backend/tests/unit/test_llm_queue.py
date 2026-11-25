"""The LLM queue: one question at a time, FIFO, bounded (PROJECT_SPEC §19.2)."""

import asyncio

import pytest

from services.llm_queue import LLMQueue, QueueFull


def test_the_first_ticket_may_start_at_once():
    queue = LLMQueue(10)
    ticket = queue.join()
    assert ticket.position == 0 and ticket.ready and not queue.busy
    queue.start(ticket)
    assert queue.busy and ticket.position == 0 and queue.depth == 0


def test_later_tickets_wait_in_order_and_report_how_many_are_ahead():
    queue = LLMQueue(10)
    first, second, third = queue.join(), queue.join(), queue.join()
    queue.start(first)
    assert (second.position, third.position) == (1, 2)  # the running one counts as ahead
    assert not second.ready
    queue.release(first)
    assert second.ready and second.position == 0 and third.position == 1
    queue.start(second)
    assert third.position == 1 and not third.ready  # still waits for the running one
    queue.release(second)
    assert third.ready


def test_a_ticket_cannot_jump_the_line():
    queue = LLMQueue(10)
    queue.join()
    second = queue.join()
    with pytest.raises(RuntimeError, match="turn"):
        queue.start(second)


def test_a_ticket_cannot_start_while_another_runs():
    queue = LLMQueue(10)
    first, second = queue.join(), queue.join()
    queue.start(first)
    with pytest.raises(RuntimeError):
        queue.start(second)


def test_the_queue_is_bounded_and_a_slot_frees_up_when_someone_leaves():
    queue = LLMQueue(2)
    running = queue.join()
    queue.start(running)
    a, b = queue.join(), queue.join()  # two may wait behind the running one
    with pytest.raises(QueueFull):
        queue.join()
    queue.release(a)  # someone gives up waiting
    assert b.position == 1
    queue.join()  # and there is room again


def test_leaving_the_line_moves_the_others_up_and_release_is_idempotent():
    queue = LLMQueue(10)
    a, b, c = queue.join(), queue.join(), queue.join()
    queue.release(b)
    queue.release(b)  # safe to call twice (e.g. cancelled, then cleaned up)
    assert (a.position, c.position) == (0, 1)
    queue.start(a)
    queue.release(a)
    queue.release(a)
    assert c.ready


async def test_a_waiting_request_is_woken_when_the_line_moves():
    queue = LLMQueue(10)
    first, second = queue.join(), queue.join()
    queue.start(first)
    waiter = asyncio.create_task(queue.changed(timeout=5))
    await asyncio.sleep(0)  # let it start waiting
    queue.release(first)
    assert await waiter is True and second.ready


async def test_waiting_times_out_so_the_caller_can_send_a_keep_alive():
    assert await LLMQueue(10).changed(timeout=0.01) is False


async def test_requests_really_run_one_at_a_time():
    queue, order, running, peak = LLMQueue(10), [], 0, 0

    async def request(name):
        nonlocal running, peak
        ticket = queue.join()
        while not ticket.ready:
            await queue.changed(timeout=5)
        queue.start(ticket)
        try:
            running += 1
            peak = max(peak, running)
            order.append(name)
            await asyncio.sleep(0.01)
            running -= 1
        finally:
            queue.release(ticket)

    await asyncio.gather(*(request(i) for i in range(6)))
    assert order == list(range(6)) and peak == 1
