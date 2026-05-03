"""Daemon entry point for blecastd."""

from __future__ import annotations

import argparse
import logging
from pathlib import Path
import time

from .beacon import (
    build_custom_manufacturer_advertising_data,
    build_ibeacon_advertising_data,
)
from .config import BlecastdConfig, ConfigError, load_config
from .dynamic_data import ensure_dynamic_data_file, normalize_dynamic_data, read_dynamic_data_file
from .hci import HCIController, HCIError
from .logging_util import configure_logging
from .signals import SignalState, install_signal_handlers


LOG = logging.getLogger(__name__)


class BlecastdDaemon:
    def __init__(self, config_path: str | Path) -> None:
        self.config_path = Path(config_path)
        self.config: BlecastdConfig | None = None
        self.controller: HCIController | None = None
        self.signal_state = SignalState()
        self.advertising_enabled = False

    def run(self) -> int:
        self.config = self._load_config_or_raise()
        self._prepare_dynamic_data_file(self.config)
        self.controller = self._open_controller(self.config)
        install_signal_handlers(self.signal_state)

        try:
            self._configure_hci(self.config)
            if self.config.service.trigger_mode in ("periodic", "both"):
                self._update_advertising_data(self.config)
                self._set_advertising_enabled(True)
            else:
                self._set_advertising_enabled(False)
            self._run_loop()
            return 0
        finally:
            self._shutdown_hci()

    def _run_loop(self) -> None:
        assert self.config is not None
        next_update = time.monotonic() + self.config.service.update_interval_ms / 1000.0

        while not self.signal_state.stop_requested:
            if self.signal_state.reload_requested:
                self.signal_state.reload_requested = False
                next_update = self._reload_config(next_update)

            if self.signal_state.send_requested:
                self.signal_state.send_requested = False
                self._handle_send_trigger()
                next_update = time.monotonic() + self.config.service.update_interval_ms / 1000.0

            if self.config.service.trigger_mode in ("periodic", "both"):
                now = time.monotonic()
                if now >= next_update:
                    self._update_advertising_data(self.config)
                    if not self.advertising_enabled:
                        self._set_advertising_enabled(True)
                    next_update = now + self.config.service.update_interval_ms / 1000.0

            time.sleep(0.1)

    def _handle_send_trigger(self) -> None:
        assert self.config is not None
        trigger_mode = self.config.service.trigger_mode
        if trigger_mode == "periodic":
            LOG.info("SIGUSR1 ignored in periodic trigger_mode")
            return

        self._update_advertising_data(self.config)
        if trigger_mode == "signal":
            self._set_advertising_enabled(True)
            LOG.info(
                "opened one-shot advertising window for %d ms",
                self.config.service.oneshot_duration_ms,
            )
            self._sleep_until_stopped(self.config.service.oneshot_duration_ms / 1000.0)
            self._set_advertising_enabled(False)
        elif trigger_mode == "both":
            if not self.advertising_enabled:
                self._set_advertising_enabled(True)
            LOG.info("handled immediate send trigger")

    def _reload_config(self, next_update: float) -> float:
        assert self.config is not None
        old_config = self.config
        old_controller = self.controller

        try:
            new_config = self._load_config_or_raise()
            self._prepare_dynamic_data_file(new_config)
            if new_config.bluetooth.device != old_config.bluetooth.device:
                new_controller = self._open_controller(new_config)
            else:
                new_controller = old_controller

            self.config = new_config
            self.controller = new_controller
            if old_controller is not None and new_controller is not old_controller:
                self._disable_and_close(old_controller)

            self._configure_hci(new_config)
            self._apply_mode_after_reload(new_config)
            LOG.info("reloaded configuration from %s", self.config_path)
            return time.monotonic() + new_config.service.update_interval_ms / 1000.0
        except Exception as exc:
            self.config = old_config
            self.controller = old_controller
            LOG.error("configuration reload failed; keeping previous config: %s", exc)
            return next_update

    def _apply_mode_after_reload(self, config: BlecastdConfig) -> None:
        if config.service.trigger_mode in ("periodic", "both"):
            self._update_advertising_data(config)
            self._set_advertising_enabled(True)
        else:
            self._set_advertising_enabled(False)

    def _load_config_or_raise(self) -> BlecastdConfig:
        config = load_config(self.config_path)
        for warning in config.warnings:
            LOG.warning(warning)
        if config.beacon.format != "custom_manufacturer":
            LOG.info("beacon.format=%s uses static Advertising Data", config.beacon.format)
        return config

    def _prepare_dynamic_data_file(self, config: BlecastdConfig) -> None:
        if config.beacon.format != "custom_manufacturer":
            return
        created = ensure_dynamic_data_file(
            config.dynamic_data.file,
            length=config.dynamic_data.length,
            fill_byte=config.dynamic_data.fill_byte,
            mode=config.dynamic_data.mode,
            owner=config.dynamic_data.owner,
            group=config.dynamic_data.group,
        )
        if created:
            LOG.warning("created missing dynamic data file: %s", config.dynamic_data.file)

    def _open_controller(self, config: BlecastdConfig) -> HCIController:
        controller = HCIController(config.bluetooth.device)
        controller.open()
        return controller

    def _configure_hci(self, config: BlecastdConfig) -> None:
        if self.controller is None:
            raise HCIError("HCI controller is not open")
        self._set_advertising_enabled(False, allow_command_disallowed=True)
        self.controller.set_advertising_parameters(config.service.advertising_interval_ms)
        LOG.info(
            "configured advertising interval %d ms on %s",
            config.service.advertising_interval_ms,
            config.bluetooth.device,
        )

    def _update_advertising_data(self, config: BlecastdConfig) -> bytes:
        advertising_data = self._build_advertising_data(config)
        if self.controller is None:
            raise HCIError("HCI controller is not open")
        self.controller.set_advertising_data(advertising_data)
        LOG.info("updated Advertising Data: %s", advertising_data.hex())
        return advertising_data

    def _build_advertising_data(self, config: BlecastdConfig) -> bytes:
        if config.beacon.format == "custom_manufacturer":
            result = read_dynamic_data_file(
                config.dynamic_data.file,
                length=config.dynamic_data.length,
                fill_byte=config.dynamic_data.fill_byte,
            )
            if result.warning is not None:
                LOG.warning("%s: %s source_length=%d configured_length=%d",
                    result.warning,
                    config.dynamic_data.file,
                    result.source_length,
                    config.dynamic_data.length,
                )
            return build_custom_manufacturer_advertising_data(
                company_id=config.custom_manufacturer.company_id,
                static_header=config.user_field.static_header,
                dynamic_data=result.dynamic_data,
            )

        if config.beacon.format == "ibeacon":
            return build_ibeacon_advertising_data(
                uuid=config.ibeacon.uuid,
                major=config.ibeacon.major,
                minor=config.ibeacon.minor,
                tx_power=config.ibeacon.tx_power,
            )

        raise ConfigError(f"beacon.format is unknown: {config.beacon.format}")

    def _set_advertising_enabled(self, enabled: bool, *, allow_command_disallowed: bool = False) -> None:
        if self.controller is None:
            raise HCIError("HCI controller is not open")
        self.controller.set_advertising_enabled(
            enabled,
            allow_command_disallowed=allow_command_disallowed,
        )
        self.advertising_enabled = enabled
        LOG.info("advertising %s", "enabled" if enabled else "disabled")

    def _sleep_until_stopped(self, seconds: float) -> None:
        deadline = time.monotonic() + seconds
        while not self.signal_state.stop_requested and time.monotonic() < deadline:
            if self.signal_state.reload_requested:
                break
            time.sleep(min(0.1, max(0.0, deadline - time.monotonic())))

    def _shutdown_hci(self) -> None:
        if self.controller is None:
            return
        try:
            if self.advertising_enabled:
                self._set_advertising_enabled(False)
        except Exception as exc:
            LOG.error("failed to disable advertising during shutdown: %s", exc)
        finally:
            self.controller.close()
            self.controller = None
            self.advertising_enabled = False

    def _disable_and_close(self, controller: HCIController) -> None:
        try:
            controller.set_advertising_enabled(False)
        except Exception as exc:
            LOG.error("failed to disable old HCI controller: %s", exc)
        finally:
            controller.close()


