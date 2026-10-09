"""Illustrator 24 private-stream compression; no Adobe application required."""
try:
    from compression import zstd
except ImportError:
    import zstandard

    def compress(data: bytes) -> bytes:
        return zstandard.ZstdCompressor(level=3).compress(data)

    def decompress(data: bytes) -> bytes:
        return zstandard.ZstdDecompressor().decompress(data, max_output_size=256 * 1024 * 1024)
else:
    compress = zstd.compress
    decompress = zstd.decompress

MARKER = b"%AI24_ZStandard_Data"


def decode_private(data: bytes) -> bytes:
    if not data.startswith(MARKER):
        raise ValueError("Not an Illustrator 24 Zstandard stream")
    return decompress(data[len(MARKER):])
