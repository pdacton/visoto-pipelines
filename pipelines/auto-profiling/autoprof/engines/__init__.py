"""Format engines: each turns a sample into model Parts."""


class NotTabular(Exception):
    """The sample isn't a table after all (e.g. nested JSON); hand it to another engine."""


class EngineError(Exception):
    """The sample can't be profiled; the message becomes the failure reason."""
