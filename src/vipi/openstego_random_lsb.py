"""Read the pixel stream used by OpenStego RandomLSB with the default seed."""

_MULTIPLIER = 0x5DEECE66D
_MASK = (1 << 48) - 1
_DEFAULT_SEED = 98234782


class RandomLsbReader:
    """Consume the header and payload with Java Random's bounded integer draws."""

    def __init__(self, image):
        self.width, self.height = image.size
        self.pixels = image.load()
        self.capacity = self.width * self.height * 3
        self.state = (_DEFAULT_SEED ^ _MULTIPLIER) & _MASK
        self.depth = 1
        self.header_positions = set()
        self.used = None

    def read(self, length):
        return bytes(self._read_byte() for _ in range(length))

    def start_payload(self, depth):
        self.depth = depth
        self.used = bytearray((self.capacity * depth + 7) // 8)
        for sample in self.header_positions:
            slot, bit = divmod(sample * depth, 8)
            self.used[slot] |= 1 << bit
        self.header_positions.clear()

    def _draw(self, bound):
        # java.util.Random.nextInt advances state even when bound is one.
        while True:
            self.state = (self.state * _MULTIPLIER + 11) & _MASK
            value = self.state >> 17
            if bound & (bound - 1) == 0:
                return (value * bound) >> 31
            choice = value % bound
            if value - choice + bound <= 1 << 31:
                return choice

    def _read_byte(self):
        value = 0
        for _ in range(8):
            value = (value << 1) | self._next_bit()
        return value

    def _next_bit(self):
        while True:
            x = self._draw(self.width)
            y = self._draw(self.height)
            # OpenStego numbers channels in Java's packed BGR bit order.
            channel = 2 - self._draw(3)
            bit = self._draw(self.depth)
            sample = (y * self.width + x) * 3 + channel
            if self._claim(sample, bit):
                return (self.pixels[x, y][channel] >> bit) & 1

    def _claim(self, sample, bit):
        if self.used is None:
            if sample in self.header_positions:
                return False
            self.header_positions.add(sample)
            return True
        slot, index = divmod(sample * self.depth + bit, 8)
        flag = 1 << index
        if self.used[slot] & flag:
            return False
        self.used[slot] |= flag
        return True
