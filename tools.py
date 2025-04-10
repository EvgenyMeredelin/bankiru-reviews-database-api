import pandas as pd
from sqlalchemy.engine import ScalarResult

from models import review_columns


def format_query_param(key: str, values: list[str]) -> str:
    """Format query parameter with array of values. """
    return "&".join(f"{key}={value}" for value in values)


def dataframe_from_scalars(scalars: list[ScalarResult]) -> pd.DataFrame:
    """Make pandas `DataFrame` from SQLAlchemy `ScalarResult` scalars. """
    # preserve columns order as they declared in the Review table
    # and drop the "_sa_instance_state" column
    records = list(map(lambda scalar: scalar.__dict__, scalars))
    return pd.DataFrame.from_records(records)[review_columns]
