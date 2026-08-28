from maxapi.context import State, StatesGroup


class OrderStates(StatesGroup):
    choosing_address = State()
    address_clarification = State()
    phone = State()
    order_text = State()


class ReviewStates(StatesGroup):
    waiting_comment = State()


class StaffStates(StatesGroup):
    """Сотрудник пишет ответ гостю после кнопки «Ответить гостю»."""

    replying = State()
