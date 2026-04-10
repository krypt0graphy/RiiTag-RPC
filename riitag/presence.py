import asyncio
import calendar
import threading

import pypresence

from .user import RiitagInfo, RiitagTitleResolver

resolver = RiitagTitleResolver()


def format_presence(riitag_info: RiitagInfo):
    last_played = riitag_info.last_played
    if not last_played:
        return {}

    start_timestamp = calendar.timegm(last_played.time.utctimetuple())
    title = resolver.resolve(last_played.console, last_played.game_id)

    return {
        'details': f'Playing {title.name}',
        'state': f'Playing on {title.console_name}',
        'start': start_timestamp,
        'large_image': title.get_cover_url(),
        'large_text': title.name,
        'small_image': 'logo',
        'small_text': 'riitag.t0g3pii.de',
        'buttons': [
            {'label': 'View RiiTag', 'url': f'https://riitag.t0g3pii.de/user/{riitag_info.id}'}
        ]
    }

class PatchedAioPresence(pypresence.AioPresence):
    async def create_reader_writer(self, ipc_path):
        import sys
        if sys.platform in ("linux", "darwin"):
            self.sock_reader, self.sock_writer = await asyncio.open_unix_connection(ipc_path)
        elif sys.platform == "win32":
            self.sock_reader = asyncio.StreamReader()
            reader_protocol = asyncio.StreamReaderProtocol(self.sock_reader)
            self.sock_writer, _ = await self.loop.create_pipe_connection(
                lambda: reader_protocol, ipc_path
            )

class RPCHandler:
    def __init__(self, client_id, on_error=None):
        self._client_id = client_id
        self._on_error = on_error
        self._is_connected = False
        self._error_count = 0

        # Dedicated event loop running on its own thread
        self._loop = asyncio.new_event_loop()
        self._thread = threading.Thread(target=self._run_loop, daemon=True)
        self._thread.start()

        self._presence = PatchedAioPresence(
            client_id=client_id,
            loop=self._loop,
            response_timeout=5,
        )

    def _run_loop(self):
        asyncio.set_event_loop(self._loop)
        self._loop.run_forever()

    def _run(self, coro):
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return future.result(timeout=10)

    @property
    def is_connected(self):
        return self._is_connected

    def _error_handler(self, exception, future):
        self._error_count += 1
        if self._error_count >= 3:
            if self._on_error:
                self._on_error(exception, future)

    def connect(self):
        try:
            self._run(self._presence.connect())
        except (ConnectionRefusedError, pypresence.PyPresenceException, TimeoutError):
            self._is_connected = False
            return False
        else:
            self._is_connected = True
            return True

    def clear(self):
        try:
            self._run(self._presence.clear())
        except (pypresence.ResponseTimeout, TimeoutError):
            # clear can timeout when using arRPC
            # see: https://github.com/RiiConnect24/RiiTag-RPC/issues/29
            pass

    def set_presence(self, **options):
        try:
            self._run(self._presence.update(**options))
        except (pypresence.ResponseTimeout, TimeoutError):
            pass