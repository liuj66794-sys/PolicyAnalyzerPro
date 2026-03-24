from __future__ import annotations

import multiprocessing
import os
import sys
import traceback
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
            "??? PySide6????????????????????\n\n"
            f"??????{sys.executable}\n"
            f"????{venv_python} main.py\n"
            f"?????{activate_script}\n"
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


def main() -> int:
    config = load_app_config()
    configure_process_environment(config)
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


