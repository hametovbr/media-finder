"""Single SQLAlchemy write-transaction and savepoint owner."""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from contextvars import ContextVar, Token
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.orm import Session, sessionmaker


@dataclass(frozen=True, slots=True)
class _TransactionState[T]:
    session: Session
    resource: T


class SqlAlchemyTransactionOwner[T]:
    """Own outer writes and nested savepoints for one application adapter."""

    def __init__(
        self,
        *,
        sessions: sessionmaker[Session],
        resource_factory: Callable[[Session], T],
    ) -> None:
        self._sessions = sessions
        self._resource_factory = resource_factory
        self._state: ContextVar[_TransactionState[T] | None] = ContextVar(
            f"transaction-state-{id(self)}", default=None
        )

    @contextmanager
    def write(self) -> Iterator[T]:
        if self._state.get() is not None:
            raise RuntimeError("transaction_write_already_active")
        session = self._sessions()
        token: Token[_TransactionState[T] | None] | None = None
        try:
            if session.get_bind().dialect.name == "sqlite":
                session.execute(text("BEGIN IMMEDIATE"))
            state = _TransactionState(
                session=session,
                resource=self._resource_factory(session),
            )
            token = self._state.set(state)
            yield state.resource
            session.commit()
        except BaseException:
            session.rollback()
            raise
        finally:
            if token is not None:
                self._state.reset(token)
            session.close()

    @contextmanager
    def savepoint(self) -> Iterator[T]:
        state = self._state.get()
        if state is None:
            raise RuntimeError("transaction_write_not_active")
        with state.session.begin_nested():
            yield state.resource


@contextmanager
def nested_savepoint(session: Session) -> Iterator[None]:
    """Run a persistence-adapter operation in an isolated nested transaction."""

    with session.begin_nested():
        yield


__all__ = ["SqlAlchemyTransactionOwner", "nested_savepoint"]
