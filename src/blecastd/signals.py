"""Signal handling state for blecastd."""

from __future__ import annotations

from dataclasses import dataclass
import signal


@dataclass
class SignalState:
    send_requested: bool = False
    reload_requested: bool = False
    stop_requested: bool = False


def install_signal_handlers(signal_state: SignalState) -> None:
    def handle_sigusr1(signum, frame) -> None:  # noqa: ANN001
        signal_state.send_requested = True

    def handle_sighup(signum, frame) -> None:  # noqa: ANN001
        signal_state.reload_requested = True

    def handle_stop(signum, frame) -> None:  # noqa: ANN001
        signal_state.stop_requested = True

    signal.signal(signal.SIGUSR1, handle_sigusr1)
    signal.signal(signal.SIGHUP, handle_sighup)
    signal.signal(signal.SIGTERM, handle_stop)
    signal.signal(signal.SIGINT, handle_stop)
