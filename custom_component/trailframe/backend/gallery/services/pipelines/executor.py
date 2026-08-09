import asyncio
import atexit
from concurrent.futures import ThreadPoolExecutor
from functools import partial


def create_executor(name: str, max_workers: int) -> ThreadPoolExecutor:
    executor = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix=name)
    atexit.register(executor.shutdown, wait=False, cancel_futures=True)
    return executor


async def run_in_thread(executor: ThreadPoolExecutor, func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(func, *args, **kwargs))
