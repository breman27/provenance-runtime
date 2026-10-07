class InvestigationError(ValueError):
    def __init__(self, code: str, stage: str, detail: str):
        self.code, self.stage, self.detail = code, stage, detail
        super().__init__(f"{code} ({stage}): {detail}")


def fail(code, stage, detail):
    raise InvestigationError(code, stage, detail)
