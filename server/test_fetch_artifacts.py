"""The private APK loader must work without an unauthenticated Release URL."""
import hashlib
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import fetch_artifacts


class ArtifactTests(unittest.TestCase):
    def test_local_source_is_verified_and_existing_copy_is_reused(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            source = root / 'source.apk'
            output = root / 'output'
            good = b'verified APK fixture'
            with patch.object(fetch_artifacts, 'SHA256', hashlib.sha256(good).hexdigest()):
                source.write_bytes(b'wrong')
                with self.assertRaisesRegex(RuntimeError, 'unexpected SHA-256'):
                    fetch_artifacts.fetch(output, source)
                self.assertFalse((output / 'PhotoSorter.apk').exists())

                source.write_bytes(good)
                destination = fetch_artifacts.fetch(output, source)
                self.assertEqual(destination.read_bytes(), good)
                source.unlink()
                self.assertEqual(fetch_artifacts.fetch(output), destination)

    def test_missing_source_does_not_use_public_release(self):
        with tempfile.TemporaryDirectory() as temporary:
            with self.assertRaisesRegex(RuntimeError, 'public GitHub releases are not used'):
                fetch_artifacts.fetch(temporary)


if __name__ == '__main__':
    unittest.main()
