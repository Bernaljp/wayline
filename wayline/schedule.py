"""The launchable subset and the pick order (Implementation Decisions 5, wave steps 7 to 9).

The frontier itself is a view over the graph and lives with the graph, in `tickets.frontier`.
What this module adds is what the conductor does with it: remove the tickets that would collide
with work already running, remove the tickets whose job resources are not free, order what is
left, and take as many as `policy.max_parallel_workers` allows.

Nothing here reads the ledger, the clock, or the machine. Every function is a pure function of the
graph, the running set, and the policy, so a wave's scheduling can be tested without a conductor
and the conductor is left with the launching.
"""

import os
from pathlib import Path

from wayline.tickets import DECISION, HARDEST, SATISFIED, frontier, is_open_decision, open_decisions

__all__ = [
    "NORMAL", "CHEAP_ONLY", "STOP", "steps_down",
    "normalize", "is_directory_entry", "entries_collide", "touch_sets_collide", "critical_path_lengths",
    "everything_free", "nothing_held", "awaits_owner", "launchable", "order_key", "pick", "held_back", "holds_model_work",
    "AUTONOMOUS",
]

# The pacing actions of decision 5 (`wayline.pacing` computes which one holds). `stop` launches
# nothing; `cheap_only` launches every ticket, each one rung down the rung ladder (decision 16,
# `conductor.stepped_down`), and puts the cheaper first. It deferred the tickets above a difficulty
# before ticket 62: a nearly spent window now stretches further instead of making hard tickets wait.
NORMAL = "normal"
CHEAP_ONLY = "cheap_only"
STOP = "stop"
# The one autonomy under which a decision ticket that is not human-only is the decider's rather than the owner's.
AUTONOMOUS = "autonomous"


def holds_model_work(action):
    """Whether this pacing action stops the conductor launching a model at all.

    Only `stop` does. `cheap_only` still launches every ticket, one rung down (decision 16), and the
    conductor holds the verdict queue under it as well, because a verdict runs above the work it
    judges, is not on the rung ladder, and is never stepped down.
    """
    return action == STOP


def steps_down(action):
    """Whether this pacing action runs a launch one rung down the rung ladder (decision 16).

    Only `cheap_only` does. Which windows the action was read from is the launch's own business
    (`pacing.rung_action`): a Fable rung is stepped down by Fable's weekly window, every other rung
    by the five-hour window, and the all-models week steps down both.
    """
    return action == CHEAP_ONLY


# --- touch sets ------------------------------------------------------------------------------


def normalize(entry, root=None):
    """One touch-set entry as a path to compare: `(path, names_a_directory)`.

    The guard resolves every entry with `realpath -m` against the project, so `./notes/`,
    `a/../notes/`, and `<project>/notes/` are one path and have to compare as one here too.
    An entry outside `root`, or absolute with no `root` to resolve against, keeps the spelling it
    came with: it can then only collide with the same spelling, which is the safe way to be wrong.
    """
    text = str(entry).strip()
    if os.path.isabs(text) and root is not None:
        text = os.path.relpath(text, str(Path(root)))
    return os.path.normpath(text), str(entry).strip().endswith("/")


def is_directory_entry(entry, root=None):
    """Whether a touch-set entry names a directory, as `hooks/touch_set_guard.sh` decides it.

    The guard's rule is a trailing slash in the entry, or a path that exists as a directory. The
    conductor schedules tickets whose worktrees do not exist yet, so `root` (the project) is where
    existence is asked about, and an entry with a trailing slash needs no `root` at all.
    """
    path, trailing = normalize(entry, root)
    return trailing or (root is not None and (Path(root) / path).is_dir())


def entries_collide(one, other, root=None):
    """Whether two touch-set entries name paths that can overlap.

    A directory entry matches everything below it, a file entry matches itself and nothing else,
    which is the guard's rule read for two touch sets rather than for one path against one set.
    """
    left, right = normalize(one, root)[0], normalize(other, root)[0]
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


def held_back(graph, autonomy=None, decider=True):
    """Why each open ticket is outside the frontier, one line each, or `[]` when none is.

    An empty frontier with open tickets left is not the end of the work, and `run_ended` can say
    only `frontier_empty` (its reasons are the spec's closed list), so the conductor says this
    aloud before it stops. Two of the frontier's rules can empty it with work still to do: a
    decision ticket nobody has answered, and a difficulty-5 blocker that is `done` and whose
    quality verdict has not passed, which happens when the verdict could not be taken at all. A
    decision ticket that `awaits_owner` under `autonomy` and `decider` is on the frontier and still waits, for the owner.
    """
    entries = {entry["id"]: entry for entry in graph["tickets"]}
    ready = frontier(graph)
    taken = {entry["id"] for entry in ready}
    waiting = [entry for entry in graph["tickets"] if entry["status"] == "open" and entry["id"] not in taken]
    lines = []
    if waiting:
        lines.append("%d open ticket(s) are outside the frontier:" % len(waiting))
        lines.extend("  ticket %d waits on %s" % (entry["id"], _waits_on(entry, entries, graph)) for entry in waiting)
    for entry in ready:
        if not awaits_owner(entry, autonomy, decider):
            continue
        if entry.get("human_only"):
            why = "it is human-only, and no session answers it"
        elif autonomy is not None and autonomy != AUTONOMOUS:
            why = "under autonomy %s the owner answers every decision ticket" % autonomy
        else:
            why = "no decider role is installed to answer it (ticket 31)"
        lines.append("  decision ticket %d waits for the owner's answer: %s" % (entry["id"], why))
    return lines


