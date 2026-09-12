"""The launchable subset and the pick order (Implementation Decisions 5, wave steps 7 to 9).

The frontier itself is a view over the graph and lives with the graph, in `tickets.frontier`.
What this module adds is what the conductor does with it: remove the tickets that would collide
with work already running, remove the tickets whose job resources are not free, order what is
left, and take as many as `policy.max_parallel_workers` allows.

Nothing here reads the ledger, the clock, or the machine. Every function is a pure function of the
graph, the running set, and the policy, so a wave's scheduling can be tested without a conductor
and the conductor is left with the launching.
"""

from pathlib import Path

from wayline.tickets import frontier

__all__ = [
    "NORMAL", "CHEAP_ONLY", "STOP",
    "is_directory_entry", "entries_collide", "touch_sets_collide", "critical_path_lengths",
    "everything_free", "launchable", "order_key", "pick",
]

# The pacing actions of decision 5. `cheap_only` changes the pick order here; which tickets an
# action refuses outright, and the `paused` event, are ticket 10's.
NORMAL = "normal"
CHEAP_ONLY = "cheap_only"
STOP = "stop"


# --- touch sets ------------------------------------------------------------------------------


def is_directory_entry(entry, root=None):
    """Whether a touch-set entry names a directory, as `hooks/touch_set_guard.sh` decides it.

    The guard's rule is a trailing slash in the entry, or a path that exists as a directory. The
    conductor schedules tickets whose worktrees do not exist yet, so `root` (the project) is where
    existence is asked about, and an entry with a trailing slash needs no `root` at all.
    """
    text = str(entry)
    if text.endswith("/"):
        return True
    return root is not None and (Path(root) / text).is_dir()


def entries_collide(one, other, root=None):
    """Whether two touch-set entries name paths that can overlap.

    A directory entry matches everything below it, a file entry matches itself and nothing else,
    which is the guard's rule read for two touch sets rather than for one path against one set.
    """
    left, right = str(one).rstrip("/"), str(other).rstrip("/")
    if left == right:
        return True
    if is_directory_entry(one, root) and right.startswith(left + "/"):
        return True
    return is_directory_entry(other, root) and left.startswith(right + "/")


def touch_sets_collide(one, other, root=None):
    """Whether any entry of one touch set can overlap any entry of the other."""
    return any(entries_collide(left, right, root) for left in one or () for right in other or ())


# --- the critical path -----------------------------------------------------------------------


def critical_path_lengths(graph):
    """The longest chain of unfinished dependents below each ticket, by id, itself counted.

    A ticket nothing waits on is 1; a ticket one unfinished ticket waits on is 2. Finished
    dependents are not counted, because what the pick order is asking is how much work is still
    held up behind this ticket, and a chain that is already closed holds up nothing.
    """
    entries = graph["tickets"]
    unfinished = {entry["id"] for entry in entries if entry["status"] not in ("done", "accepted")}
    dependents = {entry["id"]: [] for entry in entries}
    for entry in entries:
        for blocker in entry["blocked_by"]:
            if blocker in dependents and entry["id"] in unfinished:
                dependents[blocker].append(entry["id"])
    lengths = {}
    for start in dependents:
        _length(start, dependents, lengths)
    return lengths


def _length(node, dependents, lengths, seen=None):
    """The longest path from `node` down the dependent edges, memoized; the graph is acyclic."""
    if node in lengths:
        return lengths[node]
    seen = set() if seen is None else seen
    if node in seen:  # `build_graph` refuses a cycle, so this is a graph nobody built
        return 1
    seen.add(node)
    below = [_length(child, dependents, lengths, seen) for child in dependents.get(node, ())]
    lengths[node] = 1 + max(below, default=0)
    seen.discard(node)
    return lengths[node]


# --- the launchable subset -------------------------------------------------------------------


def everything_free(entry):
    """The resource seam of wave step 7, reporting every ticket's resources free.

    Ticket 16 built the detection and the slot rules (`wayline.resources`); what is still missing
    is the running-job view they are asked against, which arrives with the job poller. The
    conductor holds this as a callable, so that poller supplies the real answer by replacing it.
    """
    return True


def launchable(ready, running=(), root=None, free=everything_free):
    """The frontier minus touch-set collisions with the running set, minus unfree resources.

    `running` is the graph entries of the tickets a worker or a job is already working on; only
    their touch sets are read, so the caller may pass anything else that carries one.
    """
    held = [entry["touches"] for entry in running]
    return [entry for entry in ready
            if not any(touch_sets_collide(entry["touches"], other, root) for other in held)
            and free(entry)]


# --- the pick order --------------------------------------------------------------------------


def order_key(entry, lengths, action=NORMAL, goal_tickets=()):
    """The sort key of wave step 9, smallest first.

    Critical-path length, longest first; then a ticket that reports a goal metric; then, when
    pacing says `cheap_only`, the cheaper ticket; then difficulty, hardest first; then the lower
    id. The two difficulty keys are not the same key twice: under `cheap_only` the cheap ticket
    goes first, because what is left of the window is worth spending on what will close; otherwise
    the hard one goes first, because it is the longest job in the wave and a wave is shortest when
    its longest job starts earliest.
    """
    difficulty = entry.get("difficulty") or 0
    return (
        -lengths.get(entry["id"], 1),
        0 if entry["id"] in goal_tickets else 1,
        difficulty if action == CHEAP_ONLY else 0,
        -difficulty,
        entry["id"],
    )


def pick(graph, running=(), slots=1, action=NORMAL, root=None, free=everything_free, goal_tickets=()):
    """The tickets this wave launches, in the order it launches them (wave steps 7 to 9).

    Up to `slots` of them (`policy.max_parallel_workers`). Each pick joins the running set before
    the next is chosen, so two tickets that share a path are never launched into the same wave:
    the second waits for the first to be integrated, which is what makes the conflict serialize.
    """
    ready = frontier(graph)
    lengths = critical_path_lengths(graph)
    held = list(running)
    chosen = []
    while len(chosen) < max(0, int(slots)):
        options = launchable(ready, held, root, free)
        if not options:
            break
        best = min(options, key=lambda entry: order_key(entry, lengths, action, goal_tickets))
        ready = [entry for entry in ready if entry["id"] != best["id"]]
        held.append(best)
        chosen.append(best)
    return chosen
