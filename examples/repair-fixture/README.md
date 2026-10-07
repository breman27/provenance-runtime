# Controlled repair fixture

`clamp(value, lower, upper)` receives plain integers with `lower <= upper` and must return an integer within those bounds. The bundled version contains an upper-bound regression.

The investigation client creates a private Git repository with good and buggy revisions and captures actual source/diff evidence. Trusted tests are run in an isolated Docker container, never by importing candidate code on the host. This fixture is a constrained integration benchmark, not a production repository.
