import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial


async def run_in_thread(executor: ThreadPoolExecutor, func, *args, **kwargs):
    loop = asyncio.get_running_loop()
    return await loop.run_in_executor(executor, partial(func, *args, **kwargs))