def run_self_check(config_path: str) -> int:
    config = load_config(config_path)
    for warning in config.warnings:
        LOG.warning(warning)

    dynamic_data = normalize_dynamic_data(
        b"",
        length=config.dynamic_data.length,
        fill_byte=config.dynamic_data.fill_byte,
    ).dynamic_data

    custom_advertising_data = build_custom_manufacturer_advertising_data(
        company_id=config.custom_manufacturer.company_id,
        static_header=config.user_field.static_header,
        dynamic_data=dynamic_data,
    )
    ibeacon_advertising_data = build_ibeacon_advertising_data(
        uuid=config.ibeacon.uuid,
        major=config.ibeacon.major,
        minor=config.ibeacon.minor,
        tx_power=config.ibeacon.tx_power,
    )

    print(f"custom Manufacturer Specific Data Advertising Data: {custom_advertising_data.hex()}")
    print(f"iBeacon Advertising Data: {ibeacon_advertising_data.hex()}")
    return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="blecastd")
    parser.add_argument("--config", default="etc/blecastd.toml")
    parser.add_argument("--self-check", action="store_true")
    return parser.parse_args()


def main() -> int:
    configure_logging()
    args = parse_args()
    try:
        if args.self_check:
            return run_self_check(args.config)
        return BlecastdDaemon(args.config).run()
    except (ConfigError, HCIError, OSError) as exc:
        LOG.exception("%s", exc)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
