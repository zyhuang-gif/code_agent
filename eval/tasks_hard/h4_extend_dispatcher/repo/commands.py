from __future__ import annotations

from collections.abc import Callable

Handler = Callable[[str], str]
_HANDLERS: dict[str, Handler] = {}


def command(name: str) -> Callable[[Handler], Handler]:
    def decorator(func: Handler) -> Handler:
        _HANDLERS[name] = func
        return func
    return decorator


@command("upper")
def _upper(value: str) -> str:
    return value.upper()


@command("lower")
def _lower(value: str) -> str:
    return value.lower()




def dispatch(name: str, value: str) -> str:
    try:
        handler = _HANDLERS[name]
    except KeyError as exc:
        raise ValueError(f"unknown command: {name}") from exc
    return handler(value)


def registered_commands() -> tuple[str, ...]:
    return tuple(sorted(_HANDLERS))


