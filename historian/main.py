"""CLI entry for the Cozy Aircraft Historian."""

from __future__ import annotations

import argparse
import logging
import sys
import time
from pathlib import Path


DEFAULT_CONFIG = Path("/cozy-data-system/config/historian/historian.yaml")
DEFAULT_AIRCRAFT = Path("/cozy-data-system/config/historian/aircraft.yaml")


def _setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(levelname)s:%(asctime)s:%(name)s - %(message)s",
        datefmt="%Y%m%d-%H:%M:%S",
    )


def _print_summary(summary: dict) -> None:
    for k in (
        "rows_10hz",
        "rows_1hz",
        "rows_event",
        "actual_10hz_frames",
        "mean_sample_period_s",
        "timing_overruns",
        "last_fix_pitch",
        "last_fix_roll",
        "last_fix_alt",
    ):
        if k in summary and summary[k] is not None:
            print(f"{k}: {summary[k]}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="historian", description="Cozy Aircraft Historian")
    parser.add_argument(
        "--config",
        type=Path,
        default=DEFAULT_CONFIG,
        help=f"historian.yaml path (default: {DEFAULT_CONFIG})",
    )
    parser.add_argument(
        "--aircraft-config",
        type=Path,
        default=DEFAULT_AIRCRAFT,
        help=f"aircraft.yaml path (default: {DEFAULT_AIRCRAFT})",
    )
    parser.add_argument("-v", "--verbose", action="store_true")

    sub = parser.add_subparsers(dest="command", required=True)

    p_init = sub.add_parser("init-db", help="Create SQLite schema and seed aircraft/config")
    p_init.add_argument("--db", type=Path, default=None)

    sub.add_parser("status", help="Show DB + daemon state")

    sub.add_parser(
        "daemon",
        help="Run control daemon (idle until start-flight; used by systemd)",
    )

    p_start = sub.add_parser(
        "start-flight",
        help="Start recording via daemon (or --foreground for in-process)",
    )
    p_start.add_argument(
        "--duration",
        type=float,
        default=None,
        help="Stop automatically after N seconds",
    )
    p_start.add_argument(
        "--flight-id",
        default=None,
        help="Use an existing flight_id instead of allocating one",
    )
    p_start.add_argument(
        "--foreground",
        action="store_true",
        help="Run capture in this process (bypass daemon; for debug)",
    )

    sub.add_parser("stop-flight", help="Stop recording via the historian daemon")

    p_show = sub.add_parser("show-flight", help="Show flight summary and sample counts")
    p_show.add_argument("flight_id")

    args = parser.parse_args(argv)
    _setup_logging(args.verbose)

    from historian.control import ControlError, send_command, socket_path_from_cfg
    from historian.database.repository import HistorianDB, load_yaml
    from historian.database.schema import SCHEMA_VERSION

    hist_cfg = (load_yaml(args.config).get("historian") or {}) if args.config.exists() else {}
    sock = socket_path_from_cfg(hist_cfg)

    if args.command == "init-db":
        db = HistorianDB.from_config_files(args.config, args.aircraft_config, db_path=args.db)
        created = db.init_schema_and_seed()
        print(f"database: {db.path}")
        print(f"schema_version: {SCHEMA_VERSION}")
        print(f"seeded: {created}")
        return 0

    if args.command == "daemon":
        from historian.daemon import run_daemon

        run_daemon(args.config, args.aircraft_config)
        return 0

    if args.command == "status":
        db = HistorianDB.from_config_files(args.config, args.aircraft_config)
        info = db.status()
        for k, v in info.items():
            print(f"{k}: {v}")
        try:
            dstat = send_command({"cmd": "status"}, sock_path=sock)
            print("--- daemon ---")
            for k, v in dstat.items():
                print(f"daemon_{k}: {v}")
        except ControlError as e:
            print(f"daemon: unavailable ({e})")
            return 0
        return 0

    if args.command == "start-flight":
        if args.foreground:
            from historian.capture.sampler import run_flight_capture

            flight_id = run_flight_capture(
                args.config,
                args.aircraft_config,
                duration_s=args.duration,
                flight_id=args.flight_id,
            )
            db = HistorianDB.from_config_files(args.config, args.aircraft_config)
            print(f"flight_id: {flight_id}")
            _print_summary(db.flight_summary(flight_id))
            return 0

        try:
            resp = send_command(
                {
                    "cmd": "start",
                    "duration_s": args.duration,
                    "flight_id": args.flight_id,
                },
                sock_path=sock,
                timeout=10.0,
            )
        except ControlError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        if not resp.get("ok"):
            print(f"error: {resp.get('error')}", file=sys.stderr)
            return 1
        flight_id = resp.get("flight_id")
        print(f"flight_id: {flight_id}")
        print(f"state: {resp.get('state')}")

        if args.duration is not None:
            # Wait for daemon to finish timed capture
            deadline = time.time() + float(args.duration) + 30.0
            while time.time() < deadline:
                st = send_command({"cmd": "status"}, sock_path=sock)
                if st.get("state") != "recording":
                    break
                time.sleep(0.2)
            db = HistorianDB.from_config_files(args.config, args.aircraft_config)
            if flight_id:
                _print_summary(db.flight_summary(flight_id))
        else:
            print("recording started (use stop-flight when done)")
        return 0

    if args.command == "stop-flight":
        try:
            resp = send_command({"cmd": "stop"}, sock_path=sock, timeout=20.0)
        except ControlError as e:
            print(f"error: {e}", file=sys.stderr)
            return 1
        print(f"ok: {resp.get('ok')}")
        print(f"state: {resp.get('state')}")
        print(f"flight_id: {resp.get('flight_id')}")
        if resp.get("last_summary"):
            print(f"last_summary: {resp['last_summary']}")
        if resp.get("last_error"):
            print(f"last_error: {resp['last_error']}", file=sys.stderr)
            return 1
        flight_id = resp.get("flight_id")
        if flight_id:
            db = HistorianDB.from_config_files(args.config, args.aircraft_config)
            try:
                _print_summary(db.flight_summary(flight_id))
            except Exception:
                pass
        return 0

    if args.command == "show-flight":
        db = HistorianDB.from_config_files(args.config, args.aircraft_config)
        summary = db.flight_summary(args.flight_id)
        for k, v in summary.items():
            print(f"{k}: {v}")
        return 0

    parser.error(f"unknown command {args.command}")
    return 2


if __name__ == "__main__":
    sys.exit(main())
