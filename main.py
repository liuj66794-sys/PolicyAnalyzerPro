from __future__ import annotations

import argparse
import json
import multiprocessing
import os
import sys
import traceback
from dataclasses import asdict
from pathlib import Path

os.environ.setdefault("QT_ENABLE_HIGHDPI_SCALING", "1")
os.environ.setdefault("QT_SCALE_FACTOR_ROUNDING_POLICY", "PassThrough")

try:
    from PySide6.QtCore import QSettings, Qt
    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication, QMessageBox
except ModuleNotFoundError as exc:
    if exc.name == "PySide6":
        project_root = Path(__file__).resolve().parent
        venv_python = project_root / ".venv" / "Scripts" / "python.exe"
        activate_script = project_root / ".venv" / "Scripts" / "Activate.ps1"
        message = (
            "未检测到 PySide6，当前解释器环境缺少桌面依赖。\n\n"
            f"当前解释器：{sys.executable}\n"
            f"请改用：{venv_python} main.py\n"
            f"或先执行：{activate_script}\n"
        )
        print(message, file=sys.stderr)
        raise SystemExit(1) from exc
    raise

from core.config import AppConfig, apply_tesseract_runtime_environment, load_app_config
from core.startup_checks import (
    StartupCheckReport,
    mark_startup_wizard_completed,
    run_startup_checks,
    should_show_startup_wizard,
)
from ui.main_window import MainWindow
from ui.startup_wizard import StartupWizardDialog


APP_ORGANIZATION = "PolicyAnalyzerPro"


def configure_process_environment(config: AppConfig) -> None:
    for key, value in config.offline_env.items():
        os.environ.setdefault(key, str(value))
    os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")
    if config.tesseract_cmd:
        apply_tesseract_runtime_environment(config.tesseract_cmd)


def install_global_exception_hook() -> None:
    def handle_exception(exc_type, exc_value, exc_traceback) -> None:  # type: ignore[no-untyped-def]
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc_value, exc_traceback)
            return

        details = "".join(traceback.format_exception(exc_type, exc_value, exc_traceback))
        print(details, file=sys.stderr)

        app = QApplication.instance()
        if app is None:
            return

        message = (
            "程序发生未处理异常。\n\n"
            f"异常类型：{exc_type.__name__}\n"
            f"异常信息：{exc_value}\n\n"
            "详细堆栈已输出到控制台。"
        )
        QMessageBox.critical(None, "PolicyAnalyzerPro 致命错误", message)

    sys.excepthook = handle_exception


def load_application_font(app: QApplication, config: AppConfig) -> None:
    font_path = Path(config.resolved_font_path)
    if not font_path.exists():
        return

    try:
        from PySide6.QtGui import QFontDatabase
    except ImportError:
        return

    font_id = QFontDatabase.addApplicationFont(str(font_path))
    if font_id == -1:
        return

    families = QFontDatabase.applicationFontFamilies(font_id)
    if not families:
        return

    app_font = QFont(app.font())
    app_font.setFamily(families[0])
    app.setFont(app_font)


def maybe_run_startup_wizard(
    config: AppConfig,
    settings: QSettings,
) -> tuple[bool, StartupCheckReport]:
    report = run_startup_checks(config)
    if should_show_startup_wizard(settings, report):
        wizard = StartupWizardDialog(config=config, report=report)
        if wizard.exec() != wizard.DialogCode.Accepted:
            return False, wizard.report

        report = wizard.report
        if wizard.suppress_future_wizard:
            mark_startup_wizard_completed(settings, report)

    return True, report


def build_startup_check_payload(report: StartupCheckReport) -> dict[str, object]:
    return {
        "checked_at": report.checked_at,
        "wizard_version": report.wizard_version,
        "overall_status": report.overall_status,
        "overall_label": report.overall_label,
        "summary_text": report.summary_text,
        "ok_count": report.ok_count,
        "warning_count": report.warning_count,
        "error_count": report.error_count,
        "results": [asdict(item) for item in report.results],
    }


def write_startup_check_json(report: StartupCheckReport, output_path: str | Path) -> Path:
    target = Path(output_path).expanduser()
    if not target.is_absolute():
        target = (Path.cwd() / target).resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    payload = build_startup_check_payload(report)
    target.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return target


def run_cli_self_check(config: AppConfig, json_output_path: str | Path | None = None) -> int:
    report = run_startup_checks(config)
    print(f"[{report.overall_label}] {report.summary_text}")
    for item in report.results:
        print(f"- {item.status:<7} {item.title}: {item.summary}")

    if json_output_path:
        target = write_startup_check_json(report, json_output_path)
        print(f"自检 JSON 已写入：{target}")

    return 0 if not report.has_critical_issues else 2


def parse_cli_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="PolicyAnalyzerPro desktop entrypoint and deployment self-check.",
    )
    parser.add_argument(
        "--config",
        dest="config_path",
        help="Optional path to a config JSON file.",
    )
    parser.add_argument(
        "--self-check",
        action="store_true",
        help="Run startup checks without launching the GUI.",
    )
    parser.add_argument(
        "--self-check-json",
        dest="self_check_json",
        help="Optional path for writing startup check JSON output.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_cli_args(sys.argv[1:] if argv is None else argv)
    config = load_app_config(args.config_path)
    configure_process_environment(config)

    if args.self_check:
        return run_cli_self_check(config, json_output_path=args.self_check_json)

    install_global_exception_hook()

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(config.app_name)
    app.setOrganizationName(APP_ORGANIZATION)
    load_application_font(app, config)

    settings = QSettings(APP_ORGANIZATION, config.app_name)
    should_continue, startup_report = maybe_run_startup_wizard(config, settings)
    if not should_continue:
        return 0

    window = MainWindow(config=config, startup_report=startup_report)
    window.show()
    return app.exec()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
