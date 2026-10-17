"""One-tap follow grouping: who is master, who follows.

Master is the first-ticked profile that is still running. When nothing is
ticked, the first running profile (sorted) becomes master so a single tap
still works. Returns None when fewer than 2 profiles are running.
"""


def pick_follow_group(
    selection_order: list[str], running_names: list[str]
) -> tuple[str, list[str]] | None:
    running = set(running_names)
    ticked_running = [n for n in selection_order if n in running]
    pool = ticked_running or sorted(running)
    if len(pool) < 2:
        return None
    return pool[0], pool[1:]
