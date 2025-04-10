import inspect
import io
import sys
from abc import ABC, abstractmethod
from functools import cached_property
from itertools import chain
from pathlib import Path
from typing import Literal
from uuid import uuid4

import boto3
import matplotlib.pyplot as plt
import mplcyberpunk
import pandas as pd
import seaborn as sns
from decouple import config
from more_itertools import constrained_batches
from py_spoo_url import Shortener

import settings
from settings import PLOT_MAX_ITEMS as M

plt.rcParams.update(settings.MPL_RUNTIME_CONFIG)
plt.style.use("cyberpunk")


bucket_name = config("S3_BUCKET_NAME")
tenant_id   = config("S3_TENANT_ID")
key_id      = config("S3_KEY_ID")

session = boto3.session.Session(
    aws_access_key_id=f"{tenant_id}:{key_id}",
    aws_secret_access_key=config("S3_KEY_SECRET"),
    region_name=config("S3_REGION_NAME")
)

client = session.client(
    service_name="s3",
    endpoint_url=config("S3_ENDPOINT_URL")
)


class FileUploader(ABC):
    """
    Base class of a file uploader.
    """

    content_type = None

    def __init__(self, data: pd.DataFrame) -> None:
        self.data = data
        self._body = io.BytesIO()

    @property
    @abstractmethod
    def extension(self) -> str:
        """Target extension. """
        raise NotImplementedError

    @cached_property
    @abstractmethod
    def body(self) -> io.BytesIO:
        """File body/content corresponding to the target extension. """
        raise NotImplementedError

    def upload_file(
        self,
        filename: str | None = None,
        bucket_name: str = "temp",
        *,
        generate_url: bool = True,
        shorten_url: bool = True
    ) -> str | None:
        """
        Upload file to S3 bucket. Generate a download link and shorten it.
        """
        if not self.body.getbuffer().nbytes:  # if body is empty
            return None

        self.body.seek(0)
        filename = (filename or str(uuid4())) + self.__class__.extension
        params = {"Bucket": bucket_name, "Key": filename, "Body": self.body}

        content_type = self.__class__.content_type
        if content_type is not None:
            params["ContentType"] = content_type

        client.put_object(**params)

        if generate_url:
            url = client.generate_presigned_url(
                ClientMethod="get_object",
                Params={"Bucket": bucket_name, "Key": filename},
                ExpiresIn=settings.S3_URL_LIFESPAN
            )
            if shorten_url:
                return Shortener().shorten(url)
            return url
        return None


class database_backup(FileUploader):
    """
    Database backup.
    """

    extension = ""  # see settings.DATABASE_PATH

    def __init__(self) -> None:
        filename = Path(settings.DATABASE_PATH).parts[-1]
        super().upload_file(filename, bucket_name, generate_url=False)

    @cached_property
    def body(self) -> io.BytesIO:
        with open(settings.DATABASE_PATH, "rb") as database:
            self._body = io.BytesIO(database.read())
        return self._body


