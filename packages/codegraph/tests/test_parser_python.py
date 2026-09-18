"""Parser unit tests: Python structural extraction."""

from codegraph.parser.python import parse_python_source


def test_python_class_function_imports() -> None:
    src = (
        "import os\n"
        "from m import a, b as c\n"
        "\n"
        "class C:\n"
        "    def m(self):\n"
        "        pass\n"
        "\n"
        "def f():\n"
        "    pass\n"
    )
    parsed = parse_python_source(src)
    assert not parsed.has_error

    kinds = {(d.kind, d.name) for d in parsed.definitions}
    assert ("class", "C") in kinds
    assert ("function", "m") in kinds
    assert ("function", "f") in kinds

    method = next(d for d in parsed.definitions if d.name == "m")
    assert method.is_method
    assert method.parent == "C"

    top = next(d for d in parsed.definitions if d.name == "f")
    assert not top.is_method
    assert top.parent is None

    modules = {(i.module, i.name) for i in parsed.imports}
    assert ("os", "os") in modules
    assert ("m", "a") in modules
    assert ("m", "c") in modules


def test_python_decorated_and_relative() -> None:
    src = "@dec\ndef f():\n    pass\nfrom . import d\nfrom m import *\n"
    parsed = parse_python_source(src)
    assert ("function", "f") in {(d.kind, d.name) for d in parsed.definitions}
    modules = {(i.module, i.name) for i in parsed.imports}
    assert (".", "d") in modules
    assert ("m", "*") in modules


def test_python_blank_source() -> None:
    parsed = parse_python_source("   \n  \n")
    assert parsed.definitions == ()
    assert parsed.imports == ()
