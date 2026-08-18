import unittest

from desktoppet.state_machine import PetEvent, PetState, PetStateMachine


class PetStateMachineTests(unittest.TestCase):
    def test_hover_enters_and_leaves(self) -> None:
        machine = PetStateMachine()

        self.assertEqual(machine.dispatch(PetEvent.HOVER_ENTER), PetState.HOVER)
        self.assertEqual(machine.dispatch(PetEvent.HOVER_LEAVE), PetState.IDLE)

    def test_busy_states_override_hover_and_restore_it(self) -> None:
        machine = PetStateMachine()
        machine.dispatch(PetEvent.HOVER_ENTER)

        self.assertEqual(machine.dispatch(PetEvent.LOAD_STARTED), PetState.LOADING)
        self.assertEqual(machine.dispatch(PetEvent.WORK_STARTED), PetState.WORKING)
        self.assertEqual(machine.dispatch(PetEvent.FINISHED), PetState.HOVER)

    def test_hover_does_not_interrupt_work(self) -> None:
        machine = PetStateMachine()
        machine.dispatch(PetEvent.WORK_STARTED)

        self.assertEqual(machine.dispatch(PetEvent.HOVER_ENTER), PetState.WORKING)
        self.assertEqual(machine.dispatch(PetEvent.HOVER_LEAVE), PetState.WORKING)
        self.assertEqual(machine.dispatch(PetEvent.CANCELLED), PetState.IDLE)

    def test_listeners_only_receive_actual_changes(self) -> None:
        machine = PetStateMachine()
        changes: list[tuple[PetState, PetState]] = []
        machine.subscribe(lambda old, new: changes.append((old, new)))

        machine.dispatch(PetEvent.HOVER_LEAVE)
        machine.dispatch(PetEvent.LOAD_STARTED)
        machine.dispatch(PetEvent.LOAD_STARTED)

        self.assertEqual(changes, [(PetState.IDLE, PetState.LOADING)])


if __name__ == "__main__":
    unittest.main()
