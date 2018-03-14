import sys

import base_node_rpc.async as bnra

if sys.version_info[0] < 3:
    import trollius as asyncio
else:
    import asyncio


#: .. versionadded:: X.X.X
def test_run_from_running_loop():
    @asyncio.coroutine
    def foo():
        return bnra.available_devices()

    loop = bnra.new_file_event_loop()
    original_loop = asyncio.get_event_loop()

    asyncio.set_event_loop(loop)
    print(loop.run_until_complete(foo()))
    loop.stop()
    asyncio.set_event_loop(original_loop)


#: .. versionadded:: X.X.X
def test_run_from_default_loop():
    print(bnra.available_devices())
