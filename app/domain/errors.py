class DomainError(Exception):
    status_code = 400


class NotFound(DomainError):
    status_code = 404


class Conflict(DomainError):
    status_code = 409


class InvalidEvidence(DomainError):
    status_code = 422


class DependencyUnavailable(DomainError):
    status_code = 503
