"""
The daily (slow) loop and the event-triggered (fast) loop.

Slow loop: runs once, evaluates whether an event should be proposed.
Fast loop: runs whenever a message changes the state of a LIVE event —
           here, triggered by calling handle_fast_event() directly.
"""

from datetime import datetime
from models import EventCandidate


class EventLog:
    """Just prints what's happening so we can watch the logic run."""
    def say(self, msg):
        print(f"  >> {msg}")


log = EventLog()


def evaluate_event_possibility(households, edges, places):
    """
    Step 6 of the slow loop: look at current state, decide if a
    viable event kernel exists. Extremely simplified 3P check:
    do we have people who like each other, a place, and nothing
    blocking it?
    """
    log.say("Running daily event-possibility evaluation...")

    # naive: find any pair of households with a confirmed 'likes' edge
    # in both directions above rung 0
    candidates = []
    for e in edges:
        if e.kind != "likes" or not e.is_confirmed() or e.rung < 1:
            continue
        reverse = _find_edge(edges, e.to_id, e.from_id, e.context, "likes")
        if reverse and reverse.is_confirmed() and reverse.rung >= 1:
            candidates.append((e.from_id, e.to_id))

    if not candidates:
        log.say("No viable kernel found today. Nothing to propose.")
        return None

    kernel_pair = candidates[0]
    log.say(f"Found mutual-likes kernel: {kernel_pair}")

    # do we have a place?
    place = places[0] if places else None
    if not place:
        log.say("No place available — this becomes tomorrow's prompt instead.")
        return None
    log.say(f"Place available: {place.name}")

    event = EventCandidate(
        id="evt-001",
        kernel_household_ids=list(kernel_pair),
        place_id=place.id,
        program="coffee + kids at the park",
        status="kernel_confirming",
    )
    log.say(f"Event candidate created: {event.id}, status={event.status}")
    return event


def request_kernel_confirmation(event, household_id):
    """
    Logistics-based confirmation, not yes/no (spec §5).
    Here we just simulate asking the question.
    """
    log.say(f"Asking {household_id}: 'What time works, and what should I tell people to bring?'")


def receive_confirmation(event, household_id, response: dict | None):
    """
    response=None means they gave a vague/non-answer -> not confirmed.
    response={"time": ..., "bring": ...} means confirmed.
    """
    if response is None:
        log.say(f"{household_id} gave a vague answer — NOT confirmed.")
        event.confirmations[household_id] = False
        return

    event.confirmations[household_id] = True
    event.logistics[household_id] = response
    log.say(f"{household_id} confirmed with logistics: {response}")

    if all(event.confirmations.get(h) for h in event.kernel_household_ids):
        event.status = "broadcasting"
        log.say(f"Kernel fully confirmed. Event {event.id} status -> {event.status}")


def handle_fast_event(event, household_id, message: str):
    """
    The fast loop: something changed mid-flight and can't wait for
    tomorrow's cycle. E.g. a kernel member backs out after someone
    else already committed to bringing something.
    """
    log.say(f"[FAST LOOP] Incoming message from {household_id}: \"{message}\"")

    if "can't" in message.lower() or "cancel" in message.lower():
        if household_id in event.kernel_household_ids:
            log.say(f"{household_id} is KERNEL. Per spec: kernel falls through -> event is OFF.")
            event.status = "cancelled"
            _notify_others_immediately(event, household_id)
        else:
            log.say(f"{household_id} is not kernel — handled without cancelling the event.")


def _notify_others_immediately(event, dropped_household_id):
    for hid, confirmed in event.confirmations.items():
        if hid != dropped_household_id and confirmed:
            log.say(f"[FAST LOOP] Notifying {hid} immediately: event {event.id} is off "
                     f"({dropped_household_id} had to back out).")


def _find_edge(edges, from_id, to_id, context, kind):
    for e in edges:
        if e.from_id == from_id and e.to_id == to_id and e.context == context and e.kind == kind:
            return e
    return None
