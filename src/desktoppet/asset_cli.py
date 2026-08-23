"""Command-line entry point for M4 packaging and quality checks."""

from __future__ import annotations

import argparse
from pathlib import Path

from .packager import PackageError, build_package, install_package
from .quality import inspect_package


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="桌宠资源打包、质检与导入工具")
    commands = parser.add_subparsers(dest="command", required=True)
    pack = commands.add_parser("pack", help="清理帧、生成 manifest 并创建安装包")
    pack.add_argument("recipe", type=Path)
    pack.add_argument("output", type=Path)
    pack.add_argument("--archive", type=Path)
    check = commands.add_parser("check", help="检查现有角色资源")
    check.add_argument("manifest", type=Path)
    check.add_argument("--report", type=Path)
    install = commands.add_parser("install", help="验证并一键安装 .petpack")
    install.add_argument("archive", type=Path)
    install.add_argument("pets_root", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.command == "pack":
            manifest, report = build_package(args.recipe, args.output, archive_path=args.archive)
            print(f"OK: {manifest} ({report.frame_count} frames)")
        elif args.command == "install":
            manifest, report = install_package(args.archive, args.pets_root)
            print(f"OK: installed {manifest} ({report.frame_count} frames)")
        else:
            report = inspect_package(args.manifest)
            if args.report:
                report.write(args.report)
            print(
                f"{'OK' if report.passed else 'FAILED'}: {report.animation_count} animations, "
                f"{report.frame_count} frames, {len(report.issues)} issues"
            )
            for issue in report.issues:
                location = issue.animation or "manifest"
                if issue.frame is not None:
                    location += f"[{issue.frame}]"
                print(f"- {issue.severity.upper()} {location}: {issue.message}")
            return 0 if report.passed else 2
    except (OSError, PackageError, ValueError) as exc:
        print(f"ERROR: {exc}")
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
