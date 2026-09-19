import pytest

from clinical_retrieval.__main__ import case_output_path


def test_repeated_case_preserves_previous_outputs(tmp_path):
    first = case_output_path(tmp_path, "402_183")
    assert first == tmp_path / "402_183"
    first.mkdir()
    evidence = first / "evidence.json"
    evidence.write_text('{"evidence": []}', encoding="utf-8")
    second = case_output_path(tmp_path, "402_183")
    assert second == tmp_path / "402_183_2"
    second.mkdir()
    assert case_output_path(tmp_path, "402_183") == tmp_path / "402_183_3"
    assert evidence.read_text(encoding="utf-8") == '{"evidence": []}'


@pytest.mark.parametrize("case_id", ["../../outside", r"..\outside", "C:/outside", "...", "CON", "lpt1"])
def test_case_id_is_a_safe_directory_name(tmp_path, case_id):
    output = case_output_path(tmp_path, case_id)
    assert output.parent == tmp_path.resolve()
    output.mkdir()
    assert output.is_dir()
