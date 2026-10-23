"""Completion-driven snapshot work, with coalescing and no task backlog."""
import asyncio


async def run_snapshot_updates(wait_for_pending, publish, *, minimum_interval=.1,
                               clock=None, sleep=asyncio.sleep):
    clock = clock or asyncio.get_running_loop().time
    last_started = None
    while True:
        await wait_for_pending()
        if last_started is not None:
            delay = minimum_interval-(clock()-last_started)
            if delay > 0:
                await sleep(delay)
        last_started = clock()
        # Finish and deliver this result before taking the latest pending
        # revision. If work already took >=100ms, there is no extra delay.
        await publish()
