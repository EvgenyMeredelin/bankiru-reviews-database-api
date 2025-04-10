from contextlib import asynccontextmanager
from datetime import datetime
from typing import Annotated, Literal

import uvicorn
from decouple import config
from fastapi import Depends, FastAPI, HTTPException, Path, Query, status
from fastapi.security import APIKeyHeader
from sqlalchemy import delete, distinct, func, select
from sqlalchemy.engine import ScalarResult
from sqlalchemy.ext.asyncio import AsyncSession

import schemas
import settings
import tools
import uploaders as up
from database import create_all_tables, get_async_session
from models import Review, review_columns


valid_column_names = Literal[tuple(review_columns)]
database_api_key_header = APIKeyHeader(name="Access-Token")


async def validate_api_key(token: str = Depends(database_api_key_header)):
    """Validate header with API access token. """
    if token != config("DATABASE_API_TOKEN"):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN)


async def get_review_or_404(
    id: int, session: AsyncSession = Depends(get_async_session)
) -> Review:
    statement = select(Review).where(Review.id == id)
    result = await session.execute(statement)
    review = result.scalar_one_or_none()
    if review is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND)
    return review


async def all_distinct_scalars(
    session: AsyncSession, column_name: valid_column_names  # type: ignore
) -> list[ScalarResult]:
    column = getattr(Review, column_name)
    result = await session.execute(select(distinct(column)))
    return result.scalars().all()


async def numbered_list(
    session: AsyncSession, column_name: valid_column_names  # type: ignore
) -> str:
    values = await all_distinct_scalars(session, column_name)
    width = len(str(len(values)))
    return "\n".join(
        f"{str(number).zfill(width)}. {item}"
        for number, item in enumerate(sorted(values), 1)
    )


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_all_tables()
    yield


app = FastAPI(lifespan=lifespan, dependencies=[Depends(validate_api_key)])


@app.post("/reviews", status_code=status.HTTP_201_CREATED)
async def create_reviews(
    new_reviews: list[schemas.Review],
    session: AsyncSession = Depends(get_async_session)
):
    reviews = [Review(**review.model_dump()) for review in new_reviews]
    session.add_all(reviews)
    await session.commit()
    up.database_backup()


@app.get("/reviews")
async def filter_reviews(
    session     : AsyncSession = Depends(get_async_session),
    bankName    : Annotated[list[str] | None, Query()] = None,
    location    : Annotated[list[str] | None, Query()] = None,
    product     : Annotated[list[str] | None, Query()] = None,
    startDate   : Annotated[str | None, Query()] = None,
    reportFormat: Annotated[str | None, Query()] = up.DEFAULT_REPORT_FORMAT
) -> dict[str, str]:

    mapping = {"bankName": bankName, "location": location, "product": product}
    clauses = [
        getattr(Review, column_name).in_(query_param)
        for column_name, query_param in mapping.items()
        if query_param is not None
    ]

    # date format is hardcoded as defined in helper API
    # https://utc-plus-minus-delta.containerapps.ru
    if startDate is not None:
        startDate = datetime.strptime(startDate, "%Y%m%d")
        clauses += [Review.datePublished >= startDate]

    statement = select(Review).where(*clauses).order_by(Review.datePublished)
    result = await session.execute(statement)
    scalars = result.scalars().all()
    if not scalars:
        return {"agent_message": settings.NO_RESULT_SENTINEL}

    data = tools.dataframe_from_scalars(scalars)

    if reportFormat not in up.reporters_menu:
        reportFormat = up.DEFAULT_REPORT_FORMAT
        report_message = (
            up.AVAILABLE_REPORT_FORMATS_MESSAGE
            + up.REPORT_CREATED_MESSAGE.format(reportFormat)
        )
    else:
        report_message = up.REPORT_CREATED_MESSAGE.format(reportFormat)

    reporter_class = up.reporters_menu[reportFormat]
    report_url = reporter_class(data).upload_file(generate_url=True)
    agent_message_parts = [report_message, report_url]

    # If data is so that no plot method was invoked then plotter's body
    # remains empty. And if so then plotter.upload_file returns None.
    plot_url = up.Plotter(data).upload_file(generate_url=True)
    if plot_url is not None:
        agent_message_parts.extend([up.PLOT_CREATED_MESSAGE, plot_url])

    return {"agent_message": "\n".join(agent_message_parts)}


@app.get("/reviews/{column_name}")
async def select_distinct_values(
    column_name: Annotated[valid_column_names, Path()],  # type: ignore
    session: AsyncSession = Depends(get_async_session)
) -> dict[str, str]:
    values = await all_distinct_scalars(session, column_name)
    query_param = tools.format_query_param(column_name, values)
    return {f"query_{column_name}": query_param}


@app.get("/info")
async def info(
    session: AsyncSession = Depends(get_async_session)
) -> dict[str, str | int]:
    """
    Enrich agent's knowledge base with extra fields/facts/descr stats, etc.
    """
    all_bankNames = await numbered_list(session, column_name="bankName")
    all_products  = await numbered_list(session, column_name="product")
    all_locations = await all_distinct_scalars(session, column_name="location")
    min_date = await session.execute(select(func.min(Review.datePublished)))
    max_date = await session.execute(select(func.max(Review.datePublished)))
    return {
        "all_bankNames": all_bankNames,
        "all_products" : all_products,
        "n_locations"  : len(all_locations),
        "date_range"   : f"{min_date.scalar()} - {max_date.scalar()}",
        "available_report_formats": up.AVAILABLE_REPORT_FORMATS_MESSAGE
    }


@app.patch("/reviews/{id}", response_model=schemas.Review)
async def update_review(
    review_patch: schemas.ReviewPatch,
    review: Review = Depends(get_review_or_404),
    session: AsyncSession = Depends(get_async_session),
) -> Review:
    for key, value in review_patch.model_dump().items():
        setattr(review, key, value)
    session.add(review)
    await session.commit()
    up.database_backup()
    return review


@app.delete("/reviews", status_code=status.HTTP_204_NO_CONTENT)
async def delete_reviews(  # many reviews at once
    drop_ids: list[int],
    session: AsyncSession = Depends(get_async_session),
):
    statement = delete(Review).where(Review.id.in_(drop_ids))
    await session.execute(statement)
    await session.commit()
    up.database_backup()


if __name__ == "__main__":
    uvicorn.run(
        "main:app",
        host=config("VM_HOST"),
        port=int(config("VM_PORT")),
        reload=True
    )
