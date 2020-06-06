import locale

from decimal import Decimal
from sqlalchemy import Column, VARCHAR, INTEGER, cast, Float
from sqlalchemy.ext.hybrid import hybrid_property

from .sa_extra import DeclarativeBase, _Date


class GnucashException(Exception):
    pass


class GncNoActiveSession(GnucashException):
    pass


class GncValidationError(GnucashException):
    pass


class GncImbalanceError(GncValidationError):
    pass


class GncConversionError(GnucashException):
    pass


class Recurrence(DeclarativeBase):
    """
    Recurrence information for scheduled transactions

    Attributes:
        obj_guid (str): link to the parent ScheduledTransaction record.
        recurrence_mult (int): Multiplier for the period type. Describes how many times
            the period repeats for the next occurrence.
        recurrence_period_type (str): type or recurrence (monthly, daily).
        recurrence_period_start (date): the date the recurrence starts.
        recurrence_weekend_adjust (str): adjustment to be made if the next occurrence
            falls on weekend / non-working day.
    """

    __tablename__ = "recurrences"

    __table_args__ = {"sqlite_autoincrement": True}

    # column definitions
    id = Column("id", INTEGER(), primary_key=True, nullable=False, autoincrement=True)
    obj_guid = Column("obj_guid", VARCHAR(length=32), nullable=False)
    recurrence_mult = Column("recurrence_mult", INTEGER(), nullable=False)
    recurrence_period_type = Column("recurrence_period_type", VARCHAR(length=2048), nullable=False)
    recurrence_period_start = Column("recurrence_period_start", _Date(), nullable=False)
    recurrence_weekend_adjust = Column(
        "recurrence_weekend_adjust", VARCHAR(length=2048), nullable=False
    )

    # relation definitions
    # added from the DeclarativeBaseGUID object (as linked from different objects like the slots)
    def __str__(self):
        return "{}*{} from {} [{}]".format(
            self.recurrence_period_type,
            self.recurrence_mult,
            self.recurrence_period_start,
            self.recurrence_weekend_adjust,
        )


MAX_NUMBER = 2 ** 63 - 1


def hybrid_property_gncnumeric(num_col, denom_col):
    """Return an hybrid_property handling a Decimal represented by a numerator and a
    denominator column.
    It assumes the python field related to the sqlcolumn is named as _sqlcolumn.

    :type num_col: sqlalchemy.sql.schema.Column
    :type denom_col: sqlalchemy.sql.schema.Column
    :return: sqlalchemy.ext.hybrid.hybrid_property
    """
    num_name, denom_name = "_{}".format(num_col.name), "_{}".format(denom_col.name)
    name = num_col.name.split("_")[0]

    def fset(self, d):
        if d is None:
            num, denom = None, None
        else:
            if isinstance(d, tuple):
                d = Decimal(d[0]) / d[1]
            elif isinstance(d, (int, int, str)):
                d = Decimal(d)
            elif isinstance(d, float):
                raise TypeError(
                    (
                        "Received a floating-point number {} where a decimal is expected. "
                        + "Use a Decimal, str, or int instead"
                    ).format(d)
                )
            elif not isinstance(d, Decimal):
                raise TypeError(
                    (
                        "Received an unknown type {} where a decimal is expected. "
                        + "Use a Decimal, str, or int instead"
                    ).format(type(d).__name__)
                )

            sign, digits, exp = d.as_tuple()
            denom = 10 ** max(-exp, 0)

            denom_basis = getattr(self, "{}_basis".format(denom_name), None)
            if denom_basis is not None:
                denom = denom_basis

            num = int(d * denom)
            if not ((-MAX_NUMBER < num < MAX_NUMBER) and (-MAX_NUMBER < denom < MAX_NUMBER)):
                raise ValueError(
                    (
                        "The amount '{}' cannot be represented in GnuCash. "
                        + "Either it is too large or it has too many decimals"
                    ).format(d)
                )

        setattr(self, num_name, num)
        setattr(self, denom_name, denom)

    def fget(self):
        num, denom = getattr(self, num_name), getattr(self, denom_name)
        if num is None:
            return
        else:
            return Decimal(num) / denom

    def expr(cls):
        # todo: cast into Decimal for postgres and for sqlite (for the latter, use sqlite3.register_converter ?)
        return (cast(num_col, Float) / denom_col).label(name)

    return hybrid_property(fget=fget, fset=fset, expr=expr)


class CallableList(list):
    """
    A simple class (inherited from list) allowing to retrieve a given list element with a filter on an attribute.

    It can be used as the collection_class of a sqlalchemy relationship or to wrap any list (see examples
    in :class:`piecash.core.session.GncSession`)
    """

    fallback = None

    def __init__(self, *args):
        list.__init__(self, *args)

    def __call__(self, **kwargs):
        """
        Return the first element of the list that has attributes matching the kwargs dict. The `get` method is
        an alias for this method.

        To be used as::

            l(mnemonic="EUR", namespace="CURRENCY")
        """
        for obj in self:
            for k, v in kwargs.items():
                if getattr(obj, k) != v:
                    break
            else:
                return obj
        else:
            if self.fallback:
                return self.fallback(**kwargs)
            else:
                raise KeyError("Could not find object with {} in {}".format(kwargs, self))

    get = __call__


def get_system_currency_mnemonic():
    """Returns the mnemonic of the locale currency (and EUR if not defined).

    At the target, it could also look in Gnucash configuration/registry to see if the user
    has chosen another default currency.
    """

    if locale.getlocale() == (None, None):
        locale.setlocale(locale.LC_ALL, "")

    mnemonic = locale.localeconv()["int_curr_symbol"].strip() or "EUR"

    return mnemonic
