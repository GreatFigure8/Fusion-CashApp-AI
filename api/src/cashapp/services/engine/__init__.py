"""Engine control: pause, drain, throttle and dead-letter replay, audited.

Nothing is re-exported here on purpose: the pipeline imports ``pause_gate`` from this package,
and the service pulls in the pipeline, so an eager ``__init__`` would make a cycle. Import
``cashapp.services.engine.service`` for ``EngineService``.
"""
