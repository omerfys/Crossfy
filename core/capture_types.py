"""Key results shared by capture backends and their consumers."""


class DeadKey:
    def __init__(self, character: str) -> None:
        self.character = character


class TextInput:
    def __init__(self, text: str) -> None:
        self.text = text
