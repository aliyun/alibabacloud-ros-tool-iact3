class Iact3Exception(Exception):
    """Raised when iact3 experiences a fatal error"""

    def __init__(self, message, code=None):
        self.code = code or 'Iact3Exception'
        self.message = message


class InvalidActionError(Iact3Exception):
    """Exception raised for error when invalid action is supplied

    Attributes:
        expression -- input expression in which the error occurred
    """

    def __init__(self, expression):
        self.expression = expression
        super().__init__(expression)
