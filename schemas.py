from datetime import datetime

from pydantic import BaseModel, field_validator

from settings import DATETIME_DB_FORMAT


class Review(BaseModel):
    datePublished: str | datetime
    reviewBody   : str
    bankName     : str
    url          : str
    location     : str
    product      : str

    @field_validator("datePublished", mode="before")
    @classmethod
    def parse_format_date(cls, value: str | datetime) -> datetime | str:
        if isinstance(value, str):
            return datetime.strptime(value, DATETIME_DB_FORMAT)
        if isinstance(value, datetime):
            return value.strftime(DATETIME_DB_FORMAT)


class ReviewPatch(BaseModel):
    product: str
