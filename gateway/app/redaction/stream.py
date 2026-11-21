class StreamRestorer:
    """
    Buffers streaming chunks to safely restore placeholders (<TYPE_N>)
    even when a placeholder is split across chunk boundaries (e.g. '<PER' + 'SON_1>').
    """

    def __init__(self, placeholder_map: dict[str, str], max_placeholder_len: int = 30) -> None:
        self.placeholder_map = placeholder_map
        self.max_placeholder_len = max_placeholder_len
        self.buffer = ""

    def _replace_all(self, text: str) -> str:
        for placeholder, original in self.placeholder_map.items():
            text = text.replace(placeholder, original)
        return text

    def feed(self, chunk: str) -> str:
        if not chunk:
            return ""

        self.buffer += chunk

        # Look for possible incomplete placeholder at the tail of the buffer.
        # A partial placeholder starts with '<' and has no closing '>' after that '<'.
        last_open = self.buffer.rfind("<")
        last_close = self.buffer.rfind(">")

        # If there is an unclosed '<' within the last `max_placeholder_len` characters:
        is_unclosed = last_open != -1 and last_open > last_close
        if is_unclosed and (len(self.buffer) - last_open) < self.max_placeholder_len:
            # Emit everything up to `last_open`, keep the unclosed tail in buffer
            to_emit = self.buffer[:last_open]
            self.buffer = self.buffer[last_open:]
            return self._replace_all(to_emit)

        # If no unclosed tag is near the tail, process and emit entire buffer
        to_emit = self.buffer
        self.buffer = ""
        return self._replace_all(to_emit)

    def flush(self) -> str:
        """Flushes any remaining text in the buffer."""
        remaining = self.buffer
        self.buffer = ""
        return self._replace_all(remaining)
