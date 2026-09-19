import json

import pytest

from chesterton.__main__ import main
from chesterton.sandbox.fake import FakeSandboxRunner
from chesterton.sandbox.protocol import RunResult
from chesterton.seed.build import COVERAGE_PATH, RUN_LOGS
from chesterton.seed.record import SeedRecord

from conftest import HEAD_PAY, T_CHARGE


def a_seedable_runner():
    log = f"=== short test summary info ===\nPASSED {T_CHARGE}\n"
    coverage = {"files": {"pay.py": {"contexts": {"2": [f"{T_CHARGE}|run"]}}}}
    return FakeSandboxRunner(artifacts={
        RUN_LOGS[0]: log, RUN_LOGS[1]: log, RUN_LOGS[2]: log,
        COVERAGE_PATH: json.dumps(coverage), "/testbed/pay.py": HEAD_PAY,
    })


def test_seed_writes_a_loadable_seed_record(tmp_path, demo_seed, capsys):
    out = tmp_path / "seeds" / "demo.json"

    async def fetch(url):
        assert url == "https://github.com/acme/pay/pull/1"
        return demo_seed.pr

    code = main(
        ["seed", "--pr", "https://github.com/acme/pay/pull/1",
         "--image", "docker://example/pay", "--slug", "demo", "--out", str(out)],
        runner_factory=a_seedable_runner, fetch=fetch,
    )

    assert code == 0
    seed = SeedRecord.from_json(out.read_text(encoding="utf-8"))
    assert seed.selectable == {T_CHARGE}
    assert "chesterton:seed-demo" in capsys.readouterr().out


def test_seed_records_the_interpreter_passed_with_python(tmp_path, demo_seed):
    out = tmp_path / "demo.json"

    async def fetch(url):
        return demo_seed.pr

    code = main(
        ["seed", "--pr", "https://github.com/acme/pay/pull/1", "--image", "x",
         "--slug", "demo", "--out", str(out),
         "--python", "/opt/conda/envs/testbed/bin/python"],
        runner_factory=a_seedable_runner, fetch=fetch,
    )

    assert code == 0
    seed = SeedRecord.from_json(out.read_text(encoding="utf-8"))
    assert seed.test_command == "/opt/conda/envs/testbed/bin/python -m pytest"


def test_seed_records_the_test_scope_passed_with_tests(tmp_path, demo_seed):
    out = tmp_path / "demo.json"

    async def fetch(url):
        return demo_seed.pr

    code = main(
        ["seed", "--pr", "https://github.com/acme/pay/pull/1", "--image", "x",
         "--slug", "demo", "--out", str(out),
         "--tests", "tests/test_pay.py", "tests/test_refund.py"],
        runner_factory=a_seedable_runner, fetch=fetch,
    )

    assert code == 0
    seed = SeedRecord.from_json(out.read_text(encoding="utf-8"))
    assert seed.test_paths == ("tests/test_pay.py", "tests/test_refund.py")


def a_swebench_task(demo_seed):
    from chesterton.github.swebench import SWEBenchTask

    return SWEBenchTask(
        instance_id="acme__pay-1",
        pr=demo_seed.pr,
        test_paths=("tests/test_pay.py",),
        image="docker://swebench/sweb.eval.x86_64.acme_1776_pay-1",
    )


def test_seed_from_swebench_defaults_to_its_image_and_test_files(tmp_path, demo_seed):
    out = tmp_path / "demo.json"
    asked = []

    async def fetch_swebench(instance_id):
        asked.append(instance_id)
        return a_swebench_task(demo_seed)

    code = main(
        ["seed", "--swebench", "acme__pay-1", "--slug", "demo", "--out", str(out)],
        runner_factory=a_seedable_runner, fetch_swebench=fetch_swebench,
    )

    assert code == 0
    assert asked == ["acme__pay-1"]
    seed = SeedRecord.from_json(out.read_text(encoding="utf-8"))
    assert seed.image_ref == "docker://swebench/sweb.eval.x86_64.acme_1776_pay-1"
    assert seed.test_paths == ("tests/test_pay.py",)


