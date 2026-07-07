import base64
import json
import pathlib
import subprocess
import sys

GOLDEN_PATCH_B64 = "ZGlmZiAtLWdpdCBhL3Rlc3RzL3Rlc3RfYmx1ZXByaW50cy5weSBiL3Rlc3RzL3Rlc3RfYmx1ZXByaW50cy5weQotLS0gYS90ZXN0cy90ZXN0X2JsdWVwcmludHMucHkKKysrIGIvdGVzdHMvdGVzdF9ibHVlcHJpbnRzLnB5CkBAIC0yNTYsNiArMjU2LDExIEBAIGRlZiB0ZXN0X2RvdHRlZF9uYW1lX25vdF9hbGxvd2VkKGFwcCwgY2xpZW50KToKICAgICAgICAgZmxhc2suQmx1ZXByaW50KCJhcHAudWkiLCBfX25hbWVfXykKIAogCitkZWYgdGVzdF9lbXB0eV9uYW1lX25vdF9hbGxvd2VkKGFwcCwgY2xpZW50KToKKyAgICB3aXRoIHB5dGVzdC5yYWlzZXMoVmFsdWVFcnJvcik6CisgICAgICAgIGZsYXNrLkJsdWVwcmludCgiIiwgX19uYW1lX18pCisKKwogZGVmIHRlc3RfZG90dGVkX25hbWVzX2Zyb21fYXBwKGFwcCwgY2xpZW50KToKICAgICB0ZXN0ID0gZmxhc2suQmx1ZXByaW50KCJ0ZXN0IiwgX19uYW1lX18pCiAK"

_TESTS = json.loads(r"""{"F2P": ["tests/test_blueprints.py::test_empty_name_not_allowed"], "P2P": ["tests/test_blueprints.py::test_blueprint_specific_error_handling", "tests/test_blueprints.py::test_blueprint_specific_user_error_handling", "tests/test_blueprints.py::test_blueprint_app_error_handling", "tests/test_blueprints.py::test_blueprint_prefix_slash[-/-/]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/--/]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/-/-/]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo--/foo]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo/--/foo/]", "tests/test_blueprints.py::test_blueprint_prefix_slash[-/bar-/bar]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo/-/bar-/foo/bar]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo/-bar-/foo/bar]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo-/bar-/foo/bar]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo/-//bar-/foo/bar]", "tests/test_blueprints.py::test_blueprint_prefix_slash[/foo//-/bar-/foo/bar]", "tests/test_blueprints.py::test_blueprint_url_defaults", "tests/test_blueprints.py::test_blueprint_url_processors", "tests/test_blueprints.py::test_templates_and_static", "tests/test_blueprints.py::test_default_static_max_age", "tests/test_blueprints.py::test_templates_list", "tests/test_blueprints.py::test_dotted_name_not_allowed", "tests/test_blueprints.py::test_dotted_names_from_app", "tests/test_blueprints.py::test_empty_url_defaults", "tests/test_blueprints.py::test_route_decorator_custom_endpoint", "tests/test_blueprints.py::test_route_decorator_custom_endpoint_with_dots", "tests/test_blueprints.py::test_endpoint_decorator", "tests/test_blueprints.py::test_template_filter", "tests/test_blueprints.py::test_add_template_filter", "tests/test_blueprints.py::test_template_filter_with_name", "tests/test_blueprints.py::test_add_template_filter_with_name", "tests/test_blueprints.py::test_template_filter_with_template", "tests/test_blueprints.py::test_template_filter_after_route_with_template", "tests/test_blueprints.py::test_add_template_filter_with_template", "tests/test_blueprints.py::test_template_filter_with_name_and_template", "tests/test_blueprints.py::test_add_template_filter_with_name_and_template", "tests/test_blueprints.py::test_template_test", "tests/test_blueprints.py::test_add_template_test", "tests/test_blueprints.py::test_template_test_with_name", "tests/test_blueprints.py::test_add_template_test_with_name", "tests/test_blueprints.py::test_template_test_with_template", "tests/test_blueprints.py::test_template_test_after_route_with_template", "tests/test_blueprints.py::test_add_template_test_with_template", "tests/test_blueprints.py::test_template_test_with_name_and_template", "tests/test_blueprints.py::test_add_template_test_with_name_and_template", "tests/test_blueprints.py::test_context_processing", "tests/test_blueprints.py::test_template_global", "tests/test_blueprints.py::test_request_processing", "tests/test_blueprints.py::test_app_request_processing", "tests/test_blueprints.py::test_app_url_processors", "tests/test_blueprints.py::test_nested_blueprint", "tests/test_blueprints.py::test_nested_callback_order", "tests/test_blueprints.py::test_nesting_url_prefixes[/parent-/child-None-None]", "tests/test_blueprints.py::test_nesting_url_prefixes[/parent-None-None-/child]", "tests/test_blueprints.py::test_nesting_url_prefixes[None-None-/parent-/child]", "tests/test_blueprints.py::test_nesting_url_prefixes[/other-/something-/parent-/child]", "tests/test_blueprints.py::test_nesting_subdomains", "tests/test_blueprints.py::test_child_and_parent_subdomain", "tests/test_blueprints.py::test_unique_blueprint_names", "tests/test_blueprints.py::test_self_registration", "tests/test_blueprints.py::test_blueprint_renaming"]}""")

patch_bytes = base64.b64decode(GOLDEN_PATCH_B64)
patch_path = pathlib.Path("_test_patch.diff")
patch_path.write_bytes(patch_bytes)

proc = subprocess.run(
    ["git", "apply", str(patch_path)],
    capture_output=True, text=True, timeout=30
)
if proc.returncode != 0:
    print(f"Patch apply failed: {proc.stderr}", file=sys.stderr)
    raise SystemExit(2)

cmd = [sys.executable, "-m", "pytest", *_TESTS["F2P"], *_TESTS["P2P"], "-q", "-p", "no:cacheprovider"]
proc = subprocess.run(cmd, text=True, capture_output=True, timeout=600)
print(proc.stdout, end="")
print(proc.stderr, end="")
raise SystemExit(proc.returncode)
