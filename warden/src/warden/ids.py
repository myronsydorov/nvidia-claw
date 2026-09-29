from ulid import ULID


def new_worry_id() -> str:
    return f"w_{ULID()}"


def new_watcher_id() -> str:
    return f"wt_{ULID()}"


def new_peer_id() -> str:
    return f"p_{ULID()}"