def test_explicit_tests_override_the_swebench_scope(tmp_path, demo_seed):
    out = tmp_path / "demo.json"

    async def fetch_swebench(instance_id):
        return a_swebench_task(demo_seed)

    main(
        ["seed", "--swebench", "acme__pay-1", "--slug", "demo", "--out", str(out),
         "--tests", "tests/test_other.py"],
        runner_factory=a_seedable_runner, fetch_swebench=fetch_swebench,
    )

    seed = SeedRecord.from_json(out.read_text(encoding="utf-8"))
    assert seed.test_paths == ("tests/test_other.py",)


def test_an_unreachable_dataset_exits_1_with_the_reason(tmp_path, capsys):
    from chesterton.github.swebench import SWEBenchError

    async def fetch_swebench(instance_id):
        raise SWEBenchError("the dataset API failed twice (ReadTimeout: slow)")

    code = main(
        ["seed", "--swebench", "acme__pay-1", "--slug", "demo",
         "--out", str(tmp_path / "s.json")],
        runner_factory=a_seedable_runner, fetch_swebench=fetch_swebench,
    )

    assert code == 1
    assert "ReadTimeout" in capsys.readouterr().err


def test_a_pr_seed_still_requires_an_image():
    with pytest.raises(SystemExit):
        main(["seed", "--pr", "https://github.com/acme/pay/pull/1",
              "--slug", "demo", "--out", "x.json"])


def test_pr_and_swebench_are_mutually_exclusive():
    with pytest.raises(SystemExit):
        main(["seed", "--pr", "https://github.com/acme/pay/pull/1",
              "--swebench", "acme__pay-1", "--image", "x",
              "--slug", "demo", "--out", "x.json"])


def test_run_writes_a_report_and_names_the_undefended_surface(tmp_path, demo_seed, capsys):
    seed_path = tmp_path / "demo.json"
    seed_path.write_text(demo_seed.to_json(), encoding="utf-8")
    out = tmp_path / "runs" / "demo.json"

    def runner_factory():
        return FakeSandboxRunner(handler=lambda c, s, f: RunResult("", "", 0, None))

    code = main(
        ["run", str(seed_path), "--out", str(out), "--no-llm"],
        runner_factory=runner_factory,
    )

    assert code == 0
    assert json.loads(out.read_text(encoding="utf-8"))["slug"] == "demo"
    printed = capsys.readouterr().out
    assert "undefended" in printed
    assert "equivalent" not in printed.lower()


def test_a_refused_run_exits_2_with_the_reason(tmp_path, demo_seed, capsys):
    seed_path = tmp_path / "demo.json"
    seed_path.write_text(demo_seed.to_json(), encoding="utf-8")

    code = main(
        ["run", str(seed_path), "--out", str(tmp_path / "r.json"),
         "--no-llm", "--op-budget", "0"],
        runner_factory=FakeSandboxRunner,
    )

    assert code == 2
    assert "refusing to start" in capsys.readouterr().err


def test_a_failed_seed_build_exits_1_with_the_reason(tmp_path, demo_seed, capsys):
    async def fetch(url):
        return demo_seed.pr

    def broken():
        return FakeSandboxRunner(
            handler=lambda c, s, f: RunResult("", "error: patch failed", 1, None)
        )

    code = main(
        ["seed", "--pr", "https://github.com/acme/pay/pull/1", "--image", "x",
         "--slug", "demo", "--out", str(tmp_path / "s.json")],
        runner_factory=broken, fetch=fetch,
    )

    assert code == 1
    assert "patch failed" in capsys.readouterr().err


def test_a_missing_subcommand_is_a_usage_error():
    with pytest.raises(SystemExit):
        main([])
