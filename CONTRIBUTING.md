# Contributing

Contributions are welcome. Favor a small, deterministic core over a large dependency graph. Before opening a PR, run the standard-library test suite, add a regression test for any bug fix, and make sure comparisons never mutate the source repo.

For changes to patch parsing, include cases with spaces, tabs, non-ASCII names, binary data and malformed input. For changes to HTML, verify escaping of filenames and diff lines. Avoid adding automatic network calls or silently executing project code.

Run locally:

```sh
python -m unittest discover -s tests -v
```

Use a descriptive commit message and explain the behavior, limits and tests in your PR. The maintainers may ask you to split broad changes.