class Plotter(FileUploader):
    """
    Data visualization.
    """

    extension = ".png"
    content_type = "image/png"

    def __init__(self, data: pd.DataFrame) -> None:
        super().__init__(data)
        column_names = ["bankName", "product", "location"]
        banks, products, locations = (
            self.data[col].unique() for col in column_names
        )
        self.locations_annot = (
            f"\n({", ".join(locations)})" if locations.size <= M else ""
        )

        if banks.size == 1 and products.size <= M:
            self.lineplot(item=banks.item(), hue="product")
        elif 1 < banks.size <= M and products.size == 1:
            self.lineplot(item=products.item(), hue="bankName")
        # settings.PLOT_TOP_N: number of banks doesn't matter
        elif 1 < products.size <= M:
            self.barplot(products.size)

    def barplot(self, n_products: int) -> None:
        groupby = (
            self.data.groupby("product").bankName
            .apply(lambda g: g.value_counts()[:settings.PLOT_TOP_N])
            .reset_index()
        )
        groupby.columns = ["product", "bankName", "count"]

        fig, ax = plt.subplots(figsize=(5 * n_products, 5))
        sns.barplot(
            groupby, x="product", y="count", hue="bankName",
            saturation=1
        )
        xlabels = [
            self.__class__.wrap_label(xlabel.get_text())
            for xlabel in ax.get_xticklabels()
        ]
        ax.set_xticks(ax.get_xticks(), labels=xlabels)
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.set_axisbelow(True)
        ax.set_xlabel(None)
        ax.set_ylabel("Количество жалоб")
        ax.set_title(
            f"Сравнение банков по количеству жалоб {self.title_annot}",
            size=14
        )
        sns.move_legend(ax, "upper center")
        bars = chain.from_iterable(ax.containers)
        mplcyberpunk.add_bar_gradient(bars)
        plt.savefig(self._body, bbox_inches="tight", format="png")
        plt.close(fig)

    def lineplot(self, item: str, hue: Literal["product", "bankName"]) -> None:
        grouper = pd.Grouper(key="datePublished", freq="D")
        groupby = (
            self.data.groupby(grouper)[hue].value_counts()
            .reset_index()
        )
        fig, ax = plt.subplots(figsize=(10, 5))
        sns.lineplot(groupby, x="datePublished", y="count", hue=hue)
        plt.xticks(size=8, rotation=45, ha="right")
        ax.yaxis.get_major_locator().set_params(integer=True)
        ax.set_axisbelow(True)
        ax.set_xlabel(None)
        ax.set_ylabel("Количество жалоб")
        ax.set_title(f"{item}: динамика жалоб {self.title_annot}", size=14)
        mplcyberpunk.add_glow_effects()
        plt.savefig(self._body, bbox_inches="tight", format="png")
        plt.close(fig)

    @property
    def body(self) -> io.BytesIO:
        return self._body

    @property
    def title_annot(self) -> str:
        return self.date_range_annot + self.locations_annot

    @property
    def date_range_annot(self) -> str:
        # datePublished comes sorted
        return " — ".join(
            self.data.datePublished.iloc[index]
            .strftime(settings.DATETIME_PLOT_FORMAT)
            for index in (0, -1)
        )

    @staticmethod
    def wrap_label(label: str) -> str:
        batches = constrained_batches(
            label.split(), settings.PLOT_LABEL_MAXLEN, strict=False
        )
        return "\n".join(" ".join(batch) for batch in batches)


class CsvReporter(FileUploader):
    """
    Report in `.csv`.
    """

    extension = ".csv"
    content_type = "text/csv"

    @cached_property
    def body(self) -> io.BytesIO:
        self.data.to_csv(
            self._body,
            index=False,
            encoding="utf-8"
        )
        return self._body


class JsonReporter(FileUploader):
    """
    Report in `.json`.
    """

    extension = ".json"
    content_type = "application/json"

    @cached_property
    def body(self) -> io.BytesIO:
        self.data.to_json(
            self._body,
            orient="records",
            date_format="iso",
            force_ascii=False,
            indent=4
        )
        return self._body


class ParquetReporter(FileUploader):
    """
    Report in `.parquet`.
    """

    extension = ".parquet"
    content_type = "application/vnd.apache.parquet"

    @cached_property
    def body(self) -> io.BytesIO:
        self.data.to_parquet(self._body, index=False)
        return self._body


class XlsxReporter(FileUploader):
    """
    Report in `.xlsx`.
    """

    extension = ".xlsx"
    content_type = (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )

    @cached_property
    def body(self) -> io.BytesIO:
        with pd.ExcelWriter(self._body) as writer:
            self.data.to_excel(writer, index=False)
        return self._body


# ADD NEW REPORTER CLASSES ABOVE THIS LINE

reporters_menu = {
    obj.extension.removeprefix("."): obj
    for name, obj in inspect.getmembers(sys.modules[__name__])
    if name.endswith("Reporter")
}

DEFAULT_REPORT_FORMAT : Literal[tuple(reporters_menu)] = "xlsx"  # type: ignore
PLOT_CREATED_MESSAGE  : str = "Диаграмма:"
REPORT_CREATED_MESSAGE: str = "Ваш отчет в формате {}:"

AVAILABLE_REPORT_FORMATS_MESSAGE: str = (
    f"Доступные форматы отчетов: {", ".join(reporters_menu)}. "
    f"По умолчанию {DEFAULT_REPORT_FORMAT}.\n"
)
