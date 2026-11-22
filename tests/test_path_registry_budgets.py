"""Path collision checking must handle deep Git names without quadratic work."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from patchtransit.core import PatchTransitError, _PortablePathRegistry


class PortablePathRegistryBudgets(unittest.TestCase):
    def test_deep_path_is_registered_as_individual_components(self):
        registry = _PortablePathRegistry()
        registry.register("/".join("x" for _ in range(8_000)))
        self.assertEqual(8_000, registry.node_count)
        with self.assertRaisesRegex(
            PatchTransitError, "file/directory targets collide"
        ):
            registry.register("/".join("x" for _ in range(7_999)))

    def test_repeated_prefixes_share_nodes(self):
        registry = _PortablePathRegistry()
        registry.register("src/util/a.py")
        registry.register("src/util/b.py")
        self.assertEqual(4, registry.node_count)

    def test_duplicate_exact_file_is_rejected(self):
        registry = _PortablePathRegistry()
        registry.register("src/foo.py")
        with self.assertRaisesRegex(
            PatchTransitError, "file/directory targets collide"
        ):
            registry.register("src/foo.py")

    def test_file_directory_aliases_in_either_order(self):
        for first, second in (("abc", "abc/child"), ("abc/child", "abc")):
            with self.subTest(first=first):
                registry = _PortablePathRegistry()
                registry.register(first)
                with self.assertRaisesRegex(
                    PatchTransitError, "file/directory targets collide"
                ):
                    registry.register(second)

    def test_excess_path_components_fail_closed(self):
        registry = _PortablePathRegistry()
        with patch("patchtransit.core.MAX_PORTABLE_PATH_COMPONENTS", 3):
            registry.register("a/b/c")
            with self.assertRaisesRegex(PatchTransitError, "path component limit"):
                registry.register("a/b/d")
        self.assertEqual(3, registry.node_count)

    def test_repeated_prefix_does_not_consume_budget(self):
        registry = _PortablePathRegistry()
        with patch("patchtransit.core.MAX_PORTABLE_PATH_COMPONENTS", 5):
            registry.register("src/pkg/a.py")
            registry.register("src/pkg/b.py")
            registry.register("src/pkg/c.py")
        self.assertEqual(5, registry.node_count)