def _waits_on(entry, entries, graph):
    """The one sentence that says what is holding this open ticket out of the frontier."""
    everything = [item for item in open_decisions(graph) if item.get("blocking") == "all"]
    if everything and entry["kind"] != DECISION:
        return ("the open decision ticket %d, which pauses every other ticket until it is answered"
                % everything[0]["id"])
    decision = _decision_above(entry, entries)
    if decision is not None:
        return "the open decision ticket %d, which pauses its subgraph" % decision["id"]
    hardest = [identifier for identifier in entry["blocked_by"]
               if (entries.get(identifier) or {}).get("difficulty") == HARDEST
               and (entries.get(identifier) or {}).get("status") == "done"]
    if hardest:
        return ("ticket %d, which is done and not accepted: a difficulty-5 blocker holds its "
                "dependents until a quality verdict passes it, and no verdict has" % hardest[0])
    unmet = ["%d (%s)" % (identifier, (entries.get(identifier) or {}).get("status", "missing"))
             for identifier in entry["blocked_by"]
             if (entries.get(identifier) or {}).get("status") not in SATISFIED]
    return "ticket(s) %s" % ", ".join(unmet) if unmet else "nothing this conductor can name"


def _decision_above(entry, entries):
    """The nearest open decision ticket this one waits on, up the blocking edges; None when there is none."""
    seen, stack = set(), list(entry["blocked_by"])
    while stack:
        blocker = entries.get(stack.pop())
        if blocker is None or blocker["id"] in seen:
            continue
        seen.add(blocker["id"])
        if is_open_decision(blocker):
            return blocker
        stack.extend(blocker["blocked_by"])
    return None


def awaits_owner(entry, autonomy=None, decider=True):
    """Whether only the owner can take this ticket: a decision ticket that no session answers.

    A `human_only` decision ticket always waits for the owner. Under autonomy `interactive` and
    `checkpoints` every decision ticket does, because the owner answers every one of them; only under
    `autonomous` does the decider take the rest (decision 10, ticket 31). `autonomy` None is a caller
    that cannot say, and then only the human-only ones wait. `decider` False says no decider role can be
    read (`decisions.decider_ready`), and then every decision ticket waits for the owner, since a session
    launched on a role that is not there fails before it starts.

    It stays on the frontier, so a paused project can still be answered, but it is never picked and it
    keeps no run going; the owner's answer is what the tick relaunches the conductor for (decision 7).
    """
    if entry["kind"] != DECISION:
        return False
    return bool(entry.get("human_only")) or (autonomy is not None and autonomy != AUTONOMOUS) or not decider


def nothing_held(entry):
    """No launch is held: what `pick` is given while the hold on Fable's weekly window does not stand."""
    return False


def pick(graph, running=(), slots=1, action=NORMAL, root=None, free=everything_free, goal_tickets=(), held=nothing_held,
         autonomy=None, decider=True):
    """The tickets this wave launches, in the order it launches them (wave steps 7 to 9).

    Up to `slots` of them (`policy.max_parallel_workers`). Each pick joins the running set before
    the next is chosen, so two tickets that share a path are never launched into the same wave:
    the second waits for the first to be integrated, which is what makes the conflict serialize.
    The pacing action removes what it does not afford, which is everything under `stop` and nothing
    under `cheap_only`, where a launch runs one rung down instead (decision 16; the conductor
    resolves the rung). `held(entry)` names a launch the hold on Fable's weekly window keeps back
    (decision 15), dropped before anything is picked, so its slot goes to what else is launchable. A
    decision ticket is never picked: the owner answers it, or under `autonomous` the decider is launched
    on it by the conductor's wave step 5 (`wayline.decider`, ticket 31), never as a worker in a worktree.
    """
    ready = [entry for entry in frontier(graph)
             if entry["kind"] != DECISION and not holds_model_work(action) and not held(entry)
             and not awaits_owner(entry, autonomy, decider)]
    lengths = critical_path_lengths(graph)
    taken = list(running)
    chosen = []
    while len(chosen) < max(0, int(slots)):
        options = launchable(ready, taken, root, free)
        if not options:
            break
        best = min(options, key=lambda entry: order_key(entry, lengths, action, goal_tickets))
        ready = [entry for entry in ready if entry["id"] != best["id"]]
        taken.append(best)
        chosen.append(best)
    return chosen
