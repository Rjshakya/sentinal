"""Parser unit tests: TypeScript / JavaScript structural extraction."""

from codegraph.parser.typescript import (
    parse_javascript_source,
    parse_typescript_source,
)


def test_typescript_class_function_imports() -> None:
    src = (
        'import x from "mod";\n'
        'import {a, b as c} from "m2";\n'
        "export class C { m() {} }\n"
        "export function f() {}\n"
        "const g = () => {};\n"
    )
    parsed = parse_typescript_source(src)
    assert not parsed.has_error

    kinds = {(d.kind, d.name) for d in parsed.definitions}
    assert ("class", "C") in kinds
    assert ("function", "m") in kinds
    assert ("function", "f") in kinds
    assert ("function", "g") in kinds

    method = next(d for d in parsed.definitions if d.name == "m")
    assert method.is_method
    assert method.parent == "C"

    modules = {(i.module, i.name) for i in parsed.imports}
    assert ("mod", "x") in modules
    assert ("m2", "a") in modules
    assert ("m2", "c") in modules


def test_javascript_matches_typescript() -> None:
    # NOTE: anonymous ``function() {}`` expressions assigned to a
    # variable are not surfaced by the pack's structure rows (only
    # declarations and arrow functions are), so v1 does not record
    # them either.
    src = 'import x from "mod";\nfunction f() {}\nconst g = () => {};\n'
    parsed = parse_javascript_source(src)
    kinds = {(d.kind, d.name) for d in parsed.definitions}
    assert ("function", "f") in kinds
    assert ("function", "g") in kinds
    assert ("mod", "x") in {(i.module, i.name) for i in parsed.imports}


def test_side_effect_import() -> None:
    parsed = parse_typescript_source('import "polyfill";\n')
    assert len(parsed.imports) == 1
    assert parsed.imports[0].module == "polyfill"
    assert parsed.imports[0].name == "*"
